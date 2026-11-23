"""Render public Marketplace task terms. Reads JSON from stdin; makes no requests."""

import json
import re
import sys

DECIMALS = {"ATTO": 9, "XNO": 30}
ATOMIC = re.compile(r"0|[1-9][0-9]*")


def fixed(digits, places):
    padded = digits.zfill(places + 1)
    whole, fraction = padded[:-places], padded[-places:].rstrip("0")
    return f"{whole}.{fraction}" if fraction else whole


def lines(task):
    if not isinstance(task, dict):
        raise ValueError("expected one public task object")
    asset = task.get("asset")
    if not isinstance(asset, str) or asset not in DECIMALS:
        raise ValueError("expected ATTO or XNO")
    for field in ("grossAtomic", "feeAtomic"):
        amount = task.get(field)
        if not isinstance(amount, str) or ATOMIC.fullmatch(amount) is None:
            raise ValueError(f"{field} must be a canonical nonnegative integer string")
    rate = task.get("feeRateBasisPoints")
    if type(rate) is not int or not 0 <= rate <= 10_000:
        raise ValueError("feeRateBasisPoints must be an integer from 0 to 10000")
    budget = fixed(task["grossAtomic"], DECIMALS[asset])
    fee = fixed(task["feeAtomic"], DECIMALS[asset])
    percent = fixed(str(rate), 2)
    return (
        f"Worker budget: {budget} {asset}",
        f"Requester publication fee: {fee} {asset} ({percent}%; separate from worker budget)",
    )


def main():
    try:
        result = lines(json.load(sys.stdin))
    except ValueError as exc:
        print(f"Cannot display fee: {exc}", file=sys.stderr)
        return 1
    print(*result, sep="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
