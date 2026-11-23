#!/usr/bin/env python3
"""Re-add LLMRT's published v6 counts. Reads three local data files only."""

import argparse
from collections import Counter, defaultdict
import csv
from hashlib import sha256
import io
import json
from pathlib import Path
import sys

HASHES = {
    'counts.csv': 'c770e4692ef4a8466c04d98b7412d9ae4524848bdc31c13bb7cfc0b50dd0bb0e',
    'shared.csv': '48694c05732537e0ea188cfe3d73962c55cf9347ec3ca72fd76ed4a254ed29c8',
    'summary.json': '7d47d18402279b8c8e7bfa877ecb694eb3fadbbe6699427a645189e49a1d00c5',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load(directory):
    files = {}
    for name, expected in HASHES.items():
        raw = (directory / name).read_bytes()
        require(sha256(raw).hexdigest() == expected, f'{name}: SHA-256 mismatch')
        files[name] = raw
    return files


def csv_rows(raw):
    return csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''), strict=True)


def check(files):
    summary = json.loads(files['summary.json'])
    exclusive = Counter()
    shared_by_network = Counter()
    affected_components = defaultdict(set)
    pins, shared_rows = set(), Counter()
    row_count = 0
    for row in csv_rows(files['counts.csv']):
        row_count += 1
        network, component = row['network'], row['component']
        lines = int(row['code_lines'])
        status = row['status']
        require(lines >= 0 and status in ('counted', 'skipped'), f'invalid count on row {row_count}')
        if network == 'Shared':
            require(status == 'counted', f'uncounted Shared row {row_count}')
            # The companion ledger lists positive-credit rows only.
            if lines:
                shared_rows[(component, row['file'], row['language'], lines, row['content_sha256'],
                             row['shared_components'], row['shared_files'])] += 1
        else:
            affected_components[network].add(component)
            pins.add((row['repo'], row['commit']))
            require(status != 'skipped' or lines == 0, f'skipped row {row_count} has credit')
            exclusive[network] += lines

    shared_csv = Counter(
        (row['shared_component'], row['file'], row['language'], int(row['code_lines']),
         row['content_sha256'], row['affected_components'], row['reference_files'])
        for row in csv_rows(files['shared.csv'])
    )
    require(shared_csv == shared_rows, 'shared.csv does not match the Shared rows in counts.csv')

    shared_total = 0
    for (_, _, _, lines, _, affected, _), multiplicity in shared_rows.items():
        networks = set()
        for ref in affected.split(';'):
            network, component = ref.split('/', 1)
            require(component in affected_components.get(network, ()), f'unknown shared reference {ref}')
            networks.add(network)
        # Count each shared file once per affected network, even if two components refer to it.
        for network in networks:
            shared_by_network[network] += lines * multiplicity
        shared_total += lines * multiplicity

    network_totals = dict(exclusive, Shared=shared_total)
    footprint = {name: {'unique': unique, 'shared': shared_by_network[name],
                        'footprint': unique + shared_by_network[name]}
                 for name, unique in exclusive.items()}
    require(network_totals == summary['network_totals'], 'exclusive/shared totals disagree with summary')
    require(footprint == summary['network_footprint'], 'network footprints disagree with summary')
    totals = sum(exclusive.values()), shared_total, sum(network_totals.values())
    require(totals == tuple(summary[key] for key in ('network_unique_total', 'shared_total',
                                                    'overall_unique_total')), 'grand totals disagree')
    return row_count, len(pins), footprint, totals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data_directory', type=Path, help='directory with the three exact v6 files')
    args = parser.parse_args()
    try:
        rows, pins, footprint, totals = check(load(args.data_directory))
    except (OSError, ValueError, KeyError, TypeError, csv.Error) as error:
        print(f'Check failed: {error}', file=sys.stderr)
        return 1
    print(f'{rows:,} ledger rows; {pins} repository pins; {len(footprint)} network totals and footprints match.')
    print(f'{totals[0]:,} exclusive + {totals[1]:,} shared once = {totals[2]:,} unique lines.')
    print('\nNetwork                  Exclusive   Shared   Footprint')
    for name, values in sorted(footprint.items()):
        print(f"{name:24} {values['unique']:9,} {values['shared']:8,} {values['footprint']:11,}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
