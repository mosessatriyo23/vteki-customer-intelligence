"""Offline calibrated JSON reload: parity, strict inputs and fail-closed lineage."""

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from services.data.features.snapshot import FIELDS
from services.data.ingestion.validator import sha256
from services.data.models import calibrated_churn_inference as inference
from services.data.models import churn_calibration as calibration
from tests.data.test_churn_calibration import CUTOFFS, rows, write_source


class CalibratedInferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.bundle = self.root / "source", self.root / "bundle"
        self.data = rows()
        write_source(self.source, self.data)
        calibration.run(self.source, self.bundle)
        self.features = [
            {**{key: row[key] for key in FIELDS}, "identity_status": "APPROVED"}
            for row in self.data
            if row["cutoff_at"] == CUTOFFS[-1]
        ]
        self.features.sort(key=lambda row: row["golden_customer_id"])
        self.generated = datetime.fromisoformat(CUTOFFS[-1])

    def rewrite(self, name, change, *, rehash=True):
        path = self.bundle / name
        value = json.loads(path.read_bytes())
        change(value)
        path.write_text(json.dumps(value), encoding="utf-8")
        if rehash and name != "calibration_manifest.json":
            self.rewrite(
                "calibration_manifest.json",
                lambda manifest: manifest["output_sha256"].update({name: sha256(path)}),
            )

    def test_real_bundle_parity_no_refit_and_provenance(self):
        before = copy.deepcopy(self.features)
        with (
            patch(
                "sklearn.linear_model.LogisticRegression.fit",
                side_effect=AssertionError,
            ),
            patch(
                "sklearn.isotonic.IsotonicRegression.fit", side_effect=AssertionError
            ),
        ):
            model = inference.load_model(self.bundle)
            actual = inference.predict_rows(
                model, self.features, generated_at=self.generated
            )
        saved = json.loads((self.bundle / "test_predictions.json").read_bytes())
        for result, expected in zip(actual, saved):
            for field in ("raw_probability", "calibrated_probability"):
                self.assertAlmostEqual(result[field], expected[field], places=12)
            for key, flag in calibration.FLAGS.items():
                self.assertIs(result[key], flag)
            self.assertEqual(result["horizon_days"], 90)
            self.assertEqual(
                result["model_artifact_sha256"],
                sha256(self.bundle / "calibration_artifact.json"),
            )
            self.assertEqual(
                result["manifest_sha256"],
                sha256(self.bundle / "calibration_manifest.json"),
            )
            self.assertIn("did not generalize", " ".join(result["limitations"]))
            self.assertIn("synthetic", result["disclaimer"].lower())
            self.assertNotIn("valid_until", result)
            self.assertNotIn("band", result)
        self.assertEqual(before, self.features)
        model.artifact["isotonic"] = {
            "out_of_bounds": "clip",
            "x_thresholds": [0.0],
            "y_thresholds": [0.42],
        }
        with self.assertRaisesRegex(ValueError, "artifact changed"):
            inference.predict_rows(model, self.features, generated_at=self.generated)

    def test_strict_rows_timestamps_and_duplicate_instants(self):
        model = inference.load_model(self.bundle)
        invalid = [
            {**self.features[0], "churn90": 0},
            {**self.features[0], "cutoff_at": "2026-06-30T00:00:00"},
            {**self.features[0], "cutoff_at": "2027-01-01T00:00:00+07:00"},
            {**self.features[0], "cutoff_at": CUTOFFS[0]},
            {**self.features[0], "purchase_count_90d": float("inf")},
            {**self.features[0], "tenure_days": True},
        ]
        for row in invalid:
            with self.subTest(row=row), self.assertRaises(ValueError):
                inference.predict_rows(model, [row], generated_at=self.generated)
        equivalent = {
            **self.features[0],
            "cutoff_at": self.generated.astimezone(timezone.utc).isoformat(),
        }
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            inference.predict_rows(
                model, [self.features[0], equivalent], generated_at=self.generated
            )
        with self.assertRaises(ValueError):
            inference.predict_rows(
                model, [], generated_at=self.generated.replace(tzinfo=None)
            )
        self.assertEqual(
            inference.predict_rows(model, [], generated_at=self.generated), []
        )

    def test_manifest_flags_versions_and_provenance(self):
        original = (self.bundle / "calibration_manifest.json").read_bytes()
        mutations = [(key, not flag) for key, flag in calibration.FLAGS.items()]
        mutations += [
            ("model_version", "wrong"),
            ("feature_version", "wrong"),
            ("label_version", "wrong"),
            ("input_sha256_after", {}),
            ("input_sha256", {}),
        ]
        for key, value in mutations:
            with self.subTest(key=key):
                (self.bundle / "calibration_manifest.json").write_bytes(original)
                self.rewrite(
                    "calibration_manifest.json", lambda item: item.update({key: value})
                )
                with self.assertRaises(ValueError):
                    inference.load_model(self.bundle)

    def test_every_bundle_checksum_and_evaluation_provenance(self):
        for name in calibration.OUTPUTS:
            path = self.bundle / name
            original = path.read_bytes()
            path.write_bytes(original + b" ")
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(ValueError, "checksum"),
            ):
                inference.load_model(self.bundle)
            path.write_bytes(original)
        self.rewrite(
            "calibration_evaluation.json",
            lambda item: item.update(input_sha256_after={}),
        )
        with self.assertRaisesRegex(ValueError, "provenance"):
            inference.load_model(self.bundle)

    def test_parameter_contract_and_invalid_vectors_even_after_load(self):
        model = inference.load_model(self.bundle)
        original = copy.deepcopy(model.artifact)
        mutations = [
            lambda item: item.update(serving_ready=True),
            lambda item: item.update(method="wrong"),
            lambda item: item["logistic"].update(coef=[True]),
            lambda item: item["logistic"].update(scaler_scale=[0.0] * 7),
            lambda item: item["logistic"].update(imputer_medians=[float("nan")] * 7),
            lambda item: item["isotonic"].update(x_thresholds=[0.8, 0.2]),
            lambda item: item["isotonic"].update(y_thresholds=[-1.0]),
        ]
        for mutate in mutations:
            model.artifact.clear()
            model.artifact.update(copy.deepcopy(original))
            mutate(model.artifact)
            with self.assertRaises(ValueError):
                inference.predict_rows(
                    model, self.features, generated_at=self.generated
                )
        self.rewrite(
            "calibration_artifact.json", lambda item: item.update(final_model=True)
        )
        with self.assertRaises(ValueError):
            inference.load_model(self.bundle)
