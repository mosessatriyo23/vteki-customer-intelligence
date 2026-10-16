"""Development future labels and chronological standard-library baseline tests."""

import argparse
import csv
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from generator.generate import run as generate
from services.data.identity.cli import run as resolve
from services.data.ingestion.validator import sha256
from services.data.models.baseline import evaluate, temporal_split
from services.data.models.cli import run
from services.data.models.labels import build_labels, join_training_rows


class ModelBaselineTests(unittest.TestCase):
    def test_future_windows_and_incomplete_outcomes(self):
        cutoff = datetime.fromisoformat("2026-01-01T12:00:00+07:00")
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
            dict(
                base,
                transaction_datetime=(cutoff + timedelta(days=days)).isoformat(),
                actual_revenue=str(revenue),
                status=status,
            )
            for days, revenue, status in (
                (-365, 100, "COMPLETED"),
                (-1, 100, "COMPLETED"),
                (0, 100, "COMPLETED"),
                (1, 25, "PARTIAL_REFUND"),
                (90, 100, "COMPLETED"),
                (91, 100, "COMPLETED"),
                (2, 0, "REFUNDED"),
            )
        ]
        transactions.append(dict(transactions[3]))  # replay
        profiles = [dict(golden_customer_id="g"), dict(golden_customer_id="never")]

        def read_fixture(path):
            if path.name == "mapping.csv":
                return [dict(source_customer_id="a", golden_customer_id="g")]
            return transactions

        with tempfile.TemporaryDirectory() as tmp:
            inbound = Path(tmp)
            (inbound / "generation_manifest.json").write_text(
                json.dumps({"as_of_date": "2026-04-01"}), encoding="utf-8"
            )  # exactly 90 days after Jan 1
            with (
                patch(
                    "services.data.models.labels.build_profiles", return_value=profiles
                ),
                patch("services.data.models.labels.read", side_effect=read_fixture),
            ):
                rows = build_labels(inbound, Path("resolution"), [cutoff])
                incomplete = build_labels(inbound, Path("resolution"), [cutoff], 91)
            self.assertTrue(rows[0]["outcome_complete"])
            self.assertEqual(rows[0]["churn90"], 0)
            self.assertEqual(rows[0]["clv90"], 125)
            self.assertTrue(rows[0]["eligible"])
            self.assertFalse(rows[1]["eligible"])
            self.assertIsNone(rows[1]["churn90"])
            self.assertEqual(rows[1]["clv90"], 0)
            self.assertFalse(incomplete[0]["outcome_complete"])
            self.assertIsNone(incomplete[0]["clv90"])
            self.assertIsNone(incomplete[0]["churn90"])

    def test_temporal_holdout_is_deterministic_not_customer_random(self):
        cutoffs = ["2026-01-01T00:00:00+07:00", "2026-02-01T00:00:00+07:00"]
        rows = [
            dict(
                golden_customer_id=golden,
                cutoff_at=cutoff,
                recency_days=recency,
                churn90=churn,
                clv90=clv,
                outcome_end_at=(
                    datetime.fromisoformat(cutoff) + timedelta(days=10)
                ).isoformat(),
                eligible=True,
                outcome_complete=True,
            )
            for cutoff in cutoffs
            for golden, recency, churn, clv in (("a", 120, 1, 0), ("b", 10, 0, 100))
        ]
        train, test, train_cutoffs, test_cutoffs = temporal_split(list(reversed(rows)))
        self.assertEqual({r["cutoff_at"] for r in train}, {cutoffs[0]})
        self.assertEqual({r["cutoff_at"] for r in test}, {cutoffs[1]})
        self.assertEqual(train_cutoffs, [cutoffs[0]])
        self.assertEqual(test_cutoffs, [cutoffs[1]])
        metrics = evaluate(rows)
        self.assertEqual(metrics["churn"]["accuracy"], 1.0)
        self.assertEqual(metrics["churn"]["balanced_accuracy"], 1.0)
        self.assertEqual(metrics["clv"]["mae"], 50.0)
        self.assertEqual(metrics, evaluate(list(reversed(rows))))
        with self.assertRaisesRegex(ValueError, "two cutoffs"):
            evaluate(rows[:2])
        with self.assertRaisesRegex(ValueError, "complete labels"):
            evaluate([{**rows[0], "clv90": None}, *rows[1:]])
        early, later = cutoffs
        leaking = [
            dict(
                r,
                outcome_end_at=(
                    datetime.fromisoformat(later) + timedelta(days=1)
                ).isoformat(),
            )
            for r in rows
            if r["cutoff_at"] == early
        ]
        with self.assertRaisesRegex(ValueError, "Purged temporal"):
            evaluate(leaking + [r for r in rows if r["cutoff_at"] == later])

    def test_join_complete_eligible_only_no_label_features(self):
        features = [
            dict(
                golden_customer_id=id_,
                cutoff_at="2026-01-01T00:00:00+07:00",
                recency_days=1,
            )
            for id_ in ("a", "b")
        ]
        labels = [
            dict(
                golden_customer_id=id_,
                cutoff_at="2026-01-01T00:00:00+07:00",
                outcome_complete=True,
                eligible=id_ == "a",
                churn90=1,
                clv90=0,
            )
            for id_ in ("a", "b")
        ]
        self.assertEqual(len(join_training_rows(features, labels)), 1)
        self.assertNotIn("churn90", features[0])
        self.assertNotIn("clv90", features[0])
        with self.assertRaisesRegex(ValueError, "exactly match"):
            join_training_rows(features, labels[:1])

    def test_cli_manifest_checksums_and_single_cutoff_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inbound, resolution, output = (
                root / p for p in ("inbound", "resolution", "output")
            )
            generate(
                argparse.Namespace(
                    seed=20260906,
                    customers=30,
                    as_of_date=date(2026, 9, 6),
                    output_dir=inbound,
                    ground_truth_dir=root / "truth",
                )
            )
            resolve(inbound / "crm_customers.csv", resolution, synthetic_aliases=True)
            early = datetime.fromisoformat("2026-03-01T00:00:00+07:00")
            late = datetime.fromisoformat("2026-06-01T00:00:00+07:00")
            with self.assertRaisesRegex(ValueError, "two cutoffs"):
                run(inbound, resolution, output, [early])
            self.assertFalse(output.exists())
            result = run(inbound, resolution, output, [late, early])
            manifest = json.loads(
                (output / "model_manifest.json").read_text(encoding="utf-8")
            )
            metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
            self.assertFalse(result["experiment_ready"])
            self.assertFalse(manifest["final_model"])
            self.assertEqual(metrics["train_cutoffs"], [early.isoformat()])
            self.assertEqual(metrics["test_cutoffs"], [late.isoformat()])
            self.assertGreaterEqual(metrics["purged_rows"], 0)
            for name, digest in manifest["output_sha256"].items():
                self.assertEqual(digest, sha256(output / name))
            with (output / "labels.csv").open(newline="", encoding="utf-8") as stream:
                label_rows = list(csv.DictReader(stream))
            with (output / "training_rows.csv").open(
                newline="", encoding="utf-8"
            ) as stream:
                training_rows = list(csv.DictReader(stream))
            self.assertEqual(len(label_rows), result["label_rows"])
            self.assertEqual(len(training_rows), result["training_rows"])
            self.assertTrue(
                all(
                    r["outcome_complete"] == "True" and r["eligible"] == "True"
                    for r in training_rows
                )
            )
            with self.assertRaisesRegex(ValueError, "cannot be overwritten"):
                run(inbound, resolution, output, [early, late])


if __name__ == "__main__":
    unittest.main()
