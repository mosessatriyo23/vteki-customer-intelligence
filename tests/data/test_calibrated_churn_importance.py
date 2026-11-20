"""Saved three-fold calibrated scorer and provenance, never a new fit."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.data.ingestion.validator import sha256
from services.data.models import calibrated_churn_importance as importance
from services.data.models import churn_calibration as calibration
from tests.data.test_churn_calibration import CUTOFFS, rows, write_source


class CalibratedImportanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = rows()
        cls.evaluation, cls.predictions, cls.artifact = calibration.evaluate(cls.data)
        cls.holdout = calibration.three_fold_split(calibration._normalized(cls.data))[2]

    def test_reload_matches_saved_predictions_without_fitting_or_mutation(self):
        before = copy.deepcopy((self.artifact, self.holdout))
        with (
            patch(
                "sklearn.linear_model.LogisticRegression.fit",
                side_effect=AssertionError,
            ),
            patch(
                "sklearn.isotonic.IsotonicRegression.fit", side_effect=AssertionError
            ),
        ):
            report = importance.evaluate(self.artifact, self.holdout, repeats=3)
        expected = self.evaluation["test"]["calibrated"]["metrics"]
        for metric in ("roc_auc", "brier_score"):
            self.assertAlmostEqual(
                report["baseline"][metric], expected[metric], places=12
            )
        self.assertEqual(before, (self.artifact, self.holdout))
        self.assertEqual(
            report, importance.evaluate(self.artifact, self.holdout, repeats=3)
        )
        self.assertEqual(
            len(report["global_importance"]), len(self.artifact["features"])
        )
        for flag in (
            "training_ready",
            "experiment_ready",
            "final_model",
            "serving_ready",
            "refitted",
        ):
            self.assertIs(report[flag], False)
        self.assertTrue(report["development_only"])
        self.assertTrue(report["advisory_only"])
        json.dumps(report, allow_nan=False)

    def test_constant_saved_isotonic_proves_permutations_are_calibrated(self):
        artifact = copy.deepcopy(self.artifact)
        artifact["isotonic"] = {
            "x_thresholds": [0.2, 0.8],
            "y_thresholds": [0.3, 0.3],
            "out_of_bounds": "clip",
        }
        report = importance.evaluate(artifact, self.holdout, repeats=2)
        self.assertEqual(report["baseline"]["roc_auc"], 0.5)
        for entry in report["global_importance"] + report["grouped_importance"]:
            self.assertEqual(entry["auc_drop_mean"], 0)
            self.assertEqual(entry["brier_increase_mean"], 0)
        self.assertEqual(
            importance._interpolate([0.0, 0.5, 1.0], [0.2, 0.8], [0.1, 0.9]),
            [0.1, 0.5, 0.9],
        )

    def test_rejects_bad_isotonic_and_invalid_controls(self):
        for knots in ([0.8, 0.2], [0.2, 0.2], [float("nan"), 0.8]):
            artifact = copy.deepcopy(self.artifact)
            artifact["isotonic"]["x_thresholds"] = knots
            artifact["isotonic"]["y_thresholds"] = [0.1, 0.9]
            with self.assertRaises(ValueError):
                importance.evaluate(artifact, self.holdout)
        for kwargs in ({"repeats": 0}, {"repeats": True}, {"min_n": 0}):
            with self.assertRaises(ValueError):
                importance.evaluate(self.artifact, self.holdout, **kwargs)
        single = [{**r, "churn90": 0} for r in self.holdout]
        report = importance.evaluate(self.artifact, single, repeats=1)
        self.assertIsNone(report["baseline"]["roc_auc"])
        self.assertTrue(
            all(e["auc_drop_mean"] is None for e in report["global_importance"])
        )

    def test_rehashed_evaluation_and_source_provenance_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, model = root / "source", root / "model"
            write_source(source, self.data)
            calibration.run(source, model)
            evaluation_path = model / "calibration_evaluation.json"
            evaluation = json.loads(evaluation_path.read_text())
            evaluation["test"]["calibrated"]["metrics"]["roc_auc"] = 0.01
            evaluation_path.write_text(json.dumps(evaluation))
            manifest_path = model / "calibration_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["output_sha256"][evaluation_path.name] = sha256(evaluation_path)
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "baseline"):
                importance.run(
                    model, root / "bad-evaluation", source_dir=source, repeats=1
                )
            manifest["input_sha256"]["training_rows.csv"] = "wrong"
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "provenance"):
                importance.run(model, root / "bad-source", source_dir=source, repeats=1)
            manifest["serving_ready"] = True
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "Development-only"):
                importance.run(model, root / "bad-flags", source_dir=source, repeats=1)

    def test_real_fixture_cli_and_integrity_guards(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, model, output = root / "source", root / "model", root / "output"
            write_source(source, list(reversed(self.data)))
            calibration.run(source, model)
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "services.data.models.calibrated_churn_importance",
                    "--source-dir",
                    str(source),
                    "--model-dir",
                    str(model),
                    "--output-dir",
                    str(output),
                    "--repeats",
                    "2",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertFalse(json.loads(completed.stdout)["serving_ready"])
            report = json.loads((output / "importance_report.json").read_text())
            self.assertEqual(report["test_cutoffs"], [CUTOFFS[-1]])
            self.assertEqual(report["holdout_rows"], 20)
            self.assertEqual(report["input_sha256"], report["input_sha256_after"])
            manifest = json.loads((output / "importance_manifest.json").read_text())
            self.assertEqual(
                manifest["output_sha256"]["importance_report.json"],
                sha256(output / "importance_report.json"),
            )
            with self.assertRaisesRegex(ValueError, "new"):
                importance.run(model, output, source_dir=source)
            with self.assertRaisesRegex(ValueError, "separate"):
                importance.run(model, source / "nested", source_dir=source)
            with self.assertRaisesRegex(ValueError, "ground_truth"):
                importance.run(model, root / "ground_truth" / "out", source_dir=source)
            # A rehashed but false saved prediction must still fail baseline verification.
            predictions = json.loads((model / "test_predictions.json").read_text())
            predictions[0]["calibrated_probability"] = 0.123456
            (model / "test_predictions.json").write_text(json.dumps(predictions))
            manifest = json.loads((model / "calibration_manifest.json").read_text())
            manifest["output_sha256"]["test_predictions.json"] = sha256(
                model / "test_predictions.json"
            )
            (model / "calibration_manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "prediction"):
                importance.run(model, root / "bad", source_dir=source, repeats=1)
            self.assertFalse((root / "bad").exists())


if __name__ == "__main__":
    unittest.main()
