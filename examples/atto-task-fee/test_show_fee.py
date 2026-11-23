import unittest

from show_fee import lines


class TestShowFee(unittest.TestCase):
    def task(self, **changes):
        return {"asset": "ATTO", "grossAtomic": "1000000000", "feeAtomic": "1000000",
                "feeRateBasisPoints": 10} | changes

    def test_atto_rate_is_not_hard_coded(self):
        for fee, rate, label in [("1000000", 10, "0.001 ATTO (0.1%"),
                                 ("10000000", 100, "0.01 ATTO (1%")]:
            with self.subTest(rate=rate):
                budget, text = lines(self.task(feeAtomic=fee, feeRateBasisPoints=rate))
                self.assertEqual(budget, "Worker budget: 1 ATTO")
                self.assertEqual(text, f"Requester publication fee: {label}; separate from worker budget)")

    def test_xno_uses_thirty_places_and_preserves_low_digits(self):
        budget, fee = lines(self.task(asset="XNO", grossAtomic="125000000000000000000000000001",
                                      feeAtomic="6250000000000000000000000000", feeRateBasisPoints=500))
        self.assertEqual(budget, "Worker budget: 0.125000000000000000000000000001 XNO")
        self.assertEqual(fee, "Requester publication fee: 0.00625 XNO (5%; separate from worker budget)")

    def test_zero_fee_can_have_a_nonzero_rate(self):
        budget, fee = lines(self.task(grossAtomic="1", feeAtomic="0"))
        self.assertEqual(budget, "Worker budget: 0.000000001 ATTO")
        self.assertEqual(fee, "Requester publication fee: 0 ATTO (0.1%; separate from worker budget)")

    def test_missing_fee_is_not_zero(self):
        task = self.task()
        del task["feeAtomic"]
        with self.assertRaisesRegex(ValueError, "feeAtomic"):
            lines(task)

    def test_noncanonical_atomic_amounts_and_unsupported_asset_are_rejected(self):
        for bad in (10, "01", "-1", "1e3", "１２３", "1\n"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "grossAtomic"):
                lines(self.task(grossAtomic=bad))
        with self.assertRaisesRegex(ValueError, "ATTO or XNO"):
            lines(self.task(asset="USD"))

    def test_invalid_rates_are_rejected(self):
        for bad in (True, 10.0, "10", -1, 10001):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "feeRateBasisPoints"):
                lines(self.task(feeRateBasisPoints=bad))


if __name__ == "__main__":
    unittest.main()
