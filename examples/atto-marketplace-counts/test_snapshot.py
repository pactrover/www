import unittest
from unittest.mock import patch
from uuid import UUID

from snapshot import pages, snapshot, summarize


def uid(number):
    return str(UUID(int=number))


def agent(number):
    return {'agentId': uid(number)}


def listing(number, requester, state='OPEN'):
    return {'taskId': uid(number), 'requesterAgentId': uid(requester), 'state': state}


def closed(number, state='COMPLETED', worker=None, outcome=None):
    return {'task': listing(number, 3, state), 'worker': None if worker is None else agent(worker),
            'receipt': None if outcome is None else {'receiptId': uid(1000 + number), 'outcome': outcome}}


class SnapshotTests(unittest.TestCase):
    def test_visible_counts_do_not_equate_completed_with_a_receipt_or_payment(self):
        result = summarize(
            [agent(1), agent(2)], [listing(51, 3), listing(52, 3), listing(53, 8)],
            [closed(61, worker=1, outcome='ACCEPTED'), closed(62, worker=1, outcome='ACCEPTED'),
             closed(63, worker=4, outcome='ACCEPTED'), closed(64),
             closed(65, worker=2, outcome='NOT_ACCEPTED'), closed(66, worker=2),
             closed(67, outcome='ACCEPTED'), closed(68, 'CANCELLED', 2, 'ACCEPTED'),
             closed(69, 'EXPIRED')])
        self.assertEqual(result, {
            'published_profiles': 2,
            'published_profiles_matching_an_accepted_completed_worker': 1,
            'visible_workers_with_an_accepted_completed_task': 2,
            'open_tasks': 3, 'requesters_with_open_tasks': 2,
            'largest_open_task_count_by_one_requester': 2,
            'visible_terminal_tasks': {'COMPLETED': 7, 'CANCELLED': 1, 'EXPIRED': 1},
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
            return {'items': [], 'nextCursor': None}

        result = snapshot(1, fetch)
        self.assertEqual(calls, [('agents', {'limit': 1}), ('agents', {'limit': 1, 'cursor': token}),
                                 ('tasks', {'limit': 1}), ('task-history', {'limit': 1})])
        self.assertEqual(result['counts']['published_profiles'], 2)
        self.assertEqual(result['counts']['largest_open_task_count_by_one_requester'], 0)
        self.assertEqual(result['pages_read'], {'agents': 2, 'tasks': 1, 'task-history': 1})

    def test_rejects_duplicate_ids_and_cross_feed_state_drift(self):
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            summarize([agent(1), agent(1)], [], [])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            summarize([], [], [closed(51), closed(51, 'CANCELLED')])
        with self.assertRaisesRegex(ValueError, 'state changed'):
            summarize([], [listing(51, 3)], [closed(51)])

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


if __name__ == '__main__':
    unittest.main()
