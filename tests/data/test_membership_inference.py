"""Offline membership logistic scoring against the fitted experiment JSON."""

import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from services.data.ingestion.validator import sha256
from services.data.models import renewal_membership_experiment as experiment
from services.data.models.membership_features import FIELDS
from services.data.models.membership_inference import load_model, predict_rows
from tests.data.test_renewal_membership_experiment import write_inputs

GENERATED = datetime.fromisoformat("2026-06-02T00:00:00+07:00")


class MembershipInferenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        labels, members = write_inputs(self.root)
        self.model_dir = self.root / "model"
        experiment.run(labels, members, self.model_dir)
        self.rows = experiment._read_csv(members / "membership_features.csv", FIELDS)[
            8:
        ]

    def rewrite(self, name, key, value):
        path = self.model_dir / name
        data = json.loads(path.read_text(encoding="utf-8"))
        data[key] = value
        path.write_text(json.dumps(data), encoding="utf-8")
        manifest_path = self.model_dir / "experiment_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["output_sha256"][name] = sha256(path)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_reloads_actual_fitted_holdout_without_refitting(self):
        expected = json.loads((self.model_dir / "holdout_predictions.json").read_text())
        with patch.object(
            experiment, "evaluate", side_effect=AssertionError("refit forbidden")
        ):
            model = load_model(self.model_dir)
            actual = predict_rows(model, self.rows, generated_at=GENERATED)
        self.assertEqual(len(actual), len(expected))
        for prediction, fitted in zip(actual, expected):
            self.assertEqual(prediction["model_version"], experiment.MODEL_VERSION)
            self.assertEqual(
                prediction["golden_customer_id"], fitted["golden_customer_id"]
            )
            self.assertAlmostEqual(
                prediction["raw_probability"], fitted["logistic_probability"], places=14
            )
            self.assertAlmostEqual(
                prediction["log_odds"],
                prediction["intercept"]
                + sum(
                    item["log_odds_contribution"]
                    for item in prediction["contributions"]
                ),
            )
            self.assertEqual(
                [item["feature"] for item in prediction["contributions"]],
                list(experiment.FEATURES),
            )
            self.assertFalse(prediction["serving_ready"])
            self.assertIn("Current-snapshot", " ".join(prediction["limitations"]))
            self.assertNotIn("reason_codes", prediction)
            self.assertNotIn("target_value", prediction)

    def test_rejects_tampered_artifact_even_if_other_files_intact(self):
        for name in experiment.OUTPUTS:
            with self.subTest(name=name):
                path = self.model_dir / name
                original = path.read_bytes()
                path.write_bytes(original + b" ")
                with self.assertRaisesRegex(ValueError, "checksum"):
                    load_model(self.model_dir)
                path.write_bytes(original)

    def test_rejects_rehashed_wrong_identity_status_features_and_parameters(self):
        for name, key, value in (
            ("model_parameters.json", "features", list(reversed(experiment.FEATURES))),
            ("model_parameters.json", "model_version", "wrong"),
            ("evaluation.json", "post_holdout_inspection", False),
            ("evaluation.json", "features", ["renewal60"]),
        ):
            with self.subTest(name=name, key=key):
                original = (self.model_dir / name).read_bytes()
                manifest = (self.model_dir / "experiment_manifest.json").read_bytes()
                self.rewrite(name, key, value)
                with self.assertRaises(ValueError):
                    load_model(self.model_dir)
                (self.model_dir / name).write_bytes(original)
                (self.model_dir / "experiment_manifest.json").write_bytes(manifest)
        path = self.model_dir / "model_parameters.json"
        original = path.read_bytes()
        manifest = (self.model_dir / "experiment_manifest.json").read_bytes()
        for field, values in (
            ("coef", [True] * 6),
            ("intercept", [float("nan")]),
            ("scaler_scale", [0] * 6),
            ("scaler_mean", [1e309] * 6),
        ):
            with self.subTest(field=field):
                data = json.loads(original)
                data["logistic"][field] = values
                self.rewrite("model_parameters.json", "logistic", data["logistic"])
                with self.assertRaises(ValueError):
                    load_model(self.model_dir)
                path.write_bytes(original)
                (self.model_dir / "experiment_manifest.json").write_bytes(manifest)

    def test_rejects_rehashed_manifest_and_prediction_contracts(self):
        manifest_path = self.model_dir / "experiment_manifest.json"
        original_manifest = manifest_path.read_bytes()
        for key, value in (
            ("serving_ready", True),
            ("target", "retail_purchase30"),
            ("output_sha256", {}),
        ):
            with self.subTest(key=key):
                manifest = json.loads(original_manifest)
                manifest[key] = value
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_model(self.model_dir)
                manifest_path.write_bytes(original_manifest)
        path = self.model_dir / "holdout_predictions.json"
        original = path.read_bytes()
        predictions = json.loads(original)
        predictions[0]["independent_confirmation"] = True
        path.write_text(json.dumps(predictions), encoding="utf-8")
        manifest = json.loads(original_manifest)
        manifest["output_sha256"][path.name] = sha256(path)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_model(self.model_dir)

    def test_rejects_labels_bad_rows_naive_time_and_duplicate_instant(self):
        model = load_model(self.model_dir)
        row = self.rows[0]
        variants = [
            {**row, "renewal60": 1},
            {**row, "target_value": 0},
            {**row, "ground_truth": "unknown"},
            {k: v for k, v in row.items() if k != "renewal_count_365d"},
            {**row, "feature_version": "wrong"},
            {**row, "training_ready": "True"},
            {**row, "has_membership_history": "maybe"},
            {**row, "cutoff_at": "2026-06-01"},
            {**row, "cutoff_at": "2026-06-03T00:00:00+07:00"},
            {**row, "current_tier_ordinal": "4"},
            {**row, "renewal_count_365d": ""},
        ]
        for candidate in variants:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                predict_rows(model, [candidate], generated_at=GENERATED)
        with self.assertRaises(ValueError):
            predict_rows(model, [row], generated_at=GENERATED.replace(tzinfo=None))
        utc = {
            **row,
            "cutoff_at": datetime.fromisoformat(row["cutoff_at"])
            .astimezone(timezone.utc)
            .isoformat(),
        }
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            predict_rows(model, [row, utc], generated_at=GENERATED)
        self.assertEqual(
            predict_rows(model, [row], generated_at=GENERATED),
            predict_rows(model, [utc], generated_at=GENERATED),
        )

    def test_predict_rows_revalidates_public_dataclass_vectors(self):
        model = load_model(self.model_dir)
        bad = {
            "coef": model.coef[:-1],
            "scaler_mean": model.scaler_mean + (0.0,),
            "imputer_medians": (),
            "scaler_scale": (0.0,) * len(model.scaler_scale),
            "intercept": float("nan"),
        }
        for field, value in bad.items():
            with self.subTest(field=field), self.assertRaises(ValueError):
                predict_rows(
                    replace(model, **{field: value}),
                    self.rows[:1],
                    generated_at=GENERATED,
                )
        nan_scale = (float("nan"),) + model.scaler_scale[1:]
        with self.assertRaises(ValueError):
            predict_rows(
                replace(model, scaler_scale=nan_scale),
                self.rows[:1],
                generated_at=GENERATED,
            )

    def test_prediction_binds_manifest_sha256(self):
        model = load_model(self.model_dir)
        expected = sha256(self.model_dir / "experiment_manifest.json")
        self.assertEqual(model.manifest_sha256, expected)
        output = predict_rows(model, self.rows[:1], generated_at=GENERATED)[0]
        self.assertEqual(output["manifest_sha256"], expected)

    def test_rejects_missing_or_mismatched_input_hashes(self):
        path = self.model_dir / "experiment_manifest.json"
        original = path.read_bytes()
        manifest = json.loads(original)
        after = dict(manifest["input_sha256_after"])
        first = sorted(after)[0]
        variants = {
            "missing_before": lambda m: m.pop("input_sha256"),
            "missing_after": lambda m: m.pop("input_sha256_after"),
            "not_dict": lambda m: m.update(input_sha256=[]),
            "mismatch": lambda m: m["input_sha256_after"].update({first: "0" * 64}),
            "extra_key": lambda m: m["input_sha256"].update(extra="0" * 64),
            "missing_key": lambda m: m["input_sha256_after"].pop(first),
        }
        for name, mutate in variants.items():
            with self.subTest(name=name):
                changed = json.loads(original)
                mutate(changed)
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_model(self.model_dir)
        path.write_bytes(original)
        load_model(self.model_dir)

    def test_rejects_ground_truth_paths_directly_and_via_resolved_files(self):
        direct = self.root / "ground_truth" / "model"
        shutil.copytree(self.model_dir, direct)
        with self.assertRaisesRegex(ValueError, "ground_truth"):
            load_model(direct)
        link_dir = self.root / "gt_link"
        link_dir.mkdir()
        for name in (*experiment.OUTPUTS, "experiment_manifest.json"):
            (link_dir / name).write_bytes((self.model_dir / name).read_bytes())
        (self.root / "ground_truth").joinpath("params.json").write_bytes(
            (self.model_dir / "model_parameters.json").read_bytes()
        )
        target = link_dir / "model_parameters.json"
        target.unlink()
        try:
            target.symlink_to(self.root / "ground_truth" / "params.json")
        except OSError:
            self.skipTest("symlinks unavailable")
        with self.assertRaisesRegex(ValueError, "ground_truth"):
            load_model(link_dir)


if __name__ == "__main__":
    unittest.main()
