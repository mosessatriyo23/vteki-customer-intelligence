"""Development-only fitted churn comparison contract."""

import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from services.data.features.snapshot import FIELDS, VERSION
from services.data.ingestion.validator import sha256
from services.data.models.churn_experiment import FEATURES, evaluate, run
from services.data.models.labels import CHRIST_VERSION, TRAINING_FIELDS


def rows():
    cutoffs = ("2026-01-01T00:00:00+07:00", "2026-04-02T00:00:00+07:00")
    result = []
    for cutoff in cutoffs:
        for i in range(8):
            result.append(
                dict(
                    golden_customer_id=f"g{i}",
                    cutoff_at=cutoff,
                    identity_status="RESOLVED",
                    feature_version=VERSION,
                    training_ready=False,
                    identity_time_policy="CURRENT_SNAPSHOT_RETROSPECTIVE",
                    recency_days="" if i == 0 else str(i * 25),
                    tenure_days=str(i + 1),
                    purchase_count_365d=str(i),
                    retained_revenue_365d=str(i * 100),
                    purchase_count_60d=str(i % 2),
                    purchase_count_90d=str(i % 3),
                    retained_revenue_90d=str(i * 10),
                    label_version=CHRIST_VERSION,
                    horizon_days=90,
                    outcome_end_at=(
                        datetime.fromisoformat(cutoff) + timedelta(days=90)
                    ).isoformat(),
                    outcome_complete=True,
                    eligible=True,
                    churn90=i % 2,
                    clv90=0,
                    experiment_ready=False,
                )
            )
    return result


