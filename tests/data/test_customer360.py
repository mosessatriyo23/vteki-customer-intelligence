import argparse
import csv
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from generator.generate import run as generate
from services.data.customer360.profile import build_profiles
from services.data.identity.cli import run as resolve


class Customer360Tests(unittest.TestCase):
    def test_generated_snapshot_cutoff_and_integrity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); inbound = root / 'inbound'; output = root / 'resolution'
            generate(argparse.Namespace(seed=20260906, customers=20, as_of_date=date(2026, 9, 6),
                                        output_dir=inbound, ground_truth_dir=root / 'truth'))
            resolve(inbound / 'crm_customers.csv', output, synthetic_aliases=True)
            cutoff = datetime.fromisoformat('2026-06-01T00:00:00+07:00')
            profiles = build_profiles(inbound, output, cutoff)
            self.assertTrue(profiles)
            self.assertTrue(all(r['first_join_date'] <= '2026-06-01' for r in profiles))
            self.assertTrue(all(not r['last_transaction_at'] or datetime.fromisoformat(r['last_transaction_at']) <= cutoff for r in profiles))
            self.assertTrue(all(r['identity_status'] in {'PROVISIONAL', 'REVIEW_REQUIRED'} for r in profiles))
            # Future transaction amounts must not alter historical retained revenue.
            path = inbound / 'transactions.csv'
            with path.open(newline='', encoding='utf-8') as stream:
                reader = csv.DictReader(stream); fields = reader.fieldnames; rows = list(reader)
            for row in rows:
                if datetime.fromisoformat(row['transaction_datetime']) > cutoff:
                    row['actual_revenue'] = '999999999'
            with path.open('w', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
            self.assertEqual(profiles, build_profiles(inbound, output, cutoff))
            with self.assertRaisesRegex(ValueError, 'timezone'):
                build_profiles(inbound, output, datetime(2026, 6, 1))
            (output / 'mapping.csv').write_text('corrupted', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                build_profiles(inbound, output, cutoff)
