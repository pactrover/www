#!/usr/bin/env python3
"""Count visible Marketplace profiles and tasks using anonymous GETs only."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import sys
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

BASE = 'https://api.atto.market/v1/discovery/'
COLLECTIONS = ('agents', 'tasks', 'task-history')
TERMINAL = ('COMPLETED', 'CANCELLED', 'EXPIRED')
MAX_PAGES = 100
MAX_PAGE_BYTES = 8 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def get_page(collection, params):
    request = Request(BASE + collection + '?' + urlencode(params),
                      headers={'Accept': 'application/json', 'Cache-Control': 'no-cache'},
                      method='GET')
    with build_opener(NoRedirect()).open(request, timeout=15) as response:
        if response.status != 200:
            raise ValueError(f'{collection}: expected HTTP 200')
        body = response.read(MAX_PAGE_BYTES + 1)
    if len(body) > MAX_PAGE_BYTES:
        raise ValueError(f'{collection}: response too large')
    return json.loads(body)


def pages(collection, limit, fetch):
    rows, cursors = [], set()
    params = {'limit': limit}
    for number in range(1, MAX_PAGES + 1):
        data = fetch(collection, dict(params))
        if not isinstance(data, dict) or not isinstance(data.get('items'), list) or 'nextCursor' not in data:
            raise ValueError(f'{collection}: missing items or nextCursor')
        if len(data['items']) > limit:
            raise ValueError(f'{collection}: page exceeds requested limit')
        rows.extend(data['items'])
        cursor = data['nextCursor']
        if cursor is None:
            return rows, number
        if not isinstance(cursor, str) or not cursor or cursor in cursors:
            raise ValueError(f'{collection}: invalid or repeated cursor')
        cursors.add(cursor)
        params['cursor'] = cursor
    raise ValueError(f'{collection}: page limit exceeded; not reporting partial counts')


def field(row, key):
    if not isinstance(row, dict) or key not in row:
        raise ValueError(f'missing required field: {key}')
    return row[key]


def id_field(row, key):
    val = field(row, key)
    if not isinstance(val, str):
        raise ValueError(f'{key}: expected canonical UUID')
    try:
        canonical = str(UUID(val))
    except ValueError:
        raise ValueError(f'{key}: expected canonical UUID') from None
    if canonical != val:
        raise ValueError(f'{key}: expected canonical UUID')
    return val


def add_unique(ids, key, scope):
    if key in ids:
        raise ValueError(f'{scope}: duplicate ID; retry a fresh crawl')
    ids.add(key)


def summarize(agents, opened, history):
    published, open_ids, history_ids, workers = set(), set(), set(), set()
    requesters, states = Counter(), Counter()
    accepted_summaries = missing_receipt = missing_worker = 0
    for row in agents:
        add_unique(published, id_field(row, 'agentId'), 'agents')
    for row in opened:
        if field(row, 'state') != 'OPEN':
            raise ValueError('tasks: expected OPEN with no includeInProgress filter')
        add_unique(open_ids, id_field(row, 'taskId'), 'tasks')
        requesters[id_field(row, 'requesterAgentId')] += 1
    for row in history:
        task = field(row, 'task')
        add_unique(history_ids, id_field(task, 'taskId'), 'task-history')
        state = field(task, 'state')
        if state not in TERMINAL:
            raise ValueError('task-history: unexpected task state')
        states[state] += 1
        if state != 'COMPLETED':
            continue
        worker, receipt = field(row, 'worker'), field(row, 'receipt')
        worker_id = id_field(worker, 'agentId') if worker is not None else None
        missing_worker += worker_id is None
        if receipt is None:
            missing_receipt += 1
            continue
        id_field(receipt, 'receiptId')
        outcome = field(receipt, 'outcome')
        if not isinstance(outcome, str) or not outcome:
            raise ValueError('task-history: malformed receipt outcome')
        if outcome == 'ACCEPTED':
            accepted_summaries += 1
            if worker_id is not None:
                workers.add(worker_id)
    if open_ids & history_ids:
        raise ValueError('task state changed during the crawl; retry for a fresh snapshot')
    return {
        'published_profiles': len(published),
        'published_profiles_matching_an_accepted_completed_worker': len(published & workers),
        'visible_workers_with_an_accepted_completed_task': len(workers),
        'open_tasks': len(open_ids),
        'requesters_with_open_tasks': len(requesters),
        'largest_open_task_count_by_one_requester': max(requesters.values(), default=0),
        'visible_terminal_tasks': {state: states[state] for state in TERMINAL},
        'completed_with_accepted_receipt_summary': accepted_summaries,
        'completed_without_public_receipt_summary': missing_receipt,
        'completed_without_public_worker': missing_worker,
    }


def snapshot(limit=24, fetch=get_page):
    start = datetime.now(timezone.utc).isoformat(timespec='seconds')
    results = {collection: pages(collection, limit, fetch) for collection in COLLECTIONS}
    counts = summarize(*(results[collection][0] for collection in COLLECTIONS))
    return {
        'kind': 'anonymous_public_discovery_snapshot_not_settlement_verification',
        'started_utc': start,
        'finished_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'source': BASE,
        'page_size': limit,
        'pages_read': {collection: result[1] for collection, result in results.items()},
        'counts': counts,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=24, help='page size (1–100, default 24)')
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error('--limit must be between 1 and 100')
    try:
        counts = snapshot(args.limit)
    except (OSError, ValueError) as exc:
        sys.exit(f'No snapshot produced: {exc}')
    print(json.dumps(counts, indent=2))


if __name__ == '__main__':
    main()
