"""Read-only case study, not a general-purpose wallet or finality verifier."""
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
TASK = 'a603eb38-df75-40c1-9821-b5f664bd5099'
RECEIVE = 'D14AD8417EDB259893758CE2250D25748FF9D71D2772A208ECA5DE11FDAB3BF0'
HISTORY = API + '/v1/discovery/task-history?' + urlencode(
    {'state': 'COMPLETED', 'q': 'Hello World #4', 'limit': 20})
RECEIPT = f'{API}/v1/tasks/{TASK}/receipt'
VERSION = 'marketplace-live-v1'
KEY = f'{API}/v1/receipts/keys/{VERSION}'
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


def verify_receipt(row, receipt, key):
    task, summary = row['task'], row['receipt']
    canonical = base64.b64decode(receipt['canonicalBase64'], validate=True)
    digest = hashlib.sha256(canonical).digest()
    need(digest == hex_bytes(receipt['contentSha256'], 32), 'receipt content SHA-256 mismatch')
    content = parse(canonical)
    need(content == receipt['content'] and content['schema'] == SCHEMA, 'receipt projection/schema mismatch')
    need(key['version'] == VERSION and key['algorithm'] == 'Ed25519', 'unexpected Marketplace key metadata')
    for field, expected in {
        'taskId': TASK, 'receiptId': summary['receiptId'], 'outcome': 'ACCEPTED', 'keyVersion': VERSION,
    }.items():
        need(content[field] == receipt[field] == expected, f'receipt binding mismatch: {field}')
    need(task['taskId'] == TASK and task['state'] == 'COMPLETED' and summary['outcome'] == 'ACCEPTED'
         and content['settledAt'] == summary['createdAt'], 'receipt/history status or timestamp mismatch')
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
    need(milestone['taskId'] == TASK and milestone['ordinal'] == 1 and milestone['state'] == 'PAID'
         and milestone['network'] == 'atto:live' and milestone['refundTransactionHash'] is None
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
    if b['type'] == 'SEND':
        need(b['receiverAlgorithm'] == 'V1', 'unexpected receiver algorithm')
        tail = b'\0' + hex_bytes(b['receiverPublicKey'], 32) + struct.pack('<Q', number(b['amount']))
        code = 2
    elif b['type'] == 'RECEIVE':
        need(b['sendHashAlgorithm'] == 'V1', 'unexpected send hash algorithm')
        tail = b'\0' + hex_bytes(b['sendHash'], 32)
        code = 1
    else:
        raise ValueError('only SEND and RECEIVE are supported')
    raw = (bytes([code, 0, 0, 0, 0]) + pk
           + struct.pack('<QQq', number(b['height']), number(b['balance']), number(b['timestamp']))
           + hex_bytes(b['previous'], 32) + tail)
    digest = hashlib.blake2b(raw, digest_size=32).digest()
    need(digest == hex_bytes(expected_hash, 32), 'native block hash mismatch')
    verify_signature(ED25519_SPKI_PREFIX + pk, hex_bytes(tx['signature'], 64), digest)
    return b


def transaction(hash_):
    hex_bytes(hash_, 32)
    return read(f'{NODE}/transactions/{hash_.upper()}')


def link_payment(m, send, receive):
    need(send['type'] == 'SEND' and receive['type'] == 'RECEIVE', 'wrong payment block types')
    sender = hex_bytes(send['publicKey'], 32)
    recipient = hex_bytes(receive['publicKey'], 32)
    need(address(sender) == m['senderAddress'] and address(recipient) == m['recipientAddress']
         and hex_bytes(send['receiverPublicKey'], 32) == recipient, 'payment account mismatch')
    need(hex_bytes(receive['sendHash'], 32) == hex_bytes(m['paidTransactionHash'], 32),
         'RECEIVE does not reference the signed receipt SEND')
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
    ap.add_argument('--tamper-checks', action='store_true', help='run negative checks in memory')
    args = ap.parse_args()
    rows = read(HISTORY)['items']
    row, = (item for item in rows if item['task']['taskId'] == TASK)
    receipt, key = read(RECEIPT), read(KEY)
    content, m = verify_receipt(row, receipt, key)
    send_hash = m['paidTransactionHash']
    send_tx = transaction(send_hash)
    send = verify_block(send_tx, send_hash)
    receive = verify_block(transaction(RECEIVE), RECEIVE)
    link_payment(m, send, receive)
    send_prev = verify_block(transaction(send['previous']), send['previous'])
    receive_prev = verify_block(transaction(receive['previous']), receive['previous'])
    debit, credit = -delta(send, send_prev), delta(receive, receive_prev)
    need(debit == credit == number(send['amount']), 'signed balance changes disagree with SEND amount')
    negative = []
    if args.tamper_checks:
        bad = dict(receipt, contentSha256=flip_hex(receipt['contentSha256']))
        negative.append(rejected('wrong receipt digest', 'receipt content SHA-256 mismatch',
                                 verify_receipt, row, bad, key))
        sig = bytearray(base64.b64decode(receipt['signatureBase64'], validate=True))
        sig[0] ^= 1
        bad = dict(receipt, signatureBase64=base64.b64encode(sig).decode())
        negative.append(rejected('corrupted receipt signature', 'Ed25519 verification failed',
                                 verify_receipt, row, bad, key))
        bad = deepcopy(send_tx)
        bad['block']['amount'] = number(bad['block']['amount']) + 1
        negative.append(rejected('changed SEND amount', 'native block hash mismatch',
                                 verify_block, bad, send_hash))
        bad = dict(send_tx, signature=flip_hex(send_tx['signature']))
        negative.append(rejected('corrupted native signature', 'Ed25519 verification failed',
                                 verify_block, bad, send_hash))
        bad = dict(receive, sendHash=flip_hex(receive['sendHash']))
        negative.append(rejected('mismatched RECEIVE reference', 'RECEIVE does not reference the signed receipt SEND',
                                 link_payment, m, send, bad))
    print(json.dumps({
        'checkedAt': datetime.now(timezone.utc).isoformat(), 'taskId': TASK,
        'historyReceiptFields': sorted(row['receipt']), 'receiptId': content['receiptId'],
        'marketplaceSignature': 'verified with published key', 'outcome': content['outcome'],
        'grossAtomic': content['grossAtomic'], 'publicationFeeAtomic': content['publicationFeeAtomic'],
        'submissionHash': m['submissionHash'], 'submissionBytesVerified': False,
        'sendHash': send_hash, 'receiveHash': RECEIVE, 'nativeBlockHashesAndSignaturesVerified': 4,
        'sendHeight': number(send['height']), 'receiveHeight': number(receive['height']),
        'senderDebitAtomic': str(debit), 'recipientCreditAtomic': str(credit),
        'consensusIndependentlyVerified': False, 'publicationFeeTransferVerified': False,
        'tamperChecksRejected': negative,
    }, indent=2))


if __name__ == '__main__':
    main()
