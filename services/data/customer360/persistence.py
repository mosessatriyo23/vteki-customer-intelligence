"""Persistence adapter for immutable Customer 360 profile snapshots."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import ProfileSnapshot

_ALLOWED_IDENTITY_STATUSES = frozenset(
    {"PROVISIONAL", "REVIEW_REQUIRED", "APPROVED", "REJECTED"}
)


def _integer(value: Any, field: str, *, minimum: int = 0) -> int:
    """Parse integer-valued contract fields without float/bool coercion."""
    if isinstance(value, bool):
        raise ValueError(f"{field}: bool is not an integer")
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
        raise ValueError(f"{field}: expected integer, got {value!r}")
    if result < minimum:
        raise ValueError(f"{field}: expected value >= {minimum}")
    return result


def _integer_idr(value: Any, field: str) -> int:
    """Validate integer IDR without rounding or accepting booleans."""
    try:
        return _integer(value, field, minimum=0)
    except ValueError as exc:
        message = str(exc)
        if "expected integer" in message or "not an integer" in message:
            raise ValueError(f"{field}: expected integer IDR, got {value!r}") from exc
        if "expected value >= 0" in message:
            raise ValueError(f"{field}: IDR amount must be nonnegative") from exc
        raise


def _require_timezone(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field}: timezone-aware timestamp required")
    return value


def _timestamp(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value)
    else:
        raise ValueError(f"{field}: ISO-8601 timestamp required")
    return _require_timezone(parsed, field)


def _normalise_profile(
    profile: dict[str, Any], batch_id: str, registry_version: str, rule_version: str
) -> dict[str, Any]:
    golden_id = profile.get("golden_customer_id")
    if not isinstance(golden_id, str) or not golden_id.strip():
        raise ValueError("golden_customer_id must be a non-empty string")

    status = profile.get("identity_status")
    if status not in _ALLOWED_IDENTITY_STATUSES:
        raise ValueError(f"identity_status is not supported: {status!r}")

    first_join_value = profile.get("first_join_date")
    if isinstance(first_join_value, datetime):
        first_join = first_join_value.date()
    elif isinstance(first_join_value, date):
        first_join = first_join_value
    elif isinstance(first_join_value, str):
        first_join = date.fromisoformat(first_join_value[:10])
    else:
        raise ValueError("first_join_date must be an ISO date")

    last_transaction = (
        _timestamp(profile["last_transaction_at"], "last_transaction_at")
        if profile.get("last_transaction_at") is not None
        else None
    )

    return {
        "golden_customer_id": golden_id,
        "cutoff_at": _timestamp(profile.get("cutoff_at"), "cutoff_at"),
        "identity_registry_version": registry_version,
        "rule_version": rule_version,
        "source_batch_id": batch_id,
        "identity_status": status,
        "source_identity_count": _integer(
            profile.get("source_identity_count"), "source_identity_count", minimum=1
        ),
        "first_join_date": first_join,
        "transaction_count": _integer(
            profile.get("transaction_count"), "transaction_count"
        ),
        "retained_revenue": _integer_idr(
            profile.get("retained_revenue"), "retained_revenue"
        ),
        "last_transaction_at": last_transaction,
        "visit_count": _integer(profile.get("visit_count"), "visit_count"),
        "renewal_count": _integer(profile.get("renewal_count"), "renewal_count"),
    }


def _same_value(actual: Any, expected: Any) -> bool:
    # SQLite drops tzinfo on DateTime round-trips; PostgreSQL TIMESTAMPTZ keeps
    # the instant. Compare wall time for that SQLite-only naive/aware pairing.
    if isinstance(actual, datetime) and isinstance(expected, datetime):
        if actual.tzinfo is None and expected.tzinfo is not None:
            return actual == expected.replace(tzinfo=None)
        if expected.tzinfo is None and actual.tzinfo is not None:
            return actual.replace(tzinfo=None) == expected
    return actual == expected


def _snapshot_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Business payload compared during idempotent replay (not generation metadata)."""
    return {
        key: value
        for key, value in row.items()
        if key not in {"source_batch_id", "identity_registry_version", "rule_version"}
    }


def save_profile_snapshots(
    profiles: list[dict[str, Any]],
    batch_id: str,
    registry_version: str,
    session: Session,
    rule_version: str = "c360-development-v1",
    *,
    commit: bool = True,
) -> int:
    """Publish a whole, validated snapshot batch atomically.

    The logical key is (golden_customer_id, cutoff_at,
    identity_registry_version, rule_version). Exact replays are no-ops and retain
    their original generated_at/source_batch_id provenance. A changed payload under
    the same logical key is rejected; callers must publish a new version instead.
    """
    if not batch_id or not batch_id.strip():
        raise ValueError("batch_id must not be empty")
    if not registry_version or not registry_version.strip():
        raise ValueError("registry_version must not be empty")
    if not rule_version or not rule_version.strip():
        raise ValueError("rule_version must not be empty")

    # Validate every input before querying/updating the session. This prevents an
    # invalid late row from leaving earlier ORM objects dirty in the caller's unit
    # of work when the exception is caught by higher-level code.
    rows = [
        _normalise_profile(profile, batch_id, registry_version, rule_version)
        for profile in profiles
    ]
    keys = [
        (
            row["golden_customer_id"],
            row["cutoff_at"],
            row["identity_registry_version"],
            row["rule_version"],
        )
        for row in rows
    ]
    if len(keys) != len(set(keys)):
        raise ValueError("Snapshot batch contains duplicate logical keys")

    now = datetime.now(timezone.utc)
    existing_rows: list[tuple[dict[str, Any], ProfileSnapshot | None]] = []
    for row in rows:
        stmt = select(ProfileSnapshot).where(
            ProfileSnapshot.golden_customer_id == row["golden_customer_id"],
            ProfileSnapshot.cutoff_at == row["cutoff_at"],
            ProfileSnapshot.identity_registry_version == registry_version,
            ProfileSnapshot.rule_version == rule_version,
        )
        existing = session.scalars(stmt).first()
        if existing is not None:
            persisted = {
                key: getattr(existing, key)
                for key in _snapshot_payload(row)
                if key not in {"golden_customer_id", "cutoff_at"}
            }
            expected = {
                key: value
                for key, value in _snapshot_payload(row).items()
                if key not in {"golden_customer_id", "cutoff_at"}
            }
            if any(
                not _same_value(persisted[key], value)
                for key, value in expected.items()
            ):
                raise ValueError(
                    "Conflicting Customer 360 snapshot replay: key already exists "
                    "with different payload; publish a new rule_version or "
                    "identity_registry_version"
                )
        existing_rows.append((row, existing))

    new_snapshots = []
    for row, existing in existing_rows:
        if existing is not None:
            continue  # Exact replay: do not rewrite published provenance.
        new_snapshots.append(ProfileSnapshot(generated_at=now, **row))

    session.add_all(new_snapshots)
    if commit:
        session.commit()
    else:
        session.flush()
    return len(rows)
