"""Synthetic handoff fixtures, not candidate predictions or model results."""

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from services.data.models.score_contract import validate_score_handoff
from services.decision.nba.engine import AIScores, scores_are_valid

NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


class ScoreContractTests(unittest.TestCase):
    def setUp(self):
        self.scores = AIScores(
            customer_id="synthetic-contract-only",
            churn_score=0.5,
            churn_risk_band="MEDIUM",
            propensity_purchase=0.4,
            propensity_renew=0.6,
            clv_amount=500_000,
            clv_tier="GOLD",
            lifecycle_stage="ACTIVE",
            score_generated_at=NOW,
            reason_codes=["FIXTURE_A", "FIXTURE_B", "FIXTURE_C"],
        )

    def validate(self, scores=None, **kwargs):
        return validate_score_handoff(
            scores or self.scores,
            expected_customer_id=kwargs.get(
                "expected_customer_id", self.scores.customer_id
            ),
            known_at=kwargs.get("known_at", NOW),
        )

    def test_valid_fixture_is_compatible_with_consumer_numeric_guard(self):
        self.assertTrue(self.validate().valid)
        self.assertTrue(scores_are_valid(self.scores))

    def test_invalid_numbers_fail_closed_without_overflow(self):
        for field in (
            "churn_score",
            "propensity_purchase",
            "propensity_renew",
            "clv_amount",
        ):
            for value in (
                True,
                False,
                None,
                "0.5",
                Decimal("0.5"),
                float("nan"),
                float("inf"),
                -1,
                10**400,
            ):
                with self.subTest(field=field, value_type=type(value)):
                    result = self.validate(replace(self.scores, **{field: value}))
                    self.assertIn(f"{field}_invalid", result.errors)

    def test_probability_boundaries_and_native_ints(self):
        for field in ("churn_score", "propensity_purchase", "propensity_renew"):
            for value in (0, 1, 0.0, 1.0):
                self.assertTrue(
                    self.validate(replace(self.scores, **{field: value})).valid
                )
            self.assertFalse(self.validate(replace(self.scores, **{field: 1.01})).valid)
        self.assertTrue(self.validate(replace(self.scores, clv_amount=0)).valid)

    def test_identity_and_time_contract(self):
        self.assertFalse(self.validate(expected_customer_id="other").valid)
        self.assertFalse(self.validate(expected_customer_id="").valid)
        self.assertFalse(self.validate(replace(self.scores, customer_id=" ")).valid)
        self.assertIn(
            "known_at_not_aware",
            self.validate(known_at=NOW.replace(tzinfo=None)).errors,
        )
        self.assertIn(
            "score_generated_at_not_aware",
            self.validate(
                replace(self.scores, score_generated_at=NOW.replace(tzinfo=None))
            ).errors,
        )
        self.assertIn(
            "score_generated_after_known_at",
            self.validate(
                replace(self.scores, score_generated_at=NOW + timedelta(seconds=1))
            ).errors,
        )
        local = NOW.astimezone(timezone(timedelta(hours=7)))
        self.assertTrue(
            self.validate(replace(self.scores, score_generated_at=local)).valid
        )

    def test_reason_shortage_is_not_filled_with_duplicates(self):
        for reasons in (
            [],
            ["A", "B"],
            ["A", "A", "B"],
            ["A", "B", ""],
            ["A", "B", None],
            "ABC",
        ):
            self.assertFalse(
                self.validate(replace(self.scores, reason_codes=reasons)).valid
            )
        self.assertEqual(
            self.scores.reason_codes, ["FIXTURE_A", "FIXTURE_B", "FIXTURE_C"]
        )

    def test_unknown_vocabularies_rejected_without_remapping(self):
        self.assertIn(
            "churn_risk_band_unknown",
            self.validate(replace(self.scores, churn_risk_band="UNKNOWN")).errors,
        )
        self.assertIn(
            "clv_tier_unknown",
            self.validate(replace(self.scores, clv_tier="BRONZE")).errors,
        )


if __name__ == "__main__":
    unittest.main()
