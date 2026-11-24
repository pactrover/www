"""Exercise the public receipt replay with Python networking disabled."""
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
VERIFY = HERE.parent / 'atto-receipt' / 'verify.py'
BUNDLE = HERE / 'llmrt-node-count.json'
DENY_NETWORK = '''
import runpy, sys

def forbid(event, _):
    if event.startswith('socket.'):
        raise RuntimeError('replay tried to use Python networking')

sys.addaudithook(forbid)
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
'''


class ReplayTest(unittest.TestCase):
    def replay(self, path):
        return subprocess.run([sys.executable, '-c', DENY_NETWORK, str(VERIFY),
                               '--case', 'llmrt-node-count', '--evidence-file', str(path), '--tamper-checks'],
                              capture_output=True, text=True, timeout=30)

    def check_bad_bundle(self, alter, message):
        data = json.loads(BUNDLE.read_bytes())
        alter(data['responses'])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'modified.json'
            path.write_text(json.dumps(data), encoding='utf-8')
            result = self.replay(path)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn(message, result.stderr)
        self.assertNotIn('replay tried to use Python networking', result.stderr)

    def test_saved_receipt_and_native_credit(self):
        result = self.replay(BUNDLE)
        self.assertEqual(result.returncode, 0, result.stderr)
        proof = json.loads(result.stdout)
        self.assertEqual(proof['evidenceMode'], 'offline')
        self.assertEqual(proof['marketplaceSignature'], 'verified with pinned published key from offline evidence')
        self.assertEqual(proof['nativeBlockHashesAndSignaturesVerified'], 3)
        self.assertEqual(proof['senderDebitAtomic'], '25000000000000')
        self.assertEqual(proof['recipientCreditAtomic'], '25000000000000')
        self.assertEqual(proof['creditType'], 'OPEN')
        self.assertEqual(len(proof['tamperChecksRejected']), 8)
        self.assertFalse(proof['consensusIndependentlyVerified'])

    def test_missing_native_response_does_not_fall_back(self):
        def remove_open(responses):
            url, = [url for url, value in responses.items() if value.get('block', {}).get('type') == 'OPEN']
            del responses[url]

        self.check_bad_bundle(remove_open, 'missing offline evidence for https://')

    def test_substituted_key_is_rejected(self):
        def change_key(responses):
            key, = [value for value in responses.values() if 'publicKeyBase64' in value]
            der = bytearray(base64.b64decode(key['publicKeyBase64'], validate=True))
            der[-1] ^= 1
            key['publicKeyBase64'] = base64.b64encode(der).decode('ascii')

        self.check_bad_bundle(change_key, 'offline Marketplace key pin mismatch')


if __name__ == '__main__':
    unittest.main()
