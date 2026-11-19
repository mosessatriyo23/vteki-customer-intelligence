"""Synthetic fixtures for exploratory renewal feature ablation."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.data.ingestion.validator import sha256
from services.data.models.renewal_ablation import ablate, run
from services.data.models.renewal_membership_experiment import FEATURES, join_rows
from tests.data.test_renewal_membership_experiment import (
    LATE,
    cohort,
    write_inputs,
)


def planted():
    members, labels = cohort(16)
    for member, label in zip(members, labels):
        i = int(member["golden_customer_id"][1:])
        for feature in FEATURES:
            member[feature] = False if feature == "tier_upgraded_last_event" else 1
        member["days_to_expiry"] = (i - 8) * 10
        label["renewal60"] = int(member["days_to_expiry"] >= 0)
    return join_rows(members, labels)


class AblationTests(unittest.TestCase):
    def test_deterministic_variants_and_dominant_feature(self):
        result = ablate(planted())
        self.assertEqual(result, ablate(planted()))
        variants = result["variants"]
        self.assertEqual(len(variants), 15)

        def auc(name):
            return variants[name]["metrics"]["roc_auc"]

        self.assertEqual(auc("single_only:days_to_expiry"), 1)
        self.assertEqual(auc("drop_one:days_to_expiry"), 0.5)
        for feature in FEATURES[1:]:
            self.assertEqual(auc(f"single_only:{feature}"), 0.5)
            self.assertEqual(auc(f"drop_one:{feature}"), 1)
        for variant in variants.values():
            self.assertEqual(variant["positives"], 8)
            self.assertEqual(variant["negatives"], 8)
        json.dumps(result, allow_nan=False)

    def test_holdout_mutation_does_not_change_fitted_parameters(self):
        rows = planted()
        changed = copy.deepcopy(rows)
        for row in changed:
            if row["cutoff_at"] == LATE:
                row["target_value"] = 1 - row["target_value"]
                row["current_tier_ordinal"] = None
        self.assertEqual(
            ablate(rows)["fitted_parameters"], ablate(changed)["fitted_parameters"]
        )

    def test_fixed_rule_has_no_fit(self):
        from sklearn.linear_model import LogisticRegression

        original = LogisticRegression.fit
        calls = []

        def fit(model, *args, **kwargs):
            calls.append(1)
            return original(model, *args, **kwargs)

        with patch.object(LogisticRegression, "fit", fit):
            result = ablate(planted())
        self.assertEqual(len(calls), 13)
        name = "baseline:fixed_rule_days_to_expiry_nonnegative"
        self.assertNotIn(name, result["fitted_parameters"])
        self.assertFalse(result["variants"][name]["fitted"])
        self.assertFalse(result["variants"][name]["pre_registered"])
        self.assertIn("Post-hoc", result["variants"][name]["rule"])
        self.assertNotIn("Declared before looking", result["variants"][name]["rule"])
        self.assertEqual(result["variants"][name]["metrics"]["roc_auc"], 1)

    def test_structure_counts(self):
        result = ablate(planted())
        for fold in ("training_fold", "holdout"):
            stats = result["cohort_structure"][fold]
            self.assertEqual(stats["days_to_expiry_negative"]["count"], 8)
            self.assertEqual(stats["days_to_expiry_negative"]["base_rate"], 0)
            self.assertEqual(stats["days_to_expiry_above_60"]["count"], 1)
            self.assertEqual(stats["days_to_expiry_above_60"]["base_rate"], 1)

    def test_artifacts_and_refusals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            labels, members = write_inputs(root)
            out = root / "out"
            result = run(labels, members, out)
            manifest = json.loads((out / "experiment_manifest.json").read_text())
            self.assertEqual(manifest["input_sha256"], manifest["input_sha256_after"])
            self.assertEqual(
                manifest["output_sha256"]["evaluation.json"],
                sha256(out / "evaluation.json"),
            )
            self.assertEqual(json.loads((out / "evaluation.json").read_text()), result)
            self.assertFalse(result["serving_ready"])
            for forbidden in (out, labels / "nested", root / "ground_truth" / "out"):
                with self.assertRaises(ValueError):
                    run(labels, members, forbidden)

    def test_nonfinite_report_fails_before_creating_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            labels, members = write_inputs(root)
            with patch(
                "services.data.models.renewal_ablation.ablate",
                return_value={"bad": float("nan")},
            ):
                with self.assertRaises(ValueError):
                    run(labels, members, root / "out")
            self.assertFalse((root / "out").exists())


if __name__ == "__main__":
    unittest.main()
