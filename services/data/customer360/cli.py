"""Build development Customer360 snapshots from validated source and resolver output."""
import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from .profile import build_profiles

FIELDS = ('golden_customer_id', 'cutoff_at', 'identity_status', 'source_identity_count',
          'first_join_date', 'transaction_count', 'retained_revenue', 'last_transaction_at',
          'visit_count', 'renewal_count')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--inbound', type=Path, required=True)
    parser.add_argument('--resolution', type=Path, required=True)
    parser.add_argument('--cutoff-at', type=datetime.fromisoformat, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Customer360 output must not overwrite an existing snapshot')
    rows = build_profiles(args.inbound, args.resolution, args.cutoff_at)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + '.tmp')
    try:
        with temporary.open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator='\n')
            writer.writeheader(); writer.writerows(rows)
        temporary.replace(args.output)
    finally:
        temporary.unlink(missing_ok=True)
    print(json.dumps({'profiles': len(rows), 'cutoff_at': args.cutoff_at.isoformat()}))


if __name__ == '__main__':
    main()
