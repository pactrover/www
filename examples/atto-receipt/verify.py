"""Read-only ATTO payment examples, not a general-purpose wallet or finality verifier."""
import argparse
import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import tempfile
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, build_opener

API = 'https://api.atto.market'
NODE = 'https://node-public.live.application.atto.cash'
# The credit hash is a separately observed native block, not a receipt field.
CASES = {
    'hello-world': (
        'a603eb38-df75-40c1-9821-b5f664bd5099', 'Hello World #4', 'RECEIVE',
        'D14AD8417EDB259893758CE2250D25748FF9D71D2772A208ECA5DE11FDAB3BF0',
    ),
    'llmrt-node-count': (
        'd24d6da9-d9a3-463f-b6f0-a26085d31937', 'Count production node code', 'OPEN',
        'E796AD1D540E4A438134CA48F4859074B2552DE7C8B08FF31013E9D60193FF00',
    ),
}
VERSION = 'marketplace-live-v1'
KEY = f'{API}/v1/receipts/keys/{VERSION}'
# SHA-256 of the published marketplace-live-v1 DER key, observed 2026-11-24.
OFFLINE_KEY_SHA256 = '2ae2560719df3f6c3a0f4ee74766ea4d14283ac674a321bde16359ecad03ce45'
EVIDENCE_SCHEMA = 'pactrover-atto-receipt-evidence-v1'
SCHEMA = 'marketplace-work-receipt-v3'
ED25519_SPKI_PREFIX = bytes.fromhex('302a300506032b6570032100')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def need(condition, message):
    if not condition:
        raise ValueError(message)


def unique(pairs):
    data = dict(pairs)
    need(len(data) == len(pairs), 'duplicate JSON key')
    return data


def parse(raw):
    return json.loads(raw, object_pairs_hook=unique)


def read(url):
    with build_opener(NoRedirect()).open(url, timeout=15) as response:
        payload = response.read(512_001)
    need(len(payload) <= 512_000, 'oversized response')
    return parse(payload)


def offline_reader(path):
    with path.open('rb') as stream:
        payload = stream.read(512_001)
    need(len(payload) <= 512_000, 'oversized evidence bundle')
    bundle = parse(payload)
    need(bundle['schema'] == EVIDENCE_SCHEMA, 'unknown evidence schema')
    responses = bundle['responses']
    need(isinstance(responses, dict), 'offline evidence responses must be an object')

    def load(url):
        need(url in responses, f'missing offline evidence for {url}')
        return responses[url]

    key = base64.b64decode(load(KEY)['publicKeyBase64'], validate=True)
    need(hashlib.sha256(key).hexdigest() == OFFLINE_KEY_SHA256, 'offline Marketplace key pin mismatch')
    return load


def hex_bytes(value, size):
    need(isinstance(value, str) and re.fullmatch(rf'[0-9A-Fa-f]{{{size * 2}}}', value),
         f'expected exactly {size} bytes of hex')
    return bytes.fromhex(value)


def number(value):
    need(type(value) is int or (isinstance(value, str) and re.fullmatch(r'0|[1-9][0-9]*', value)),
         'expected nonnegative integer or canonical decimal string')
    value = int(value)
    need(0 <= value < 2**64, 'integer outside uint64')
    return value


def verify_signature(der, signature, message):
    need(len(der) == 44 and der.startswith(ED25519_SPKI_PREFIX) and len(signature) == 64,
         'wrong Ed25519 key or signature format')
    with tempfile.TemporaryDirectory(prefix='atto-receipt-') as directory:
        for name, data in [('key.der', der), ('signature', signature), ('message', message)]:
            (Path(directory) / name).write_bytes(data)
        proc = subprocess.run(
            ['openssl', 'pkeyutl', '-verify', '-pubin', '-keyform', 'DER', '-inkey', 'key.der',
             '-rawin', '-in', 'message', '-sigfile', 'signature'],
            cwd=directory, capture_output=True, timeout=10, check=False)
        need(proc.returncode == 0, 'Ed25519 verification failed')


