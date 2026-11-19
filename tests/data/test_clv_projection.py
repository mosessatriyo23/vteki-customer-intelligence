"""Development-only gross CLV arithmetic contract (not retention model training)."""

import math

import pytest

from services.data.models.clv_projection import project_clv


def test_exact_monthly_frequency_and_gross_components():
    result = project_clv(1_200_000, 8, 0.5, "supplied-test-v1")
    assert result["historical_spend_365d_gross_idr"] == 1_200_000
    assert result["transaction_count_365d"] == 8
    assert result["avg_txn_value_gross_idr"] == 150_000
    assert result["freq_per_month"] == 8 / 12
    assert result["projected_forward_12m_gross_idr"] == 600_000
    assert result["clv_total_gross_idr"] == 1_800_000
    assert result["tier"] == "PLATINUM"
    assert result["retention_factor"] == 0.5
    assert result["retention_factor_version"] == "supplied-test-v1"
    assert result["retention_scope_provenance"] == "supplied_not_approved"
    assert result["formula_version"] == "christ-clv-gross-365d-dev-1"
    assert result["production_ready"] is False


@pytest.mark.parametrize(
    ("gross", "count", "factor", "expected", "tier"),
    [
        (200_000, 2, 0.0, 200_000, "SILVER"),
        (250_000, 2, 1.0, 500_000, "GOLD"),
        (500_000, 2, 1.0, 1_000_000, "PLATINUM"),
        (99_999, 2, 1.0, 199_998, "INSUFFICIENT_HISTORY"),
        (1_000_000, 1, 1.0, 2_000_000, "INSUFFICIENT_HISTORY"),
        (0, 0, 0.0, 0, "INSUFFICIENT_HISTORY"),
    ],
)
def test_tier_boundaries_and_history(gross, count, factor, expected, tier):
    result = project_clv(gross, count, factor, "manual-v1")
    assert result["clv_total_gross_idr"] == expected
    assert result["tier"] == tier
    if count == 0:
        assert result["avg_txn_value_gross_idr"] == 0
        assert result["freq_per_month"] == 0


def test_missing_retention_blocks_projection_and_tier_even_with_history():
    result = project_clv(1_200_000, 8, None, None)
    assert result["historical_spend_365d_gross_idr"] == 1_200_000
    assert result["avg_txn_value_gross_idr"] == 150_000
    assert result["freq_per_month"] == 8 / 12
    assert result["clv_total_gross_idr"] is None
    assert result["projected_forward_12m_gross_idr"] is None
    assert result["tier"] is None
    assert result["retention_scope_provenance"] == "missing_blocked"
    assert result["production_ready"] is False


@pytest.mark.parametrize(
    ("gross", "count", "factor", "version"),
    [
        (10**1000, 2, 0.5, "v1"),
        (0, 10**1000, None, None),
        (1e308, 2, 1.0, "v1"),
        (10**1000, 2, None, None),
        (True, 2, 0.5, "v1"),
        (-1, 2, 0.5, "v1"),
        (float("nan"), 2, 0.5, "v1"),
        (float("inf"), 2, 0.5, "v1"),
        (0, True, 0.5, "v1"),
        (0, -1, 0.5, "v1"),
        (0, 1.5, 0.5, "v1"),
        (1, 0, 0.5, "v1"),
        (0, 2, True, "v1"),
        (0, 2, math.nan, "v1"),
        (0, 2, math.inf, "v1"),
        (0, 2, -0.01, "v1"),
        (0, 2, 1.01, "v1"),
        (0, 2, 0.5, None),
        (0, 2, 0.5, " "),
        (0, 2, None, "v1"),
    ],
)
def test_rejects_invalid_inputs(gross, count, factor, version):
    with pytest.raises(ValueError):
        project_clv(gross, count, factor, version)


def test_retention_inputs_must_be_explicit():
    with pytest.raises(TypeError):
        project_clv(500_000, 2)
