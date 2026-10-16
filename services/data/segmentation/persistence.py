"""Versioned RFM/lifecycle persistence (integer IDR, replay-safe)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import RFMLifecycleSnapshot


def _integer_idr(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field}: bool is not an IDR integer")
    if isinstance(value, int):
        result = value
    elif (
        isinstance(value, str)
        and value
        and value.strip() == value
        and (value.isdigit() or (value[0] == "-" and value[1:].isdigit()))
    ):
        result = int(value)
    else:
        raise ValueError(f"{field}: expected integer IDR, got {value!r}")
    if result < 0:
        raise ValueError(f"{field}: IDR amount must be nonnegative")
    return result


def _require_timezone(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field}: timezone-aware timestamp required")
    return value


def save_segmentation_snapshots(
    segments: list[dict[str, Any]],
    batch_id: str,
    registry_version: str,
    session: Session,
    *,
    commit: bool = True,
) -> int:
    """Persist RFM/lifecycle rows; commit=False delegates commit to caller."""
    if not batch_id or not registry_version:
        raise ValueError("batch_id and registry_version are required")
    now = datetime.now(timezone.utc)
    processed: set[tuple[str, datetime, str]] = set()
    for row in segments:
        cutoff_at = _require_timezone(
            datetime.fromisoformat(row["cutoff_at"])
            if isinstance(row["cutoff_at"], str)
            else row["cutoff_at"],
            "cutoff_at",
        )
        rule_version = row.get("rule_version", "lifecycle-proposed-1.0")
        if not rule_version:
            raise ValueError("rule_version is required")
        key = (row["golden_customer_id"], cutoff_at, rule_version)
        if key in processed:
            raise ValueError("Duplicate segmentation natural key in the same publish")
        processed.add(key)
        attrs = dict(
            golden_customer_id=row["golden_customer_id"],
            cutoff_at=cutoff_at,
            identity_registry_version=registry_version,
            rule_version=rule_version,
            source_batch_id=batch_id,
            identity_status=row["identity_status"],
            recency_days=row.get("recency_days"),
            frequency=int(row["frequency"]),
            monetary=_integer_idr(row["monetary"], "monetary"),
            rfm_window_days=int(row.get("rfm_window_days", 365)),
            r_score=int(row["r_score"]),
            f_score=int(row["f_score"]),
            m_score=int(row["m_score"]),
            rfm_code=str(row["rfm_code"]),
            tenure_days=int(row["tenure_days"]),
            transactions_60d=int(row["transactions_60d"]),
            transactions_90d=int(row["transactions_90d"]),
            revenue_90d=_integer_idr(row["revenue_90d"], "revenue_90d"),
            lifecycle=str(row["lifecycle"]),
        )
        existing = session.scalars(
            select(RFMLifecycleSnapshot).where(
                RFMLifecycleSnapshot.golden_customer_id == attrs["golden_customer_id"],
                RFMLifecycleSnapshot.cutoff_at == cutoff_at,
                RFMLifecycleSnapshot.identity_registry_version == registry_version,
                RFMLifecycleSnapshot.rule_version == rule_version,
            )
        ).first()
        if existing:
            fields = set(attrs) - {"cutoff_at"}
            if any(getattr(existing, field) != attrs[field] for field in fields):
                raise ValueError("Conflicting segmentation snapshot replay")
        else:
            session.add(RFMLifecycleSnapshot(**attrs, generated_at=now))
    if commit:
        session.commit()
    else:
        session.flush()
    return len(segments)
