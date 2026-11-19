"""Development-only reason mapping from exact logistic log-odds contributions."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from services.data.features.snapshot import FIELDS, VERSION
from services.data.ingestion.validator import sha256
from services.data.models.churn_experiment import FEATURES, MODEL_VERSION, evaluate
from services.data.models.churn_inference import load_model, predict_rows
from services.data.models.churn_reasons import (
    MIN_ABS_CONTRIBUTION,
    REASON_MAPPING_VERSION,
    explain,
    run,
)
from services.data.models.labels import CHRIST_VERSION
from tests.data.test_churn_inference import GENERATED, training_rows, write_json

CODES = {
    "recency_days": "PURCHASE_RECENCY",
    "tenure_days": "TENURE",
    "purchase_count_365d": "PURCHASE_FREQUENCY_365D",
    "retained_revenue_365d": "RETAINED_REVENUE_365D",
    "purchase_count_60d": "PURCHASE_FREQUENCY_60D",
    "purchase_count_90d": "PURCHASE_FREQUENCY_90D",
    "retained_revenue_90d": "RETAINED_REVENUE_90D",
}


def make_prediction(values, *, missing=(), intercept=-0.25):
    """Synthetic prediction consistent with churn_inference.predict_rows output."""
    contributions = []
    for feature in FEATURES:
        is_missing = feature in missing
        contributions.append(
            {
                "feature": feature,
                "feature_value": None if is_missing else 3.0,
                "missing": is_missing,
                "imputed_value": 3.0,
                "log_odds_contribution": values.get(feature, 0.0),
            }
        )
    return {
        "golden_customer_id": "g1",
        "cutoff_at": "2026-04-02T00:00:00+07:00",
        "model_version": MODEL_VERSION,
        "feature_version": VERSION,
        "label_version": CHRIST_VERSION,
        "intercept": intercept,
        "log_odds": intercept + sum(values.get(f, 0.0) for f in FEATURES),
        "contributions": contributions,
    }


class ExplainTests(unittest.TestCase):
    def test_mapping_version_and_output_metadata(self):
        self.assertEqual(
            REASON_MAPPING_VERSION, "moses-churn-reason-map-proposed-dev-1.0"
        )
        result = explain(make_prediction({"tenure_days": 0.5, "recency_days": -0.4}))
        for key, value in (
            ("golden_customer_id", "g1"),
            ("cutoff_at", "2026-04-02T00:00:00+07:00"),
            ("model_version", MODEL_VERSION),
            ("feature_version", VERSION),
            ("label_version", CHRIST_VERSION),
            ("development_only", True),
            ("approved_taxonomy", False),
            ("display_text", None),
            ("mapping_version", REASON_MAPPING_VERSION),
        ):
            self.assertEqual(result[key], value)
        text = " ".join(result["limitations"])
        for fragment in ("not causal", "Christ taxonomy", "PIT"):
            self.assertIn(fragment, text)

    def test_sign_maps_to_direction_and_codes_are_allowlisted(self):
        values = {f: (0.3 if i % 2 else -0.3) for i, f in enumerate(FEATURES)}
        result = explain(make_prediction(values))
        self.assertEqual(result["status"], "OK")
        self.assertEqual(len(result["reasons"]), 7)
        for reason in result["reasons"]:
            self.assertEqual(reason["code"], CODES[reason["feature"]])
            expected = (
                "INCREASES_RISK" if values[reason["feature"]] > 0 else "DECREASES_RISK"
            )
            self.assertEqual(reason["direction"], expected)
            self.assertEqual(reason["method"], "logistic_exact_log_odds_contribution")
            self.assertEqual(reason["mapping_version"], REASON_MAPPING_VERSION)
            self.assertEqual(reason["feature_version"], VERSION)
            for key in ("feature_value", "missing", "imputed_value"):
                self.assertIn(key, reason)

    def test_sorted_by_absolute_contribution_desc(self):
        result = explain(
            make_prediction(
                {
                    "tenure_days": 0.2,
                    "recency_days": -0.9,
                    "purchase_count_90d": 0.5,
                    "retained_revenue_90d": -0.3,
                }
            )
        )
        self.assertEqual(
            [r["feature"] for r in result["reasons"]],
            [
                "recency_days",
                "purchase_count_90d",
                "retained_revenue_90d",
                "tenure_days",
            ],
        )

    def test_imputed_feature_excluded_and_never_listed_as_observed(self):
        result = explain(
            make_prediction(
                {
                    "recency_days": 5.0,
                    "tenure_days": 0.4,
                    "purchase_count_90d": 0.3,
                    "retained_revenue_90d": 0.2,
                },
                missing=("recency_days",),
            )
        )
        self.assertEqual(result["status"], "OK")
        self.assertNotIn("recency_days", [r["feature"] for r in result["reasons"]])
        self.assertEqual(
            [e["feature"] for e in result["excluded_imputed"]], ["recency_days"]
        )
        self.assertNotIn("code", result["excluded_imputed"][0])

    def test_fewer_than_min_is_insufficient_without_duplication(self):
        result = explain(
            make_prediction({"tenure_days": 0.4, "purchase_count_90d": -0.3})
        )
        self.assertEqual(result["status"], "INSUFFICIENT_EXPLANATION")
        self.assertEqual(len(result["reasons"]), 2)
        self.assertEqual(len({r["feature"] for r in result["reasons"]}), 2)
        self.assertEqual(len({r["code"] for r in result["reasons"]}), 2)

    def test_imputed_dominant_feature_can_cause_insufficient(self):
        result = explain(
            make_prediction(
                {"recency_days": 3.0, "tenure_days": 0.4, "purchase_count_90d": 0.3},
                missing=("recency_days",),
            )
        )
        self.assertEqual(result["status"], "INSUFFICIENT_EXPLANATION")
        self.assertEqual(len(result["reasons"]), 2)

    def test_threshold_boundary_is_inclusive(self):
        at = MIN_ABS_CONTRIBUTION
        below = MIN_ABS_CONTRIBUTION * 0.999
        result = explain(
            make_prediction(
                {"tenure_days": at, "purchase_count_90d": -at, "recency_days": below}
            )
        )
        self.assertEqual(
            sorted(r["feature"] for r in result["reasons"]),
            ["purchase_count_90d", "tenure_days"],
        )
        self.assertEqual(result["status"], "INSUFFICIENT_EXPLANATION")
        self.assertEqual(
            [e["feature"] for e in result["excluded_below_threshold"]],
            [f for f in FEATURES if f not in ("tenure_days", "purchase_count_90d")],
        )

    def test_custom_parameters_validated(self):
        prediction = make_prediction({"tenure_days": 0.4, "recency_days": 0.3})
        self.assertEqual(explain(prediction, min_reasons=2)["status"], "OK")
        for kwargs in (
            {"min_reasons": 0},
            {"min_abs_contribution": 0.0},
            {"min_abs_contribution": float("nan")},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                explain(prediction, **kwargs)

    def test_reconstruction_tamper_rejected(self):
        prediction = make_prediction({"tenure_days": 0.4})
        prediction["contributions"][1]["log_odds_contribution"] += 1e-3
        with self.assertRaisesRegex(ValueError, "reconstruct"):
            explain(prediction)
        prediction = make_prediction({"tenure_days": 0.4})
        prediction["log_odds"] += 0.01
        with self.assertRaisesRegex(ValueError, "reconstruct"):
            explain(prediction)
        prediction = make_prediction({"tenure_days": 0.4})
        prediction["intercept"] += 0.01
        with self.assertRaisesRegex(ValueError, "reconstruct"):
            explain(prediction)

    def test_contribution_set_must_be_exactly_the_seven_features(self):
        base = make_prediction({"tenure_days": 0.4})
        cases = []
        missing = copy.deepcopy(base)
        missing["contributions"].pop()
        cases.append(missing)
        extra = copy.deepcopy(base)
        extra["contributions"].append(dict(extra["contributions"][0]))
        cases.append(extra)
        duplicate = copy.deepcopy(base)
        duplicate["contributions"][1]["feature"] = FEATURES[0]
        cases.append(duplicate)
        unknown = copy.deepcopy(base)
        unknown["contributions"][1]["feature"] = "visits_90d"
        cases.append(unknown)
        for case in cases:
            with self.subTest(), self.assertRaises(ValueError):
                explain(case)

    def test_malformed_input_rejected(self):
        for mutate in (
            lambda p: p.pop("golden_customer_id"),
            lambda p: p.pop("cutoff_at"),
            lambda p: p.pop("intercept"),
            lambda p: p.pop("log_odds"),
            lambda p: p.pop("contributions"),
            lambda p: p.update(golden_customer_id=" "),
            lambda p: p["contributions"][0].pop("imputed_value"),
            lambda p: p["contributions"][1].update(log_odds_contribution=float("nan")),
            lambda p: p["contributions"][1].update(log_odds_contribution=True),
            lambda p: p["contributions"][1].update(log_odds_contribution="0.4"),
            lambda p: p["contributions"][1].update(missing=1),
            lambda p: p["contributions"][1].update(feature_value=None),
            lambda p: p["contributions"][1].update(feature_value=9.0),
            lambda p: p["contributions"][0].update(missing=True),
            lambda p: p.update(log_odds=float("inf")),
        ):
            prediction = make_prediction({"tenure_days": 0.4})
            mutate(prediction)
            with self.subTest(), self.assertRaises(ValueError):
                explain(prediction)
        with self.assertRaises(ValueError):
            explain([])

    def test_version_mismatch_rejected(self):
        for key in ("model_version", "feature_version", "label_version"):
            prediction = make_prediction({"tenure_days": 0.4})
            prediction[key] = "wrong"
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "version"):
                explain(prediction)

    def test_input_not_mutated(self):
        prediction = make_prediction({"tenure_days": 0.4, "recency_days": -0.5})
        before = copy.deepcopy(prediction)
        explain(prediction)
        self.assertEqual(prediction, before)


class RealPredictionTests(unittest.TestCase):
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
        write_json(
            self.model_dir / "experiment_manifest.json",
            dict(
                model_version=MODEL_VERSION,
                development_only=True,
                serving_ready=False,
                output_sha256={
                    n: sha256(self.model_dir / n)
                    for n in (
                        "evaluation.json",
                        "holdout_predictions.json",
                        "model_parameters.json",
                    )
                },
            ),
        )
        self.predictions = predict_rows(
            load_model(self.model_dir), self.features, generated_at=GENERATED
        )

    def prediction_dir(self, name="preds"):
        directory = self.root / name
        directory.mkdir()
        write_json(directory / "predictions.json", self.predictions)
        write_json(
            directory / "prediction_manifest.json",
            dict(
                development_only=True,
                serving_ready=False,
                rows=len(self.predictions),
                output_sha256={
                    "predictions.json": sha256(directory / "predictions.json")
                },
            ),
        )
        return directory

    def test_real_predictions_pass_faithfulness_check(self):
        for prediction in self.predictions:
            result = explain(prediction)
            self.assertIn(result["status"], {"OK", "INSUFFICIENT_EXPLANATION"})
            for reason in result["reasons"]:
                self.assertFalse(reason["missing"])
        missing_one = explain(self.predictions[0])
        self.assertEqual(
            [e["feature"] for e in missing_one["excluded_imputed"]], ["recency_days"]
        )

    def test_cli_writes_outputs_with_checksum_and_summary(self):
        source = self.prediction_dir()
        output = self.root / "reasons"
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "services.data.models.churn_reasons",
                "--predictions-dir",
                str(source),
                "--output-dir",
                str(output),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        manifest = json.loads((output / "reasons_manifest.json").read_text())
        reasons = json.loads((output / "reasons.json").read_text())
        self.assertEqual(len(reasons), len(self.predictions))
        self.assertEqual(
            manifest["output_sha256"]["reasons.json"], sha256(output / "reasons.json")
        )
        self.assertEqual(manifest["mapping_version"], REASON_MAPPING_VERSION)
        self.assertTrue(manifest["development_only"])
        self.assertFalse(manifest["approved_taxonomy"])
        self.assertEqual(manifest["input_sha256"], manifest["input_sha256_after"])
        summary = manifest["summary"]
        self.assertEqual(summary["total"], len(reasons))
        self.assertEqual(
            summary["OK"] + summary["INSUFFICIENT_EXPLANATION"], summary["total"]
        )
        self.assertEqual(summary["OK"], sum(r["status"] == "OK" for r in reasons))
        top = sum(len(r["reasons"][:3]) for r in reasons)
        self.assertEqual(sum(summary["top3_code_distribution"].values()), top)

    def test_cli_refusals(self):
        source = self.prediction_dir()
        done = self.root / "done"
        run(source, done)
        for destination in (
            done,
            source / "nested",
            self.root,
            self.root / "ground_truth" / "out",
        ):
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                run(source, destination)
        gt = self.root / "ground_truth" / "preds"
        gt.parent.mkdir()
        source.rename(gt)
        with self.assertRaises(ValueError):
            run(gt, self.root / "fresh")

    def test_input_checksum_verified_before_reading(self):
        source = self.prediction_dir()
        with (source / "predictions.json").open("a") as stream:
            stream.write(" ")
        with self.assertRaisesRegex(ValueError, "checksum"):
            run(source, self.root / "bad")
        self.assertFalse((self.root / "bad").exists())

    def test_manifest_flags_required(self):
        source = self.prediction_dir()
        path = source / "prediction_manifest.json"
        original = json.loads(path.read_text())
        for key, value in (("development_only", False), ("serving_ready", True)):
            write_json(path, {**original, key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                run(source, self.root / "bad")

    def test_tampered_contributions_abort_output(self):
        self.predictions[1]["contributions"][2]["log_odds_contribution"] += 0.5
        source = self.prediction_dir()
        with self.assertRaisesRegex(ValueError, "reconstruct"):
            run(source, self.root / "bad")
        self.assertFalse((self.root / "bad").exists())

    def test_changed_input_during_run_aborts(self):
        from unittest.mock import patch

        from services.data.models import churn_reasons

        source = self.prediction_dir()
        original = churn_reasons.explain

        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            with (source / "predictions.json").open("a") as stream:
                stream.write(" ")
            return result

        with patch.object(churn_reasons, "explain", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "changed"):
                run(source, self.root / "changed")
        self.assertFalse((self.root / "changed").exists())


if __name__ == "__main__":
    unittest.main()
