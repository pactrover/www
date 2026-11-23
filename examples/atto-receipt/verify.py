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
    need(content['taskId'] == task['id'] == TASK, 'task ID mismatch')
    need(content['taskNonce'] == task['nonce'], 'task nonce mismatch')
    need(content['provider'] == task['provider'], 'provider mismatch')
    need(content['consumer'] == task['consumer'], 'consumer mismatch')
    need(number(content['priceAtto']) == number(task['priceAtto']), 'price mismatch')
    need(content['state'] == task['state'] == 'COMPLETED', 'task state mismatch')
    need(content['resultHash'] == task['resultHash'], 'result hash mismatch')
    need(summary['contentSha256'] == receipt['contentSha256'], 'summary content SHA-256 mismatch')
    need(summary['signatureBase64'] == receipt['signatureBase64'], 'summary signature mismatch')
    need(summary['signerKeyId'] == receipt['signerKeyId'] == VERSION, 'signer key ID mismatch')
    need(key['version'] == VERSION, 'key version mismatch')
    der = base64.b64decode(key['publicKeyDerBase64'], validate=True)
    sig = base64.b64decode(receipt['signatureBase64'], validate=True)
    verify_signature(der, sig, canonical)


def verify_block(block, expected_hash=None):
    need(isinstance(block, dict), 'block must be a dictionary')
    required_fields = {'account', 'previous', 'representative', 'balance', 'link', 'signature', 'work'}
    need(set(block.keys()) == required_fields, 'invalid block fields')
    
    account = hex_bytes(block['account'], 32)
    previous = hex_bytes(block['previous'], 32)
    representative = hex_bytes(block['representative'], 32)
    balance = number(block['balance'])
    link = hex_bytes(block['link'], 32)
    signature = hex_bytes(block['signature'], 64)
    work = hex_bytes(block['work'], 8)
    
    # Blake2b hash verification (preamble + account + previous + representative + balance + link)
    preamble = bytes.fromhex('0000000000000000000000000000000000000000000000000000000000000006')
    hasher = hashlib.blake2b(digest_size=32)
    hasher.update(preamble)
    hasher.update(account)
    hasher.update(previous)
    hasher.update(representative)
    hasher.update(balance.to_bytes(16, 'big'))
    hasher.update(link)
    computed_hash = hasher.digest()
    
    if expected_hash:
        need(computed_hash == hex_bytes(expected_hash, 32), 'block hash mismatch')
        
    # Verify work (PoW) over previous (or account if previous is all zeros)
    work_root = previous if previous != b'\x00'*32 else account
    work_hasher = hashlib.blake2b(digest_size=8)
    work_hasher.update(work[::-1])
    work_hasher.update(work_root)
    work_val = work_hasher.digest()
    need(struct.unpack('<Q', work_val)[0] >= 0xffffffc000000000, 'invalid block work difficulty')
    
    # Verify Ed25519 signature of the block hash
    der = bytes.fromhex('302a300506032b6570032100') + account
    verify_signature(der, signature, computed_hash)
    return computed_hash


def verify_chain():
    print(f'Fetching task history from {HISTORY}')
    history = read(HISTORY)
    need(isinstance(history, list), 'invalid history response')
    row = next((item for item in history if item.get('task', {}).get('id') == TASK), None)
    need(row is not None, f'task {TASK} not found in history')
    
    print(f'Fetching receipt from {RECEIPT}')
    receipt = read(RECEIPT)
    print(f'Fetching signing key from {KEY}')
    key = read(KEY)
    
    verify_receipt(row, receipt, key)
    print('Receipt and signature verified successfully.')
    
    print(f'Fetching node receive block info for {RECEIVE}')
    receive_url = f'{NODE}/block/{RECEIVE}'
    block_data = read(receive_url)
    need('block' in block_data, 'block not found in node response')
    block = block_data['block']
    
    computed_hash = verify_block(block, RECEIVE)
    print(f'Block {RECEIVE} and its signature/work verified successfully.')


def main():
    parser = argparse.ArgumentParser(description='Read-only case study verifier for Atto receipt and block.')
    parser.add_argument('--verify-chain', action='store_true', help='Verify marketplace receipt and node block chain')
    args = parser.parse_args()
    
    if args.verify_chain:
        verify_chain()
    else:
        print('Atto verify.py case study loaded successfully. Pass --verify-chain to run verification.')


if __name__ == '__main__':
    main()