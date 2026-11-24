"""Check the published NovaCraft pilot report and its direct ATTO payment (GET only)."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
from urllib.request import build_opener


# Load the shared native block checker from this repository, not from PyPI.
spec = importlib.util.spec_from_file_location(
    'native_atto_example', Path(__file__).resolve().parents[1] / 'atto-receipt' / 'verify.py',
)
if spec is None or spec.loader is None:
    raise ImportError('cannot load the local native ATTO block checker')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)

REPORT_COMMIT = '81df8bad76f57758cf1701338dced5e939c3a3b7'
REPORT = (f'https://raw.githubusercontent.com/z121245017-ai/novacraft-samples/{REPORT_COMMIT}'
          '/pactrover-pilot/2026-11-24-atto-nano-boundary-pilot.md')
REPORT_SHA256 = 'b6247042d0a08efbbf36ddb2345e14bd6d4256a5ebeed10c007de3052851d8e5'
# The address and amount are transcribed from the worker's public confirmation
# (pactrover/www#1, comment 7120527190), not taken from the proof under test.
AGREED_RECIPIENT = 'atto://adyrqzn7y6xywmwxdsvkjwkzhpyekoegmpirqksacxbeijlaoycqrdk4thqoa'
AGREED_ATOMIC = 12_000_000_000_000
SEND_HASH = '6AD065A5823C93809EC88340DD5DECC911D1D4791ADFC65AF8A354F57928F8AB'
OPEN_HASH = '8CEB0186795BA222110F5E53F082A2845D676D76942A0485C9265499B8E57F90'
ATOMIC_PER_ATTO = 1_000_000_000


def check_report(data):
    digest = hashlib.sha256(data).hexdigest()
    native.need(digest == REPORT_SHA256, 'report SHA-256 mismatch')
    return digest


def check_credit(send, before, opened, send_hash, recipient, agreed_atomic):
    native.need(send['type'] == 'SEND' and opened['type'] == 'OPEN', 'expected SEND and OPEN')
    worker_key = native.hex_bytes(opened['publicKey'], 32)
    native.need(native.address(worker_key) == recipient
                and native.hex_bytes(send['receiverPublicKey'], 32) == worker_key,
                'payment does not match the agreed recipient')
    native.need(native.hex_bytes(opened['sendHash'], 32) == native.hex_bytes(send_hash, 32),
                'OPEN does not reference this SEND')
    amount = native.number(send['amount'])
    native.need(amount == agreed_atomic > 0, 'SEND does not match the agreed amount')
    debit, credit = -native.delta(send, before), native.number(opened['balance'])
    native.need(debit == credit == amount, 'signed balance changes do not match SEND')
    return debit, credit


def utc_ms(value):
    seconds, millis = divmod(native.number(value), 1000)
    return datetime.fromtimestamp(seconds, timezone.utc).replace(microsecond=millis * 1000).isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tamper-checks', action='store_true', help='test in-memory alterations')
    args = parser.parse_args()
    report_limit = 64 * 1024
    with build_opener(native.NoRedirect()).open(REPORT, timeout=15) as response:
        report = response.read(report_limit + 1)
    native.need(len(report) <= report_limit, 'oversized report')
    digest = check_report(report)

    send_tx = native.transaction(SEND_HASH)
    send = native.verify_block(send_tx, SEND_HASH)
    native.need(send['type'] == 'SEND', 'wrong SEND block type')
    prior_hash = send['previous']
    before = native.verify_block(native.transaction(prior_hash), prior_hash)
    opened = native.verify_block(native.transaction(OPEN_HASH), OPEN_HASH)
    debit, credit = check_credit(send, before, opened, SEND_HASH, AGREED_RECIPIENT, AGREED_ATOMIC)
    negative = []
    if args.tamper_checks:
        reject = native.rejected
        negative.append(reject('changed report bytes', 'report SHA-256 mismatch', check_report, report + b'\n'))
        negative.append(reject('changed signed SEND amount', 'native block hash mismatch', native.verify_block,
                               dict(send_tx, block=dict(send, amount=debit + 1)), SEND_HASH))
        negative.append(reject('corrupted native signature', 'Ed25519 verification failed', native.verify_block,
                               dict(send_tx, signature=native.flip_hex(send_tx['signature'])), SEND_HASH))
        negative.append(reject('wrong agreed recipient', 'payment does not match the agreed recipient', check_credit,
                               send, before, opened, SEND_HASH, native.address(native.hex_bytes(send['publicKey'], 32)),
                               AGREED_ATOMIC))
        negative.append(reject('wrong OPEN reference', 'OPEN does not reference this SEND', check_credit,
                               send, before, dict(opened, sendHash=prior_hash), SEND_HASH, AGREED_RECIPIENT,
                               AGREED_ATOMIC))
        negative.append(reject('wrong agreed amount', 'SEND does not match the agreed amount', check_credit,
                               send, before, opened, SEND_HASH, AGREED_RECIPIENT, AGREED_ATOMIC + 1))
        negative.append(reject('wrong sender balance delta', 'signed balance changes do not match SEND', check_credit,
                               send, dict(before, balance=native.number(before['balance']) + 1), opened, SEND_HASH,
                               AGREED_RECIPIENT, AGREED_ATOMIC))
    print(json.dumps({
        'report_commit': REPORT_COMMIT,
        'report_sha256': digest,
        'network': 'LIVE',
        'send': SEND_HASH,
        'signed_sender_predecessor': prior_hash,
        'open': OPEN_HASH,
        'open_block_timestamp_utc': utc_ms(opened['timestamp']),
        'sender_debit_atomic': debit,
        'recipient_credit_atomic': credit,
        'atto': str(credit // ATOMIC_PER_ATTO),  # fixed case: exactly 12,000 ATTO before output
        'matches_publicly_agreed_amount_and_recipient': True,
        'marketplace_receipt_checked': False,
        'independent_network_finality_checked': False,
        'rejected_tamper_checks': negative,
    }, indent=2))


if __name__ == '__main__':
    main()