def verify_receipt(task_id, row, receipt, key):
    task, summary = row['task'], row['receipt']
    canonical = base64.b64decode(receipt['canonicalBase64'], validate=True)
    digest = hashlib.sha256(canonical).digest()
    need(digest == hex_bytes(receipt['contentSha256'], 32), 'receipt content SHA-256 mismatch')
    content = parse(canonical)
    need(content == receipt['content'] and content['schema'] == SCHEMA, 'receipt projection/schema mismatch')
    need(key['version'] == VERSION and key['algorithm'] == 'Ed25519', 'unexpected Marketplace key metadata')
    for field, expected in {
        'taskId': task_id, 'receiptId': summary['receiptId'], 'outcome': 'ACCEPTED', 'keyVersion': VERSION,
    }.items():
        need(content[field] == receipt[field] == expected, f'receipt binding mismatch: {field}')
    need(task['taskId'] == task_id and task['state'] == 'COMPLETED' and summary['outcome'] == 'ACCEPTED'
         and content['settledAt'] == receipt['createdAt'] == summary['createdAt'],
         'receipt/history status or timestamp mismatch')
    need(content['buyerAgentId'] == task['requesterAgentId']
         and content['workerAgentId'] == row['worker']['agentId'], 'receipt participant mismatch')
    need(content['asset'] == task['asset'] == 'ATTO'
         and number(content['grossAtomic']) == number(task['grossAtomic'])
         and number(content['publicationFeeAtomic']) == number(task['feeAtomic'])
         and number(content['feeRateBasisPoints']) == number(task['feeRateBasisPoints']),
         'receipt/history amount or asset mismatch')
    verify_signature(base64.b64decode(key['publicKeyBase64'], validate=True),
                     base64.b64decode(receipt['signatureBase64'], validate=True),
                     SCHEMA.encode() + b'\0' + digest)
    milestone, = parse(content['milestones'])
    need(milestone['taskId'] == task_id and milestone['ordinal'] == 1 and milestone['state'] == 'PAID'
         and milestone['network'] == 'atto:live' and milestone['refundTransactionHash'] is None
         and milestone['paymentRequirementId'] == receipt['paymentRequirementId']
         and number(milestone['amountAtomic']) == number(content['grossAtomic']), 'unexpected milestone')
    hex_bytes(milestone['submissionHash'], 32)
    return content, milestone


def address(key):
    payload = b'\0' + key
    checksum = hashlib.blake2b(payload, digest_size=5).digest()
    return 'atto://' + base64.b32encode(payload + checksum).decode().lower().rstrip('=')


def verify_block(tx, expected_hash):
    b = tx['block']
    need(b['network'] == 'LIVE' and b['algorithm'] == 'V1' and number(b['version']) == 0,
         'only LIVE V1 blocks at version 0 are supported')
    pk = hex_bytes(b['publicKey'], 32)
    height, balance, timestamp = map(number, (b['height'], b['balance'], b['timestamp']))
    if b['type'] == 'OPEN':
        # Atto Commons derives height 1 for OPEN; neither height nor a
        # predecessor is serialized. Balance and timestamp precede the source.
        need(height == 1 and 'previous' not in b, 'OPEN must be height one without a predecessor')
        need(b['sendHashAlgorithm'] == b['representativeAlgorithm'] == 'V1', 'unexpected OPEN algorithm')
        code = 0
        body = (struct.pack('<Qq', balance, timestamp) + b'\0' + hex_bytes(b['sendHash'], 32)
                + b'\0' + hex_bytes(b['representativePublicKey'], 32))
    elif b['type'] in ('SEND', 'RECEIVE'):
        need(height > 1, 'SEND or RECEIVE height must exceed one')
        body = struct.pack('<QQq', height, balance, timestamp) + hex_bytes(b['previous'], 32)
        if b['type'] == 'SEND':
            need(b['receiverAlgorithm'] == 'V1', 'unexpected receiver algorithm')
            code = 2
            body += b'\0' + hex_bytes(b['receiverPublicKey'], 32) + struct.pack('<Q', number(b['amount']))
        else:
            need(b['sendHashAlgorithm'] == 'V1', 'unexpected send hash algorithm')
            code = 1
            body += b'\0' + hex_bytes(b['sendHash'], 32)
    else:
        raise ValueError('only OPEN, SEND and RECEIVE are supported')
    raw = bytes([code, 0, 0, 0, 0]) + pk + body
    digest = hashlib.blake2b(raw, digest_size=32).digest()
    need(digest == hex_bytes(expected_hash, 32), 'native block hash mismatch')
    verify_signature(ED25519_SPKI_PREFIX + pk, hex_bytes(tx['signature'], 64), digest)
    return b


def transaction(hash_, load=read):
    hex_bytes(hash_, 32)
    return load(f'{NODE}/transactions/{hash_.upper()}')


def link_payment(m, send, credit, credit_type):
    need(send['type'] == 'SEND' and credit['type'] == credit_type, 'wrong payment block types')
    sender = hex_bytes(send['publicKey'], 32)
    recipient = hex_bytes(credit['publicKey'], 32)
    need(address(sender) == m['senderAddress'] and address(recipient) == m['recipientAddress']
         and hex_bytes(send['receiverPublicKey'], 32) == recipient, 'payment account mismatch')
    need(hex_bytes(credit['sendHash'], 32) == hex_bytes(m['paidTransactionHash'], 32),
         'credit does not reference the signed receipt SEND')
    need(number(send['amount']) == number(m['amountAtomic']), 'payment amount mismatch')


def delta(current, previous):
    need(hex_bytes(current['publicKey'], 32) == hex_bytes(previous['publicKey'], 32)
         and number(current['height']) == number(previous['height']) + 1,
         'predecessor account or height mismatch')
    return number(current['balance']) - number(previous['balance'])


def rejected(label, message, fn, *args):
    try:
        fn(*args)
    except ValueError as error:
        need(str(error) == message, f'{label} failed for unexpected reason: {error}')
        return label
    raise ValueError(f'{label} was unexpectedly accepted')


