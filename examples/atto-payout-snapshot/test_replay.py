"""Regression checks for re-verifying the dated credits, with no live calls."""
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest

import replay


class SnapshotReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        library = Path(os.environ['NANO_VERIFY_LIB']).resolve(strict=True)
        cls.proofs = {task_id: replay.verify_credit(task_id, library) for task_id in replay.CASES}

    def setUp(self):
        self.snapshot = json.loads(replay.SNAPSHOT.read_bytes())

    def check(self):
        return replay.replay(self.snapshot, self.proofs.__getitem__)

    def test_all_three_credits_reconcile_by_asset(self):
        result = self.check()
        self.assertEqual(result['evidenceMode'], 'offline')
        self.assertEqual(result['verifiedWorkerCreditsByAsset'], {
            'ATTO': dict(verifiedCredits=2, creditSumAtomic='25001000000000', atomicUnitsPerUnit=str(10**9)),
            'XNO': dict(verifiedCredits=1, creditSumAtomic='125000000000000000000000000000',
                        atomicUnitsPerUnit=str(10**30)),
        })
        self.assertEqual([row['nativeBlockSignaturesChecked'] for row in result['credits']], [4, 3, 4])
        self.assertEqual([row['tamperChecksRejected'] for row in result['credits']], [5, 8, 7])

    def test_changed_credit_amount_is_rejected(self):
        row = next(row for row in self.snapshot['rows'] if row['payment'] is not None)
        row['payment']['workerCreditAtomic'] = '999999999'
        with self.assertRaisesRegex(ValueError, 'workerCreditAtomic does not match'):
            self.check()

    def test_changed_receipt_id_is_rejected(self):
        row = next(row for row in self.snapshot['rows'] if row['payment'] is not None)
        row['receiptSummary']['receiptId'] = 'not-the-signed-receipt'
        with self.assertRaisesRegex(ValueError, 'receipt does not match'):
            self.check()

    def test_changed_total_is_rejected(self):
        self.snapshot['verifiedWorkerCreditsByAsset']['ATTO']['creditSumAtomic'] = '1'
        with self.assertRaisesRegex(ValueError, 'recomputed sums do not match'):
            self.check()

    def test_unknown_is_not_a_credit(self):
        unknown = next(row for row in self.snapshot['rows'] if row['evidenceStatus'] == 'no_public_summary_receipt_404')
        known = next(row for row in self.snapshot['rows'] if row['payment'] is not None)
        unknown['payment'] = deepcopy(known['payment'])
        with self.assertRaisesRegex(ValueError, 'payment rows do not match'):
            self.check()


if __name__ == '__main__':
    unittest.main()
