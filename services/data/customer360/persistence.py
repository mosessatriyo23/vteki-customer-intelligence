"""Versioned Customer 360 snapshot persistence (integer IDR, replay-safe)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import ProfileSnapshot


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


def _date_time(value: Any, field: str) -> datetime:
    return _require_timezone(
        datetime.fromisoformat(value) if isinstance(value, str) else value, field
    )


def _same_timestamp(stored: datetime | None, incoming: datetime | None) -> bool:
    if stored is None or incoming is None:
        return stored is None and incoming is None
    if stored.tzinfo is None:
        # SQLite development backend drops timezone info when persisting values.
        return stored == incoming.replace(tzinfo=None)
    return stored.astimezone(timezone.utc) == incoming.astimezone(timezone.utc)


def save_profile_snapshots(
    profiles: list[dict[str, Any]],
    batch_id: str,
    registry_version: str,
    session: Session,
    rule_version: str = "c360-development-v1",
    *,
    commit: bool = True,
) -> int:
    """Persist snapshots; commit=False lets a parent transaction publish both outputs.

    Once a natural key is published, replay with identical data is idempotent.
    A conflicting replay is rejected instead of rewriting historical state.
    """
    if not batch_id or not registry_version or not rule_version:
        raise ValueError("batch_id, registry_version and rule_version are required")
    now = datetime.now(timezone.utc)
    processed: set[tuple[str, datetime]] = set()
    for profile in profiles:
        cutoff_at = _date_time(profile["cutoff_at"], "cutoff_at")
        key = (profile["golden_customer_id"], cutoff_at)
        if key in processed:
            raise ValueError("Duplicate Customer 360 natural key in the same publish")
        processed.add(key)
        first_join = profile["first_join_date"]
        if isinstance(first_join, str):
            first_join = datetime.fromisoformat(first_join).date()
        last_tx = (
            _date_time(profile["last_transaction_at"], "last_transaction_at")
            if profile.get("last_transaction_at")
            else None
        )
        attrs = dict(
            golden_customer_id=profile["golden_customer_id"],
            cutoff_at=cutoff_at,
            identity_registry_version=registry_version,
            rule_version=rule_version,
            source_batch_id=batch_id,
            identity_status=profile["identity_status"],
            source_identity_count=int(profile["source_identity_count"]),
            first_join_date=first_join,
            transaction_count=int(profile["transaction_count"]),
            retained_revenue=_integer_idr(
                profile["retained_revenue"], "retained_revenue"
            ),
            last_transaction_at=last_tx,
            visit_count=int(profile["visit_count"]),
            renewal_count=int(profile["renewal_count"]),
        )
        existing = session.scalars(
            select(ProfileSnapshot).where(
                ProfileSnapshot.golden_customer_id == attrs["golden_customer_id"],
                ProfileSnapshot.cutoff_at == cutoff_at,
                ProfileSnapshot.identity_registry_version == registry_version,
                ProfileSnapshot.rule_version == rule_version,
            )
        ).first()
        if existing:
            # SQLite does not preserve TZINFO; do not compare timestamp object
            # values on replay.  All other fields must agree exactly.
            fields = set(attrs) - {"cutoff_at", "last_transaction_at"}
            if any(getattr(existing, field) != attrs[field] for field in fields):
                raise ValueError("Conflicting Customer 360 snapshot replay")
            if not _same_timestamp(existing.last_transaction_at, last_tx):
                raise ValueError("Conflicting Customer 360 last_transaction_at replay")
        else:
            session.add(ProfileSnapshot(**attrs, generated_at=now))
    if commit:
        session.commit()
    else:
        session.flush()
    return len(profiles)
