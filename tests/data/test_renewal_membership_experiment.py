"""Exploratory membership-only renewal60 comparison (post-holdout inspection)."""

import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from services.data.ingestion.validator import sha256
from services.data.models.membership_features import (
    FIELDS as MEMBERSHIP_FIELDS,
)
from services.data.models.membership_features import (
    MEMBERSHIP_FEATURE_VERSION,
)
from services.data.models.propensity_labels import (
    FIELDS as LABEL_FIELDS,
)
from services.data.models.propensity_labels import (
    RENEWAL_VERSION,
    RETAIL_VERSION,
    TARGETS,
)
from services.data.models.renewal_membership_experiment import (
    FEATURES,
    MODEL_VERSION,
    OUTPUTS,
    evaluate,
    join_rows,
    run,
)

EARLY = "2026-03-01T00:00:00+07:00"
LATE = "2026-06-01T00:00:00+07:00"
CUTOFFS = (EARLY, LATE)


def membership_row(index: int, cutoff: str) -> dict:
    late = cutoff == LATE
    return dict(
        golden_customer_id=f"g{index}",
        cutoff_at=cutoff,
        feature_version=MEMBERSHIP_FEATURE_VERSION,
        training_ready=False,
        has_membership_history=True,
        current_tier_ordinal=None if index == 0 else (3 if late else index % 4),
        days_since_last_membership_event=100 + index,
        days_to_expiry=30 - index * 10,
        membership_tenure_days=None if index == 1 else 400 + index * 7,
        renewal_count_365d=index % 3,
        tier_upgraded_last_event=index % 2 == 0,
    )


