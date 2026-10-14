import argparse
import csv
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from generator.generate import run
from services.data.ingestion.validator import BatchValidator, sha256


class NegativeIngestionTests(unittest.TestCase):
    def batch(self, root):
        inbound = root / 'inbound'
        run(argparse.Namespace(seed=20260906, customers=20, as_of_date=date(2026, 9, 6),
                               output_dir=inbound, ground_truth_dir=root / 'truth'))
        return inbound

    def mutate(self, inbound, filename, change):
        path = inbound / filename
        with path.open(newline='', encoding='utf-8') as stream:
            rows = list(csv.DictReader(stream))
            fields = stream.seek(0) or next(csv.reader(stream))
        change(rows)
        with path.open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
            writer.writeheader()
            writer.writerows(rows)
        manifest_path = inbound / 'generation_manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['tables'][filename]['sha256'] = sha256(path)
        manifest['checksums_sha256'][filename] = sha256(path)
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        return BatchValidator().validate(inbound)

    def test_duplicate_primary_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbound = self.batch(Path(tmp))
            report = self.mutate(inbound, 'branches.csv', lambda rows: rows.append(dict(rows[0])))
            self.assertIn('duplicate_primary_key', report.errors)

    def test_unknown_foreign_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbound = self.batch(Path(tmp))
            report = self.mutate(inbound, 'crm_customers.csv', lambda rows: rows[0].update(preferred_branch_code='BR-X'))
            self.assertIn('foreign_key', report.errors)

    def test_invalid_type_enum_and_temporal(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbound = self.batch(Path(tmp))
            report = self.mutate(inbound, 'crm_customers.csv', lambda rows: rows[0].update(
                birth_month='13', status='INVALID', source_updated_at='2020-01-01T00:00:00+07:00'))
            self.assertIn('invalid_birth_month', report.errors)
            self.assertIn('invalid_enum', report.errors)
            self.assertIn('timestamp_outside_window', report.errors)

    def test_membership_chain_and_chronology(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbound = self.batch(Path(tmp))
            report = self.mutate(inbound, 'membership_events.csv',
                                 lambda rows: rows[0].update(expires_at=rows[0]['period_start']))
            self.assertIn('membership_period', report.errors)
        with tempfile.TemporaryDirectory() as tmp:
            inbound = self.batch(Path(tmp))
            report = self.mutate(inbound, 'crm_customers.csv',
                                 lambda rows: rows[0].update(source_updated_at='2025-03-07T00:00:00+07:00',
                                                             join_date='2026-09-06'))
            self.assertIn('update_before_join', report.errors)

    def test_visit_transaction_relationship(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbound = self.batch(Path(tmp))
            report = self.mutate(inbound, 'customer_visits.csv',
                                 lambda rows: rows[0].update(branch_code='BR-99'))
            self.assertIn('foreign_key', report.errors)

    def test_header_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbound = self.batch(Path(tmp))
            path = inbound / 'branches.csv'
            path.write_text(path.read_text(encoding='utf-8').replace('branch_name', 'wrong_name', 1), encoding='utf-8')
            manifest_path = inbound / 'generation_manifest.json'
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest['tables']['branches.csv']['sha256'] = sha256(path)
            manifest['checksums_sha256']['branches.csv'] = sha256(path)
            manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
            self.assertIn('header_mismatch', BatchValidator().validate(inbound).errors)


if __name__ == '__main__':
    unittest.main()
