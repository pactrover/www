#!/usr/bin/env python3
"""Read-only live or offline check for the public Atto Marketplace Hello World #5 receipt.

Requires Python 3.11+, OpenSSL 3, and a locally built Nano signature library.
Checks one fixed case; relies on RPC confirmation reports, not vote validation.
"""
import argparse
import base64
from copy import deepcopy
import ctypes
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
import re
import subprocess
import tempfile

from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

API = 'https://api.atto.market'
TASK = 'e61c0cc0-641d-4414-ae76-9239dceff016'
RPCS = ('https://rpc.nano.to', 'https://rpc.nano-gpt.com')
VERSION = 'marketplace-live-v1'
SCHEMA = 'marketplace-work-receipt-v3'
EVIDENCE_FORMAT = 'pactrover-nano-marketplace-evidence-v1'
OFFLINE_KEY_SHA256 = '2ae2560719df3f6c3a0f4ee74766ea4d14283ac674a321bde16359ecad03ce45'
QUERY = urlencode({'state': 'COMPLETED', 'asset': 'XNO', 'q': 'Hello World #5', 'limit': 20})
HISTORY_URL = f'{API}/v1/discovery/task-history?{QUERY}'
RECEIPT_URL = f'{API}/v1/tasks/{TASK}/receipt'
KEY_URL = f'{API}/v1/receipts/keys/{VERSION}'
ALPHABET = '13456789abcdefghijkmnopqrstuwxyz'
AMOUNT = 125 * 10**27
HASHES = (
    '46A52556441A42270EFFF7FFA7829A0A3A92AC41305199DE3AF8C5A8E65F1780',  # SEND
    '89F05620E0CBFEACF24DBC64241A6B20B598C07E8E039BE239955171BE35B0FE',  # sender predecessor
    'E50C8EEFDD60CCD4F931D2028F228AC29FEA7CB1C3B8308C922EDB4994ED43F1',  # RECEIVE
    '6DF2FF052F3E8ED59301CE1A1C475B367D571F3698886B0F3FDFAA5BCA1D619B',  # recipient predecessor
)


def require(test, message):
    if not test:
        raise ValueError(message)


def unique(pairs):
    result = dict(pairs)
    require(len(result) == len(pairs), 'duplicate JSON key')
    return result


def parse(data):
    return json.loads(data, object_pairs_hook=unique)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request(url, payload=None):
    req = Request(url, headers={'User-Agent': 'Pactrover-public-receipt-check/1.0'})
    if payload is not None:
        req.add_header('Content-Type', 'application/json')
        req.data = json.dumps(payload).encode()
    with build_opener(NoRedirect()).open(req, timeout=12) as response:
        data = response.read(512_001)
    require(len(data) <= 512_000, 'oversized response')
    return parse(data)


def hex32(text):
    require(re.fullmatch(r'[0-9a-fA-F]{64}', text), 'invalid 32-byte hex')
    return bytes.fromhex(text)


def integer(text, bound=2**128):
    require(isinstance(text, str) and re.fullmatch(r'0|[1-9][0-9]*', text), 'invalid decimal')
    value = int(text)
    require(value < bound, 'decimal out of range')
    return value


def account_key(address):
    require(re.fullmatch(r'nano_[13][' + ALPHABET + r']{59}', address), 'invalid Nano address')
    def decode(text, size):
        value = 0
        for char in text:
            value = (value << 5) | ALPHABET.index(char)
        return value.to_bytes(size, 'big')
    payload = address[5:]
    key = decode(payload[:52], 32)
    require(decode(payload[52:], 5) == hashlib.blake2b(key, digest_size=5).digest()[::-1],
            'Nano address checksum mismatch')
    return key


