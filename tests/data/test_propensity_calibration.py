"""Independent three-fold POS propensity calibration safety checks."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.data.models import propensity_calibration as calibration
from tests.data.test_propensity_experiment import joined, write_inputs

CUTOFFS = (
    "2025-12-01T00:00:00+07:00",
    "2026-03-01T00:00:00+07:00",
    "2026-06-01T00:00:00+07:00",
)
TARGETS = ("retail_purchase30", "renewal60")


class CalibrationTests(unittest.TestCase):
    def test_reports_independent_targets_and_strict_json(self):
        for target in TARGETS:
            report, predictions, artifact = calibration.evaluate(
                joined(target, CUTOFFS), target
            )
            self.assertEqual(report["target"], target)
            self.assertEqual(report["folds"]["train"]["rows"], 8)
            self.assertEqual(report["purged_rows"], 0)
            for flag in (
                "training_ready",
                "experiment_ready",
                "final_model",
                "serving_ready",
                "calibration_final",
            ):
                self.assertIs(report[flag], False)
            for kind in ("uncalibrated", "calibrated"):
                block = report["test"][kind]
                self.assertIn("average_precision", block["metrics"])
                self.assertIn("top_20_percent", block["lift_gains"])
            self.assertEqual(len(predictions), 8)
            json.dumps((report, predictions, artifact), allow_nan=False)

    def test_heldout_mutations_never_fit_train_or_tune_on_test(self):
        for target in TARGETS:
            rows = joined(target, CUTOFFS)
            original = calibration.evaluate(rows, target)[2]
            for cutoff in CUTOFFS[1:]:
                changed = copy.deepcopy(rows)
                for row in changed:
                    if row["cutoff_at"] == cutoff:
                        row["target_value"] = 1 - row["target_value"]
                        row["recency_days"] = 9999
                artifact = calibration.evaluate(changed, target)[2]
                self.assertEqual(original["logistic"], artifact["logistic"])
                if cutoff == CUTOFFS[2]:
                    self.assertEqual(original, artifact)

    def test_stored_labels_are_not_predictors(self):
        rows = joined(TARGETS[0], CUTOFFS)
        original = calibration.evaluate(rows, TARGETS[0])
        for row in rows:
            row.update(churn90=999, renewal60=999, retail_purchase30=999)
        self.assertEqual(original, calibration.evaluate(rows, TARGETS[0]))

    def test_single_class_train_refused_calibration_falls_back(self):
        for fold in (0, 1):
            rows = joined(TARGETS[0], CUTOFFS)
            for row in rows:
                if row["cutoff_at"] == CUTOFFS[fold]:
                    row["target_value"] = 0
            if fold == 0:
                with self.assertRaisesRegex(ValueError, "two classes"):
                    calibration.evaluate(rows, TARGETS[0])
            else:
                report, predictions, artifact = calibration.evaluate(rows, TARGETS[0])
                self.assertEqual(report["selected_threshold"], 0.5)
                self.assertEqual(
                    artifact["isotonic"]["status"], "identity_fallback_single_class"
                )
                self.assertTrue(
                    all(
                        p["raw_probability"] == p["calibrated_probability"]
                        for p in predictions
                    )
                )

    def test_exact_three_cutoffs_and_declared_months(self):
        for cutoffs in (
            CUTOFFS[1:],
            (*CUTOFFS, "2026-09-01T00:00:00+07:00"),
            ("2025-11-01T00:00:00+07:00", *CUTOFFS[1:]),
        ):
            with self.assertRaisesRegex(ValueError, "three|December"):
                calibration.evaluate(joined(TARGETS[0], cutoffs), TARGETS[0])

    def test_split_purges_each_rows_outcome_and_keeps_boundary(self):
        rows = joined(TARGETS[0], CUTOFFS)
        rows[0]["outcome_end_at"] = CUTOFFS[1]
        rows[1]["outcome_end_at"] = "2026-03-02T00:00:00+07:00"
        rows[8]["outcome_end_at"] = "2026-06-02T00:00:00+07:00"
        train, cal, test, info = calibration.three_fold_split(rows)
        self.assertEqual((len(train), len(cal), len(test)), (7, 7, 8))
        self.assertEqual(
            info["purged_counts"], {"train": 1, "calibration": 1, "test": 0}
        )

    def test_negative_calibration_result_is_retained_without_selection(self):
        rows = joined(TARGETS[0], CUTOFFS)
        for row in rows:
            if row["cutoff_at"] == CUTOFFS[1]:
                row["target_value"] = 1 - row["target_value"]
        report, _, _ = calibration.evaluate(rows, TARGETS[0])
        delta = report["test_calibration_minus_raw"]["brier_score"]
        self.assertGreater(delta, 0)
        self.assertAlmostEqual(
            delta,
            report["test"]["calibrated"]["metrics"]["brier_score"]
            - report["test"]["uncalibrated"]["metrics"]["brier_score"],
        )
        self.assertFalse(report["calibration_final"])

    def test_booking_refused(self):
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED_SOURCE"):
            calibration.evaluate([], "service_booking30")

    def test_manifest_checksums_pre_and_post_and_output_guards(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            labels, features = write_inputs(root, cutoffs=CUTOFFS)
            output = root / "output"
            report = calibration.run(labels, features, TARGETS[0], output)
            self.assertEqual(report["input_sha256"], report["input_sha256_after"])
            self.assertTrue((output / "calibration_manifest.json").is_file())
            for bad in (output, labels / "nested", root / "ground_truth" / "out"):
                with self.assertRaises(ValueError):
                    calibration.run(labels, features, TARGETS[0], bad)
            real_evaluate = calibration.evaluate

            def mutate(*args):
                result = real_evaluate(*args)
                with (features / "feature_manifest.json").open("a") as stream:
                    stream.write(" ")
                return result

            with patch.object(calibration, "evaluate", side_effect=mutate):
                with self.assertRaisesRegex(ValueError, "changed"):
                    calibration.run(labels, features, TARGETS[0], root / "post")
            with (features / "features.csv").open("a") as stream:
                stream.write("\n")
            with self.assertRaisesRegex(ValueError, "checksum"):
                calibration.run(labels, features, TARGETS[0], root / "tamper")
            self.assertFalse((root / "tamper").exists())


if __name__ == "__main__":
    unittest.main()
