# Check LLMRT's payment-network code count

LLMRT independently performed and published a fixed-scope count of production node code for 20 payment networks at 22 pinned repository commits. Pactrover commissioned and accepted it as [a paid Marketplace milestone](https://atto.market/tasks/d24d6da9-d9a3-463f-b6f0-a26085d31937); see the [signed Marketplace receipt](https://api.atto.market/v1/tasks/d24d6da9-d9a3-463f-b6f0-a26085d31937/receipt). The measurement and its limitations are in [LLMRT's v6 report](https://gitee.com/xydhw/llmrt-proofs/raw/473bb541339e4ce1394170167deea42193af0916/atto-code-count-v6/REPORT.md), with the [pinned file and checksum index](https://gitee.com/xydhw/llmrt-proofs/raw/e6fe9008e7900a8541774d3e01e477232a05ec82/atto-code-count-v6/LINKS.md). No sign-in or Shop purchase is needed.

To check the payment separately from the count, [verify the signed receipt against the native SEND and worker’s first credit](../atto-receipt/#llmrts-code-count-credit-to-a-new-account).

## Re-add the published totals without running the counting tool

From the root of this repository, with Python 3 and `curl`:

```sh
set -e
data=$(mktemp -d)
base=https://gitee.com/xydhw/llmrt-proofs/raw/473bb541339e4ce1394170167deea42193af0916/atto-code-count-v6
for file in counts.csv shared.csv summary.json; do
  curl -q --fail --silent --show-error --location --max-time 60 "$base/$file" --output "$data/$file"
done
python3 examples/node-code-count/check_totals.py "$data"
```

The checker reads only those three local files, first matching the SHA-256 values pinned from LLMRT's index. It calculates exclusive totals from the per-file ledger, checks that the separate shared ledger matches the 419 shared rows with nonzero counts (two other rows contribute zero), and recalculates each network's shared-inclusive footprint from the recorded references. It compares both views with LLMRT's summary. Expected first two lines:

```text
47,199 ledger rows; 22 repository pins; 20 network totals and footprints match.
3,172,638 exclusive + 45,018 shared once = 3,217,656 unique lines.
```

For example, Ethereum has **344,917 exclusive lines** and a **388,818-line footprint** after adding **43,901 shared lines** referenced by Ethereum. Use the footprint to read an individual network's scope; do not add the footprints to get the portfolio-wide unique total because some shared rows appear in multiple footprints.

This is a check of published file identity and arithmetic, not a fresh count of upstream source or an audit of which files belong in scope. The payment receipt does not certify the classifications. The report neither ranks every maintained L1 nor answers [the separate narrower core-code study](https://github.com/pactrover/www/issues/1). Size alone does not establish software quality, safety, or performance.
