"""Descriptive diagnostics must not silently expand the development cohort."""

import unittest

from services.data.models.retention_diagnostics import summarize_retention90


class RetentionDiagnosticsTests(unittest.TestCase):
    def label(self, customer="g1", **changes):
        return {
            "golden_customer_id": customer,
            "cutoff_at": "2026-01-01T00:00:00+07:00",
            "label_version": "christ-churn90-three-events-dev-1.1",
            "horizon_days": 90,
            "outcome_complete": True,
            "eligible": True,
            "churn90": 0,
            **changes,
        }

    def segment(self, customer="g1", **changes):
        return {
            "golden_customer_id": customer,
            "cutoff_at": "2026-01-01T00:00:00+07:00",
            "lifecycle": "ACTIVE",
            "rule_version": "development-rule",
            **changes,
        }

    def test_counts_exclusions_and_reports_descriptive_subset(self):
        labels = [
            self.label(),
            self.label("g2", churn90=1),
            self.label("g3", outcome_complete=False, churn90=None),
            self.label("g4", eligible=False, churn90=None),
        ]
        result = summarize_retention90(
            labels, [self.segment(f"g{i}") for i in range(1, 5)]
        )
        row = result[0]
        self.assertEqual(row["eligible_complete_count"], 2)
        self.assertEqual(row["retained_count"], 1)
        self.assertEqual(row["retention90_rate"], 0.5)
        self.assertEqual(row["excluded_incomplete_count"], 1)
        self.assertEqual(row["excluded_ineligible_count"], 1)
        self.assertEqual(row["cohort_scope"], "existing_pos_365d_eligible_subset")
        self.assertFalse(row["clv_factor_ready"])

    def test_empty_denominator_is_null_not_zero(self):
        result = summarize_retention90(
            [self.label(eligible=False, churn90=None)], [self.segment()]
        )
        self.assertIsNone(result[0]["retention90_rate"])

    def test_duplicate_or_unmatched_keys_reject(self):
        for labels, segments in (
            ([self.label()] * 2, [self.segment()]),
            ([self.label()], [self.segment()] * 2),
            ([self.label()], [self.segment("other")]),
        ):
            with (
                self.subTest(labels=labels, segments=segments),
                self.assertRaises(ValueError),
            ):
                summarize_retention90(labels, segments)

    def test_wrong_version_horizon_or_invalid_label_reject(self):
        for changes in (
            {"horizon_days": 180},
            {"label_version": "other"},
            {"churn90": True},
            {"churn90": None},
            {"eligible": "False"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                summarize_retention90([self.label(**changes)], [self.segment()])

    def test_cutoffs_and_rule_versions_are_not_pooled(self):
        labels = [self.label(), self.label("g2")]
        segments = [self.segment(), self.segment("g2", rule_version="other")]
        self.assertEqual(len(summarize_retention90(labels, segments)), 2)

    def test_empty_inputs(self):
        self.assertEqual(summarize_retention90([], []), [])
