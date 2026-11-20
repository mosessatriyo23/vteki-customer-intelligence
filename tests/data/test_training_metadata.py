"""Fresh evaluation reports describe the estimators that were actually fitted."""

import json
import unittest
from unittest.mock import patch

from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier

from services.data.models import (
    churn_experiment,
    propensity_experiment,
    renewal_ablation,
    renewal_membership_experiment,
)
from tests.data.test_churn_experiment import rows as churn_rows
from tests.data.test_propensity_experiment import joined
from tests.data.test_renewal_ablation import planted


class TrainingMetadataTests(unittest.TestCase):
    def assert_metadata(self, metadata, estimator):
        cls = type(estimator)
        self.assertEqual(metadata["algorithm"], f"{cls.__module__}.{cls.__qualname__}")
        self.assertEqual(metadata["hyperparameters"], estimator.get_params(deep=False))
        json.dumps(metadata, allow_nan=False)

    def test_reports_describe_actual_fitted_logistic_estimators(self):
        original_fit = LogisticRegression.fit
        fitted = []

        def fit(estimator, *args, **kwargs):
            # A non-default fit-time value catches hard-coded parameter duplicates.
            estimator.set_params(C=0.75)
            result = original_fit(estimator, *args, **kwargs)
            fitted.append(estimator)
            return result

        cases = [
            (lambda: churn_experiment.evaluate(churn_rows())[0], "logistic"),
            (
                lambda: propensity_experiment.evaluate(
                    joined("retail_purchase30"), "retail_purchase30"
                )[0],
                "models",
            ),
            (
                lambda: propensity_experiment.evaluate(
                    joined("renewal60"), "renewal60"
                )[0],
                "models",
            ),
            (lambda: renewal_membership_experiment.evaluate(planted())[0], "models"),
            (lambda: renewal_ablation.ablate(planted()), "variants"),
        ]
        for evaluate, location in cases:
            with self.subTest(location=location, evaluate=evaluate):
                fitted.clear()
                with patch.object(LogisticRegression, "fit", fit):
                    report = evaluate()
                self.assert_metadata(report, fitted[0])
                self.assertEqual(report["hyperparameters"]["max_iter"], 1000)
                self.assertEqual(report["hyperparameters"]["random_state"], 42)
                if location == "variants":
                    variants = report["variants"]
                    variant_fits = [
                        v
                        for name, v in variants.items()
                        if v["kind"] == "logistic" and not name.startswith("baseline:")
                    ]
                    self.assertEqual(len(variant_fits), len(fitted))
                    for metadata, estimator in zip(variant_fits, fitted):
                        self.assert_metadata(metadata, estimator)
                    self.assert_metadata(
                        variants["baseline:logistic_days_to_expiry_only"], fitted[1]
                    )
                    self.assertNotIn("algorithm", report["train_base_rate_comparator"])
                else:
                    metadata = (
                        report["logistic"]
                        if location == "logistic"
                        else report["models"]["logistic"]
                    )
                    self.assert_metadata(metadata, fitted[0])
                json.dumps(report, allow_nan=False)

    def test_churn_keeps_tree_metadata_distinct_from_logistic_and_fixed_rule(self):
        original_fit = DecisionTreeClassifier.fit
        fitted = []

        def fit(estimator, *args, **kwargs):
            result = original_fit(estimator, *args, **kwargs)
            fitted.append(estimator)
            return result

        with patch.object(DecisionTreeClassifier, "fit", fit):
            report = churn_experiment.evaluate(churn_rows())[0]
        self.assert_metadata(report["shallow_tree"], fitted[0])
        self.assertEqual(report["shallow_tree"]["hyperparameters"]["max_depth"], 3)
        self.assertEqual(
            report["shallow_tree"]["hyperparameters"]["min_samples_leaf"], 2
        )
        self.assertEqual(report["shallow_tree"]["hyperparameters"]["random_state"], 42)
        self.assertNotIn("algorithm", report["baseline"])
        self.assertNotEqual(report["algorithm"], report["shallow_tree"]["algorithm"])
