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
    need(summary['contentSha256'] == receipt['contentSha256'], 'summary content SHA-256 mismatch')
    need(summary['signature'] == receipt['signature'], 'summary signature mismatch')
    need(task['id'] == TASK and task['state'] == 'COMPLETED', 'invalid task metadata')
    need(content['taskId'] == TASK, 'receipt task ID mismatch')
    need(content['version'] == VERSION, 'receipt version mismatch')
    
    signed_payload = base64.b64decode(receipt['signedPayloadBase64'], validate=True)
    signed_obj = parse(signed_payload)
    need(signed_obj.get('canonicalSha256') == receipt['contentSha256'], 'signed payload digest mismatch')
    
    der = base64.b64decode(key['publicKeySpkiDerBase64'], validate=True)
    sig = hex_bytes(receipt['signature'], 64)
    verify_signature(der, sig, signed_payload)
    return content


def verify_account(state):
    need(isinstance(state, dict), 'invalid account state format')
    need(state.get('account') == RECEIVE, 'account address mismatch')
    balance = number(state.get('balance'))
    need(balance > 0, 'non-positive balance')
    return balance


def main():
    parser = argparse.ArgumentParser(description='Verify Atto marketplace receipt and node state.')
    parser.add_argument('--offline', action='store_true', help='Skip network calls and run checks locally where possible.')
    args = parser.parse_args()

    print('Starting Atto receipt and state verification case study...')
    
    try:
        if args.offline:
            print('Offline mode requested. Skipping live network fetches.')
            return

        print(f'Fetching task history from: {HISTORY}')
        history_data = read(HISTORY)
        need(isinstance(history_data.get('tasks'), list), 'invalid history response')
        
        target_row = None
        for item in history_data['tasks']:
            if item.get('task', {}).get('id') == TASK:
                target_row = item
                break
        need(target_row is not None, f'Task {TASK} not found in history')

        print(f'Fetching receipt from: {RECEIPT}')
        receipt_data = read(RECEIPT)
        
        print(f'Fetching signing key from: {KEY}')
        key_data = read(KEY)

        print('Verifying cryptographic receipt and signature...')
        content = verify_receipt(target_row, receipt_data, key_data)
        print(f'Receipt successfully verified for task: {content.get("taskId")}')

        node_url = f'{NODE}/v1/accounts/{RECEIVE}'
        print(f'Fetching node account state from: {node_url}')
        account_data = read(node_url)
        balance = verify_account(account_data)
        print(f'Account balance verified: {balance} ATTO')
        
        print('Case study verification completed successfully.')
    except Exception as e:
        print(f'Verification failed: {e}')
        raise


if __name__ == '__main__':
    main()