"""Persistence adapter for Customer360 profile snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import ProfileSnapshot


def _integer_idr(value: Any, field: str) -> int:
    """Never silently round fractional money or accept booleans as integers."""
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


def save_profile_snapshots(
    profiles: list[dict[str, Any]],
    batch_id: str,
    registry_version: str,
    session: Session,
    rule_version: str = "c360-development-v1",
) -> int:
    """Persists Customer 360 profile snapshots into persistent storage.

    Enforces unique constraint:
    (golden_customer_id, cutoff_at, identity_registry_version, rule_version)
    """
    if not rule_version:
        raise ValueError("rule_version must not be empty")
    now = datetime.now(timezone.utc)
    persisted_count = 0

    for p in profiles:
        cutoff_dt = _require_timezone(
            datetime.fromisoformat(p["cutoff_at"]), "cutoff_at"
        )
        first_join = (
            datetime.fromisoformat(p["first_join_date"]).date()
            if isinstance(p["first_join_date"], str)
            else p["first_join_date"]
        )
        last_tx = (
            _require_timezone(
                datetime.fromisoformat(p["last_transaction_at"]), "last_transaction_at"
            )
            if p.get("last_transaction_at")
            else None
        )

        stmt = select(ProfileSnapshot).where(
            ProfileSnapshot.golden_customer_id == p["golden_customer_id"],
            ProfileSnapshot.cutoff_at == cutoff_dt,
            ProfileSnapshot.identity_registry_version == registry_version,
            ProfileSnapshot.rule_version == rule_version,
        )
        existing = session.scalars(stmt).first()

        if existing:
            existing.generated_at = now
            existing.source_batch_id = batch_id
            existing.identity_status = p["identity_status"]
            existing.source_identity_count = int(p["source_identity_count"])
            existing.first_join_date = first_join
            existing.transaction_count = int(p["transaction_count"])
            existing.retained_revenue = _integer_idr(
                p["retained_revenue"], "retained_revenue"
            )
            existing.last_transaction_at = last_tx
            existing.visit_count = int(p["visit_count"])
            existing.renewal_count = int(p["renewal_count"])
        else:
            snapshot = ProfileSnapshot(
                golden_customer_id=p["golden_customer_id"],
                cutoff_at=cutoff_dt,
                generated_at=now,
                identity_registry_version=registry_version,
                source_batch_id=batch_id,
                rule_version=rule_version,
                identity_status=p["identity_status"],
                source_identity_count=int(p["source_identity_count"]),
                first_join_date=first_join,
                transaction_count=int(p["transaction_count"]),
                retained_revenue=_integer_idr(
                    p["retained_revenue"], "retained_revenue"
                ),
                last_transaction_at=last_tx,
                visit_count=int(p["visit_count"]),
                renewal_count=int(p["renewal_count"]),
            )
            session.add(snapshot)
        persisted_count += 1

    session.commit()
    return persisted_count
 