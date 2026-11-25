"""Regression checks using synthetic ledgers, not LLMRT's data."""

import json
from typing import Any
import unittest

from check_breakdown import check


def fixture():
    a = dict(network='A', component='First', repo='repo-a', commit='pin-a')
    b = dict(network='A', component='Second', repo='repo-b', commit='pin-b')
    group = dict(network='Shared', component='Common', repo='multiple', commit='multiple')
    date = '2026-01-01T00:00:00Z'
    manifest: dict[str, Any] = dict(measurement_date=date, repositories=[dict(a, language='hint'), b])
    summary: dict[str, Any] = dict(
        measurement_date=date,
        network_totals={'A': 9, 'Shared': 3},
        network_footprint={'A': {'unique': 9, 'shared': 3, 'footprint': 12}},
        network_unique_total=9, shared_total=3, overall_unique_total=12,
        component_totals=[dict(a, language='go', code_lines=4),
                          dict(b, language='rust', code_lines=5),
                          dict(group, language='go', code_lines=3),
                          dict(group, language='c', code_lines=0)],
        component_unique_totals=[dict(network='A', component='First', code_lines=4),
                                 dict(network='A', component='Second', code_lines=5)],
        component_footprint=[dict(network='A', component='First', unique=4, shared=3, footprint=7),
                             dict(network='A', component='Second', unique=5, shared=3, footprint=8)],
        language_totals={'go': 7, 'rust': 5},
    )
    files = {
        'counts.csv': (
            'network,component,repo,commit,language,file,code_lines,status,'
            'content_sha256,shared_components,shared_files\n'
            'A,First,repo-a,pin-a,go,a.go,4,counted,h1,,\n'
            'A,Second,repo-b,pin-b,rust,b.rs,5,counted,h2,,\n'
            'A,Second,repo-b,pin-b,python,test.py,0,skipped,,,\n'
            'Shared,Common,multiple,multiple,go,both.go,3,counted,h3,A/First;A/Second,ref\n'
            'Shared,Common,multiple,multiple,c,zero.c,0,counted,h4,A/First;A/Second,ref0\n'
        ).encode(),
        'shared.csv': (
            'shared_component,file,language,code_lines,content_sha256,affected_components,reference_files\n'
            'Common,both.go,go,3,h3,A/First;A/Second,ref\n'
        ).encode(),
    }
    return files, manifest, summary


class BreakdownTest(unittest.TestCase):
    def setUp(self):
        self.files, self.manifest, self.summary = fixture()

    def run_check(self):
        self.files['summary.json'] = json.dumps(self.summary).encode()
        return check(self.files, self.manifest)

    def test_shared_row_once_globally_but_in_both_component_footprints(self):
        self.assertEqual(self.run_check(), ({('A', 'First'): (4, 3, 7),
                                             ('A', 'Second'): (5, 3, 8)},
                                            {'go': 7, 'rust': 5}, 4))

    def test_different_manifest_commit(self):
        self.manifest['repositories'][1]['commit'] = 'wrong-pin'
        with self.assertRaisesRegex(ValueError, 'pins disagree'):
            self.run_check()

    def test_bad_footprint_that_leaves_network_summary_untouched(self):
        self.summary['component_footprint'][0].update(shared=0, footprint=4)
        with self.assertRaisesRegex(ValueError, 'component_footprint disagrees'):
            self.run_check()

    def test_shared_language_cannot_be_counted_twice(self):
        self.summary['language_totals']['go'] += 3
        with self.assertRaisesRegex(ValueError, 'language_totals disagrees'):
            self.run_check()

    def test_missing_zero_line_language_row(self):
        self.summary['component_totals'].pop()
        with self.assertRaisesRegex(ValueError, 'component_totals disagrees'):
            self.run_check()

    def test_duplicate_component_summary_row(self):
        self.summary['component_unique_totals'].append(self.summary['component_unique_totals'][0])
        with self.assertRaisesRegex(ValueError, 'duplicate key'):
            self.run_check()


if __name__ == '__main__':
    unittest.main()
