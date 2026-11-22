"""Offline diagnostics must replay the saved propensity test, not retrain it."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.data.ingestion.validator import sha256
from services.data.models import calibrated_propensity_importance as importance
from services.data.models import propensity_calibration as calibration
from tests.data.test_propensity_calibration import CUTOFFS, TARGETS
from tests.data.test_propensity_experiment import joined, write_inputs


class CalibratedPropensityImportanceTests(unittest.TestCase):
    def test_both_targets_are_deterministic_calibrated_and_do_not_fit(self):
        for target in TARGETS:
            with self.subTest(target=target):
                rows = joined(target, CUTOFFS)
                evaluation, predictions, artifact = calibration.evaluate(rows, target)
                holdout = calibration.three_fold_split(rows)[2]
                before = copy.deepcopy((artifact, holdout))
                with (
                    patch(
                        "sklearn.linear_model.LogisticRegression.fit",
                        side_effect=AssertionError,
                    ),
                    patch(
                        "sklearn.isotonic.IsotonicRegression.fit",
                        side_effect=AssertionError,
                    ),
                    patch.object(
                        calibration, "select_threshold", side_effect=AssertionError
                    ),
                ):
                    report = importance.evaluate(artifact, holdout, repeats=2, min_n=3)
                self.assertEqual(before, (artifact, holdout))
                self.assertEqual(
                    report, importance.evaluate(artifact, holdout, repeats=2, min_n=3)
                )
                self.assertEqual(report["target"], target)
                self.assertEqual(report["target_version"], artifact["target_version"])
                self.assertFalse(report["serving_ready"])
                self.assertFalse(report["calibration_final"])
                self.assertFalse(report["refitted"])
                self.assertEqual(
                    report["baseline"]["roc_auc"],
                    evaluation["test"]["calibrated"]["metrics"]["roc_auc"],
                )
                self.assertAlmostEqual(
                    report["baseline"]["brier_score"],
                    evaluation["test"]["calibrated"]["metrics"]["brier_score"],
                )
                self.assertEqual(
                    len(report["global_importance"]), len(artifact["features"])
                )
                self.assertEqual(report["label_key"], "target_value")
                self.assertIn("recency_days", report["segments"])
                self.assertEqual(
                    sum(s["n"] for s in report["segments"]["recency_days"]),
                    len(predictions),
                )
                json.dumps(report, allow_nan=False)

    def test_fallback_and_constant_isotonic_are_scored_in_calibrated_space(self):
        for fallback in (False, True):
            rows = joined(TARGETS[0], CUTOFFS)
            if fallback:
                for row in rows:
                    if row["cutoff_at"] == CUTOFFS[1]:
                        row["target_value"] = 0
            _, _, artifact = calibration.evaluate(rows, TARGETS[0])
            holdout = calibration.three_fold_split(rows)[2]
            if not fallback:
                artifact["isotonic"] = {
                    "status": "fit_on_calibration_only",
                    "x_thresholds": [0.2, 0.8],
                    "y_thresholds": [0.3, 0.3],
                    "out_of_bounds": "clip",
                }
            report = importance.evaluate(artifact, holdout, repeats=2)
            if fallback:
                self.assertEqual(
                    report["calibration_status"], "identity_fallback_single_class"
                )
            else:
                self.assertEqual(report["baseline"]["roc_auc"], 0.5)
                self.assertTrue(
                    all(
                        e["auc_drop_mean"] == e["brier_increase_mean"] == 0
                        for e in report["global_importance"]
                        + report["grouped_importance"]
                    )
                )

    def test_rejects_malformed_calibrator_contract_and_controls(self):
        rows = joined(TARGETS[0], CUTOFFS)
        artifact = calibration.evaluate(rows, TARGETS[0])[2]
        holdout = calibration.three_fold_split(rows)[2]
        bad = [
            ("target", TARGETS[1]),
            ("target_version", "wrong"),
            ("serving_ready", True),
            ("features", ["target_value"]),
            ("isotonic", {"status": "unknown"}),
            (
                "isotonic",
                {
                    "status": "fit_on_calibration_only",
                    "x_thresholds": [0.8, 0.2],
                    "y_thresholds": [0.1, 0.9],
                    "out_of_bounds": "clip",
                },
            ),
            (
                "isotonic",
                {"status": "identity_fallback_single_class", "x_thresholds": [0.2]},
            ),
        ]
        for key, value in bad:
            with self.subTest(key=key, value=value):
                changed = copy.deepcopy(artifact)
                changed[key] = value
                with self.assertRaises(ValueError):
                    importance.evaluate(changed, holdout, repeats=1)
        for kwargs in ({"repeats": 0}, {"repeats": True}, {"min_n": 0}, {"seed": True}):
            with self.assertRaises(ValueError):
                importance.evaluate(artifact, holdout, **kwargs)

    def test_cli_and_rehashed_tampering_still_fails_parity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            labels, features = write_inputs(root, cutoffs=CUTOFFS)
            model = root / "model"
            calibration.run(labels, features, TARGETS[0], model)
            output = root / "importance"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "services.data.models.calibrated_propensity_importance",
                    "--labels-dir",
                    str(labels),
                    "--features-dir",
                    str(features),
                    "--model-dir",
                    str(model),
                    "--output-dir",
                    str(output),
                    "--target",
                    TARGETS[0],
                    "--repeats",
                    "1",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertFalse(json.loads(completed.stdout)["serving_ready"])
            report = json.loads((output / "importance_report.json").read_text())
            self.assertEqual(report["test_cutoffs"], [CUTOFFS[-1]])
            self.assertEqual(report["holdout_rows"], 8)
            self.assertEqual(report["input_sha256"], report["input_sha256_after"])
            manifest = json.loads((output / "importance_manifest.json").read_text())
            self.assertEqual(
                manifest["output_sha256"]["importance_report.json"],
                sha256(output / "importance_report.json"),
            )
            with self.assertRaises(ValueError):
                importance.run(
                    model,
                    output,
                    labels_dir=labels,
                    features_dir=features,
                    target=TARGETS[0],
                )
            with self.assertRaisesRegex(ValueError, "target"):
                importance.run(
                    model,
                    root / "wrong-target",
                    labels_dir=labels,
                    features_dir=features,
                    target=TARGETS[1],
                    repeats=1,
                )
            for file, mutate, expected in (
                (
                    "test_predictions.json",
                    lambda obj: obj[0].update(golden_customer_id="fake"),
                    "identity",
                ),
                (
                    "test_predictions.json",
                    lambda obj: obj[0].update(calibrated_probability=0.1234567),
                    "prediction",
                ),
                (
                    "calibration_evaluation.json",
                    lambda obj: obj["test"]["calibrated"]["metrics"].update(
                        brier_score=0.999
                    ),
                    "baseline",
                ),
            ):
                path = model / file
                original = path.read_text()
                obj = json.loads(original)
                mutate(obj)
                path.write_text(json.dumps(obj))
                manifest_path = model / "calibration_manifest.json"
                original_manifest = manifest_path.read_text()
                record = json.loads(original_manifest)
                record["output_sha256"][file] = sha256(path)
                manifest_path.write_text(json.dumps(record))
                with self.assertRaisesRegex(ValueError, expected):
                    importance.run(
                        model,
                        root / f"bad-{expected}",
                        labels_dir=labels,
                        features_dir=features,
                        target=TARGETS[0],
                        repeats=1,
                    )
                self.assertFalse((root / f"bad-{expected}").exists())
                path.write_text(original)
                manifest_path.write_text(original_manifest)
            record = json.loads((model / "calibration_manifest.json").read_text())
            record["input_sha256"]["features.csv"] = "wrong"
            (model / "calibration_manifest.json").write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, "provenance"):
                importance.run(
                    model,
                    root / "bad-provenance",
                    labels_dir=labels,
                    features_dir=features,
                    target=TARGETS[0],
                    repeats=1,
                )


if __name__ == "__main__":
    unittest.main()
