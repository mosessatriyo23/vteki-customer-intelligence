"""Development-only fitted propensity experiment (retail 30d, renewal 60d).

Each target is trained, scored and reported independently; booking is refused.
"""

import csv
import json
import math
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from services.data.features.snapshot import FIELDS as FEATURE_FIELDS
from services.data.features.snapshot import VERSION as FEATURE_VERSION
from services.data.ingestion.validator import sha256
from services.data.models.propensity_experiment import (
    FEATURES,
    MODEL_VERSION,
    RULES,
    evaluate,
    run,
)
from services.data.models.propensity_labels import (
    FIELDS as LABEL_FIELDS,
)
from services.data.models.propensity_labels import (
    RENEWAL_VERSION,
    RETAIL_VERSION,
    TARGETS,
    UNSUPPORTED_SOURCE,
    booking_status,
    join_propensity_training_rows,
)

MODULE = "services.data.models.propensity_experiment"
EARLY = "2026-03-01T00:00:00+07:00"
LATE = "2026-06-01T00:00:00+07:00"
CUTOFFS = (EARLY, LATE)


def feature_row(index: int, cutoff: str) -> dict:
    return dict(
        golden_customer_id=f"g{index}",
        cutoff_at=cutoff,
        identity_status="RESOLVED",
        feature_version=FEATURE_VERSION,
        training_ready=False,
        identity_time_policy="CURRENT_SNAPSHOT_RETROSPECTIVE",
        recency_days=None if index == 0 else index * 25,
        tenure_days=index + 1,
        purchase_count_365d=index,
        retained_revenue_365d=index * 100,
        purchase_count_60d=index % 2,
        purchase_count_90d=index % 3,
        retained_revenue_90d=index * 10,
    )


