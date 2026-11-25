#!/usr/bin/env python3
"""Recheck the dated snapshot's three worker credits from saved evidence only."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parent
SNAPSHOT = HERE / '2026-11-24.json'
CASES = {
    'a603eb38-df75-40c1-9821-b5f664bd5099': ('ATTO', 'hello-world', 'hello-world-4.json'),
    'd24d6da9-d9a3-463f-b6f0-a26085d31937': ('ATTO', 'llmrt-node-count', 'llmrt-node-count.json'),
    'e61c0cc0-641d-4414-ae76-9239dceff016': ('XNO', None, 'hello-world-5.json'),
}
SCALE = {'ATTO': 10**9, 'XNO': 10**30}


def require(test, message):
    if not test:
        raise ValueError(message)


def verify_credit(task_id, library):
    asset, case, filename = CASES[task_id]
    if asset == 'ATTO':
        cmd = [EXAMPLES / 'atto-receipt/verify.py', '--case', case]
        bundle = EXAMPLES / 'atto-receipt-offline' / filename
    else:
        nano = EXAMPLES / 'nano-marketplace-receipt'
        cmd = [nano / 'verify.py', '--nano-lib', library]
        bundle = nano / filename
    proof = json.loads(subprocess.check_output(
        [sys.executable, *cmd, '--evidence-file', bundle, '--tamper-checks'], timeout=60))
    require(proof['evidenceMode'] == 'offline', 'expected saved evidence')
    if asset == 'ATTO':
        require(proof['taskId'] == task_id and proof['outcome'] == 'ACCEPTED'
                and proof['marketplaceSignature'] == 'verified with pinned published key from offline evidence',
                'unexpected ATTO verification output')
        debit, credit = proof['senderDebitAtomic'], proof['recipientCreditAtomic']
        kind, credit_hash = proof['creditType'], proof['creditHash']
        signatures, tamper = proof['nativeBlockHashesAndSignaturesVerified'], proof['tamperChecksRejected']
    else:
        require(proof['receiptUrl'] == f'https://api.atto.market/v1/tasks/{task_id}/receipt'
                and proof['marketplaceSignatureVerified'] is True, 'unexpected Nano verification output')
        debit, credit = proof['senderDebitRaw'], proof['workerCreditRaw']
        kind, credit_hash = 'RECEIVE', proof['receiveHash']
        signatures, tamper = proof['nativeSignaturesVerified'], proof['negativeChecks']
    return dict(asset=asset, receiptId=proof['receiptId'], sendHash=proof['sendHash'],
                senderDebitAtomic=debit, workerCreditAtomic=credit, creditType=kind,
                creditHash=credit_hash, nativeBlockSignaturesChecked=signatures,
                tamperChecksRejected=len(tamper))


def replay(snapshot, verify) -> dict[str, Any]:
    require(snapshot['schema'] == 'pactrover-public-payout-snapshot-v1', 'unexpected snapshot format')
    rows = {row['taskId']: row for row in snapshot['rows']}
    require(len(rows) == len(snapshot['rows']), 'duplicate snapshot task ID')
    require({task_id for task_id, row in rows.items() if row['payment'] is not None} == CASES.keys(),
            'snapshot payment rows do not match the three saved cases')
    credits, seen = [], set()
    amounts, counts = defaultdict(int), defaultdict(int)
    for task_id in CASES:
        row, actual = rows[task_id], verify(task_id)
        receipt = row['receiptSummary']
        require(row['asset'] == actual['asset'] and row['state'] == 'COMPLETED'
                and receipt['outcome'] == 'ACCEPTED' and receipt['receiptId'] == actual['receiptId'],
                f'receipt does not match the snapshot: {task_id}')
        for field, value in actual.items():
            if field in ('asset', 'receiptId'):
                continue
            expected = row['payment'][field]
            if field in ('sendHash', 'creditHash'):
                expected, value = expected.lower(), value.lower()
            require(type(expected) is type(value) and expected == value,
                    f'{field} does not match the snapshot: {task_id}')
        asset, credit = actual['asset'], actual['workerCreditAtomic']
        require(actual['senderDebitAtomic'] == credit == str(int(credit)) and int(credit) > 0,
                f'invalid signed balance changes: {task_id}')
        key = asset, actual['sendHash'].lower()
        require(key not in seen, 'duplicate verified SEND')
        seen.add(key)
        amounts[asset] += int(credit)
        counts[asset] += 1
        credits.append(dict(taskId=task_id, **actual))
    totals = {asset: dict(verifiedCredits=counts[asset], creditSumAtomic=str(amounts[asset]),
                          atomicUnitsPerUnit=str(SCALE[asset])) for asset in sorted(counts)}
    require(totals == snapshot['verifiedWorkerCreditsByAsset'], 'recomputed sums do not match the snapshot')
    return dict(evidenceMode='offline', snapshotFile=SNAPSHOT.name, verifiedWorkerCreditsByAsset=totals,
                independentlyVerifiedConsensus=False, credits=credits)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nano-lib', type=Path, required=True, help='trusted locally built Nano verifier library')
    args = parser.parse_args()
    library = args.nano_lib.resolve(strict=True)
    snapshot = json.loads(SNAPSHOT.read_bytes())
    print(json.dumps(replay(snapshot, lambda task_id: verify_credit(task_id, library)), indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        sys.exit(f'No offline payout summary produced: {exc}')
