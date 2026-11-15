"""Append-only transaction event recording and bitemporal history queries."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from api.models import TransactionEventHistory

EVENT_TYPES = {
    "TRANSACTION_RECORDED",
    "REFUND_RECORDED",
    "STATUS_CHANGED",
    "CORRECTION",
}

ACTOR_TYPES = {"USER", "SYSTEM", "WORKER", "SOURCE"}


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def append_transaction_event(
    session: Session,
    *,
    source_transaction_id: str,
    event_type: str,
    occurred_at: datetime,
    source_batch_id: str,
    idempotency_key: str,
    payload: dict[str, Any],
    actor_type: str,
    actor_id: str | None = None,
    source_event_id: str | None = None,
    source_version: str | None = None,
    correlation_id: str | None = None,
    corrects_event_id: int | None = None,
) -> TransactionEventHistory:
    """Append a transaction event; receipt time is assigned by PostgreSQL."""

    if session.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Transaction event history requires PostgreSQL")

    _require_aware(occurred_at, "occurred_at")

    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unsupported event_type: {event_type}")

    if actor_type not in ACTOR_TYPES:
        raise ValueError(f"Unsupported actor_type: {actor_type}")

    if not source_transaction_id or not source_batch_id or not idempotency_key:
        raise ValueError("Transaction, batch, and idempotency identifiers are required")

    if not isinstance(payload, dict):
        raise ValueError("payload must be a dictionary")

    if bool(source_event_id) != bool(source_version):
        raise ValueError("source_event_id and source_version must be supplied together")

    # Validate that the transaction belongs to the supplied batch.
    transaction_exists = session.execute(
        text(
            """
            SELECT 1
            FROM source.transactions
            WHERE source_transaction_id = :transaction_id
              AND source_batch_id = :batch_id
            """
        ),
        {
            "transaction_id": source_transaction_id,
            "batch_id": source_batch_id,
        },
    ).first()

    if transaction_exists is None:
        raise ValueError("Source transaction does not exist in the specified batch")

    # Events can only be appended to published batches.
    batch_status = session.execute(
        text(
            """
            SELECT status
            FROM stg.ingestion_batches
            WHERE batch_id = :batch_id
            """
        ),
        {"batch_id": source_batch_id},
    ).scalar_one_or_none()

    if batch_status != "PUBLISHED":
        raise ValueError("Event batch must already be PUBLISHED")

    # Check idempotency before inserting a new event.
    existing = session.scalar(
        select(TransactionEventHistory).where(
            TransactionEventHistory.idempotency_key == idempotency_key
        )
    )

    if existing is not None:
        same_event = (
            existing.source_transaction_id == source_transaction_id
            and existing.event_type == event_type
            and existing.occurred_at == occurred_at
            and existing.source_batch_id == source_batch_id
            and existing.payload == payload
            and existing.actor_type == actor_type
            and existing.actor_id == actor_id
            and existing.source_event_id == source_event_id
            and existing.source_version == source_version
            and existing.correlation_id == correlation_id
            and existing.corrects_event_id == corrects_event_id
        )

        if not same_event:
            raise ValueError("Idempotency key was already used for a different event")

        return existing

    # Validate correction references.
    if corrects_event_id is not None:
        if event_type != "CORRECTION":
            raise ValueError("corrects_event_id is only valid for CORRECTION events")

        original = session.get(TransactionEventHistory, corrects_event_id)

        if original is None:
            raise ValueError("The event being corrected does not exist")

        if original.source_transaction_id != source_transaction_id:
            raise ValueError(
                "Correction must reference an event for the same transaction"
            )

    elif event_type == "CORRECTION":
        raise ValueError("CORRECTION events must reference corrects_event_id")

    # PostgreSQL triggers assign the authoritative receipt timestamps.
    now = datetime.now(timezone.utc)

    event = TransactionEventHistory(
        source_transaction_id=source_transaction_id,
        event_type=event_type,
        occurred_at=occurred_at,
        available_at=now,
        source_batch_id=source_batch_id,
        idempotency_key=idempotency_key,
        payload=payload,
        actor_type=actor_type,
        actor_id=actor_id,
        source_event_id=source_event_id,
        source_version=source_version,
        correlation_id=correlation_id,
        corrects_event_id=corrects_event_id,
    )

    session.add(event)
    session.flush()

    session.refresh(
        event,
        attribute_names=["available_at", "recorded_at"],
    )

    return event


def get_transaction_events_as_of(
    session: Session,
    *,
    source_transaction_id: str,
    effective_at: datetime,
    known_at: datetime,
) -> list[TransactionEventHistory]:
    """Return events effective by one cutoff and known by another."""

    if session.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Transaction event history requires PostgreSQL")

    _require_aware(effective_at, "effective_at")
    _require_aware(known_at, "known_at")

    statement = (
        select(TransactionEventHistory)
        .where(
            TransactionEventHistory.source_transaction_id == source_transaction_id,
            TransactionEventHistory.occurred_at <= effective_at,
            TransactionEventHistory.available_at <= known_at,
        )
        .order_by(
            TransactionEventHistory.occurred_at,
            TransactionEventHistory.available_at,
            TransactionEventHistory.recorded_at,
            TransactionEventHistory.event_id,
        )
    )

    return list(session.scalars(statement).all())