class ChurnExperimentTests(unittest.TestCase):
    def test_same_purged_holdout_raw_probabilities_and_fixed_comparator(self):
        data = rows()
        report, predictions, parameters = evaluate(data)
        self.assertEqual(
            FEATURES,
            (
                "recency_days",
                "tenure_days",
                "purchase_count_365d",
                "retained_revenue_365d",
                "purchase_count_60d",
                "purchase_count_90d",
                "retained_revenue_90d",
            ),
        )
        self.assertEqual(report["train_cutoffs"], [data[0]["cutoff_at"]])
        self.assertEqual(report["test_cutoffs"], [data[-1]["cutoff_at"]])
        self.assertEqual(report["purged_rows"], 0)
        self.assertEqual(len(predictions), 8)
        self.assertEqual(predictions[0]["baseline_probability"], 1.0)
        self.assertEqual(predictions[-1]["baseline_probability"], 1.0)
        self.assertTrue(all(0 <= p["logistic_probability"] <= 1 for p in predictions))
        self.assertEqual(report["baseline"]["confusion"]["threshold"], 0.5)
        self.assertEqual(report["baseline"]["brier_score"], 0.625)
        self.assertFalse(report["serving_ready"])
        self.assertFalse(report["experiment_ready"])
        self.assertIn("coef", parameters["logistic"])
        self.assertNotIn("clv", json.dumps(report).lower())
        self.assertEqual(report, evaluate(data)[0])

    def test_rejects_bad_flags_versions_time_duplicates_and_numeric(self):
        original = rows()
        changes = (
            ("eligible", False),
            ("eligible", 1),
            ("outcome_complete", False),
            ("training_ready", 0),
            ("training_ready", True),
            ("experiment_ready", True),
            ("feature_version", "wrong"),
            ("label_version", "wrong"),
            ("identity_time_policy", "wrong"),
            ("horizon_days", 180),
            ("outcome_end_at", "2026-03-01T00:00:00+07:00"),
            ("cutoff_at", "2026-01-01"),
            ("recency_days", "NaN"),
            ("tenure_days", "inf"),
            ("purchase_count_90d", "bad"),
            ("retained_revenue_90d", "-inf"),
            ("churn90", 2),
        )
        for field, value in changes:
            with self.subTest(field=field, value=value):
                changed = [r.copy() for r in original]
                changed[0][field] = value
                with self.assertRaises(ValueError):
                    evaluate(changed)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            evaluate([*original, original[0].copy()])
        with self.assertRaisesRegex(ValueError, "two classes"):
            evaluate(
                [
                    (
                        {**r, "churn90": 1}
                        if r["cutoff_at"] == original[0]["cutoff_at"]
                        else r
                    )
                    for r in original
                ]
            )

    def test_preprocessing_is_train_only_and_event_only_train_is_supported(self):
        data = rows()
        _, _, original = evaluate(data)
        changed = [r.copy() for r in data]
        for row in changed[8:]:
            row["tenure_days"] = "999999"
            row["churn90"] = 1 - row["churn90"]
            row["clv90"] = "not a feature"
        _, _, mutated = evaluate(changed)
        self.assertEqual(original, mutated)
        for row in data:
            row["recency_days"] = None
        report, predictions, params = evaluate(data)
        self.assertEqual(len(predictions), 8)
        self.assertEqual(params["logistic"]["imputer_medians"][0], 0.0)
        self.assertEqual(report["baseline"]["positives"], 4)
        json.dumps(params, allow_nan=False)

    def test_equivalent_aware_timestamps_and_row_order_are_normalized(self):
        data = rows()
        expected = evaluate(data)
        changed = [r.copy() for r in reversed(data)]
        for row in changed:
            row["cutoff_at"] = datetime.fromisoformat(row["cutoff_at"]).isoformat(
                timespec="microseconds"
            )
        self.assertEqual(expected, evaluate(changed))

    def test_purge_excludes_recent_overlapping_training_outcomes(self):
        data = rows()
        middle = []
        for row in data[:8]:
            cutoff = datetime.fromisoformat("2026-03-01T00:00:00+07:00")
            middle.append(
                {
                    **row,
                    "cutoff_at": cutoff.isoformat(),
                    "outcome_end_at": (cutoff + timedelta(days=90)).isoformat(),
                }
            )
        report, _, params = evaluate(data + middle)
        self.assertEqual(report["purged_rows"], 8)
        self.assertEqual(params, evaluate(data)[2])

    def test_single_class_holdout_has_null_auc_and_ap_if_no_positives(self):
        data = rows()
        for row in data[8:]:
            row["churn90"] = 0
        report, _, _ = evaluate(data)
        self.assertIsNone(report["logistic"]["roc_auc"])
        self.assertIsNone(report["logistic"]["average_precision"])

    def test_equivalent_recency_representations_give_same_baseline(self):
        """'25' and '25.0' are equivalent recency values and must produce the
        same fixed-recency baseline comparator, not silently diverge."""
        data = rows()
        data[-1]["recency_days"] = "25"
        same_int = evaluate(data)[0]["baseline"]
        data[-1]["recency_days"] = "25.0"
        same_float_text = evaluate(data)[0]["baseline"]
        self.assertEqual(same_int, same_float_text)

    def test_different_utc_offsets_for_the_same_instant_are_not_dropped(self):
        """A cutoff expressed with a different (but equivalent) UTC offset
        must not be silently excluded from its own cutoff group."""
        data = rows()
        data[8]["cutoff_at"] = (
            datetime.fromisoformat(data[8]["cutoff_at"])
            .astimezone(timezone.utc)
            .isoformat()
        )
        report, predictions, _ = evaluate(data)
        self.assertEqual(report["purged_rows"], 0)
        self.assertEqual(report["test_rows"], 8)
        self.assertEqual(len(predictions), 8)

    def test_run_emits_an_output_manifest_with_output_checksums(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, output = root / "source", root / "output"
            source.mkdir()
            with (source / "training_rows.csv").open(
                "w", newline="", encoding="utf-8"
            ) as stream:
                writer = csv.DictWriter(stream, fieldnames=TRAINING_FIELDS)
                writer.writeheader()
                writer.writerows(rows())
            manifest = dict(
                experiment_ready=False,
                final_model=False,
                label_version=CHRIST_VERSION,
                feature_fields=list(FIELDS),
                training_rows=16,
                output_sha256={
                    "training_rows.csv": sha256(source / "training_rows.csv")
                },
            )
            (source / "model_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            run(source, output)
            experiment_manifest = json.loads(
                (output / "experiment_manifest.json").read_text(encoding="utf-8")
            )
            for name in (
                "evaluation.json",
                "holdout_predictions.json",
                "model_parameters.json",
            ):
                self.assertEqual(
                    experiment_manifest["output_sha256"][name],
                    sha256(output / name),
                )
            self.assertEqual(
                experiment_manifest["input_sha256"]["training_rows.csv"],
                sha256(source / "training_rows.csv"),
            )

    def test_cli_checks_manifest_and_inputs_and_keeps_output_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, output = root / "source", root / "output"
            source.mkdir()
            with (source / "training_rows.csv").open(
                "w", newline="", encoding="utf-8"
            ) as stream:
                writer = csv.DictWriter(stream, fieldnames=TRAINING_FIELDS)
                writer.writeheader()
                writer.writerows(rows())
            manifest = dict(
                experiment_ready=False,
                final_model=False,
                label_version=CHRIST_VERSION,
                feature_fields=list(FIELDS),
                training_rows=16,
                output_sha256={
                    "training_rows.csv": sha256(source / "training_rows.csv")
                },
            )
            (source / "model_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            report = run(source, output)
            self.assertFalse(report["training_ready"])
            self.assertEqual(
                len(json.loads((output / "holdout_predictions.json").read_text())), 8
            )
            self.assertEqual(
                json.loads((output / "model_parameters.json").read_text())[
                    "feature_version"
                ],
                VERSION,
            )
            with self.assertRaisesRegex(ValueError, "new"):
                run(source, output)
            with self.assertRaisesRegex(ValueError, "separate"):
                run(source, source / "nested")
            with self.assertRaisesRegex(ValueError, "ground_truth"):
                run(source, root / "ground_truth" / "out")
            manifest["output_sha256"]["training_rows.csv"] = "invalid"
            (source / "model_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "checksum"):
                run(source, root / "bad")
            manifest["output_sha256"]["training_rows.csv"] = sha256(
                source / "training_rows.csv"
            )
            (source / "model_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            with patch(
                "services.data.models.churn_experiment.sha256",
                side_effect=[
                    "before",
                    manifest["output_sha256"]["training_rows.csv"],
                    "before",
                    "after",
                ],
            ):
                with self.assertRaisesRegex(ValueError, "changed"):
                    run(source, root / "changed")
            self.assertFalse((root / "changed").exists())


if __name__ == "__main__":
    unittest.main()
