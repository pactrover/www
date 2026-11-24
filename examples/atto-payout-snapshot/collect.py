#!/usr/bin/env python3
"""Export visible Marketplace history and replay three known payout checks."""
import argparse
from collections import Counter, defaultdict
from datetime import UTC, datetime
import json
from pathlib import Path
import runpy
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, build_opener

EXAMPLES = Path(__file__).resolve().parents[1]
DISCOVERY = runpy.run_path(str(EXAMPLES / 'atto-marketplace-counts' / 'snapshot.py'))
API = 'https://api.atto.market/v1'
CASES = {
    'a603eb38-df75-40c1-9821-b5f664bd5099': ('ATTO', 'hello-world', 'test'),
    'd24d6da9-d9a3-463f-b6f0-a26085d31937': ('ATTO', 'llmrt-node-count', 'pactrover_commission'),
    'e61c0cc0-641d-4414-ae76-9239dceff016': ('XNO', None, 'test'),
}
DECIMALS = {'ATTO': 9, 'XNO': 30}


def require(test, message):
    if not test:
        raise ValueError(message)


def public_receipt_probe(url):
    # Do not follow redirects, and do not recast a connection/HTTP error as nonpayment.
    request = Request(url, headers={'Accept': 'application/json'}, method='GET')
    with build_opener(DISCOVERY['NoRedirect']()).open(request, timeout=15) as response:
        return response.status


def run_case(task_id, library):
    asset, example, _ = CASES[task_id]
    if asset == 'ATTO':
        cmd = [EXAMPLES / 'atto-receipt/verify.py', '--case', example]
    else:
        cmd = [EXAMPLES / 'nano-marketplace-receipt/verify.py', '--nano-lib', library]
    return json.loads(subprocess.check_output([sys.executable, *cmd, '--tamper-checks'], timeout=140))


def payout(task, summary, proof):
    task_id, asset, gross = (task[k] for k in ('taskId', 'asset', 'grossAtomic'))
    expected_asset, example, purpose = CASES[task_id]
    require(asset == expected_asset and summary['outcome'] == 'ACCEPTED'
            and proof['receiptId'] == summary['receiptId'], 'verification/history mismatch')
    if asset == 'ATTO':
        require(proof['taskId'] == task_id and proof['case'] == example
                and proof['marketplaceSignature'] == 'verified with published key'
                and proof['outcome'] == 'ACCEPTED' and proof['grossAtomic'] == gross,
                'ATTO receipt mismatch')
        debit, credit = proof['senderDebitAtomic'], proof['recipientCreditAtomic']
        credit_type, credit_hash = proof['creditType'], proof['creditHash']
        signatures = proof['nativeBlockHashesAndSignaturesVerified']
        negative = proof['tamperChecksRejected']
        rpc_reports = None
        checked_at = proof['checkedAt']
    else:
        require(proof['receiptUrl'] == f'{API}/tasks/{task_id}/receipt'
                and proof['marketplaceSignatureVerified'] is True
                and proof['marketplaceSettledAt'] == summary['createdAt'], 'XNO receipt mismatch')
        debit, credit = proof['senderDebitRaw'], proof['workerCreditRaw']
        credit_type, credit_hash = 'RECEIVE', proof['receiveHash']
        signatures = proof['nativeSignaturesVerified']
        negative = proof['negativeChecks']
        rpc_reports = proof['nanoRpcEndpoints'] if proof['confirmedReported'] else []
        checked_at = proof['observedAtUtc']
    require(credit == debit == gross and str(int(credit)) == credit and int(credit) > 0,
            'credit/debit/award mismatch')
    require(signatures in (3, 4) and len(negative) in (5, 7, 8), 'incomplete verification output')
    return dict(case=purpose, checkedAtUtc=checked_at, sendHash=proof['sendHash'],
                senderDebitAtomic=debit, workerCreditAtomic=credit, creditType=credit_type,
                creditHash=credit_hash, nativeBlockSignaturesChecked=signatures,
                tamperChecksRejected=len(negative), rpcEndpointsReportingConfirmation=rpc_reports)


