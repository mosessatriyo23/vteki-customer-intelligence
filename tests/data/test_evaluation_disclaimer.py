"""Every generated model evaluation states the limits of synthetic metrics."""

import unittest

from services.data.models import (
    churn_calibration,
    churn_experiment,
    evaluator,
    propensity_calibration,
    propensity_experiment,
    renewal_ablation,
    renewal_membership_experiment,
)
from tests.data import test_model_evaluator
from tests.data.test_churn_calibration import rows as calibration_rows
from tests.data.test_churn_experiment import rows as churn_rows
from tests.data.test_propensity_calibration import CUTOFFS as PROPENSITY_CUTOFFS
from tests.data.test_propensity_experiment import joined
from tests.data.test_renewal_ablation import planted
from tests.data.test_renewal_membership_experiment import cohort


class EvaluationDisclaimerTests(unittest.TestCase):
    def assert_synthetic_disclaimer(self, report):
        text = report["synthetic_data_disclaimer"]
        self.assertIsInstance(text, str)
        self.assertIn("synthetic", text.lower())
        self.assertIn("generator", text.lower())
        self.assertIn("real customers", text.lower())
        self.assertIn("production performance", text.lower())

    def test_baseline_evaluation(self):
        first, second = "2026-01-01T00:00:00+07:00", "2026-07-01T00:00:00+07:00"
        rows = [
            test_model_evaluator.row(cutoff, customer, label, recency)
            for cutoff in (first, second)
            for customer, label, recency in (("a", 1, 120), ("b", 0, 10))
        ]
        self.assert_synthetic_disclaimer(evaluator.evaluate(rows))

    def test_churn_experiment(self):
        self.assert_synthetic_disclaimer(churn_experiment.evaluate(churn_rows())[0])

    def test_churn_calibration(self):
        self.assert_synthetic_disclaimer(
            churn_calibration.evaluate(calibration_rows())[0]
        )

    def test_propensity_experiment_for_each_target(self):
        for target in ("retail_purchase30", "renewal60"):
            with self.subTest(target=target):
                self.assert_synthetic_disclaimer(
                    propensity_experiment.evaluate(joined(target), target)[0]
                )

    def test_propensity_calibration_for_each_target(self):
        for target in ("retail_purchase30", "renewal60"):
            with self.subTest(target=target):
                self.assert_synthetic_disclaimer(
                    propensity_calibration.evaluate(
                        joined(target, PROPENSITY_CUTOFFS), target
                    )[0]
                )

    def test_renewal_membership_experiment(self):
        members, labels = cohort()
        self.assert_synthetic_disclaimer(
            renewal_membership_experiment.evaluate(
                renewal_membership_experiment.join_rows(members, labels)
            )[0]
        )

    def test_renewal_ablation(self):
        self.assert_synthetic_disclaimer(renewal_ablation.ablate(planted()))
