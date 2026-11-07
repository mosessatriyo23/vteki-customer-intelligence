"""
test_ev_calculator.py — Test kalkulator Expected Value (Minggu 6).

Rumus: EV = Propensity x ExpectedRevenue x ActionWeight - IncentiveCost
Jalankan: python -m pytest tests/decision/test_ev_calculator.py -v
"""

from datetime import datetime

import pytest

from services.decision.nba.catalogue import IncentiveBand
from services.decision.nba.engine import AIScores
from services.decision.nba.ev_calculator import (
    calculate_expected_value,
    estimate_expected_revenue,
    estimate_incentive_cost,
    get_propensity,
)

NOW = datetime(2026, 11, 5)


def _scores(**kw) -> AIScores:
    base = dict(
        customer_id="C1",
        churn_score=0.4,
        churn_risk_band="MEDIUM",
        propensity_purchase=0.7,
        propensity_renew=0.6,
        clv_amount=1_000_000.0,
        clv_tier="GOLD",
        lifecycle_stage="ACTIVE",
        score_generated_at=NOW,
    )
    base.update(kw)
    return AIScores(**base)


class TestCalculateExpectedValue:
    def test_formula(self):
        # 0.5 x 1_000_000 x 1.2 - 25_000 = 575_000
        assert calculate_expected_value(0.5, 1_000_000, 1.2, 25_000) == 575_000.0

    def test_default_incentive_cost_zero(self):
        assert calculate_expected_value(0.5, 100.0, 2.0) == 100.0

    def test_can_be_negative(self):
        assert calculate_expected_value(0.0, 1_000_000, 1.5, 10_000) == -10_000.0

    def test_zero_propensity_gives_minus_cost(self):
        assert calculate_expected_value(0.0, 500.0, 1.0, 40.0) == -40.0

    def test_zero_weight_gives_minus_cost(self):
        assert calculate_expected_value(1.0, 500.0, 0.0, 40.0) == -40.0

    def test_boundary_propensity_values_ok(self):
        assert calculate_expected_value(1.0, 100.0, 1.0) == 100.0
        assert calculate_expected_value(0.0, 100.0, 1.0) == 0.0

    def test_rounded_to_two_decimals(self):
        assert calculate_expected_value(1 / 3, 100.0, 1.0) == 33.33

    def test_deterministic(self):
        a = calculate_expected_value(0.37, 123456.0, 1.3, 777.0)
        b = calculate_expected_value(0.37, 123456.0, 1.3, 777.0)
        assert a == b

    @pytest.mark.parametrize(
        "args",
        [
            (-0.01, 100.0, 1.0, 0.0),
            (1.01, 100.0, 1.0, 0.0),
            (0.5, -1.0, 1.0, 0.0),
            (0.5, 100.0, -0.1, 0.0),
            (0.5, 100.0, 1.0, -5.0),
        ],
    )
    def test_invalid_inputs_raise(self, args):
        with pytest.raises(ValueError):
            calculate_expected_value(*args)


class TestGetPropensity:
    def test_expired_scores_gives_zero(self):
        assert get_propensity("CROSS_SELL", _scores(), scores_expired=True) == 0.0

    def test_mapping_by_action(self):
        s = _scores()
        assert get_propensity("RETENTION_OUTREACH", s, False) == 0.4
        assert get_propensity("RENEWAL_REMINDER", s, False) == 0.6
        assert get_propensity("CROSS_SELL", s, False) == 0.7
        assert get_propensity("EDUCATION", s, False) == pytest.approx(0.6)
        assert get_propensity("SERVICE_REMINDER", s, False) == 0.9

    def test_out_of_range_is_clamped(self):
        assert (
            get_propensity("CROSS_SELL", _scores(propensity_purchase=1.7), False) == 1.0
        )
        assert (
            get_propensity("CROSS_SELL", _scores(propensity_purchase=-0.2), False)
            == 0.0
        )


class TestEstimators:
    def test_expected_revenue_by_factor(self):
        assert estimate_expected_revenue(1_000_000, "CROSS_SELL") == 300_000
        assert estimate_expected_revenue(1_000_000, "COMPLAINT_RESOLUTION") == 0
        assert estimate_expected_revenue(1_000_000, "UNKNOWN_ACTION") == 100_000

    def test_expected_revenue_never_negative(self):
        assert estimate_expected_revenue(-500.0, "CROSS_SELL") == 0.0

    def test_incentive_cost_none_is_zero(self):
        assert estimate_incentive_cost(IncentiveBand.NONE, 10_000_000) == 0.0

    def test_incentive_cost_percentage_and_cap(self):
        assert estimate_incentive_cost(IncentiveBand.LOW, 100_000) == 5_000
        assert estimate_incentive_cost(IncentiveBand.LOW, 100_000_000) == 25_000
        assert estimate_incentive_cost(IncentiveBand.HIGH, 100_000_000) == 150_000
        assert estimate_incentive_cost(IncentiveBand.MEDIUM, 500_000) == 50_000
