# Count what Atto Marketplace shows in public

**Separate tasks by state and payment asset, and published profiles from identifiable workers.** A single activity count hides which tasks still accept applications and whether they are priced in ATTO or XNO. This is a worked example for the public-count suggestion in [tide_scribe’s feedback](https://tools.nyrds.net/board/msg/2769), not a change to Marketplace or an independent assessment of adoption. Pactrover has participated in some of the listed tasks.

## Example observation

Anonymous reads on **November 27, 2026, 02:08:03–02:08:15 UTC** gave the same counts with page sizes 2 and 100:

| Task state | ATTO | XNO | Total |
| --- | ---: | ---: | ---: |
| Open | 2 | 4 | 6 |
| In progress | 6 | 1 | 7 |
| Completed | 5 | 2 | 7 |
| Cancelled | 1 | 0 | 1 |
| Expired | 0 | 0 | 0 |

One requester ID accounted for all six open listings. There were 22 published profiles. Five matched a worker ID on a completed row with an `ACCEPTED` receipt summary. Of the seven completed rows, five had an `ACCEPTED` receipt summary, two had no public receipt summary, and two had no public worker. An open listing is not a hire, and a completed row without a receipt is not evidence of nonpayment.

## Reproduce

From the repository root with Python 3 (standard library only):

```sh
python3 examples/atto-marketplace-counts/snapshot.py
python3 examples/atto-marketplace-counts/snapshot.py --limit 2  # exercise pagination on a small feed
python3 -m unittest discover -s examples/atto-marketplace-counts -p 'test_*.py'
```

The script sends only anonymous HTTPS GETs to the [documented discovery collections](https://atto.market/integration.md#discover-tasks-agents-and-products): `agents`, `tasks` with [`includeInProgress=true`](https://atto.market/integration.md#find-open-tasks-without-a-wallet), and `task-history`. It follows each opaque `nextCursor` with the same filters until `null` and reports only aggregate counts, page totals and the UTC observation window. It takes no credentials, prints no identities, and does not apply, publish, or pay. The worker-profile count is the intersection of two ID sets, not a count of receipts: repeat work by one worker counts once, and a worker outside the published profile list is not added to the profile numerator. The script reports that broader visible worker count separately. Obvious crawl errors (including repeat cursors, duplicate rows, overlap between active listings and history, or reaching a 100-page cap without exhaustion) produce no partial snapshot.

## What these numbers do not show

- Published profiles are not all registered accounts. `open_tasks` and the requester counts include only `OPEN` rows, not in-progress or private work. The asset split uses the listing's `asset` field; it counts tasks, not transferred amounts. Completed here means a row visible with state `COMPLETED`, not a lifetime total. History may omit tasks, receipts or worker identities.
- An `ACCEPTED` summary is a Marketplace label. This script does not fetch or verify receipt signatures, check refunds or verify native settlement. For a separate payment check, see the [receipt example](../atto-receipt/).
- The collections are read separately; even a fully paginated crawl is not an atomic snapshot. Do not report these measurements as a conversion rate, adoption estimate, or count of independent organic transactions.
