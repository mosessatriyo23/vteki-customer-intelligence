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
