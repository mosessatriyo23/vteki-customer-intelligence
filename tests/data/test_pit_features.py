import argparse
import csv
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from generator.generate import run as generate
from services.data.features.cli import run
from services.data.features.snapshot import build_features, validate_cutoffs
from services.data.identity.cli import run as resolve
from services.data.ingestion.validator import sha256


class HistoricalFeatureTests(unittest.TestCase):
    def test_cutoff_validation(self):
        early = datetime.fromisoformat("2026-05-01T00:00:00+07:00")
        late = datetime.fromisoformat("2026-06-01T00:00:00+07:00")
        self.assertEqual(validate_cutoffs([late, early]), [early, late])
        for cutoffs in ([], [early, early], [datetime(2026, 6, 1)]):
            with self.assertRaises(ValueError):
                validate_cutoffs(cutoffs)

    def test_window_boundaries_dedup_and_future_exclusion(self):
        cutoff = datetime.fromisoformat("2026-06-01T12:00:00+07:00")
        base = dict(
            source_customer_ref="a",
            source_system="POS",
            branch_code="BR-01",
            channel_code="POS_STORE",
            gross_amount="100",
            discount_amount="0",
            net_amount="100",
            actual_revenue="100",
            status="COMPLETED",
        )
        transactions = [
            dict(base, transaction_datetime=(cutoff - timedelta(days=d)).isoformat())
            for d in (0, 60, 90, 365, -1)
        ]
        transactions.append(dict(transactions[0]))
        profile = dict(
            golden_customer_id="g",
            first_join_date="2024-01-01",
            identity_status="PROVISIONAL",
        )

        def read_fixture(path):
            if path.name == "mapping.csv":
                return [dict(source_customer_id="a", golden_customer_id="g")]
            return transactions

        with (
            patch(
                "services.data.segmentation.snapshot.build_profiles",
                return_value=[profile],
            ),
            patch("services.data.segmentation.snapshot.read", side_effect=read_fixture),
        ):
            row = build_features(Path("inbound"), Path("resolution"), [cutoff])[0]
        self.assertEqual(row["purchase_count_60d"], 1)
        self.assertEqual(row["purchase_count_90d"], 2)
        self.assertEqual(row["purchase_count_365d"], 3)
        self.assertEqual(row["retained_revenue_365d"], 300)
        self.assertEqual(row["recency_days"], 0)

    def test_cli_manifest_and_future_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inbound = root / "inbound"
            resolution = root / "resolution"
            generate(
                argparse.Namespace(
                    seed=20260906,
                    customers=20,
                    as_of_date=date(2026, 9, 6),
                    output_dir=inbound,
                    ground_truth_dir=root / "truth",
                )
            )
            resolve(inbound / "crm_customers.csv", resolution, synthetic_aliases=True)
            early = datetime.fromisoformat("2026-06-01T00:00:00+07:00")
            late = datetime.fromisoformat("2026-09-06T23:59:59+07:00")
            output = root / "features"
            result = run(inbound, resolution, output, [late, early])
            self.assertEqual(result["training_ready"], False)
            manifest = json.loads(
                (output / "feature_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest["output_sha256"]["features.csv"],
                sha256(output / "features.csv"),
            )
            self.assertEqual(manifest["cutoffs"], [early.isoformat(), late.isoformat()])
            with (output / "features.csv").open(newline="", encoding="utf-8") as stream:
                original = list(csv.DictReader(stream))
            self.assertEqual(len(original), result["rows"])
            self.assertTrue(all(r["training_ready"] == "False" for r in original))
            self.assertTrue(
                all(
                    r["identity_time_policy"] == "CURRENT_SNAPSHOT_RETROSPECTIVE"
                    for r in original
                )
            )
            expected = [
                {key: "" if value is None else str(value) for key, value in row.items()}
                for row in build_features(inbound, resolution, [early])
            ]
            self.assertEqual(
                [r for r in original if r["cutoff_at"] == early.isoformat()], expected
            )
            path = inbound / "transactions.csv"
            with path.open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                fields = reader.fieldnames
                transactions = list(reader)
            for transaction in transactions:
                if datetime.fromisoformat(transaction["transaction_datetime"]) > early:
                    transaction["actual_revenue"] = "999999999"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(transactions)
            early_rows = build_features(inbound, resolution, [early])
            self.assertEqual(
                [
                    {k: "" if v is None else str(v) for k, v in r.items()}
                    for r in early_rows
                ],
                [r for r in original if r["cutoff_at"] == early.isoformat()],
            )
            with self.assertRaisesRegex(ValueError, "cannot be overwritten"):
                run(inbound, resolution, output, [early])
            with self.assertRaisesRegex(ValueError, "Inbound validation failed"):
                run(inbound, resolution, root / "invalid", [early])
            self.assertFalse((root / "invalid").exists())


if __name__ == "__main__":
    unittest.main()
