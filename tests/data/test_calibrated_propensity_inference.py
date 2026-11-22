"""Saved calibrated POS predictions can be replayed without fitting or labels."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from services.data.ingestion.validator import sha256
from services.data.models import calibrated_propensity_inference as inference
from services.data.models import propensity_calibration as calibration
from services.data.models.propensity_experiment import _read_features
from tests.data.test_propensity_calibration import CUTOFFS, TARGETS
from tests.data.test_propensity_experiment import write_inputs


class CalibratedInferenceTests(unittest.TestCase):
    def test_saved_test_parity_and_cli(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            labels, features = write_inputs(root, cutoffs=CUTOFFS)
            rows = _read_features(features / "features.csv")
            for target in TARGETS:
                model = root / target
                calibration.run(labels, features, target, model)
                artifact = json.loads((model / "calibration_artifact.json").read_text())
                scored = inference.predict_rows(
                    artifact,
                    rows,
                    generated_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
                )
                saved = json.loads((model / "test_predictions.json").read_text())
                for expected in saved:
                    actual = next(
                        p
                        for p in scored
                        if p["golden_customer_id"] == expected["golden_customer_id"]
                        and datetime.fromisoformat(p["cutoff_at"])
                        == datetime.fromisoformat(expected["cutoff_at"])
                    )
                    self.assertAlmostEqual(
                        actual["raw_probability"], expected["raw_probability"]
                    )
                    self.assertAlmostEqual(
                        actual["calibrated_probability"],
                        expected["calibrated_probability"],
                    )
                self.assertNotIn("uncalibrated_probability", scored[0])
                self.assertNotIn("target_value", scored[0])
                output = root / f"output-{target}"
                cli = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "services.data.models.calibrated_propensity_inference",
                        "--model-dir",
                        str(model),
                        "--features-dir",
                        str(features),
                        "--target",
                        target,
                        "--output-dir",
                        str(output),
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                self.assertFalse(json.loads(cli.stdout)["serving_ready"])
                manifest = json.loads(
                    (output / "calibrated_prediction_manifest.json").read_text()
                )
                self.assertEqual(manifest["rows"], len(rows))
                self.assertEqual(
                    manifest["input_sha256"], manifest["input_sha256_after"]
                )
                self.assertEqual(
                    manifest["output_sha256"]["calibrated_predictions.json"],
                    sha256(output / "calibrated_predictions.json"),
                )
                with self.assertRaises(ValueError):
                    inference.run(model, features, target, output)

    def test_rejects_tampering_and_invalid_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            labels, features = write_inputs(root, cutoffs=CUTOFFS)
            model = root / "model"
            calibration.run(labels, features, TARGETS[0], model)
            artifact_path = model / "calibration_artifact.json"
            manifest_path = model / "calibration_manifest.json"
            original = artifact_path.read_text()
            manifest_original = manifest_path.read_text()
            rows = _read_features(features / "features.csv")
            now = datetime(2027, 1, 1, tzinfo=timezone.utc)
            artifact = json.loads(original)
            for key, value in (
                ("target_version", "wrong"),
                ("serving_ready", True),
                ("features", ["target_value"]),
                ("isotonic", {"status": "unknown"}),
            ):
                changed = copy.deepcopy(artifact)
                changed[key] = value
                with self.assertRaises(ValueError):
                    inference.predict_rows(changed, rows, generated_at=now)
            changed = copy.deepcopy(artifact)
            changed["logistic"]["scaler_scale"][0] = 0
            with self.assertRaises(ValueError):
                inference.predict_rows(changed, rows, generated_at=now)
            for bad_rows, at in (
                ([{**rows[0], "target_value": "1"}], now),
                ([{**rows[0], "cutoff_at": "2027-02-01T00:00:00+07:00"}], now),
                (rows[:1] * 2, now),
                (rows[:1], datetime(2027, 1, 1)),
            ):
                with self.assertRaises(ValueError):
                    inference.predict_rows(artifact, bad_rows, generated_at=at)
            artifact_path.write_text(original + " ")
            with self.assertRaises(ValueError):
                inference.run(model, features, TARGETS[0], root / "tampered")
            artifact_path.write_text(original)
            record = json.loads(manifest_original)
            record["input_sha256"]["features.csv"] = "wrong"
            manifest_path.write_text(json.dumps(record))
            with self.assertRaises(ValueError):
                inference.run(model, features, TARGETS[0], root / "lineage")
            manifest_path.write_text(manifest_original)
            with self.assertRaises(ValueError):
                inference.run(
                    model,
                    root / "ground_truth" / "features",
                    TARGETS[0],
                    root / "blocked",
                )
            with self.assertRaises(ValueError):
                inference.run(model, features, TARGETS[1], root / "wrong-target")

    def test_malformed_manifest_and_parameters_raise_value_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            labels, features = write_inputs(root, cutoffs=CUTOFFS)
            model = root / "model"
            calibration.run(labels, features, TARGETS[0], model)
            feature_manifest = features / "feature_manifest.json"
            original = feature_manifest.read_text()
            record = json.loads(original)
            record["output_sha256"] = ["features.csv"]
            feature_manifest.write_text(json.dumps(record))
            with self.assertRaises(ValueError):
                inference.run(model, features, TARGETS[0], root / "bad-hashes")
            feature_manifest.write_text(original)
            rows = _read_features(features / "features.csv")
            artifact = json.loads((model / "calibration_artifact.json").read_text())
            artifact["logistic"]["coef"][0] = 10**400
            with self.assertRaises(ValueError):
                inference.predict_rows(
                    artifact,
                    rows,
                    generated_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
                )

    def test_equivalent_utc_offsets_are_duplicates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            labels, features = write_inputs(root, cutoffs=CUTOFFS)
            model = root / "model"
            calibration.run(labels, features, TARGETS[0], model)
            artifact = json.loads((model / "calibration_artifact.json").read_text())
            first = _read_features(features / "features.csv")[0]
            same_instant = {**first, "cutoff_at": "2026-03-01T00:00:00+07:00"}
            twin = {**first, "cutoff_at": "2026-02-28T17:00:00+00:00"}
            with self.assertRaises(ValueError):
                inference.predict_rows(
                    artifact,
                    [same_instant, twin],
                    generated_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
                )

    def test_manifest_records_whether_scored_features_match_calibration_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            labels, features = write_inputs(root, cutoffs=CUTOFFS)
            model = root / "model"
            calibration.run(labels, features, TARGETS[0], model)
            result = inference.run(model, features, TARGETS[0], root / "out")
            calibration_manifest = json.loads(
                (model / "calibration_manifest.json").read_text()
            )
            self.assertEqual(
                result["calibration_input_sha256"], calibration_manifest["input_sha256"]
            )
            self.assertIs(result["scored_features_match_calibration"], True)

    def test_failed_write_leaves_no_partial_output_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            labels, features = write_inputs(root, cutoffs=CUTOFFS)
            model = root / "model"
            calibration.run(labels, features, TARGETS[0], model)
            real_dumps = json.dumps
            calls = {"n": 0}

            def failing(*args, **kwargs):
                calls["n"] += 1
                if calls["n"] == 2:
                    raise ValueError("serialization failed")
                return real_dumps(*args, **kwargs)

            from unittest.mock import patch

            with patch.object(inference.json, "dumps", failing):
                with self.assertRaises(ValueError):
                    inference.run(model, features, TARGETS[0], root / "partial")
            self.assertFalse((root / "partial").exists())


if __name__ == "__main__":
    unittest.main()
