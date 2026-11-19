"""Offline JSON logistic inference; never a production prediction handoff."""

import csv
import json
import math
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from services.data.features.snapshot import FIELDS, VERSION
from services.data.ingestion.validator import sha256
from services.data.models.churn_experiment import FEATURES, MODEL_VERSION, evaluate
from services.data.models.churn_inference import load_model, predict_rows, run
from services.data.models.labels import CHRIST_VERSION

GENERATED = datetime.fromisoformat("2026-04-03T00:00:00+07:00")


def training_rows():
    result = []
    for cutoff in ("2026-01-01T00:00:00+07:00", "2026-04-02T00:00:00+07:00"):
        for i in range(8):
            result.append(
                dict(
                    golden_customer_id=f"g{i}",
                    cutoff_at=cutoff,
                    identity_status="PROVISIONAL",
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


def write_json(path, value):
    path.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")


class ChurnInferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report, cls.expected, cls.parameters = evaluate(training_rows())
        cls.features = [
            {key: row[key] for key in FIELDS} for row in training_rows()[8:]
        ]

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model_dir = self.root / "model"
        self.model_dir.mkdir()
        for name, value in (
            ("evaluation.json", self.report),
            ("holdout_predictions.json", self.expected),
            ("model_parameters.json", self.parameters),
        ):
            write_json(self.model_dir / name, value)
        self.refresh_manifest()

    def refresh_manifest(self):
        write_json(
            self.model_dir / "experiment_manifest.json",
            dict(
                model_version=MODEL_VERSION,
                development_only=True,
                serving_ready=False,
                output_sha256={
                    name: sha256(self.model_dir / name)
                    for name in (
                        "evaluation.json",
                        "holdout_predictions.json",
                        "model_parameters.json",
                    )
                },
            ),
        )

    def feature_dir(self):
        source = self.root / "features"
        source.mkdir()
        with (source / "features.csv").open(
            "w", newline="", encoding="utf-8"
        ) as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(self.features)
        write_json(
            source / "feature_manifest.json",
            dict(
                feature_version=VERSION,
                training_ready=False,
                rows=len(self.features),
                output_sha256={"features.csv": sha256(source / "features.csv")},
            ),
        )
        return source

    def test_json_model_matches_sklearn_holdout_and_exact_log_odds_explanations(self):
        model = load_model(self.model_dir)
        predictions = predict_rows(model, self.features, generated_at=GENERATED)
        for actual, expected in zip(predictions, self.expected):
            self.assertAlmostEqual(
                actual["churn_probability"], expected["logistic_probability"], places=14
            )
            self.assertEqual(
                actual["golden_customer_id"], expected["golden_customer_id"]
            )
            self.assertEqual(actual["model_version"], MODEL_VERSION)
            self.assertEqual(actual["feature_version"], VERSION)
            self.assertEqual(actual["label_version"], CHRIST_VERSION)
            self.assertEqual(actual["horizon_days"], 90)
            self.assertEqual(
                actual["model_artifact_sha256"],
                sha256(self.model_dir / "model_parameters.json"),
            )
            self.assertEqual(actual["generated_at"], GENERATED.isoformat())
            self.assertIsNone(actual["valid_until"])
            self.assertFalse(actual["serving_ready"])
            self.assertFalse(actual["training_ready"])
            self.assertFalse(actual["experiment_ready"])
            self.assertIn("calibration_absent", actual["serving_blockers"])
            self.assertNotIn("reason_codes", actual)
            self.assertEqual(
                [item["feature"] for item in actual["contributions"]], list(FEATURES)
            )
            self.assertIn("not causal", actual["explanation_method"])
            total = actual["intercept"] + sum(
                item["log_odds_contribution"] for item in actual["contributions"]
            )
            self.assertAlmostEqual(total, actual["log_odds"])
            self.assertAlmostEqual(
                1 / (1 + math.exp(-total)), actual["churn_probability"]
            )
        missing = predictions[0]["contributions"][0]
        self.assertTrue(missing["missing"])
        self.assertIsNone(missing["feature_value"])
        self.assertEqual(
            missing["imputed_value"], self.parameters["logistic"]["imputer_medians"][0]
        )

    def test_hashes_all_outputs_before_loading_and_rejects_tampering(self):
        for name in (
            "evaluation.json",
            "holdout_predictions.json",
            "model_parameters.json",
        ):
            with self.subTest(name=name):
                path = self.model_dir / name
                original = path.read_bytes()
                path.write_bytes(original + b" ")
                with self.assertRaisesRegex(ValueError, "checksum"):
                    load_model(self.model_dir)
                path.write_bytes(original)

    def test_rejects_rehashed_bad_model_contract_shapes_and_numbers(self):
        mutations = [
            ("feature_version", "wrong"),
            ("label_version", "wrong"),
            ("model_version", "wrong"),
            ("features", list(reversed(FEATURES))),
            ("development_only", False),
            ("serving_ready", True),
        ]
        for key, value in mutations:
            with self.subTest(key=key):
                write_json(
                    self.model_dir / "model_parameters.json",
                    {**self.parameters, key: value},
                )
                self.refresh_manifest()
                with self.assertRaises(ValueError):
                    load_model(self.model_dir)
        for key, value in (
            ("coef", [0] * 6),
            ("coef", [True] * 7),
            ("coef", ["1"] * 7),
            ("scaler_scale", [0] * 7),
            ("scaler_scale", [-1] * 7),
            ("intercept", [0, 1]),
            ("imputer_medians", [-1] * 7),
            ("scaler_mean", [-1] * 7),
        ):
            with self.subTest(key=key, value=value):
                write_json(
                    self.model_dir / "model_parameters.json",
                    {
                        **self.parameters,
                        "logistic": {**self.parameters["logistic"], key: value},
                    },
                )
                self.refresh_manifest()
                with self.assertRaises(ValueError):
                    load_model(self.model_dir)
        path = self.model_dir / "model_parameters.json"
        path.write_text(
            json.dumps(self.parameters).replace('"intercept": [', '"intercept": [NaN,')
        )
        self.refresh_manifest()
        with self.assertRaises(ValueError):
            load_model(self.model_dir)

    def test_rejects_report_identity_missing_boundary_and_nonfinite_parameters(self):
        for key, value in (
            ("model_version", "wrong"),
            ("feature_version", "wrong"),
            ("label_version", "wrong"),
            ("features", ["churn90"]),
            ("train_cutoffs", []),
            ("train_cutoffs", ["2026-01-01"]),
            ("training_ready", True),
            ("experiment_ready", True),
            ("final_model", True),
            ("serving_ready", True),
        ):
            with self.subTest(key=key):
                write_json(
                    self.model_dir / "evaluation.json", {**self.report, key: value}
                )
                self.refresh_manifest()
                with self.assertRaises(ValueError):
                    load_model(self.model_dir)
        write_json(self.model_dir / "evaluation.json", self.report)
        for value in (float("inf"), float("nan"), 10**400):
            parameters = {
                **self.parameters,
                "logistic": {**self.parameters["logistic"], "coef": [value] * 7},
            }
            (self.model_dir / "model_parameters.json").write_text(
                json.dumps(parameters)
            )
            self.refresh_manifest()
            with self.subTest(value=str(value)), self.assertRaises(ValueError):
                load_model(self.model_dir)

    def test_rejects_contract_metadata_future_prior_and_bad_raw_values(self):
        model = load_model(self.model_dir)
        mutations = [
            ("golden_customer_id", " "),
            ("golden_customer_id", 1),
            ("identity_status", "invented"),
            ("feature_version", "wrong"),
            ("training_ready", True),
            ("training_ready", 0),
            ("identity_time_policy", "wrong"),
            ("cutoff_at", "2026-04-02"),
            ("cutoff_at", "2026-04-04T00:00:00+07:00"),
            ("cutoff_at", "2026-03-31T00:00:00+07:00"),
            ("recency_days", "NaN"),
            ("tenure_days", None),
            ("purchase_count_90d", True),
            ("retained_revenue_90d", -1),
            ("retained_revenue_365d", "inf"),
            ("churn90", 1),
        ]
        for key, value in mutations:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                predict_rows(
                    model, [{**self.features[0], key: value}], generated_at=GENERATED
                )
        with self.assertRaises(ValueError):
            predict_rows(
                model,
                [{k: v for k, v in self.features[0].items() if k != "recency_days"}],
                generated_at=GENERATED,
            )
        with self.assertRaises(ValueError):
            predict_rows(
                model, self.features, generated_at=GENERATED.replace(tzinfo=None)
            )

    def test_normalizes_time_duplicates_and_accepts_training_outcome_boundary(self):
        model = load_model(self.model_dir)
        first = self.features[0]
        utc = {
            **first,
            "cutoff_at": datetime.fromisoformat(first["cutoff_at"])
            .astimezone(timezone.utc)
            .isoformat(),
        }
        self.assertEqual(
            predict_rows(model, [first], generated_at=GENERATED),
            predict_rows(model, [utc], generated_at=GENERATED),
        )
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            predict_rows(model, [first, utc], generated_at=GENERATED)
        boundary = (
            datetime.fromisoformat(self.report["train_cutoffs"][0]) + timedelta(days=90)
        ).isoformat()
        self.assertEqual(
            predict_rows(
                model, [{**first, "cutoff_at": boundary}], generated_at=GENERATED
            )[0]["cutoff_at"],
            boundary,
        )

    def test_stable_sigmoid_extremes_and_finite_arithmetic(self):
        for intercept, probability in ((1000, 1.0), (-1000, 0.0)):
            write_json(
                self.model_dir / "model_parameters.json",
                {
                    **self.parameters,
                    "logistic": {
                        **self.parameters["logistic"],
                        "intercept": [intercept],
                    },
                },
            )
            self.refresh_manifest()
            prediction = predict_rows(
                load_model(self.model_dir), [self.features[0]], generated_at=GENERATED
            )[0]
            self.assertEqual(prediction["churn_probability"], probability)
        write_json(
            self.model_dir / "model_parameters.json",
            {
                **self.parameters,
                "logistic": {**self.parameters["logistic"], "coef": [1e308] * 7},
            },
        )
        self.refresh_manifest()
        with self.assertRaises(ValueError):
            predict_rows(
                load_model(self.model_dir),
                [{**self.features[0], "tenure_days": 1e308}],
                generated_at=GENERATED,
            )

    def test_cli_writes_completion_checksums_and_rejects_overwrite_and_overlap(self):
        source = self.feature_dir()
        output = self.root / "predictions"
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "services.data.models.churn_inference",
                "--model-dir",
                str(self.model_dir),
                "--features-dir",
                str(source),
                "--generated-at",
                GENERATED.isoformat(),
                "--output-dir",
                str(output),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        manifest = json.loads((output / "prediction_manifest.json").read_text())
        self.assertFalse(manifest["serving_ready"])
        self.assertEqual(manifest["rows"], 8)
        self.assertEqual(
            manifest["output_sha256"]["predictions.json"],
            sha256(output / "predictions.json"),
        )
        self.assertEqual(manifest["input_sha256"], manifest["input_sha256_after"])
        for destination in (
            output,
            source / "nested",
            self.model_dir / "nested",
            self.root / "ground_truth" / "out",
        ):
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                run(self.model_dir, source, destination, GENERATED)

    def test_feature_manifest_count_hash_flags_and_columns_checked_before_output(self):
        source = self.feature_dir()
        manifest_path = source / "feature_manifest.json"
        original = json.loads(manifest_path.read_text())
        for key, value in (
            ("rows", 99),
            ("feature_version", "bad"),
            ("training_ready", True),
            ("output_sha256", {}),
        ):
            write_json(manifest_path, {**original, key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                run(self.model_dir, source, self.root / "bad", GENERATED)
            self.assertFalse((self.root / "bad").exists())
        write_json(manifest_path, original)
        with (source / "features.csv").open("a") as stream:
            stream.write("bad\n")
        with self.assertRaisesRegex(ValueError, "checksum"):
            run(self.model_dir, source, self.root / "bad", GENERATED)
        text = (source / "features.csv").read_text().replace("recency_days", "churn90")
        (source / "features.csv").write_text(text)
        write_json(
            manifest_path,
            {
                **original,
                "output_sha256": {"features.csv": sha256(source / "features.csv")},
            },
        )
        with self.assertRaisesRegex(ValueError, "columns"):
            run(self.model_dir, source, self.root / "bad", GENERATED)

    def test_changed_inputs_abort_without_completion(self):
        source = self.feature_dir()
        from services.data.models import churn_inference

        original = churn_inference.predict_rows

        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            with (source / "features.csv").open("a") as stream:
                stream.write(" ")
            return result

        with patch.object(churn_inference, "predict_rows", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "changed"):
                run(self.model_dir, source, self.root / "changed", GENERATED)
        self.assertFalse((self.root / "changed").exists())


if __name__ == "__main__":
    unittest.main()