def label_row(index: int, cutoff: str, **overrides) -> dict:
    moment = datetime.fromisoformat(cutoff)
    row = dict(
        golden_customer_id=f"g{index}",
        cutoff_at=cutoff,
        retail_label_version=RETAIL_VERSION,
        renewal_label_version=RENEWAL_VERSION,
        retail_purchase30_eligible=True,
        retail_purchase30_outcome_complete=True,
        retail_purchase30_outcome_end_at=(moment + timedelta(days=30)).isoformat(),
        retail_purchase30=1,
        renewal60_eligible=True,
        renewal60_outcome_complete=True,
        renewal60_outcome_end_at=(moment + timedelta(days=60)).isoformat(),
        renewal60=(index // 2) % 2,
        experiment_ready=False,
    )
    row.update(overrides)
    return row


def cohort(count=8):
    members = [membership_row(i, c) for c in CUTOFFS for i in range(count)]
    labels = [label_row(i, c) for c in CUTOFFS for i in range(count)]
    return members, labels


def write_csv(path: Path, fields, rows) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(
            [{k: "" if v is None else v for k, v in row.items()} for row in rows]
        )


def write_manifests(labels_dir: Path, members_dir: Path, rows, label_over, mem_over):
    label_manifest = dict(
        target_versions={name: version for name, (version, _) in TARGETS.items()},
        cutoffs=list(CUTOFFS),
        training_ready=False,
        experiment_ready=False,
        final_model=False,
        development_only=True,
        output_sha256={
            "propensity_labels.csv": sha256(labels_dir / "propensity_labels.csv")
        },
    )
    label_manifest.update(label_over)
    member_manifest = dict(
        feature_version=MEMBERSHIP_FEATURE_VERSION,
        training_ready=False,
        development_only=True,
        identity_time_policy="CURRENT_SNAPSHOT_RETROSPECTIVE",
        cutoffs=list(CUTOFFS),
        row_count=rows,
        output_sha256={
            "membership_features.csv": sha256(members_dir / "membership_features.csv")
        },
    )
    member_manifest.update(mem_over)
    (labels_dir / "propensity_manifest.json").write_text(
        json.dumps(label_manifest), encoding="utf-8"
    )
    (members_dir / "membership_manifest.json").write_text(
        json.dumps(member_manifest), encoding="utf-8"
    )


def write_inputs(root: Path, members=None, labels=None, label_over=None, mem_over=None):
    built_members, built_labels = cohort()
    members = built_members if members is None else members
    labels = built_labels if labels is None else labels
    labels_dir, members_dir = root / "labels", root / "membership"
    labels_dir.mkdir(parents=True)
    members_dir.mkdir(parents=True)
    write_csv(labels_dir / "propensity_labels.csv", LABEL_FIELDS, labels)
    write_csv(members_dir / "membership_features.csv", MEMBERSHIP_FIELDS, members)
    write_manifests(
        labels_dir, members_dir, len(members), label_over or {}, mem_over or {}
    )
    return labels_dir, members_dir


class JoinAndEvaluateTests(unittest.TestCase):
    def joined(self):
        members, labels = cohort()
        return join_rows(
            [
                {
                    **m,
                    "has_membership_history": "True",
                    "training_ready": "False",
                    "tier_upgraded_last_event": str(m["tier_upgraded_last_event"]),
                    **{
                        k: "" if m[k] is None else str(m[k])
                        for k in (
                            "current_tier_ordinal",
                            "days_since_last_membership_event",
                            "days_to_expiry",
                            "membership_tenure_days",
                            "renewal_count_365d",
                        )
                    },
                }
                for m in members
            ],
            labels,
        )

    def test_features_are_the_explicit_membership_only_list(self):
        self.assertEqual(
            FEATURES,
            (
                "days_to_expiry",
                "current_tier_ordinal",
                "membership_tenure_days",
                "renewal_count_365d",
                "tier_upgraded_last_event",
                "days_since_last_membership_event",
            ),
        )

    def test_report_is_flagged_exploratory_and_not_confirmatory(self):
        report, predictions, params = evaluate(self.joined())
        self.assertEqual(report["model_version"], MODEL_VERSION)
        self.assertTrue(report["exploratory"])
        self.assertTrue(report["post_holdout_inspection"])
        self.assertFalse(report["independent_confirmation"])
        self.assertFalse(report["serving_ready"])
        self.assertEqual(report["seed"], 42)
        self.assertEqual(report["train_cutoffs"], [EARLY])
        self.assertEqual(report["test_cutoffs"], [LATE])
        self.assertEqual(report["train_rows"], 8)
        self.assertEqual(report["test_rows"], 8)
        text = " ".join(report["limitations"]).lower()
        self.assertIn("post-holdout", text)
        self.assertIn("not independent confirmation", text)
        self.assertIn("separate report", report["comparison_note"])
        self.assertEqual(len(predictions), 8)
        self.assertEqual(params["features"], list(FEATURES))

    def test_metrics_and_threshold_confusion_are_reported(self):
        report = evaluate(self.joined())[0]
        for name in ("logistic", "base_rate"):
            model = report["models"][name]
            self.assertEqual(
                set(model["metrics"]),
                {"roc_auc", "average_precision", "brier_score"},
            )
            self.assertEqual(model["operating_metrics"]["threshold"], 0.5)
            ops = model["operating_metrics"]
            self.assertEqual(ops["tp"] + ops["tn"] + ops["fp"] + ops["fn"], 8)
        self.assertEqual(report["test_base_rate"], 0.5)
        self.assertEqual(report["train_base_rate"], 0.5)
        self.assertEqual(report["models"]["base_rate"]["metrics"]["roc_auc"], 0.5)

    def test_imputer_uses_training_fold_only(self):
        params = evaluate(self.joined())[2]
        tier = FEATURES.index("current_tier_ordinal")
        # Train tiers (index 1..7, EARLY): 1,2,3,0,1,2,3 -> median 2.0, not
        # the 3.0-dominated pooled median.
        self.assertEqual(params["logistic"]["imputer_medians"][tier], 2.0)

    def test_deterministic_for_seed_42(self):
        self.assertEqual(evaluate(self.joined()), evaluate(self.joined()))

    def test_ineligible_or_incomplete_rows_are_excluded(self):
        members, labels = cohort()
        labels[0] = label_row(0, EARLY, renewal60_eligible=False, renewal60=None)
        labels[1] = label_row(1, EARLY, renewal60_outcome_complete=False)
        rows = join_rows(
            [{k: "" if v is None else str(v) for k, v in m.items()} for m in members],
            labels,
        )
        self.assertEqual(len(rows), 14)

    def test_duplicate_keys_are_rejected(self):
        members, labels = cohort()
        text = [{k: "" if v is None else str(v) for k, v in m.items()} for m in members]
        with self.assertRaises(ValueError):
            join_rows(text + [text[0]], labels)

    def test_keysets_must_match_exactly(self):
        members, labels = cohort()
        text = [{k: "" if v is None else str(v) for k, v in m.items()} for m in members]
        with self.assertRaises(ValueError):
            join_rows(text[:-1], labels)


class RunTests(unittest.TestCase):
    def run_in(self, **kwargs):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        labels_dir, members_dir = write_inputs(root, **kwargs)
        return root, labels_dir, members_dir

    def test_run_writes_outputs_with_hashes(self):
        root, labels_dir, members_dir = self.run_in()
        out = root / "out"
        before = {p: sha256(p) for p in labels_dir.glob("*")}
        report = run(labels_dir, members_dir, out)
        self.assertEqual({p: sha256(p) for p in labels_dir.glob("*")}, before)
        for name in OUTPUTS:
            self.assertTrue((out / name).is_file())
        manifest = json.loads((out / "experiment_manifest.json").read_text())
        self.assertEqual(manifest["input_sha256"], manifest["input_sha256_after"])
        self.assertEqual(set(manifest["input_sha256"]), set(report["input_sha256"]))
        for name in OUTPUTS:
            self.assertEqual(manifest["output_sha256"][name], sha256(out / name))
        self.assertTrue(manifest["exploratory"])
        self.assertFalse(manifest["independent_confirmation"])
        self.assertNotIn("recency_days", json.dumps(report))

    def test_input_changed_during_run_is_rejected(self):
        root, labels_dir, members_dir = self.run_in()
        real = evaluate

        def mutate(rows):
            with (members_dir / "membership_features.csv").open("a") as stream:
                stream.write("\n")
            return real(rows)

        with patch(
            "services.data.models.renewal_membership_experiment.evaluate", mutate
        ):
            with self.assertRaisesRegex(ValueError, "changed"):
                run(labels_dir, members_dir, root / "out")
        self.assertFalse((root / "out").exists())

    def test_existing_output_is_not_overwritten(self):
        root, labels_dir, members_dir = self.run_in()
        out = root / "out"
        out.mkdir()
        with self.assertRaises(ValueError):
            run(labels_dir, members_dir, out)

    def test_overlapping_and_ground_truth_paths_are_rejected(self):
        root, labels_dir, members_dir = self.run_in()
        with self.assertRaises(ValueError):
            run(labels_dir, members_dir, labels_dir / "out")
        with self.assertRaises(ValueError):
            run(labels_dir, members_dir, root / "ground_truth" / "out")

    def test_checksum_mismatch_is_rejected(self):
        root, labels_dir, members_dir = self.run_in(
            mem_over={"output_sha256": {"membership_features.csv": "0" * 64}}
        )
        with self.assertRaisesRegex(ValueError, "checksum"):
            run(labels_dir, members_dir, root / "out")

    def test_wrong_membership_version_is_rejected(self):
        members, _ = cohort()
        members[3]["feature_version"] = "other"
        root, labels_dir, members_dir = self.run_in(members=members)
        with self.assertRaisesRegex(ValueError, "version"):
            run(labels_dir, members_dir, root / "out")

    def test_wrong_manifest_version_is_rejected(self):
        root, labels_dir, members_dir = self.run_in(
            mem_over={"feature_version": "other"}
        )
        with self.assertRaisesRegex(ValueError, "version"):
            run(labels_dir, members_dir, root / "out")

    def test_label_version_mismatch_is_rejected(self):
        _, labels = cohort()
        labels[2]["renewal_label_version"] = "other"
        root, labels_dir, members_dir = self.run_in(labels=labels)
        with self.assertRaisesRegex(ValueError, "version"):
            run(labels_dir, members_dir, root / "out")

    def test_bad_flag_is_rejected(self):
        members, _ = cohort()
        members[0]["tier_upgraded_last_event"] = "maybe"
        root, labels_dir, members_dir = self.run_in(members=members)
        with self.assertRaisesRegex(ValueError, "tier_upgraded_last_event"):
            run(labels_dir, members_dir, root / "out")

    def test_missing_history_flag_is_rejected(self):
        members, _ = cohort()
        members[0]["has_membership_history"] = None
        root, labels_dir, members_dir = self.run_in(members=members)
        with self.assertRaisesRegex(ValueError, "has_membership_history"):
            run(labels_dir, members_dir, root / "out")

    def test_non_integer_numeric_is_rejected(self):
        members, _ = cohort()
        members[0]["days_to_expiry"] = "12.5"
        root, labels_dir, members_dir = self.run_in(members=members)
        with self.assertRaisesRegex(ValueError, "days_to_expiry"):
            run(labels_dir, members_dir, root / "out")

    def test_negative_days_to_expiry_is_accepted(self):
        root, labels_dir, members_dir = self.run_in()
        report = run(labels_dir, members_dir, root / "out")
        self.assertEqual(report["features"][0], "days_to_expiry")

    def test_training_ready_true_is_rejected(self):
        members, _ = cohort()
        members[0]["training_ready"] = True
        root, labels_dir, members_dir = self.run_in(members=members)
        with self.assertRaises(ValueError):
            run(labels_dir, members_dir, root / "out")

    def test_manifest_flags_are_enforced(self):
        root, labels_dir, members_dir = self.run_in(
            label_over={"experiment_ready": True}
        )
        with self.assertRaises(ValueError):
            run(labels_dir, members_dir, root / "out")

    def test_cutoff_mismatch_between_manifests_is_rejected(self):
        root, labels_dir, members_dir = self.run_in(mem_over={"cutoffs": [EARLY]})
        with self.assertRaisesRegex(ValueError, "cutoffs"):
            run(labels_dir, members_dir, root / "out")


if __name__ == "__main__":
    unittest.main()