def assemble(rows, verify, probe=public_receipt_probe):
    # Reuse the public discovery example's shape, state and uniqueness checks.
    DISCOVERY['summarize']([], [], rows)
    output, paid = [], set()
    amounts, counts = defaultdict(int), Counter()
    for record in sorted(rows, key=lambda r: (r['task']['closedAt'] or '', r['task']['taskId'])):
        t, summary = record['task'], record['receipt']
        task_id, state, asset = (t[k] for k in ('taskId', 'state', 'asset'))
        receipt_url = f'{API}/tasks/{task_id}/receipt'
        row = {k: t[k] for k in ('taskId', 'title', 'state', 'asset', 'closedAt')}
        row.update(workerVisible=record['worker'] is not None,
                   receiptSummary=summary, receiptUrl=receipt_url if state == 'COMPLETED' else None,
                   receiptProbeHttpStatus=None, payment=None)
        if task_id in CASES:
            require(state == 'COMPLETED' and isinstance(summary, dict) and summary['outcome'] == 'ACCEPTED',
                    'known case missing its completed row or receipt summary')
            payment = payout(t, summary, verify(task_id))
            row['payment'] = payment
            row['evidenceStatus'] = 'signed_receipt_and_native_blocks_verified'
            send_hash = payment['sendHash']
            credit = payment['workerCreditAtomic']
            if not isinstance(send_hash, str) or not isinstance(credit, str):
                raise ValueError('invalid verification output types')
            key = (asset, send_hash.lower())
            require(key not in paid, 'duplicate verified payment hash')
            paid.add(key)
            amounts[asset] += int(credit)
            counts[asset] += 1
        elif state == 'COMPLETED' and summary is None:
            try:
                status = probe(receipt_url)
            except HTTPError as exc:
                with exc:
                    if exc.code != 404:
                        raise
                    status = exc.code
            row['receiptProbeHttpStatus'] = status
            row['evidenceStatus'] = ('no_public_summary_receipt_404' if status == 404
                                     else 'no_public_summary_receipt_not_verified')
        elif state == 'COMPLETED':
            row['evidenceStatus'] = 'completed_summary_not_checked'
        else:
            row['evidenceStatus'] = 'not_a_completed_row'
        output.append(row)
    require(CASES.keys() <= {r['taskId'] for r in output}, 'known payout absent from visible history')
    totals = {asset: {'verifiedCredits': counts[asset], 'creditSumAtomic': str(amounts[asset]),
                      'atomicUnitsPerUnit': str(10**DECIMALS[asset])} for asset in sorted(counts)}
    return output, totals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nano-lib', type=Path, required=True, help='locally built Nano verifier library')
    parser.add_argument('--limit', type=int, default=24, help='public history page size (1–100)')
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error('limit must be between 1 and 100')
    library = args.nano_lib.resolve(strict=True)
    started = datetime.now(UTC).isoformat()
    rows, pages = DISCOVERY['pages']('task-history', args.limit, DISCOVERY['get_page'])
    entries, totals = assemble(rows, lambda task_id: run_case(task_id, library))
    states = Counter(r['state'] for r in entries)
    print(json.dumps(dict(schema='pactrover-public-payout-snapshot-v1',
                          startedAtUtc=started, finishedAtUtc=datetime.now(UTC).isoformat(),
                          source=f'{API}/discovery/task-history', pageSize=args.limit,
                          pagesRead=pages, paginationExhausted=True, platformTotalKnown=False,
                          independentlyVerifiedConsensus=False, payoutAttemptCount=None,
                          visibleRowsByState=dict(states), verifiedWorkerCreditsByAsset=totals,
                          rows=entries), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError, KeyError) as exc:
        sys.exit(f'No payout snapshot produced: {exc}')
