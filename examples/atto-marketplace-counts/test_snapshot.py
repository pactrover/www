import unittest
from unittest.mock import patch
from uuid import UUID

from snapshot import pages, snapshot, summarize


def uid(number):
    return str(UUID(int=number))


def agent(number):
    return {'agentId': uid(number)}


def listing(number, requester, state='OPEN', asset='ATTO'):
    return {'taskId': uid(number), 'requesterAgentId': uid(requester), 'state': state, 'asset': asset}


def closed(number, state='COMPLETED', worker=None, outcome=None, asset='ATTO'):
    return {'task': listing(number, 3, state, asset), 'worker': None if worker is None else agent(worker),
            'receipt': None if outcome is None else {'receiptId': uid(1000 + number), 'outcome': outcome}}


class SnapshotTests(unittest.TestCase):
    def test_visible_counts_do_not_equate_completed_with_a_receipt_or_payment(self):
        result = summarize(
            [agent(1), agent(2)], [listing(51, 3), listing(52, 3), listing(53, 8, asset='XNO'),
                                  listing(54, 3, 'IN_PROGRESS'), listing(55, 9, 'IN_PROGRESS', 'XNO')],
            [closed(61, worker=1, outcome='ACCEPTED'), closed(62, worker=1, outcome='ACCEPTED', asset='XNO'),
             closed(63, worker=4, outcome='ACCEPTED'), closed(64),
             closed(65, worker=2, outcome='NOT_ACCEPTED'), closed(66, worker=2),
             closed(67, outcome='ACCEPTED'), closed(68, 'CANCELLED', 2, 'ACCEPTED'),
             closed(69, 'EXPIRED', asset='XNO')])
        self.assertEqual(result, {
            'published_profiles': 2,
            'published_profiles_matching_an_accepted_completed_worker': 1,
            'visible_workers_with_an_accepted_completed_task': 2,
            'open_tasks': 3, 'visible_in_progress_tasks': 2, 'requesters_with_open_tasks': 2,
            'largest_open_task_count_by_one_requester': 2,
            'visible_terminal_tasks': {'COMPLETED': 7, 'CANCELLED': 1, 'EXPIRED': 1},
            'visible_task_counts_by_asset': {
                'ATTO': {'OPEN': 2, 'IN_PROGRESS': 1, 'COMPLETED': 6, 'CANCELLED': 1, 'EXPIRED': 0},
                'XNO': {'OPEN': 1, 'IN_PROGRESS': 1, 'COMPLETED': 1, 'CANCELLED': 0, 'EXPIRED': 1},
            },
            'completed_with_accepted_receipt_summary': 4,
            'completed_without_public_receipt_summary': 2,
            'completed_without_public_worker': 2,
        })

    def test_follows_each_opaque_cursor_exactly_until_null(self):
        calls = []
        token = 'opaque+/?&=%'

        def fetch(collection, params):
            calls.append((collection, params))
            if collection == 'agents':
                if 'cursor' not in params:
                    return {'items': [agent(1)], 'nextCursor': token}
                return {'items': [agent(2)], 'nextCursor': None}
            if collection == 'tasks':
                if 'cursor' not in params:
                    return {'items': [listing(51, 3)], 'nextCursor': token}
                return {'items': [listing(52, 7, 'IN_PROGRESS', 'XNO')], 'nextCursor': None}
            return {'items': [], 'nextCursor': None}

        result = snapshot(1, fetch)
        self.assertEqual(calls, [('agents', {'limit': 1}), ('agents', {'limit': 1, 'cursor': token}),
                                 ('tasks', {'limit': 1, 'includeInProgress': 'true'}),
                                 ('tasks', {'limit': 1, 'includeInProgress': 'true', 'cursor': token}),
                                 ('task-history', {'limit': 1})])
        self.assertEqual(result['counts']['published_profiles'], 2)
        self.assertEqual(result['counts']['largest_open_task_count_by_one_requester'], 1)
        self.assertEqual(result['counts']['visible_in_progress_tasks'], 1)
        self.assertEqual(result['pages_read'], {'agents': 2, 'tasks': 2, 'task-history': 1})

    def test_rejects_duplicate_ids_and_cross_feed_state_drift(self):
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            summarize([agent(1), agent(1)], [], [])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            summarize([], [], [closed(51), closed(51, 'CANCELLED')])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            summarize([], [listing(51, 3), listing(51, 3, 'IN_PROGRESS')], [])
        for state in ('OPEN', 'IN_PROGRESS'):
            with self.subTest(state=state), self.assertRaisesRegex(ValueError, 'state changed'):
                summarize([], [listing(51, 3, state)], [closed(51)])

    def test_rejects_missing_invalid_and_repeated_cursors(self):
        for page in ({'items': []}, {'items': [], 'nextCursor': 1}, {'items': [], 'nextCursor': ''}):
            with self.subTest(page=page), self.assertRaisesRegex(ValueError, 'nextCursor|invalid'):
                pages('agents', 1, lambda *_: page)
        with self.assertRaisesRegex(ValueError, 'repeated'):
            pages('agents', 1, lambda *_: {'items': [], 'nextCursor': 'repeat'})

    def test_rejects_a_truncated_crawl_and_oversized_page(self):
        with patch('snapshot.MAX_PAGES', 1), self.assertRaisesRegex(ValueError, 'page limit exceeded'):
            pages('agents', 1, lambda *_: {'items': [agent(1)], 'nextCursor': 'more'})
        with self.assertRaisesRegex(ValueError, 'exceeds requested limit'):
            pages('agents', 1, lambda *_: {'items': [agent(1), agent(2)], 'nextCursor': None})

    def test_wrong_states_and_malformed_fields_do_not_turn_into_zeros(self):
        with self.assertRaisesRegex(ValueError, 'expected OPEN'):
            summarize([], [listing(51, 3, 'COMPLETED')], [])
        with self.assertRaisesRegex(ValueError, 'unexpected task state'):
            summarize([], [], [closed(51, 'OPEN')])
        with self.assertRaisesRegex(ValueError, 'missing required field'):
            summarize([], [], [{'task': listing(51, 3, 'COMPLETED'), 'receipt': None}])
        with self.assertRaisesRegex(ValueError, 'expected canonical UUID'):
            summarize([{'agentId': 'not-an-id'}], [], [])

    def test_rejects_missing_and_unknown_assets_in_both_task_feeds(self):
        row = listing(51, 3)
        del row['asset']
        with self.assertRaisesRegex(ValueError, 'missing required field: asset'):
            summarize([], [row], [])
        with self.assertRaisesRegex(ValueError, 'tasks: unexpected task asset'):
            summarize([], [listing(51, 3, asset='OTHER')], [])
        with self.assertRaisesRegex(ValueError, 'task-history: unexpected task asset'):
            summarize([], [], [closed(61, asset='OTHER')])


if __name__ == '__main__':
    unittest.main()
