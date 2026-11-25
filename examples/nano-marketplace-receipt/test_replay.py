"""Regression tests for the saved Nano payout, with no Python socket activity."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
VERIFY = HERE / 'verify.py'
BUNDLE = HERE / 'hello-world-5.json'
SECOND_RPC = 'https://rpc.nano-gpt.com'
SEND_HASH = '46A52556441A42270EFFF7FFA7829A0A3A92AC41305199DE3AF8C5A8E65F1780'
BLOCKED = 'offline replay attempted Python networking'
AUDIT_RUNNER = '''
import os, runpy, sys

def deny_socket(event, args):
    if event.startswith('socket.'):
        # Report the attempt even if the code under test catches the exception.
        os.write(2, ('offline replay attempted Python networking: ' + event + '\\n').encode())
        raise RuntimeError('Python sockets disabled for this test')

sys.addaudithook(deny_socket)
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
'''


def audited_python(script, *args):
    return subprocess.run([sys.executable, '-I', '-c', AUDIT_RUNNER, str(script), *map(str, args)],
                          capture_output=True, text=True, timeout=30)


class ReplayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        lib = os.environ.get('NANO_VERIFY_LIB')
        if not lib or not Path(lib).is_file():
            raise RuntimeError('Set NANO_VERIFY_LIB to the trusted shared library built in README.md')
        cls.lib = Path(lib).resolve()

    def replay(self, path):
        result = audited_python(VERIFY, '--nano-lib', self.lib, '--evidence-file', path, '--tamper-checks')
        self.assertNotIn(BLOCKED, result.stderr)
        return result

    def check_bad_bytes(self, data, diagnostic):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'evidence.json'
            path.write_bytes(data)
            result = self.replay(path)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn(diagnostic, result.stderr)

    def check_mutation(self, mutate, diagnostic):
        data = json.loads(BUNDLE.read_bytes())
        mutate(data)
        self.check_bad_bytes(json.dumps(data).encode(), diagnostic)

    def test_network_guard_blocks_even_a_caught_socket_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'canary.py'
            path.write_text('import socket\ntry:\n    socket.socket()\nexcept RuntimeError:\n    pass\n',
                            encoding='utf-8')
            result = audited_python(path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f'{BLOCKED}: socket.__new__', result.stderr)

    def test_bundled_receipt_and_native_credit(self):
        result = self.replay(BUNDLE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        proof = json.loads(result.stdout)
        self.assertEqual(proof['evidenceMode'], 'offline')
        self.assertIs(proof['marketplaceSignatureVerified'], True)
        self.assertEqual(proof['stateBlockHashesRecomputed'], 4)
        self.assertEqual(proof['nativeSignaturesVerified'], 4)
        self.assertEqual(proof['senderDebitRaw'], '125000000000000000000000000000')
        self.assertEqual(proof['workerCreditRaw'], proof['senderDebitRaw'])
        self.assertEqual(proof['workerCreditXNO'], '0.125')
        self.assertIs(proof['confirmedReported'], True)
        self.assertIs(proof['representativeVotesChecked'], False)
        self.assertCountEqual(proof['negativeChecks'], [
            'changed SEND balance', 'changed Marketplace signature', 'changed SEND signature',
            'changed sender predecessor signature', 'changed RECEIVE signature',
            'changed recipient predecessor signature', 'wrong receipt-to-SEND link',
        ])

    def test_missing_saved_rpc_does_not_fall_back(self):
        self.check_mutation(lambda data: data['rpcBlocks'].pop(SECOND_RPC),
                            'missing or unexpected Nano RPC evidence source')

    def test_missing_saved_block_does_not_fall_back(self):
        def remove_block(data):
            del data['rpcBlocks'][SECOND_RPC][SEND_HASH]
        self.check_mutation(remove_block, 'missing or unrelated saved blocks')

    def test_substituted_marketplace_key_is_rejected(self):
        def replace_key(data):
            key = data['key']['body']
            der = bytearray(base64.b64decode(key['publicKeyBase64'], validate=True))
            der[-1] ^= 1
            key['publicKeyBase64'] = base64.b64encode(der).decode('ascii')
        self.check_mutation(replace_key, 'offline Marketplace key pin mismatch')

    def test_corrupt_signature_in_only_second_rpc_is_rejected(self):
        def change_signature(data):
            send = data['rpcBlocks'][SECOND_RPC][SEND_HASH]['contents']
            sig = bytearray.fromhex(send['signature'])
            sig[0] ^= 1
            send['signature'] = sig.hex()
        self.check_mutation(change_signature, 'Nano signature verification failed')

    def test_duplicate_json_key_is_rejected(self):
        self.check_bad_bytes(b'{"format":"first","format":"second"}', 'duplicate JSON key')

    def test_oversized_evidence_is_rejected(self):
        self.check_bad_bytes(b' ' * 512_001, 'oversized evidence file')


if __name__ == '__main__':
    unittest.main()