def flip_hex(value):
    return f'{int(value[0], 16) ^ 1:x}' + value[1:]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--case', choices=CASES, default='hello-world', help='public example (default: %(default)s)')
    ap.add_argument('--tamper-checks', action='store_true', help='run negative checks in memory')
    ap.add_argument('--evidence-file', type=Path, help='replay stored responses; never fetch missing entries')
    args = ap.parse_args()
    load = read if args.evidence_file is None else offline_reader(args.evidence_file)
    task_id, query, credit_type, credit_hash = CASES[args.case]
    history = API + '/v1/discovery/task-history?' + urlencode({'state': 'COMPLETED', 'q': query, 'limit': 20})
    rows = load(history)['items']
    row, = (item for item in rows if item['task']['taskId'] == task_id)
    receipt, key = load(f'{API}/v1/tasks/{task_id}/receipt'), load(KEY)
    content, m = verify_receipt(task_id, row, receipt, key)
    send_hash = m['paidTransactionHash']
    send_tx = transaction(send_hash, load)
    send = verify_block(send_tx, send_hash)
    credit_tx = transaction(credit_hash, load)
    credit_block = verify_block(credit_tx, credit_hash)
    link_payment(m, send, credit_block, credit_type)
    send_prev = verify_block(transaction(send['previous'], load), send['previous'])
    debit = -delta(send, send_prev)
    if credit_type == 'OPEN':
        credit = number(credit_block['balance'])
        native_blocks = 3
    else:
        credit_prev = verify_block(transaction(credit_block['previous'], load), credit_block['previous'])
        credit = delta(credit_block, credit_prev)
        native_blocks = 4
    need(debit == credit == number(send['amount']) > 0, 'signed balances disagree with SEND amount')
    negative = []
    if args.tamper_checks:
        bad = dict(receipt, contentSha256=flip_hex(receipt['contentSha256']))
        negative.append(rejected('wrong receipt digest', 'receipt content SHA-256 mismatch',
                                 verify_receipt, task_id, row, bad, key))
        sig = bytearray(base64.b64decode(receipt['signatureBase64'], validate=True))
        sig[0] ^= 1
        bad = dict(receipt, signatureBase64=base64.b64encode(sig).decode())
        negative.append(rejected('corrupted receipt signature', 'Ed25519 verification failed',
                                 verify_receipt, task_id, row, bad, key))
        bad = deepcopy(send_tx)
        bad['block']['amount'] = number(bad['block']['amount']) + 1
        negative.append(rejected('changed SEND amount', 'native block hash mismatch',
                                 verify_block, bad, send_hash))
        bad = dict(send_tx, signature=flip_hex(send_tx['signature']))
        negative.append(rejected('corrupted native signature', 'Ed25519 verification failed',
                                 verify_block, bad, send_hash))
        bad = dict(credit_block, sendHash=flip_hex(credit_block['sendHash']))
        negative.append(rejected(f'mismatched {credit_type} reference', 'credit does not reference the signed receipt SEND',
                                 link_payment, m, send, bad, credit_type))
        if credit_type == 'OPEN':
            bad = dict(credit_tx, block=dict(credit_block, height=2))
            negative.append(rejected('changed OPEN height', 'OPEN must be height one without a predecessor',
                                     verify_block, bad, credit_hash))
            bad = dict(credit_tx, block=dict(credit_block, representativePublicKey=flip_hex(
                credit_block['representativePublicKey'])))
            negative.append(rejected('changed OPEN representative', 'native block hash mismatch',
                                     verify_block, bad, credit_hash))
            bad = dict(credit_tx, signature=flip_hex(credit_tx['signature']))
            negative.append(rejected('corrupted OPEN signature', 'Ed25519 verification failed',
                                     verify_block, bad, credit_hash))
    print(json.dumps({
        'checkedAt': datetime.now(timezone.utc).isoformat(), 'taskId': task_id, 'case': args.case,
        'historyReceiptFields': sorted(row['receipt']), 'receiptId': content['receiptId'],
        'marketplaceSignature': ('verified with published key' if args.evidence_file is None
                                 else 'verified with pinned published key from offline evidence'),
        'outcome': content['outcome'],
        **({'evidenceMode': 'offline'} if args.evidence_file is not None else {}),
        'grossAtomic': content['grossAtomic'], 'publicationFeeAtomic': content['publicationFeeAtomic'],
        'submissionHash': m['submissionHash'], 'submissionBytesVerified': False,
        'sendHash': send_hash, 'creditHash': credit_hash, 'creditType': credit_type,
        'nativeBlockHashesAndSignaturesVerified': native_blocks,
        'sendHeight': number(send['height']), 'creditHeight': number(credit_block['height']),
        **({'receiveHash': credit_hash, 'receiveHeight': number(credit_block['height'])}
           if credit_type == 'RECEIVE' else {}),
        'senderDebitAtomic': str(debit), 'recipientCreditAtomic': str(credit),
        'consensusIndependentlyVerified': False, 'publicationFeeTransferVerified': False,
        'tamperChecksRejected': negative,
    }, indent=2))


if __name__ == '__main__':
    main()
