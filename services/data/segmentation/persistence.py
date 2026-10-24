"""Persistence adapter for immutable RFM and lifecycle snapshots."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import RFMLifecycleSnapshot

_ALLOWED_IDENTITY_STATUSES = frozenset(
    {"PROVISIONAL", "REVIEW_REQUIRED", "APPROVED", "REJECTED"}
)


def _integer(
    value: Any,
    field: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
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
    if result < minimum or (maximum is not None and result > maximum):
        upper = f" and <= {maximum}" if maximum is not None else ""
        raise ValueError(f"{field}: expected value >= {minimum}{upper}")
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


def _normalise_segment(
    segment: dict[str, Any], batch_id: str, registry_version: str
) -> dict[str, Any]:
    golden_id = segment.get("golden_customer_id")
    if not isinstance(golden_id, str) or not golden_id.strip():
        raise ValueError("golden_customer_id must be a non-empty string")
    status = segment.get("identity_status")
    if status not in _ALLOWED_IDENTITY_STATUSES:
        raise ValueError(f"identity_status is not supported: {status!r}")
    rule_version = segment.get("rule_version", "lifecycle-proposed-1.0")
    if not isinstance(rule_version, str) or not rule_version.strip():
        raise ValueError("rule_version must not be empty")
    recency = segment.get("recency_days")
    if recency is not None:
        recency = _integer(recency, "recency_days")
    rfm_window_days = _integer(
        segment.get("rfm_window_days", 365), "rfm_window_days", minimum=1
    )

    rfm_code = str(segment.get("rfm_code", ""))
    if re.fullmatch(r"[1-5]{3}", rfm_code) is None:
        raise ValueError("rfm_code must contain exactly three digits from 1 to 5")
    lifecycle = segment.get("lifecycle")
    if not isinstance(lifecycle, str) or not lifecycle.strip():
        raise ValueError("lifecycle must be a non-empty string")

    return {
        "golden_customer_id": golden_id,
        "cutoff_at": _timestamp(segment.get("cutoff_at"), "cutoff_at"),
        "identity_registry_version": registry_version,
        "rule_version": rule_version,
        "source_batch_id": batch_id,
        "identity_status": status,
        "recency_days": recency,
        "frequency": _integer(segment.get("frequency"), "frequency"),
        "monetary": _integer_idr(segment.get("monetary"), "monetary"),
        "rfm_window_days": rfm_window_days,
        "r_score": _integer(segment.get("r_score"), "r_score", minimum=1, maximum=5),
        "f_score": _integer(segment.get("f_score"), "f_score", minimum=1, maximum=5),
        "m_score": _integer(segment.get("m_score"), "m_score", minimum=1, maximum=5),
        "rfm_code": rfm_code,
        "tenure_days": _integer(segment.get("tenure_days"), "tenure_days"),
        "transactions_60d": _integer(
            segment.get("transactions_60d"), "transactions_60d"
        ),
        "transactions_90d": _integer(
            segment.get("transactions_90d"), "transactions_90d"
        ),
        "revenue_90d": _integer_idr(segment.get("revenue_90d"), "revenue_90d"),
        "lifecycle": lifecycle,
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
    return {
        key: value
        for key, value in row.items()
        if key not in {"source_batch_id", "identity_registry_version", "rule_version"}
    }


def save_segmentation_snapshots(
    segments: list[dict[str, Any]],
    batch_id: str,
    registry_version: str,
    session: Session,
    *,
    commit: bool = True,
) -> int:
    """Publish a fully validated batch; exact replays are no-ops.

    Set commit=False to let the caller control the transaction boundary.

    Existing logical keys with changed business payload are rejected so historical
    snapshots cannot silently change without a rule or registry version change.
    """
    if not batch_id or not batch_id.strip():
        raise ValueError("batch_id must not be empty")
    if not registry_version or not registry_version.strip():
        raise ValueError("registry_version must not be empty")

    rows = [
        _normalise_segment(segment, batch_id, registry_version) for segment in segments
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
    existing_rows: list[tuple[dict[str, Any], RFMLifecycleSnapshot | None]] = []
    for row in rows:
        stmt = select(RFMLifecycleSnapshot).where(
            RFMLifecycleSnapshot.golden_customer_id == row["golden_customer_id"],
            RFMLifecycleSnapshot.cutoff_at == row["cutoff_at"],
            RFMLifecycleSnapshot.identity_registry_version == registry_version,
            RFMLifecycleSnapshot.rule_version == row["rule_version"],
        )
        existing = session.scalars(stmt).first()
        if existing is not None:
            expected = {
                key: value
                for key, value in _snapshot_payload(row).items()
                if key not in {"golden_customer_id", "cutoff_at"}
            }
            persisted = {key: getattr(existing, key) for key in expected}
            if any(
                not _same_value(persisted[key], value)
                for key, value in expected.items()
            ):
                raise ValueError(
                    "Segmentation snapshot key already exists with different payload; "
                    "publish a new rule_version or identity_registry_version"
                )
        existing_rows.append((row, existing))

    new_snapshots = [
        RFMLifecycleSnapshot(generated_at=now, **row)
        for row, existing in existing_rows
        if existing is None
    ]
    session.add_all(new_snapshots)
    if commit:
        session.commit()
    else:
        session.flush()
    return len(rows)
