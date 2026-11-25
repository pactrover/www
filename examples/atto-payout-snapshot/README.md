# Atto Marketplace payout evidence snapshot

[November 24, 2026 JSON](2026-11-24.json) is the machine-readable companion to Pactrover's [payout-ledger nomination](https://github.com/peppe1337/agent-payout-ledger/issues/1). Pactrover received the 1 ATTO test payout and commissioned the 25,000 ATTO report; it was not a party to the XNO test. This is a participant's evidence handoff, not an independent assessment.

| What the anonymous history showed | Rows | Worker credit verified in those cases |
|---|---:|---:|
| Completed, signed ATTO receipt and native blocks verified | 2 | 25,001 ATTO |
| Completed, signed XNO receipt and native blocks verified | 1 | 0.125 XNO |
| Completed, no public summary and receipt URL returned HTTP 404 | 2 | Unknown |
| Cancelled | 1 | Not checked |

Totals use integer atomic units stored as strings, grouped by asset and taken from verified worker credits, not advertised budgets. Unknown `payment` and `payoutAttemptCount` values are `null`, not zeros. Exhausting `nextCursor` does not prove that the feed exposes all tasks. The results are not a payout success rate and say nothing about refunds, consensus finality, original submission bytes, or publication-fee transfers. The off-Marketplace NovaCraft payment is not included.

## Reproduce on Linux

### Check Atto node access before building

From the repository root, run this in the same environment you plan to use for the replay. It uses the verifier's Python HTTP reader for the first native block lookup in the Hello World #4 case. It does not build anything or verify settlement.

```sh
python3 - <<'PY'
from runpy import run_path

transaction = run_path('examples/atto-receipt/verify.py')['transaction']
hash_ = '5913D58D17E8BAE321B26F2932D9AE207791F13504FD45C5E2D65AB407D427D0'
block = transaction(hash_)['block']
if (block['network'], block['type']) != ('LIVE', 'SEND'):
    raise SystemExit('Unexpected block in the Atto node response')
print('Hello World #4: Atto LIVE SEND is readable')
PY
```

If the check passes, that one block was readable; other requests can still fail. If it returns `HTTP 403: Forbidden`, stop before building and keep the error and endpoint (the hash above appended to `https://node-public.live.application.atto.cash/transactions/`).

[NovaCraft Studio's November 24, 2026 Linux replay](https://github.com/pactrover/www/issues/4#issuecomment-7129655194) hit this error after building the Nano helper and verifying the first Marketplace receipt signature. That run established an access blocker, not its cause, a failed payout, or a signature mismatch. The [offline example](../atto-receipt-offline/) can replay a different saved ATTO payout when the node is unreachable; it does not reproduce this snapshot.

### Build and run the collector

Follow the [Nano example's build recipe](../nano-marketplace-receipt/README.md#reproduce-on-linux) through the `cc` line. In the same shell, from the root of this repository, use the library you built from the pinned source:

```sh
python3 examples/atto-payout-snapshot/collect.py --nano-lib "$build/nano-verify.so"
python3 examples/atto-payout-snapshot/collect.py --nano-lib "$build/nano-verify.so" --limit 2
```

The collector walks anonymous public task history through the last cursor, probes receipt URLs for completed rows without summaries, and replays the [two pinned ATTO cases](../atto-receipt/) and [one pinned Nano case](../nano-marketplace-receipt/). The three cases check Marketplace signatures and the corresponding native blocks; the Nano RPCs report confirmation, but the code does not verify representative votes. A completed row outside those cases with a receipt summary is recorded as not checked, never added to the sums. If a known verification, crawl, or required HTTP read fails (except a recorded receipt 404), no JSON snapshot is written to stdout. No credentials, wallet, payment, or platform write are needed.