def verify_receipt(row, envelope, key):
    task, summary = row['task'], row['receipt']
    canonical = base64.b64decode(envelope['canonicalBase64'], validate=True)
    digest = hashlib.sha256(canonical).digest()
    require(digest == hex32(envelope['contentSha256']), 'receipt digest mismatch')
    c = parse(canonical)
    require(c == envelope['content'] and c['schema'] == SCHEMA, 'receipt projection mismatch')
    require(c['taskId'] == envelope['taskId'] == task['taskId'] == TASK
            and task['state'] == 'COMPLETED'
            and c['receiptId'] == envelope['receiptId'] == summary['receiptId']
            and c['outcome'] == envelope['outcome'] == summary['outcome'] == 'ACCEPTED'
            and c['settledAt'] == envelope['createdAt'] == summary['createdAt'], 'receipt/history binding mismatch')
    require(c['buyerAgentId'] == task['requesterAgentId'] and c['workerAgentId'] == row['worker']['agentId']
            and c['asset'] == task['asset'] == 'XNO'
            and integer(c['grossAtomic']) == integer(task['grossAtomic']) == AMOUNT
            and integer(c['publicationFeeAtomic']) == integer(task['feeAtomic'])
            and integer(c['feeRateBasisPoints']) == task['feeRateBasisPoints'], 'receipt/history field mismatch')
    require(c['keyVersion'] == envelope['keyVersion'] == key['version'] == VERSION
            and key['algorithm'] == 'Ed25519', 'receipt key metadata mismatch')
    der = base64.b64decode(key['publicKeyBase64'], validate=True)
    sig = base64.b64decode(envelope['signatureBase64'], validate=True)
    require(len(der) == 44 and der.startswith(bytes.fromhex('302a300506032b6570032100')) and len(sig) == 64,
            'receipt key or signature format mismatch')
    with tempfile.TemporaryDirectory(prefix='nano-receipt-') as d:
        for name, value in (('key.der', der), ('msg', SCHEMA.encode() + b'\0' + digest), ('sig', sig)):
            (Path(d) / name).write_bytes(value)
        p = subprocess.run(['openssl','pkeyutl','-verify','-pubin','-keyform','DER','-inkey','key.der',
                            '-rawin','-in','msg','-sigfile','sig'], cwd=d, capture_output=True, timeout=8)
        require(p.returncode == 0, 'Marketplace signature verification failed')
    m, = parse(c['milestones'])
    require(m['taskId'] == TASK and m['ordinal'] == 1 and m['state'] == 'PAID' and m['network'] == 'nano:mainnet'
            and m['paymentRequirementId'] == envelope['paymentRequirementId']
            and m['refundTransactionHash'] is None and integer(m['amountAtomic']) == AMOUNT, 'unexpected milestone')
    hex32(m['submissionHash'])
    return c, m


def blocks(host):
    result = request(host, {'action': 'blocks_info', 'hashes': HASHES, 'json_block': 'true', 'receive_hash': 'true'})
    require(set(result['blocks']) == set(HASHES), 'Nano RPC returned missing or unrelated blocks')
    return result['blocks']


def block_hash(b):
    require(b['type'] == 'state', 'expected Nano state block')
    data = ((6).to_bytes(32, 'big') + account_key(b['account']) + hex32(b['previous'])
            + account_key(b['representative']) + integer(b['balance']).to_bytes(16, 'big') + hex32(b['link']))
    return hashlib.blake2b(data, digest_size=32).digest()


def verify_block(entry, expected, native_verify):
    b = entry['contents']
    digest = block_hash(b)
    require(digest == hex32(expected), 'state block hash mismatch')
    require(entry['confirmed'] == 'true' and entry['block_account'] == b['account']
            and entry['balance'] == b['balance'], 'RPC confirmation or projection mismatch')
    # Epoch state blocks use a different signer and are outside this example.
    require(entry['subtype'] in ('send', 'receive', 'change', 'open'), 'unsupported state block subtype')
    signature = b['signature']
    require(re.fullmatch(r'[0-9a-fA-F]{128}', signature), 'invalid 64-byte signature hex')
    require(native_verify(digest, len(digest), account_key(b['account']), bytes.fromhex(signature)) == 0,
            'Nano signature verification failed')
    return b


def change(current, prior, a, b):
    require(current['block_account'] == prior['block_account']
            and integer(current['height']) == 1 + integer(prior['height']), 'predecessor account/height mismatch')
    return integer(a['balance']) - integer(b['balance'])


def check_nano(entries, m, native_verify):
    send_hash, sp, receive_hash, rp = HASHES
    require(hex32(m['paidTransactionHash']) == hex32(send_hash), 'signed receipt names a different SEND')
    s, s0, r, r0 = (entries[h] for h in HASHES)
    a, a0, b, b0 = (verify_block(entries[h], h, native_verify) for h in HASHES)
    require(s['subtype'] == 'send' and a['account'] == m['senderAddress']
            and hex32(a['link']) == account_key(m['recipientAddress']), 'SEND destination mismatch')
    require(r['subtype'] == 'receive' and b['account'] == m['recipientAddress']
            and hex32(b['link']) == hex32(send_hash), 'RECEIVE source mismatch')
    require(hex32(s['receive_hash']) == hex32(receive_hash), 'RPC reports a different RECEIVE')
    require(hex32(a['previous']) == hex32(sp) and hex32(b['previous']) == hex32(rp), 'predecessor hash mismatch')
    require(-change(s, s0, a, a0) == change(r, r0, b, b0) == integer(s['amount']) == integer(r['amount']) == AMOUNT,
            'worker credit or sender debit mismatch')
    return {'sendHash': send_hash, 'sendPrevious': sp, 'receiveHash': receive_hash, 'receivePrevious': rp,
            'senderDebitRaw': str(AMOUNT), 'workerCreditRaw': str(AMOUNT), 'confirmedReported': True,
            'stateBlockHashesRecomputed': 4, 'nativeSignaturesVerified': 4}


