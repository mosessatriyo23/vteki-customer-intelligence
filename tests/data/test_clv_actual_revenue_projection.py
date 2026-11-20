"""v1.4 proposed revenue mapping, not approved retention or serving."""

from datetime import datetime

import pytest

from services.data.models import clv_projection
from services.data.models.clv_features import build_clv_actual_revenue_aggregates


def test_actual_revenue_aggregate_flows_to_projection_without_gross_labels():
    rows = [
        {
            "source_transaction_id": identifier,
            "source_customer_ref": "a",
            "source_system": "POS",
            "transaction_datetime": "2026-05-31T12:00:00+07:00",
            "gross_amount": str(gross),
            "discount_amount": str(discount),
            "net_amount": str(gross - discount),
            "refund_amount": str(refund),
            "actual_revenue": str(gross - discount - refund),
            "status": status,
        }
        for identifier, gross, discount, refund, status in (
            ("one", 100, 10, 0, "COMPLETED"),
            ("two", 200, 20, 50, "PARTIAL_REFUND"),
        )
    ]
    aggregate = build_clv_actual_revenue_aggregates(
        rows, {"a": "golden-a"}, datetime.fromisoformat("2026-06-01T00:00:00+07:00")
    )[0]
    # 0.5 is only a unit-test fixture, not an estimated business factor.
    result = clv_projection.project_clv_actual_revenue(
        aggregate["historical_spend_12m_actual_revenue"],
        aggregate["transaction_count_12m"],
        0.5,
        "unit-test-only",
    )
    assert result["historical_spend_365d_actual_revenue_idr"] == 220
    assert result["avg_txn_value_actual_revenue_idr"] == 110
    assert result["projected_forward_12m_actual_revenue_idr"] == 110
    assert result["clv_total_actual_revenue_idr"] == 330
    assert result["revenue_basis"] == "actual_revenue"
    assert result["formula_version"] == "christ-clv-actual-revenue-365d-dev-1"
    assert result["value_horizon_months"] == 12
    assert result["availability_time_status"] == "UNPROVEN"
    assert not any("gross" in key for key in result)
    for flag in (
        "training_ready",
        "experiment_ready",
        "final_model",
        "serving_ready",
        "calibration_final",
        "approved",
        "targeting_allowed",
        "production_ready",
    ):
        assert result[flag] is False


def test_missing_retention_stays_blocked_in_actual_revenue_path():
    result = clv_projection.project_clv_actual_revenue(220, 2, None, None)
    assert result["historical_spend_365d_actual_revenue_idr"] == 220
    assert result["clv_total_actual_revenue_idr"] is None
    assert result["projected_forward_12m_actual_revenue_idr"] is None
    assert result["tier"] is None
    assert result["retention_scope_provenance"] == "missing_blocked"


@pytest.mark.parametrize(
    "history,count,factor,version",
    [
        (-1, 2, None, None),
        (True, 2, None, None),
        (float("inf"), 2, None, None),
        (200, 0, None, None),
        (200, 2, 1.1, "test"),
        (200, 2, 0.5, None),
    ],
)
def test_invalid_inputs_are_rejected(history, count, factor, version):
    with pytest.raises(ValueError):
        clv_projection.project_clv_actual_revenue(history, count, factor, version)
