"""Development-only three-fold calibration/threshold contract (no test-fold fitting)."""

import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from services.data.features.snapshot import FIELDS, VERSION
from services.data.ingestion.validator import sha256
from services.data.models.churn_calibration import (
    CALIBRATION_METHOD,
    MODEL_VERSION,
    THRESHOLD_RULE,
    evaluate,
    lift_gains,
    run,
    three_fold_split,
)
from services.data.models.labels import CHRIST_VERSION, TRAINING_FIELDS

CUTOFFS = (
    "2026-01-01T00:00:00+07:00",
    "2026-04-01T00:00:00+07:00",
    "2026-06-30T00:00:00+07:00",
)
CUSTOMERS = 20


def row(customer: int, cutoff: str, shift: int) -> dict:
    moment = datetime.fromisoformat(cutoff)
    churn = 1 if customer >= 10 else 0
    if customer in (2, 14):
        churn = 1 - churn
    return dict(
        golden_customer_id=f"g{customer}",
        cutoff_at=cutoff,
        identity_status="RESOLVED",
        feature_version=VERSION,
        training_ready=False,
        identity_time_policy="CURRENT_SNAPSHOT_RETROSPECTIVE",
        recency_days="" if customer == 0 else str(customer * 8 + shift),
        tenure_days=str(400 - customer * 5 + shift),
        purchase_count_365d=str(max(0, 20 - customer)),
        retained_revenue_365d=str(max(0, 20 - customer) * 100),
        purchase_count_60d=str(customer % 3),
        purchase_count_90d=str(customer % 4),
        retained_revenue_90d=str((customer % 4) * 50),
        label_version=CHRIST_VERSION,
        horizon_days=90,
        outcome_end_at=(moment + timedelta(days=90)).isoformat(),
        outcome_complete=True,
        eligible=True,
        churn90=churn,
        clv90=0,
        experiment_ready=False,
    )


def rows(cutoffs: tuple[str, ...] = CUTOFFS) -> list[dict]:
    return [
        row(customer, cutoff, shift)
        for shift, cutoff in enumerate(cutoffs)
        for customer in range(CUSTOMERS)
    ]


class ThreeFoldSplitTests(unittest.TestCase):
    def test_rejects_fewer_than_three_cutoffs_without_silent_fallback(self):
        with self.assertRaisesRegex(ValueError, "three"):
            three_fold_split(rows(CUTOFFS[:2]))
        with self.assertRaisesRegex(ValueError, "three"):
            evaluate(rows(CUTOFFS[:2]))

    def test_purge_boundary_keeps_outcomes_ending_exactly_at_next_cutoff(self):
        train, calibration, test, cutoffs = three_fold_split(rows())
        self.assertEqual(len(train), CUSTOMERS)
        self.assertEqual(len(calibration), CUSTOMERS)
        self.assertEqual(len(test), CUSTOMERS)
        self.assertEqual(cutoffs["train_cutoffs"], [CUTOFFS[0]])
        self.assertEqual(cutoffs["calibration_cutoffs"], [CUTOFFS[1]])
        self.assertEqual(cutoffs["test_cutoffs"], [CUTOFFS[2]])

    def test_purge_drops_training_outcomes_overlapping_the_calibration_cutoff(self):
        overlapping = (CUTOFFS[0], "2026-03-01T00:00:00+07:00", *CUTOFFS[1:])
        train, calibration, test, _ = three_fold_split(rows(overlapping))
        self.assertEqual(len(train), CUSTOMERS)
        self.assertTrue(all(r["cutoff_at"] == CUTOFFS[0] for r in train))
        self.assertEqual(len(calibration), CUSTOMERS)
        self.assertEqual(len(test), CUSTOMERS)
        report, _, artifact = evaluate(rows(overlapping))
        self.assertEqual(report["purged_rows"], CUSTOMERS)
        without_purged = [
            r for r in rows(overlapping) if r["cutoff_at"] != overlapping[1]
        ]
        self.assertEqual(artifact, evaluate(without_purged)[2])


