"""Development-only gross and actual-revenue CLV wrappers.

``project_clv_actual_revenue`` is the separately versioned Christ v1.4
proposal path. It shares arithmetic and validation with the legacy gross
wrapper but labels its outputs as actual revenue. Approval and historical
knowledge-time evidence remain missing. The following describes the legacy
``project_clv`` path:

Inputs are pre-aggregated rolling-365-day gross IDR amounts. The existing
producer, clv_features.build_clv_aggregates, sums gross_amount exclusively for
COMPLETED/PARTIAL_REFUND transactions; discounts and refunds are not deducted.
This helper performs no ingestion and cannot verify or change that convention.
It does NOT implement Christ's net-preferred/partial-refund-retained wording;
see docs/moses_data_ai/CLV_REVENUE_RECONCILIATION_DEV.md for the unresolved
business meaning. Do not describe these amounts as net or retained revenue. Retention is caller-supplied, not
estimated here; a 90-day churn score or descriptive rate is not a 12-month
CLV factor. No output is approved for production use.
"""

from __future__ import annotations

import math

from services.data.models.business_clv import calculate_business_clv

FORMULA_VERSION = "christ-clv-gross-365d-dev-1"
ACTUAL_REVENUE_FORMULA_VERSION = "christ-clv-actual-revenue-365d-dev-1"


def project_clv(
    history_gross_365d: int | float,
    transaction_count_365d: int,
    retention_factor: int | float | None,
    retention_factor_version: str | None,
) -> dict:
    """Return observed components and separate 12-month forward/total CLV.

    Both retention arguments must be explicitly passed; ``None, None`` blocks
    projection and tier while leaving the observed components available.
    """
    if isinstance(history_gross_365d, bool) or not isinstance(
        history_gross_365d, (int, float)
    ):
        raise ValueError("history_gross_365d must be numeric and not boolean")
    try:
        history = float(history_gross_365d)
    except (OverflowError, ValueError) as exc:
        raise ValueError("history_gross_365d must be finite") from exc
    if not math.isfinite(history) or history < 0:
        raise ValueError("history_gross_365d must be finite and nonnegative")
    if (
        isinstance(transaction_count_365d, bool)
        or not isinstance(transaction_count_365d, int)
        or transaction_count_365d < 0
    ):
        raise ValueError("transaction_count_365d must be a nonnegative integer")
    try:
        count_float = float(transaction_count_365d)
    except OverflowError as exc:
        raise ValueError("transaction_count_365d must be finite") from exc
    if not math.isfinite(count_float):
        raise ValueError("transaction_count_365d must be finite")
    if transaction_count_365d == 0 and history > 0:
        raise ValueError("positive spend with zero transactions is contradictory")
    if (retention_factor is None) != (retention_factor_version is None):
        raise ValueError("retention_factor and version must both be supplied or None")
    if retention_factor_version is not None and (
        not isinstance(retention_factor_version, str)
        or not retention_factor_version.strip()
    ):
        raise ValueError("retention_factor_version must be a non-empty string")
    if retention_factor is not None:
        if isinstance(retention_factor, bool) or not isinstance(
            retention_factor, (int, float)
        ):
            raise ValueError("retention_factor must be numeric and not boolean")
        try:
            retention = float(retention_factor)
        except (OverflowError, ValueError) as exc:
            raise ValueError("retention_factor must be finite") from exc
        if not math.isfinite(retention) or not 0 <= retention <= 1:
            raise ValueError("retention_factor must be finite and within [0, 1]")

    average = history / transaction_count_365d if transaction_count_365d else 0.0
    frequency = transaction_count_365d / 12
    if not math.isfinite(average) or not math.isfinite(frequency):
        raise ValueError("calculated historical components must be finite")

    result = None
    if retention_factor is not None:
        result = calculate_business_clv(
            history, average, frequency, retention_factor, transaction_count_365d
        )
        forward_component = result["forward_component"]
        assert isinstance(forward_component, (int, float))
        if not math.isfinite(forward_component):
            raise ValueError("calculated forward component must be finite")

    return {
        "historical_spend_365d_gross_idr": history_gross_365d,
        "transaction_count_365d": transaction_count_365d,
        "avg_txn_value_gross_idr": average,
        "freq_per_month": frequency,
        "retention_factor": retention_factor,
        "retention_factor_version": retention_factor_version,
        "projected_forward_12m_gross_idr": (
            result["forward_component"] if result is not None else None
        ),
        "clv_total_gross_idr": result["clv"] if result is not None else None,
        "tier": result["tier"] if result is not None else None,
        "retention_scope_provenance": (
            "supplied_not_approved" if result is not None else "missing_blocked"
        ),
        "formula_version": FORMULA_VERSION,
        "production_ready": False,
    }


def project_clv_actual_revenue(
    history_actual_revenue_365d: int | float,
    transaction_count_365d: int,
    retention_factor: int | float | None,
    retention_factor_version: str | None,
) -> dict:
    """Project CLV from ``actual_revenue`` aggregates (Christ v1.4 proposal).

    Validation and arithmetic are shared with ``project_clv``; only the revenue
    basis and output labels differ. Retention remains caller-supplied and
    missing retention blocks projection and tier. The v1.4 mapping is pending
    approval and ``actual_revenue`` knowledge-time is unproven, so every
    readiness/approval flag stays false.
    """
    gross = project_clv(
        history_actual_revenue_365d,
        transaction_count_365d,
        retention_factor,
        retention_factor_version,
    )
    return {
        "historical_spend_365d_actual_revenue_idr": gross[
            "historical_spend_365d_gross_idr"
        ],
        "transaction_count_365d": gross["transaction_count_365d"],
        "avg_txn_value_actual_revenue_idr": gross["avg_txn_value_gross_idr"],
        "freq_per_month": gross["freq_per_month"],
        "retention_factor": gross["retention_factor"],
        "retention_factor_version": gross["retention_factor_version"],
        "projected_forward_12m_actual_revenue_idr": gross[
            "projected_forward_12m_gross_idr"
        ],
        "clv_total_actual_revenue_idr": gross["clv_total_gross_idr"],
        "tier": gross["tier"],
        "retention_scope_provenance": gross["retention_scope_provenance"],
        "revenue_basis": "actual_revenue",
        "value_horizon_months": 12,
        "availability_time_status": "UNPROVEN",
        "formula_version": ACTUAL_REVENUE_FORMULA_VERSION,
        "training_ready": False,
        "experiment_ready": False,
        "final_model": False,
        "serving_ready": False,
        "calibration_final": False,
        "approved": False,
        "targeting_allowed": False,
        "production_ready": False,
    }
