import argparse
import csv
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from generator.generate import run as generate
from services.data.eda.cli import run
from services.data.eda.report import summarize
from services.data.ingestion.validator import sha256


class EdaTests(unittest.TestCase):
    def test_validated_outputs_and_future_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbound = root / "inbound"
            generate(
                argparse.Namespace(
                    seed=20260906,
                    customers=20,
                    as_of_date=date(2026, 9, 6),
                    output_dir=inbound,
                    ground_truth_dir=root / "truth",
                )
            )
            cutoff = datetime.fromisoformat("2026-06-01T00:00:00+07:00")
            first = summarize(inbound, cutoff)
            self.assertEqual(
                sum(first["source_purchase_frequency"].values()),
                first["eligible_source_identities"],
            )
            self.assertEqual(
                first["totals"]["qualifying_purchases"],
                sum(r["purchases"] for r in first["groups"]["month"]),
            )
            output = root / "report"
            run(inbound, cutoff, output)
            manifest = json.loads(
                (output / "eda_manifest.json").read_text(encoding="utf-8")
            )
            for name, digest in manifest["output_sha256"].items():
                self.assertEqual(digest, sha256(output / name))
            self.assertNotIn(
                "full_name", (output / "summary.json").read_text(encoding="utf-8")
            )
            with self.assertRaisesRegex(ValueError, "must not be overwritten"):
                run(inbound, cutoff, output)

            path = inbound / "transactions.csv"
            with path.open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                fields = reader.fieldnames
                rows = list(reader)
            for row in rows:
                if datetime.fromisoformat(row["transaction_datetime"]) > cutoff:
                    row["actual_revenue"] = "999999999"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            self.assertEqual(first, summarize(inbound, cutoff))

    def test_timezone_and_empty_transactions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbound = root / "inbound"
            generate(
                argparse.Namespace(
                    seed=1,
                    customers=1,
                    as_of_date=date(2026, 9, 6),
                    output_dir=inbound,
                    ground_truth_dir=root / "truth",
                )
            )
            path = inbound / "transactions.csv"
            with path.open(newline="", encoding="utf-8") as stream:
                fields = csv.DictReader(stream).fieldnames
            with path.open("w", newline="", encoding="utf-8") as stream:
                csv.DictWriter(stream, fieldnames=fields).writeheader()
            result = summarize(
                inbound, datetime.fromisoformat("2026-09-06T23:59:59+07:00")
            )
            self.assertEqual(result["totals"]["qualifying_purchases"], 0)
            with self.assertRaisesRegex(ValueError, "timezone"):
                summarize(inbound, datetime(2026, 9, 6))


if __name__ == "__main__":
    unittest.main()