class CalibrationEvaluationTests(unittest.TestCase):
    def test_calibrated_scores_differ_yet_stay_monotone_in_raw_scores(self):
        report, predictions, artifact = evaluate(rows())
        raw = [p["raw_probability"] for p in predictions]
        calibrated = [p["calibrated_probability"] for p in predictions]
        self.assertNotEqual(raw, calibrated)
        for i, _ in enumerate(raw):
            for j, _ in enumerate(raw):
                if raw[i] < raw[j]:
                    self.assertLessEqual(calibrated[i], calibrated[j])
        # Isotonic is monotone: no strict inversions, only possible new ties.
        self.assertIsNotNone(report["test"]["uncalibrated"]["metrics"]["roc_auc"])
        self.assertIsNotNone(report["test"]["calibrated"]["metrics"]["roc_auc"])
        self.assertEqual(artifact["method"], CALIBRATION_METHOD)
        self.assertEqual(report["model_version"], MODEL_VERSION)

    def test_threshold_is_selected_on_calibration_fold_not_on_test(self):
        data = rows()
        baseline_report, _, baseline_artifact = evaluate(data)
        flipped = [
            {**r, "churn90": 1 - r["churn90"]} if r["cutoff_at"] == CUTOFFS[2] else r
            for r in data
        ]
        flipped_report, _, flipped_artifact = evaluate(flipped)
        self.assertEqual(
            baseline_report["selected_threshold"], flipped_report["selected_threshold"]
        )
        self.assertEqual(
            baseline_report["calibration_selection"],
            flipped_report["calibration_selection"],
        )
        self.assertEqual(baseline_artifact, flipped_artifact)
        self.assertEqual(baseline_report["threshold_rule"], THRESHOLD_RULE)
        self.assertEqual(
            baseline_report["selected_threshold_source"], "calibration_fold"
        )
        self.assertNotEqual(
            baseline_report["test"]["calibrated"]["metrics"],
            flipped_report["test"]["calibrated"]["metrics"],
        )

    def test_reports_both_operating_points_and_development_only_flags(self):
        report, _, artifact = evaluate(rows())
        for scores in ("uncalibrated", "calibrated"):
            block = report["test"][scores]
            self.assertEqual(block["operating_at_fixed_threshold"]["threshold"], 0.5)
            self.assertEqual(
                block["operating_at_selected_threshold"]["threshold"],
                report["calibration_selection"][scores]["threshold"],
            )
            self.assertEqual(len(block["reliability"]), 10)
            self.assertIsNotNone(block["expected_calibration_error"])
            self.assertIn("brier_score", block["metrics"])
        self.assertEqual(
            report["selected_threshold"],
            report["calibration_selection"]["calibrated"]["threshold"],
        )
        for flag in (
            "training_ready",
            "experiment_ready",
            "final_model",
            "serving_ready",
        ):
            self.assertFalse(report[flag])
            self.assertFalse(artifact[flag])
        self.assertTrue(report["development_only"])
        self.assertNotIn("segments", report)
        self.assertTrue(any("causal" in text for text in report["limitations"]))
        self.assertTrue(
            any("not production calibration" in text for text in report["limitations"])
        )
        json.dumps([report, artifact], allow_nan=False)

    def test_segment_breakdown_only_when_rows_carry_a_segment_column(self):
        segmented = [
            {**r, "segment": f"s{int(r['golden_customer_id'][1:]) % 2}"} for r in rows()
        ]
        report, _, _ = evaluate(segmented)
        self.assertEqual(sorted(report["segments"]), ["s0", "s1"])
        self.assertEqual(
            sum(block["rows"] for block in report["segments"].values()), CUSTOMERS
        )

    def test_single_class_folds_produce_nulls_instead_of_crashing(self):
        negative_test = [
            {**r, "churn90": 0} if r["cutoff_at"] == CUTOFFS[2] else r for r in rows()
        ]
        report, _, _ = evaluate(negative_test)
        for scores in ("uncalibrated", "calibrated"):
            metrics = report["test"][scores]["metrics"]
            self.assertIsNone(metrics["roc_auc"])
            self.assertIsNone(metrics["average_precision"])
            lift = report["test"][scores]["lift_gains"]
            self.assertIsNone(lift["top_10_percent"]["capture_rate"])
            self.assertIsNone(
                report["test"][scores]["operating_at_selected_threshold"]["recall"]
            )
        negative_calibration = [
            {**r, "churn90": 0} if r["cutoff_at"] == CUTOFFS[1] else r for r in rows()
        ]
        report, _, artifact = evaluate(negative_calibration)
        self.assertEqual(report["selected_threshold"], 0.5)
        for scores in ("uncalibrated", "calibrated"):
            selection = report["calibration_selection"][scores]
            self.assertEqual(selection["threshold"], 0.5)
            self.assertIsNone(selection["f1"])
            self.assertIsNotNone(selection["note"])
        json.dumps([report, artifact], allow_nan=False)
        single_class_train = [
            {**r, "churn90": 1} if r["cutoff_at"] == CUTOFFS[0] else r for r in rows()
        ]
        with self.assertRaisesRegex(ValueError, "two classes"):
            evaluate(single_class_train)