def label_row(index: int, cutoff: str, *, retail=None, renewal=None) -> dict:
    moment = datetime.fromisoformat(cutoff)
    retail_value = index % 2 if retail is None else retail
    renewal_value = (index // 2) % 2 if renewal is None else renewal
    return dict(
        golden_customer_id=f"g{index}",
        cutoff_at=cutoff,
        retail_label_version=RETAIL_VERSION,
        renewal_label_version=RENEWAL_VERSION,
        retail_purchase30_eligible=True,
        retail_purchase30_outcome_complete=True,
        retail_purchase30_outcome_end_at=(moment + timedelta(days=30)).isoformat(),
        retail_purchase30=retail_value,
        renewal60_eligible=True,
        renewal60_outcome_complete=True,
        renewal60_outcome_end_at=(moment + timedelta(days=60)).isoformat(),
        renewal60=renewal_value,
        experiment_ready=False,
    )


def cohort(cutoffs=CUTOFFS, count=8) -> tuple[list[dict], list[dict]]:
    features, labels = [], []
    for cutoff in cutoffs:
        for index in range(count):
            features.append(feature_row(index, cutoff))
            labels.append(label_row(index, cutoff))
    return features, labels


def joined(target: str, cutoffs=CUTOFFS, count=8) -> list[dict]:
    features, labels = cohort(cutoffs, count)
    return join_propensity_training_rows(features, labels, target)


def write_csv(path: Path, fields, rows) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(
            [{k: "" if v is None else v for k, v in row.items()} for row in rows]
        )


def write_inputs(root: Path, features=None, labels=None, cutoffs=CUTOFFS) -> tuple:
    """Mirror the real labels/features CLI output directories."""
    built_features, built_labels = cohort(cutoffs)
    features = built_features if features is None else features
    labels = built_labels if labels is None else labels
    labels_dir, features_dir = root / "labels", root / "features"
    labels_dir.mkdir(parents=True)
    features_dir.mkdir(parents=True)
    write_csv(labels_dir / "propensity_labels.csv", LABEL_FIELDS, labels)
    write_csv(features_dir / "features.csv", FEATURE_FIELDS, features)
    write_label_manifest(labels_dir, cutoffs)
    write_feature_manifest(features_dir, cutoffs, len(features))
    return labels_dir, features_dir


def write_label_manifest(labels_dir: Path, cutoffs=CUTOFFS, **overrides) -> None:
    manifest = dict(
        target_versions={name: version for name, (version, _) in TARGETS.items()},
        horizon_days={name: days for name, (_, days) in TARGETS.items()},
        cutoffs=list(cutoffs),
        training_ready=False,
        experiment_ready=False,
        final_model=False,
        development_only=True,
        booking=booking_status(),
        proposed_rules={},
        row_counts={},
        input_sha256={},
        output_sha256={
            "propensity_labels.csv": sha256(labels_dir / "propensity_labels.csv")
        },
    )
    manifest.update(overrides)
    (labels_dir / "propensity_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def write_feature_manifest(
    features_dir: Path, cutoffs=CUTOFFS, rows=16, **overrides
) -> None:
    manifest = dict(
        feature_version=FEATURE_VERSION,
        training_ready=False,
        rows=rows,
        cutoffs=list(cutoffs),
        input_sha256={},
        output_sha256={"features.csv": sha256(features_dir / "features.csv")},
        limitations=[],
    )
    manifest.update(overrides)
    (features_dir / "feature_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


class IndependenceTests(unittest.TestCase):
    def test_each_target_is_reported_with_its_own_version_and_horizon(self):
        retail = evaluate(joined("retail_purchase30"), "retail_purchase30")[0]
        renewal = evaluate(joined("renewal60"), "renewal60")[0]
        self.assertEqual(retail["target"], "retail_purchase30")
        self.assertEqual(retail["target_version"], RETAIL_VERSION)
        self.assertEqual(retail["horizon_days"], 30)
        self.assertEqual(renewal["target"], "renewal60")
        self.assertEqual(renewal["target_version"], RENEWAL_VERSION)
        self.assertEqual(renewal["horizon_days"], 60)
        self.assertNotIn("renewal60", json.dumps(retail))
        self.assertNotIn("retail_purchase30", json.dumps(renewal))
        self.assertEqual(retail["model_version"], MODEL_VERSION)
        self.assertEqual(retail["feature_version"], FEATURE_VERSION)
        self.assertEqual(retail["features"], list(FEATURES))

    def test_target_column_of_the_other_target_is_never_read(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            labels_dir, features_dir = write_inputs(root)
            run(labels_dir, features_dir, "retail_purchase30", root / "one")
            _, labels = cohort()
            for row in labels:
                row["renewal60"] = "junk"
                row["renewal60_eligible"] = "junk"
                row["renewal60_outcome_complete"] = "junk"
                row["renewal60_outcome_end_at"] = "junk"
                row["renewal_label_version"] = "junk"
            write_csv(labels_dir / "propensity_labels.csv", LABEL_FIELDS, labels)
            write_label_manifest(labels_dir)
            run(labels_dir, features_dir, "retail_purchase30", root / "two")
            self.assertEqual(
                (root / "one" / "model_parameters.json").read_text(encoding="utf-8"),
                (root / "two" / "model_parameters.json").read_text(encoding="utf-8"),
            )

    def test_booking_is_refused_everywhere(self):
        self.assertEqual(booking_status()["status"], UNSUPPORTED_SOURCE)
        with self.assertRaisesRegex(ValueError, UNSUPPORTED_SOURCE):
            evaluate(joined("retail_purchase30"), "service_booking30")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            labels_dir, features_dir = write_inputs(root)
            with self.assertRaisesRegex(ValueError, UNSUPPORTED_SOURCE):
                run(labels_dir, features_dir, "service_booking30", root / "out")
            with self.assertRaisesRegex(ValueError, "Unknown propensity target"):
                run(labels_dir, features_dir, "churn90", root / "out2")
            self.assertFalse((root / "out").exists())


class PurgeTests(unittest.TestCase):
    def test_purge_uses_each_rows_own_outcome_end_at_per_target(self):
        """A middle cutoff whose horizon-based outcome overlaps the holdout
        boundary must be purged for the 60d target but kept for the 30d
        target, proving the purge is per-target, not a fixed 90d assumption."""
        early = "2026-01-01T00:00:00+07:00"
        middle = "2026-03-01T00:00:00+07:00"
        holdout = "2026-04-02T00:00:00+07:00"
        cutoffs = (early, middle, holdout)
        retail = evaluate(joined("retail_purchase30", cutoffs), "retail_purchase30")[0]
        self.assertEqual(retail["purged_rows"], 0)
        self.assertEqual(retail["train_rows"], 16)
        self.assertEqual(retail["train_cutoffs"], [early, middle])
        self.assertEqual(retail["test_cutoffs"], [holdout])
        renewal = evaluate(joined("renewal60", cutoffs), "renewal60")[0]
        self.assertEqual(renewal["purged_rows"], 8)
        self.assertEqual(renewal["train_rows"], 8)
        self.assertEqual(renewal["train_cutoffs"], [early])
        self.assertEqual(renewal["test_cutoffs"], [holdout])
        # 2026-02-01 + 60d == holdout exactly: on the boundary, so kept.
        boundary = evaluate(
            joined("renewal60", (early, "2026-02-01T00:00:00+07:00", holdout)),
            "renewal60",
        )[0]
        self.assertEqual(boundary["purged_rows"], 0)
        self.assertEqual(boundary["train_rows"], 16)


class ComparatorTests(unittest.TestCase):
    def test_base_rate_and_fixed_rule_come_from_train_or_declaration_only(self):
        rows = joined("retail_purchase30")
        report, predictions, parameters = evaluate(rows, "retail_purchase30")
        self.assertEqual(report["train_base_rate"], 0.5)
        self.assertEqual(parameters["base_rate"]["train_base_rate"], 0.5)
        self.assertTrue(
            all(p["base_rate_probability"] == 0.5 for p in predictions),
        )
        self.assertEqual(report["models"]["base_rate"]["metrics"]["roc_auc"], 0.5)
        self.assertEqual(RULES["retail_purchase30"], "recency_days <= 30 -> 1 else 0")
        self.assertEqual(RULES["renewal60"], "purchase_count_90d >= 1 -> 1 else 0")
        self.assertEqual(
            report["comparator_rules"]["fixed_rule"], RULES[rows[0]["target"]]
        )
        # recency_days: missing, 25, 50, 75, ... -> only index 1 is within 30 days.
        self.assertEqual(
            [p["fixed_rule_probability"] for p in predictions],
            [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        )
        renewal_predictions = evaluate(joined("renewal60"), "renewal60")[1]
        # purchase_count_90d cycles 0, 1, 2 -> positive whenever >= 1.
        self.assertEqual(
            [p["fixed_rule_probability"] for p in renewal_predictions],
            [0.0, 1.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0],
        )

    def test_base_rate_brier_matches_train_rate_not_holdout_rate(self):
        features, labels = cohort()
        for row in labels:
            if row["cutoff_at"] == LATE:
                row["retail_purchase30"] = 1
        rows = join_propensity_training_rows(features, labels, "retail_purchase30")
        report = evaluate(rows, "retail_purchase30")[0]
        self.assertEqual(report["train_base_rate"], 0.5)
        self.assertAlmostEqual(
            report["models"]["base_rate"]["metrics"]["brier_score"], 0.25
        )


class FoldClassTests(unittest.TestCase):
    def test_single_class_train_fold_is_rejected(self):
        features, labels = cohort()
        for row in labels:
            if row["cutoff_at"] == EARLY:
                row["retail_purchase30"] = 1
        rows = join_propensity_training_rows(features, labels, "retail_purchase30")
        with self.assertRaisesRegex(ValueError, "two classes"):
            evaluate(rows, "retail_purchase30")

    def test_single_class_holdout_reports_null_ranking_metrics(self):
        features, labels = cohort()
        for row in labels:
            if row["cutoff_at"] == LATE:
                row["retail_purchase30"] = 0
        rows = join_propensity_training_rows(features, labels, "retail_purchase30")
        report = evaluate(rows, "retail_purchase30")[0]
        for name in ("logistic", "base_rate", "fixed_rule"):
            metrics = report["models"][name]["metrics"]
            self.assertIsNone(metrics["roc_auc"], name)
            self.assertIsNone(metrics["average_precision"], name)
            self.assertEqual(report["models"][name]["positives"], 0)
            self.assertEqual(report["models"][name]["negatives"], 8)

    def test_holdout_outcome_mutation_does_not_change_fitted_parameters(self):
        features, labels = cohort()
        rows = join_propensity_training_rows(features, labels, "retail_purchase30")
        original = evaluate(rows, "retail_purchase30")[2]
        for row in labels:
            if row["cutoff_at"] == LATE:
                row["retail_purchase30"] = 1 - row["retail_purchase30"]
        mutated_rows = join_propensity_training_rows(
            features, labels, "retail_purchase30"
        )
        mutated = evaluate(mutated_rows, "retail_purchase30")[2]
        self.assertEqual(original, mutated)


class ValidationTests(unittest.TestCase):
    def test_rejects_version_flag_and_window_mismatches(self):
        changes = (
            ("feature_version", "wrong"),
            ("target_version", "wrong"),
            ("horizon_days", 90),
            ("identity_time_policy", "wrong"),
            ("eligible", False),
            ("outcome_complete", False),
            ("training_ready", True),
            ("experiment_ready", True),
            ("outcome_end_at", "2026-09-09T00:00:00+07:00"),
            ("cutoff_at", "2026-03-01"),
            ("target_value", None),
            ("target_value", 2),
            ("tenure_days", "inf"),
            ("purchase_count_90d", "bad"),
            ("retained_revenue_90d", -5),
        )
        for field, value in changes:
            with self.subTest(field=field, value=value):
                rows = [r.copy() for r in joined("retail_purchase30")]
                rows[0][field] = value
                with self.assertRaises(ValueError):
                    evaluate(rows, "retail_purchase30")
        rows = joined("retail_purchase30")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            evaluate([*rows, rows[0].copy()], "retail_purchase30")
        with self.assertRaises(ValueError):
            evaluate([], "retail_purchase30")


class RunTests(unittest.TestCase):
    def test_outputs_are_strict_json_development_only_and_checksummed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            labels_dir, features_dir = write_inputs(root)
            output = root / "out"
            report = run(labels_dir, features_dir, "renewal60", output)
            names = (
                "evaluation.json",
                "holdout_predictions.json",
                "model_parameters.json",
            )
            manifest = json.loads(
                (output / "experiment_manifest.json").read_text(encoding="utf-8")
            )
            for name in names:
                self.assertEqual(manifest["output_sha256"][name], sha256(output / name))
                data = json.loads((output / name).read_text(encoding="utf-8"))
                json.dumps(data, allow_nan=False)
            self.assertEqual(manifest["input_sha256"], manifest["input_sha256_after"])
            self.assertEqual(
                manifest["input_sha256"]["propensity_labels.csv"],
                sha256(labels_dir / "propensity_labels.csv"),
            )
            self.assertEqual(
                manifest["input_sha256"]["features.csv"],
                sha256(features_dir / "features.csv"),
            )
            self.assertIs(manifest["development_only"], True)
            self.assertIs(manifest["serving_ready"], False)
            self.assertEqual(manifest["target"], "renewal60")
            for flag in (
                "training_ready",
                "experiment_ready",
                "final_model",
                "serving_ready",
            ):
                self.assertIs(report[flag], False, flag)
            self.assertIs(report["development_only"], True)
            self.assertIsNone(report["valid_until"])
            self.assertEqual(report["input_sha256"], report["input_sha256_after"])
            text = json.dumps(report["limitations"]).lower()
            for phrase in (
                "membership",
                "not point-in-time",
                "uncalibrated",
                "proposed",
                "upgrade",
                "i-04",
                "reason",
                "causal",
                "synthetic",
            ):
                self.assertIn(phrase, text, phrase)
            self.assertEqual(manifest["limitations"], report["limitations"])
            predictions = json.loads(
                (output / "holdout_predictions.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(predictions), 8)
            for row in predictions:
                self.assertIs(row["development_only"], True)
                self.assertIs(row["serving_ready"], False)
                self.assertEqual(row["target"], "renewal60")
                self.assertIn(row["target_value"], (0, 1))
                self.assertTrue(0 <= row["logistic_probability"] <= 1)
                self.assertNotIn("reasons", row)
            parameters = json.loads(
                (output / "model_parameters.json").read_text(encoding="utf-8")
            )
            self.assertEqual(parameters["serialization_note"].count("pickle"), 0)
            self.assertIn("coef", parameters["logistic"])
            reliability = report["models"]["logistic"]["reliability"]
            self.assertEqual(len(reliability), 10)
            self.assertTrue(
                math.isfinite(report["models"]["logistic"]["descriptive_ece"])
            )

    def test_refuses_overwrite_overlap_and_ground_truth(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            labels_dir, features_dir = write_inputs(root)
            output = root / "out"
            run(labels_dir, features_dir, "retail_purchase30", output)
            with self.assertRaisesRegex(ValueError, "new"):
                run(labels_dir, features_dir, "retail_purchase30", output)
            with self.assertRaisesRegex(ValueError, "separate"):
                run(labels_dir, features_dir, "retail_purchase30", labels_dir / "sub")
            with self.assertRaisesRegex(ValueError, "separate"):
                run(labels_dir, features_dir, "retail_purchase30", features_dir / "sub")
            with self.assertRaisesRegex(ValueError, "ground_truth"):
                run(
                    labels_dir,
                    features_dir,
                    "retail_purchase30",
                    root / "ground_truth" / "out",
                )
            with self.assertRaisesRegex(ValueError, "ground_truth"):
                run(
                    root / "ground_truth",
                    features_dir,
                    "retail_purchase30",
                    root / "gt",
                )
            self.assertFalse((root / "gt").exists())

    def test_rejects_tampered_checksums_and_mid_run_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            labels_dir, features_dir = write_inputs(root)
            labels_csv = labels_dir / "propensity_labels.csv"
            original = labels_csv.read_bytes()
            labels_csv.write_bytes(original + b"\n")
            with self.assertRaisesRegex(ValueError, "checksum"):
                run(labels_dir, features_dir, "renewal60", root / "a")
            labels_csv.write_bytes(original)
            features_csv = features_dir / "features.csv"
            features_text = features_csv.read_bytes()
            features_csv.write_bytes(features_text + b"\n")
            with self.assertRaisesRegex(ValueError, "checksum"):
                run(labels_dir, features_dir, "renewal60", root / "b")
            features_csv.write_bytes(features_text)
            real = evaluate

            def tamper(rows, target):
                result = real(rows, target)
                labels_csv.write_bytes(original + b"\n")
                return result

            with patch(f"{MODULE}.evaluate", side_effect=tamper):
                with self.assertRaisesRegex(ValueError, "changed"):
                    run(labels_dir, features_dir, "renewal60", root / "c")
            self.assertFalse((root / "a").exists())
            self.assertFalse((root / "c").exists())

    def test_rejects_non_development_manifests_and_contract_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            labels_dir, features_dir = write_inputs(root)
            write_label_manifest(labels_dir, experiment_ready=True)
            with self.assertRaisesRegex(ValueError, "[Dd]evelopment"):
                run(labels_dir, features_dir, "renewal60", root / "a")
            write_label_manifest(labels_dir, development_only=False)
            with self.assertRaisesRegex(ValueError, "[Dd]evelopment"):
                run(labels_dir, features_dir, "renewal60", root / "b")
            write_label_manifest(labels_dir, target_versions={"renewal60": "wrong"})
            with self.assertRaisesRegex(ValueError, "version"):
                run(labels_dir, features_dir, "renewal60", root / "c")
            write_label_manifest(labels_dir)
            write_feature_manifest(features_dir, feature_version="wrong")
            with self.assertRaisesRegex(ValueError, "version"):
                run(labels_dir, features_dir, "renewal60", root / "d")
            write_feature_manifest(features_dir, cutoffs=[EARLY])
            with self.assertRaisesRegex(ValueError, "cutoff"):
                run(labels_dir, features_dir, "renewal60", root / "e")
            write_feature_manifest(features_dir, rows=99)
            with self.assertRaisesRegex(ValueError, "count"):
                run(labels_dir, features_dir, "renewal60", root / "f")

    def test_rejects_unexpected_csv_columns(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            labels_dir, features_dir = write_inputs(root)
            write_csv(
                features_dir / "features.csv",
                FEATURE_FIELDS[:-1],
                [{k: "" for k in FEATURE_FIELDS[:-1]}],
            )
            write_feature_manifest(features_dir, rows=1)
            with self.assertRaisesRegex(ValueError, "columns"):
                run(labels_dir, features_dir, "renewal60", root / "a")


if __name__ == "__main__":
    unittest.main()
