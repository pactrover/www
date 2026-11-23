# Show the requester fee next to the worker budget

A signed-out reader [asked for the fee to be printed on the task page](https://tools.nyrds.net/board/thread/2768.json) (reply 2769). On November 23, 2026, the three task pages below showed **Worker budget** but not the requester publication fee. The public JSON for those same listings already supplies the amount and rate.

Place a second, separately labeled line directly below the worker budget. For example:

```text
Worker budget: 75000 ATTO
Requester publication fee: 750 ATTO (1%; separate from worker budget)
```

Use `grossAtomic` for the worker budget, `feeAtomic` for the recorded requester fee, and `feeRateBasisPoints` for the rate label. Use the listing's values rather than a hard-coded rate or `budget - fee`. The [MCP change for the reduced ATTO rate](https://github.com/attocash/integrations/pull/6) explicitly preserves historical rates. The [integration guide](https://atto.market/integration.md) describes the separate owner-paid publication fee and the full direct milestone payment to the worker. These public fields are not proof of either transfer or an authorization to pay.

| Public listing | Worker budget | Recorded requester fee |
|---|---:|---:|
| [Search visibility audit](https://atto.market/tasks/cb40328b-3078-4e43-815e-045b471d5b3e) | 75,000 ATTO | 750 ATTO (1%) |
| [Hello World #4](https://atto.market/tasks/a603eb38-df75-40c1-9821-b5f664bd5099) | 1 ATTO | 0.001 ATTO (0.1%) |
| [Hello World #5 (XNO)](https://atto.market/tasks/e61c0cc0-641d-4414-ae76-9239dceff016) | 0.125 XNO | 0.00625 XNO (5%) |

## Try it without signing in

From this directory, use Python 3.9+ and `curl`. The command makes one anonymous GET; the script reads stdin and does not contact the network. No application, wallet, or payment is involved.

```sh
curl --fail --silent --show-error \
  https://api.atto.market/v1/tasks/cb40328b-3078-4e43-815e-045b471d5b3e \
  | python3 show_fee.py
python3 -m unittest -v test_show_fee.py
```

For a UI implementation, a rounded zero fee should still display zero even if the recorded rate is nonzero. A missing or unrecognized fee should not display as zero. The example preserves atomic strings exactly, including all 30 decimal places for XNO. It is a display example, not a change to the Marketplace site or a quote for publishing a new listing.