class LiftGainsTests(unittest.TestCase):
    def test_ties_share_deciles_and_top_decile_math_is_hand_checked(self):
        scored = [(1, 0.9)] * 8 + [(0, 0.9)] * 2 + [(1, 0.1)] * 2 + [(0, 0.1)] * 8
        table = lift_gains(scored)
        self.assertEqual(table["rows"], 20)
        self.assertEqual(table["positives"], 10)
        self.assertEqual(table["base_rate"], 0.5)
        # A tied group is spread uniformly across the ranks it occupies, so
        # row order inside a tie cannot change any decile or top-k figure.
        self.assertEqual(len(table["deciles"]), 10)
        for i, bucket in enumerate(table["deciles"]):
            self.assertAlmostEqual(bucket["rows"], 2.0)
            self.assertAlmostEqual(bucket["positives"], 1.6 if i < 5 else 0.4)
            self.assertAlmostEqual(bucket["lift"], 1.6 if i < 5 else 0.4)
        self.assertAlmostEqual(table["deciles"][4]["cumulative_capture_rate"], 0.8)
        self.assertAlmostEqual(table["deciles"][9]["cumulative_capture_rate"], 1.0)
        top10 = table["top_10_percent"]
        self.assertAlmostEqual(top10["rows"], 2.0)
        self.assertAlmostEqual(top10["captured_positives"], 1.6)
        self.assertAlmostEqual(top10["capture_rate"], 0.16)
        self.assertAlmostEqual(top10["lift"], 1.6)
        top20 = table["top_20_percent"]
        self.assertAlmostEqual(top20["rows"], 4.0)
        self.assertAlmostEqual(top20["captured_positives"], 3.2)
        self.assertAlmostEqual(top20["capture_rate"], 0.32)
        self.assertAlmostEqual(top20["lift"], 1.6)
        self.assertIsNotNone(table["tie_policy"])
        self.assertEqual(table, lift_gains(list(reversed(scored))))

    def test_no_positives_yields_null_capture_rates(self):
        table = lift_gains([(0, 0.4), (0, 0.6)])
        self.assertEqual(table["base_rate"], 0.0)
        self.assertIsNone(table["top_10_percent"]["capture_rate"])
        self.assertIsNone(table["top_10_percent"]["lift"])


def write_source(source: Path, data: list[dict]) -> dict:
    source.mkdir(parents=True)
    with (source / "training_rows.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TRAINING_FIELDS)
        writer.writeheader()
        writer.writerows(data)
    manifest = dict(
        experiment_ready=False,
        final_model=False,
        label_version=CHRIST_VERSION,
        feature_fields=list(FIELDS),
        training_rows=len(data),
        output_sha256={"training_rows.csv": sha256(source / "training_rows.csv")},
    )
    (source / "model_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


class RunTests(unittest.TestCase):
    def test_run_writes_outputs_and_a_completion_manifest_with_checksums(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, output = root / "source", root / "output"
            write_source(source, rows())
            report = run(source, output)
            self.assertFalse(report["serving_ready"])
            manifest = json.loads(
                (output / "calibration_manifest.json").read_text(encoding="utf-8")
            )
            for name in (
                "calibration_evaluation.json",
                "test_predictions.json",
                "calibration_artifact.json",
            ):
                self.assertEqual(manifest["output_sha256"][name], sha256(output / name))
            self.assertEqual(manifest["input_sha256"], manifest["input_sha256_after"])
            predictions = json.loads(
                (output / "test_predictions.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(predictions), CUSTOMERS)
            artifact = json.loads(
                (output / "calibration_artifact.json").read_text(encoding="utf-8")
            )
            self.assertEqual(artifact["serialization"], "JSON inspection only")

    def test_run_rejects_unsafe_paths_checksums_and_overwrites(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, output = root / "source", root / "output"
            manifest = write_source(source, rows())
            run(source, output)
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
                "services.data.models.churn_calibration.sha256",
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
            manifest["final_model"] = True
            (source / "model_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "[Dd]evelopment"):
                run(source, root / "final")


if __name__ == "__main__":
    unittest.main()
