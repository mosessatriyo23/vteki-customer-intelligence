"""Development-only pure business CLV calculator.

This is a deterministic calculation over prevalidated as-of aggregates, not a
trained model or production estimate. Retention must be explicitly estimated
and supplied by the caller; it must not be assumed or inferred via a proxy such
as ``1 - churn90``.
"""

import math
from numbers import Real


def calculate_business_clv(
    historical_spend_12m: int | float,
    average_transaction_value: int | float,
    frequency_per_month: int | float,
    retention_factor: int | float,
    transaction_count: int,
) -> dict[str, int | float | str]:
    """Calculate gross-revenue CLV and tier from prevalidated as-of aggregates.

    Retention is mandatory and must be an explicitly supplied estimate in [0, 1].
    This pure function performs no ingestion, fitting, or ground-truth access.
    """
    historical = _finite_nonnegative("historical_spend_12m", historical_spend_12m)
    average = _finite_nonnegative("average_transaction_value", average_transaction_value)
    frequency = _finite_nonnegative("frequency_per_month", frequency_per_month)
    retention = _finite_nonnegative("retention_factor", retention_factor)
    if retention > 1:
        raise ValueError("retention_factor must be between 0 and 1")
    if isinstance(transaction_count, bool) or not isinstance(transaction_count, int):
        raise ValueError("transaction_count must be a nonnegative integer")
    if transaction_count < 0:
        raise ValueError("transaction_count must be a nonnegative integer")

    clv = historical + average * frequency * 12 * retention
    if transaction_count < 2 or clv < 200_000:
        tier = "INSUFFICIENT_HISTORY"
    elif clv >= 1_000_000:
        tier = "PLATINUM"
    elif clv >= 500_000:
        tier = "GOLD"
    else:
        tier = "SILVER"
    return {"clv": clv, "tier": tier}


def _finite_nonnegative(name: str, value: int | float) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite nonnegative number")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")
    return number