def rejected(label, message, fn, *args):
    try:
        fn(*args)
    except ValueError as e:
        require(str(e) == message, f'{label} rejected for an unexpected reason: {e}')
        return label
    raise ValueError(f'negative check accepted: {label}')


def load_evidence(path):
    with path.open('rb') as f:
        data = f.read(512_001)
    require(len(data) <= 512_000, 'oversized evidence file')
    obj = parse(data)
    require(obj['format'] == EVIDENCE_FORMAT, 'unexpected evidence format')
    require(obj['history']['url'] == HISTORY_URL and obj['receipt']['url'] == RECEIPT_URL
            and obj['key']['url'] == KEY_URL, 'unexpected Marketplace evidence source')
    rpc_blocks = obj['rpcBlocks']
    require(set(rpc_blocks) == set(RPCS), 'missing or unexpected Nano RPC evidence source')
    require(all(set(rpc_blocks[host]) == set(HASHES) for host in RPCS),
            'missing or unrelated saved blocks')
    key = obj['key']['body']
    der = base64.b64decode(key['publicKeyBase64'], validate=True)
    require(hashlib.sha256(der).hexdigest() == OFFLINE_KEY_SHA256, 'offline Marketplace key pin mismatch')
    captured = datetime.fromisoformat(obj['capturedAtUtc'])
    require(captured.utcoffset() == UTC.utcoffset(None), 'expected an evidence timestamp in UTC')
    return (obj['history']['row'], obj['receipt']['body'], key,
            [rpc_blocks[host] for host in RPCS], captured.isoformat())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nano-lib', required=True, type=Path, help='trusted locally built shared library')
    parser.add_argument('--tamper-checks', action='store_true', help='run negative checks in memory')
    parser.add_argument('--evidence-file', type=Path, help='replay a saved case without HTTP lookups')
    args = parser.parse_args()
    lib = ctypes.CDLL(str(args.nano_lib.resolve(strict=True)))
    native_verify = lib.ed25519_sign_open
    native_verify.argtypes = (ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_char_p)
    native_verify.restype = ctypes.c_int
    if args.evidence_file:
        row, envelope, key, fetched, observed_at = load_evidence(args.evidence_file)
        c, m = verify_receipt(row, envelope, key)
        mode = 'offline'
    else:
        rows = request(HISTORY_URL)['items']
        row, = (item for item in rows if item['task']['taskId'] == TASK)
        envelope = request(RECEIPT_URL)
        key = request(KEY_URL)
        c, m = verify_receipt(row, envelope, key)
        fetched = [blocks(host) for host in RPCS]
        observed_at = datetime.now(UTC).isoformat()
        mode = 'live'
    one, two = (check_nano(entries, m, native_verify) for entries in fetched)
    require(one == two, 'two RPC results disagree')
    negatives = []
    if args.tamper_checks:
        h = HASHES[0]
        original = fetched[0][h]
        changed = deepcopy(original)
        changed['contents']['balance'] = str(integer(original['contents']['balance']) + 1)
        negatives.append(rejected('changed SEND balance', 'state block hash mismatch',
                                  verify_block, changed, h, native_verify))
        sig = bytearray(base64.b64decode(envelope['signatureBase64'], validate=True))
        sig[0] ^= 1
        negatives.append(rejected('changed Marketplace signature', 'Marketplace signature verification failed',
                                  verify_receipt, row,
                                  dict(envelope, signatureBase64=base64.b64encode(sig).decode()), key))
        for label, h in zip(('SEND', 'sender predecessor', 'RECEIVE', 'recipient predecessor'), HASHES):
            changed = deepcopy(fetched[0][h])
            sig = bytearray.fromhex(changed['contents']['signature'])
            sig[0] ^= 1
            changed['contents']['signature'] = sig.hex()
            negatives.append(rejected(f'changed {label} signature', 'Nano signature verification failed',
                                      verify_block, changed, h, native_verify))
        wrong = dict(m, paidTransactionHash=HASHES[2])
        negatives.append(rejected('wrong receipt-to-SEND link', 'signed receipt names a different SEND',
                                  check_nano, fetched[0], wrong, native_verify))
    print(json.dumps({'observedAtUtc': observed_at, 'evidenceMode': mode,
                      'receiptUrl': RECEIPT_URL, 'receiptId': c['receiptId'],
                      'keyVersion': VERSION, 'marketplaceSettledAt': c['settledAt'],
                      'marketplaceSignatureVerified': True, 'nanoRpcEndpoints': RPCS, **one,
                      'workerCreditXNO': '0.125',
                      'representativeVotesChecked': False, 'negativeChecks': negatives}, indent=2))


if __name__ == '__main__':
    main()
