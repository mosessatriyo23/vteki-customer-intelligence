import argparse
import csv
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from generator.generate import run as generate
from services.data.identity.cli import run as resolve
from services.data.segmentation.snapshot import build_segments, lifecycle, score


class SegmentationTests(unittest.TestCase):
    def test_lifecycle_boundaries_priority_and_fallback(self):
        self.assertEqual(lifecycle(30, None, 0, 0, 0, False), 'NEW')
        self.assertEqual(lifecycle(31, None, 0, 0, 0, False), 'NEVER_TRANSACTED')
        for recency, label in ((90, 'OCCASIONAL'), (91, 'AT_RISK'), (180, 'AT_RISK'),
                               (181, 'DORMANT'), (365, 'DORMANT'), (366, 'CHURNED')):
            self.assertEqual(lifecycle(400, recency, 0, 0, 0, False), label)
        self.assertEqual(lifecycle(60, 1, 5, 5, 500000, False), 'LOYAL')
        self.assertEqual(lifecycle(59, 1, 3, 5, 500000, False), 'ACTIVE')
        self.assertEqual(lifecycle(400, 1, 5, 5, 500000, True), 'REACTIVATED')
        self.assertEqual(score(30, (31, 61, 91, 181), True), 5)
        self.assertEqual(score(181, (31, 61, 91, 181), True), 1)

    def test_future_mutation_isolation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); inbound = root / 'inbound'; resolution = root / 'identity'
            generate(argparse.Namespace(seed=20260906, customers=20, as_of_date=date(2026, 9, 6),
                                        output_dir=inbound, ground_truth_dir=root / 'truth'))
            resolve(inbound / 'crm_customers.csv', resolution, synthetic_aliases=True)
            cutoff = datetime.fromisoformat('2026-06-01T00:00:00+07:00')
            first = build_segments(inbound, resolution, cutoff)
            self.assertTrue(first)
            path = inbound / 'transactions.csv'
            with path.open(newline='', encoding='utf-8') as stream:
                reader = csv.DictReader(stream); fields = reader.fieldnames; rows = list(reader)
            for row in rows:
                if datetime.fromisoformat(row['transaction_datetime']) > cutoff:
                    row['actual_revenue'] = '999999999'
            with path.open('w', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
            self.assertEqual(first, build_segments(inbound, resolution, cutoff))
            self.assertTrue(all(1 <= row[key] <= 5 for row in first for key in ('r_score', 'f_score', 'm_score')))
            with self.assertRaises(ValueError):
                build_segments(inbound, resolution, cutoff, 30)
