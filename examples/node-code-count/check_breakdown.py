#!/usr/bin/env python3
"""Check the published v6 repository pins, component counts and language totals."""

import argparse
from collections import Counter
import csv
from hashlib import sha256
import json
from pathlib import Path
import sys

import check_totals

MANIFEST_SHA256 = 'cf4ff95e896e8d6f65b92e132517088aa89cad2dfb2fe09b0c606197b38ccfb4'
COMPONENT = ('network', 'component')
PIN = (*COMPONENT, 'repo', 'commit')
COMPONENT_LANGUAGE = (*PIN, 'language')


def load(directory):
    files = check_totals.load(directory)
    raw = (directory / 'manifest.json').read_bytes()
    check_totals.require(sha256(raw).hexdigest() == MANIFEST_SHA256,
                         'manifest.json: SHA-256 mismatch')
    return files, json.loads(raw)


def indexed(rows, key_fields, value_fields, name):
    result = {}
    for row in rows:
        key = tuple(row[field] for field in key_fields)
        check_totals.require(key not in result, f'{name}: duplicate key {key!r}')
        result[key] = tuple(row[field] for field in value_fields)
    return result


def check(files, manifest):
    check_totals.check(files)  # Also reconcile the network totals and both shared ledgers.
    summary = json.loads(files['summary.json'])
    check_totals.require(manifest['measurement_date'] == summary['measurement_date'],
                         'manifest date disagrees with summary')
    pins = indexed(manifest['repositories'], COMPONENT, ('repo', 'commit'), 'manifest')

    ledger_pins = set()
    by_component_language, exclusive, shared, by_language = (Counter() for _ in range(4))
    for row in check_totals.csv_rows(files['counts.csv']):
        component = tuple(row[field] for field in COMPONENT)
        if row['network'] != 'Shared':
            ledger_pins.add(tuple(row[field] for field in PIN))
            exclusive[component] += int(row['code_lines'])
        if row['status'] != 'counted':
            continue
        lines = int(row['code_lines'])
        # The summary retains counted zero-line component/language rows, but
        # skipped rows contribute no language credit.
        by_component_language[tuple(row[field] for field in COMPONENT_LANGUAGE)] += lines
        if lines:
            by_language[row['language']] += lines
            if row['network'] == 'Shared':
                for ref in set(row['shared_components'].split(';')):
                    shared[tuple(ref.split('/', 1))] += lines

    check_totals.require(ledger_pins == {key + value for key, value in pins.items()},
                         'ledger repository pins disagree with manifest')
    footprints = {key: (lines, shared[key], lines + shared[key])
                  for key, lines in exclusive.items()}
    checks = (
        ('component_totals', COMPONENT_LANGUAGE, ('code_lines',),
         {key: (lines,) for key, lines in by_component_language.items()}),
        ('component_unique_totals', COMPONENT, ('code_lines',),
         {key: (lines,) for key, lines in exclusive.items()}),
        ('component_footprint', COMPONENT, ('unique', 'shared', 'footprint'), footprints),
    )
    for name, key_fields, value_fields, actual in checks:
        expected = indexed(summary[name], key_fields, value_fields, name)
        check_totals.require(actual == expected, f'{name} disagrees with ledger')
    check_totals.require(dict(by_language) == summary['language_totals'],
                         'language_totals disagrees with ledger')
    return footprints, dict(by_language), len(by_component_language)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data_directory', type=Path, help='directory with the four exact v6 files')
    args = parser.parse_args()
    try:
        footprints, languages, groups = check(*load(args.data_directory))
    except (OSError, ValueError, KeyError, TypeError, csv.Error) as error:
        print(f'Check failed: {error}', file=sys.stderr)
        return 1
    print(f'{len(footprints)} repository pins and component footprints, '
          f'{groups} component/language rows and {len(languages)} language totals match.')
    print('\nNetwork / Component                         Exclusive   Shared   Footprint')
    for (network, component), (exclusive, shared, footprint) in sorted(footprints.items()):
        print(f"{f'{network} / {component}':42} {exclusive:9,} {shared:8,} {footprint:11,}")
    print('\nLanguage totals (shared lines counted once):')
    for name, lines in sorted(languages.items()):
        print(f'{name:16} {lines:9,}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
