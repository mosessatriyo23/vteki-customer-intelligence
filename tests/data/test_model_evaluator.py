import csv
import json
import tempfile
import unittest
from pathlib import Path

from services.data.features.snapshot import FIELDS
from services.data.ingestion.validator import sha256
from services.data.models.evaluator import (
    _auc,
    _average_precision,
    _binary,
    _evaluate_rows,
    evaluate,
    run,
)
from services.data.models.labels import CHRIST_VERSION


def row(cutoff, customer, label, recency, end=None):
    from datetime import datetime, timedelta

    parsed = datetime.fromisoformat(cutoff)
    return {
        "golden_customer_id": customer,
        "cutoff_at": cutoff,
        "outcome_end_at": end or (parsed + timedelta(days=90)).isoformat(),
        "label_version": CHRIST_VERSION,
        "horizon_days": "90",
        "eligible": "True",
        "outcome_complete": "True",
        "churn90": str(label),
        "recency_days": str(recency),
    }


class ModelEvaluatorTests(unittest.TestCase):
    def valid_rows(self):
        first = "2026-01-01T00:00:00+07:00"
        second = "2026-07-01T00:00:00+07:00"
        return [
            row(first, "a", 1, 120),
            row(first, "b", 0, 10),
            row(second, "a", 1, 120),
            row(second, "b", 0, 10),
        ]

    def test_auc_handles_ties_and_class_absence(self):
        self.assertEqual(_auc([(1, 0.8), (0, 0.2)]), 1.0)
        self.assertEqual(_auc([(1, 0.5), (0, 0.5)]), 0.5)
        self.assertIsNone(_auc([(1, 0.5)]))

    def test_metrics_binary_ties_and_single_class(self):
        metrics = _evaluate_rows(
            [
                {"churn90": "1", "recency_days": "120"},
                {"churn90": "0", "recency_days": "10"},
                {"churn90": "1", "recency_days": "10"},
                {"churn90": "0", "recency_days": "120"},
            ]
        )
        self.assertEqual(metrics["roc_auc"], 0.5)
        self.assertEqual(metrics["brier_score"], 0.5)
        self.assertIsNone(metrics["top_decile_lift"])
        self.assertEqual(
            metrics["average_precision"],
            _average_precision([(1, 0.5), (0, 0.5), (1, 0.0), (0, 0.0)]),
        )
        single = _evaluate_rows([{"churn90": "0", "recency_days": "10"}])
        self.assertIsNone(single["roc_auc"])
        self.assertIsNone(single["average_precision"])
        with self.assertRaisesRegex(ValueError, "0 or 1"):
            _binary(True, "churn90")

    def test_temporal_report_and_permutation(self):
        rows = self.valid_rows()
        report = evaluate(rows)
        self.assertFalse(report["training_ready"])
        self.assertEqual(report["holdout"]["rows"], 2)
        self.assertEqual(report["test_cutoffs"], [rows[2]["cutoff_at"]])
        self.assertEqual(report, evaluate(list(reversed(rows))))

    def test_rejects_invalid_rows(self):
        cases = []
        duplicate = self.valid_rows()
        duplicate.append(dict(duplicate[0]))
        cases.append(duplicate)
        for field, value in (
            ("eligible", "False"),
            ("outcome_complete", "false"),
            ("label_version", "wrong"),
            ("horizon_days", "89"),
            ("outcome_end_at", "2026-05-01T00:00:00+07:00"),
            ("recency_days", "-1"),
            ("recency_days", "1.5"),
            ("recency_days", "NaN"),
        ):
            candidate = self.valid_rows()
            candidate[0][field] = value
            cases.append(candidate)
        for candidate in cases:
            with self.subTest(candidate=candidate[0]):
                with self.assertRaises(ValueError):
                    evaluate(candidate)

    def test_run_publication_replay_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = root / "source", root / "published"
            source.mkdir()
            rows = self.valid_rows()
            with (source / "training_rows.csv").open(
                "w", newline="", encoding="utf-8"
            ) as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            manifest = {
                "experiment_ready": False,
                "final_model": False,
                "label_version": CHRIST_VERSION,
                "feature_fields": list(FIELDS),
                "training_rows": len(rows),
                "output_sha256": {
                    "training_rows.csv": sha256(source / "training_rows.csv")
                },
            }
            manifest_path = source / "model_manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            report = run(source, output)
            recorded = json.loads((output / "evaluation_manifest.json").read_text())
            self.assertEqual(
                recorded["input_sha256"]["model_manifest.json"], sha256(manifest_path)
            )
            self.assertEqual(
                recorded["input_sha256"]["training_rows.csv"],
                sha256(source / "training_rows.csv"),
            )
            self.assertEqual(report["holdout"]["rows"], 2)
            with self.assertRaisesRegex(ValueError, "new evaluator"):
                run(source, output)
            tampered = root / "tampered"
            manifest["output_sha256"]["training_rows.csv"] = "bad"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "checksum"):
                run(source, tampered)
            self.assertFalse(tampered.exists())


if __name__ == "__main__":
    unittest.main()
