"""Development-only as-of CLV aggregates from observable transaction data.

This module computes gross-revenue aggregates only. It does not estimate a
retention factor, fit a model, or access ground truth. Refund/status
availability is not versioned in the current source contract, so callers must
keep ``training_ready`` false until that contract is resolved.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Iterable


def build_clv_aggregates(
    transactions: Iterable[dict[str, str]],
    customer_mapping: dict[str, str],
    cutoff: datetime,
) -> list[dict[str, object]]:
    """Return 12-month gross-revenue aggregates as of ``cutoff``.

    The interval is ``(cutoff - 365 days, cutoff]``. Only completed or
    partially refunded transactions are included. Input rows must follow the
    validated ingestion contract. Only in-window, qualifying records participate
    in deduplication; identical replays are ignored, while conflicting eligible
    records with the same transaction ID are rejected (no version is guessed).
    Customers without qualifying transactions are omitted. The result remains
    development-only because availability-time history is not yet proven.
    """
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("cutoff must be timezone-aware")

    buckets: dict[str, list[tuple[datetime, int]]] = defaultdict(list)
    seen_ids: dict[str, tuple[str, ...]] = {}
    seen_fingerprints: set[tuple[str, ...]] = set()
    start = cutoff - timedelta(days=365)
    for row in transactions:
        source_id = row.get("source_transaction_id", "")
        ref = row.get("source_customer_ref", "")
        if not source_id:
            raise ValueError("source_transaction_id is required")
        if not ref:
            continue
        if ref not in customer_mapping:
            raise ValueError("Unknown transaction customer reference")
        if row.get("status") not in {"COMPLETED", "PARTIAL_REFUND"}:
            continue
        occurred = datetime.fromisoformat(row["transaction_datetime"])
        if occurred.tzinfo is None or occurred.utcoffset() is None:
            raise ValueError("transaction_datetime must be timezone-aware")
        if not start < occurred <= cutoff:
            continue
        fingerprint = tuple(
            row.get(key, "")
            for key in (
                "source_customer_ref",
                "source_system",
                "transaction_datetime",
                "gross_amount",
                "discount_amount",
                "net_amount",
                "status",
            )
        )
        if source_id in seen_ids:
            if fingerprint != seen_ids[source_id]:
                raise ValueError(
                    "Conflicting in-window records share source_transaction_id"
                )
            continue
        seen_ids[source_id] = fingerprint
        if fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(fingerprint)
        buckets[customer_mapping[ref]].append(
            (occurred, _gross_amount(row.get("gross_amount", "")))
        )

    result = []
    for customer_id in sorted(buckets):
        values = [amount for _, amount in buckets[customer_id]]
        total = sum(values)
        result.append(
            {
                "golden_customer_id": customer_id,
                "cutoff_at": cutoff.isoformat(),
                "historical_spend_12m_gross": total,
                "average_transaction_value_12m": total / len(values),
                "transaction_count_12m": len(values),
                "frequency_per_month_12m": len(values) / 12,
                "history_sufficient_12m": len(values) >= 2,
                "retention_factor": None,
                "training_ready": False,
                "availability_time_status": "UNPROVEN",
            }
        )
    return result


def _gross_amount(value: str) -> int:
    if not value.isdigit():
        raise ValueError("gross_amount must be a nonnegative integer IDR")
    return int(value)


ACTUAL_REVENUE_FEATURE_VERSION = "clv-actual-revenue-365d-dev-1.0-christ-v1.4"


def build_clv_actual_revenue_aggregates(
    transactions: Iterable[dict[str, str]],
    customer_mapping: dict[str, str],
    cutoff: datetime,
) -> list[dict[str, object]]:
    """Return 12-month ``actual_revenue`` aggregates as of ``cutoff``.

    This is a separately versioned sibling of ``build_clv_aggregates``. It
    sums the ingestion-provided ``actual_revenue`` field (net of discount and
    any refund recorded as-of the source) instead of ``gross_amount``, in
    line with Christ's v1.4 proposal that the CLV historical figure be
    ``actual_revenue`` (``docs/christ_business/approved/target_definitions.md``
    §2.1). That proposal is still pending mentor approval, so this function
    does not replace ``build_clv_aggregates`` and callers must not treat its
    output as approved or production-ready. It performs no ingestion, fitting,
    or ground-truth access, and it cannot prove that ``actual_revenue`` was
    known at ``cutoff`` rather than updated later by a subsequent refund — that
    availability-time guarantee is a separate, unresolved prerequisite
    (see ``CLV_REVENUE_RECONCILIATION_DEV.md``).

    Window, status filter, and deduplication rules are identical to
    ``build_clv_aggregates``.
    """
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("cutoff must be timezone-aware")

    buckets: dict[str, list[tuple[datetime, int]]] = defaultdict(list)
    seen_ids: dict[str, tuple[str, ...]] = {}
    seen_fingerprints: set[tuple[str, ...]] = set()
    start = cutoff - timedelta(days=365)
    for row in transactions:
        source_id = row.get("source_transaction_id", "")
        ref = row.get("source_customer_ref", "")
        if not source_id:
            raise ValueError("source_transaction_id is required")
        if not ref:
            continue
        if ref not in customer_mapping:
            raise ValueError("Unknown transaction customer reference")
        if row.get("status") not in {"COMPLETED", "PARTIAL_REFUND"}:
            continue
        occurred = datetime.fromisoformat(row["transaction_datetime"])
        if occurred.tzinfo is None or occurred.utcoffset() is None:
            raise ValueError("transaction_datetime must be timezone-aware")
        if not start < occurred <= cutoff:
            continue
        fingerprint = tuple(
            row.get(key, "")
            for key in (
                "source_customer_ref",
                "source_system",
                "transaction_datetime",
                "gross_amount",
                "discount_amount",
                "net_amount",
                "refund_amount",
                "actual_revenue",
                "status",
            )
        )
        if source_id in seen_ids:
            if fingerprint != seen_ids[source_id]:
                raise ValueError(
                    "Conflicting in-window records share source_transaction_id"
                )
            continue
        seen_ids[source_id] = fingerprint
        if fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(fingerprint)
        buckets[customer_mapping[ref]].append(
            (occurred, _actual_revenue(row.get("actual_revenue", "")))
        )

    result = []
    for customer_id in sorted(buckets):
        values = [amount for _, amount in buckets[customer_id]]
        total = sum(values)
        result.append(
            {
                "golden_customer_id": customer_id,
                "cutoff_at": cutoff.isoformat(),
                "historical_spend_12m_actual_revenue": total,
                "average_transaction_value_12m": total / len(values),
                "transaction_count_12m": len(values),
                "frequency_per_month_12m": len(values) / 12,
                "history_sufficient_12m": len(values) >= 2,
                "revenue_basis": "actual_revenue",
                "feature_version": ACTUAL_REVENUE_FEATURE_VERSION,
                "retention_factor": None,
                "training_ready": False,
                "availability_time_status": "UNPROVEN",
            }
        )
    return result


def _actual_revenue(value: str) -> int:
    if not value.isdigit():
        raise ValueError("actual_revenue must be a nonnegative integer IDR")
    return int(value)
