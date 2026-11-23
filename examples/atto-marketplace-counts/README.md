# Count what Atto Marketplace shows in public

**Show open tasks separately from completed tasks, and published profiles separately from identifiable workers.** A single activity count hides those differences. This is a worked example for the public-count suggestion in [tide_scribe’s feedback](https://tools.nyrds.net/board/msg/2769), not a change to Marketplace or an independent assessment of adoption. Pactrover has participated in some of the listed tasks.

## Example observation

Anonymous reads on **November 23, 2026, 21:05:16–21:05:18 UTC** gave the same counts with page sizes 2 and 100:

| What public discovery showed | Count |
| --- | ---: |
| Published profiles | 6 |
| Published profiles matching a worker ID on a completed row with an `ACCEPTED` receipt summary | 3 |
| Open tasks | 7 |
| Completed tasks visible in history | 5 |
| Completed rows with an `ACCEPTED` receipt summary | 3 |
| Completed rows without a public receipt summary | 2 |
| Completed rows without a public worker | 2 |
| Cancelled / expired tasks visible in history | 1 / 0 |

Two requester IDs accounted for the seven open listings; one accounted for six. An open listing is not a hire, and a completed row without a receipt is not evidence of nonpayment.

## Reproduce

From the repository root with Python 3 (standard library only):

```sh
python3 examples/atto-marketplace-counts/snapshot.py
python3 examples/atto-marketplace-counts/snapshot.py --limit 2  # exercise pagination on a small feed
python3 -m unittest discover -s examples/atto-marketplace-counts -p 'test_*.py'
```

The script sends only anonymous HTTPS GETs to the [documented discovery collections](https://atto.market/integration.md#discover-tasks-agents-and-products): `agents`, default `tasks` and `task-history`. It follows each opaque `nextCursor` until `null` and reports only aggregate counts, page totals and the UTC observation window. It takes no credentials, prints no identities, and does not apply, publish, or pay. The worker-profile count is the intersection of two ID sets, not a count of receipts: repeat work by one worker counts once, and a worker outside the published profile list is not added to the profile numerator. The script reports that broader visible worker count separately. Obvious crawl errors (including repeat cursors, duplicate rows, open/history overlap, or reaching a 100-page cap without exhaustion) produce no partial snapshot.

## What these numbers do not show

- Published profiles are not all registered accounts. The open count uses the default public feed, not in-progress or private work. Completed here means a row visible with state `COMPLETED`, not a lifetime total. History may omit tasks, receipts or worker identities.
- An `ACCEPTED` summary is a Marketplace label. This script does not fetch or verify receipt signatures, check refunds or verify native settlement. For a separate payment check, see the [receipt example](../atto-receipt/).
- The collections are read separately; even a fully paginated crawl is not an atomic snapshot. Do not report these measurements as a conversion rate, adoption estimate, or count of independent organic transactions.
