"""Append-only transaction event recording and bitemporal projections."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from api.models import IngestionBatch, TransactionEventHistory

EVENT_TYPES = {
    "TRANSACTION_RECORDED",
    "REFUND_RECORDED",
    "STATUS_CHANGED",
    "CORRECTION",
}

ACTOR_TYPES = {"USER", "SYSTEM", "WORKER", "SOURCE"}
TRANSACTION_STATUSES = {"CANCELLED", "COMPLETED", "PARTIAL_REFUND", "REFUNDED"}


@dataclass(frozen=True)
class TransactionState:
    source_transaction_id: str
    effective_at: datetime
    known_at: datetime
    status: str
    gross_amount: int
    discount_amount: int
    refund_amount: int
    net_amount: int
    actual_revenue: int
    cancelled: bool
    event_ids: tuple[int, ...]
    source_coverage: str


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

    if not source_event_id or not source_version:
        raise ValueError("source_event_id and source_version are required")

    # The event batch is the receiving batch; the transaction batch is immutable
    # lineage and is stored separately on the event.
    transaction_source_batch_id = session.execute(
        text(
            """
            SELECT t.source_batch_id
            FROM source.transactions AS t
            JOIN stg.ingestion_batches AS b ON b.batch_id = t.source_batch_id
            WHERE t.source_transaction_id = :transaction_id
              AND b.status = 'PUBLISHED'
            """
        ),
        {"transaction_id": source_transaction_id},
    ).scalar_one_or_none()

    if transaction_source_batch_id is None:
        raise ValueError("Source transaction does not exist in a PUBLISHED batch")

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

    def matches_existing(existing: TransactionEventHistory) -> bool:
        same_event = (
            existing.source_transaction_id == source_transaction_id
            and existing.event_type == event_type
            and existing.occurred_at == occurred_at
            and existing.source_batch_id == source_batch_id
            and existing.source_transaction_batch_id == transaction_source_batch_id
            and existing.payload == payload
            and existing.actor_type == actor_type
            and existing.actor_id == actor_id
            and existing.source_event_id == source_event_id
            and existing.source_version == source_version
            and existing.correlation_id == correlation_id
            and existing.corrects_event_id == corrects_event_id
        )
        return same_event

    # Corrections may only point to an existing event for the same transaction.
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

    # PostgreSQL atomically arbitrates concurrent retries on the unique key.
    event_id = session.execute(
        insert(TransactionEventHistory)
        .values(
            source_transaction_id=source_transaction_id,
            event_type=event_type,
            occurred_at=occurred_at,
            source_batch_id=source_batch_id,
            source_transaction_batch_id=transaction_source_batch_id,
            idempotency_key=idempotency_key,
            payload=payload,
            actor_type=actor_type,
            actor_id=actor_id,
            source_event_id=source_event_id,
            source_version=source_version,
            correlation_id=correlation_id,
            corrects_event_id=corrects_event_id,
        )
        .on_conflict_do_nothing(
            index_elements=[TransactionEventHistory.idempotency_key]
        )
        .returning(TransactionEventHistory.event_id)
    ).scalar_one_or_none()

    event = (
        session.get(TransactionEventHistory, event_id)
        if event_id is not None
        else session.scalar(
            select(TransactionEventHistory).where(
                TransactionEventHistory.idempotency_key == idempotency_key
            )
        )
    )

    if event is None:
        raise RuntimeError("Event insert did not return or resolve an event")
    if not matches_existing(event):
        raise ValueError("Idempotency key was already used for a different event")

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

    origin_batch = aliased(IngestionBatch)
    statement = (
        select(TransactionEventHistory)
        .join(
            IngestionBatch,
            IngestionBatch.batch_id == TransactionEventHistory.source_batch_id,
        )
        .join(
            origin_batch,
            origin_batch.batch_id
            == TransactionEventHistory.source_transaction_batch_id,
        )
        .where(
            TransactionEventHistory.source_transaction_id == source_transaction_id,
            TransactionEventHistory.occurred_at <= effective_at,
            TransactionEventHistory.available_at <= known_at,
            IngestionBatch.status == "PUBLISHED",
            origin_batch.status == "PUBLISHED",
        )
        .order_by(
            TransactionEventHistory.occurred_at,
            TransactionEventHistory.available_at,
            TransactionEventHistory.recorded_at,
            TransactionEventHistory.event_id,
        )
    )

    return list(session.scalars(statement).all())


def project_transaction_events(
    events: list[TransactionEventHistory],
    *,
    effective_at: datetime,
    known_at: datetime,
) -> TransactionState:
    """Project a transaction deterministically from the visible event set.

    A correction replaces the effect of its referenced event; it is not an
    additional financial event. Corrections must form a single-child chain.
    """
    _require_aware(effective_at, "effective_at")
    _require_aware(known_at, "known_at")

    visible = sorted(
        (
            event
            for event in events
            if event.occurred_at <= effective_at and event.available_at <= known_at
        ),
        key=lambda event: (
            event.occurred_at,
            event.available_at,
            event.recorded_at,
            event.event_id,
        ),
    )
    if not visible:
        raise ValueError("No transaction events are visible at the requested cutoffs")

    transaction_ids = {event.source_transaction_id for event in visible}
    if len(transaction_ids) != 1:
        raise ValueError("Projection requires events for exactly one transaction")

    visible_by_id = {event.event_id: event for event in visible}
    correction_children: dict[int, list[TransactionEventHistory]] = {}
    for event in visible:
        if event.event_type == "CORRECTION" and event.corrects_event_id is not None:
            if event.corrects_event_id in visible_by_id:
                correction_children.setdefault(event.corrects_event_id, []).append(
                    event
                )

    if any(len(children) > 1 for children in correction_children.values()):
        raise ValueError(
            "Correction history branches; each correction must extend one chain"
        )

    def root_event(event: TransactionEventHistory) -> TransactionEventHistory | None:
        current = event
        visited: set[int] = set()
        while current.event_type == "CORRECTION":
            if current.event_id in visited or current.corrects_event_id is None:
                raise ValueError("Invalid correction chain")
            visited.add(current.event_id)
            parent = visible_by_id.get(current.corrects_event_id)
            if parent is None:
                return None
            current = parent
        return current

    corrected_ids = set(correction_children)
    state: dict[str, Any] | None = None
    applied_ids: list[int] = []

    for event in visible:
        if event.event_id in corrected_ids:
            continue
        if event.event_type == "CORRECTION":
            root = root_event(event)
            if root is None:
                continue
            effect_type = root.event_type
        else:
            effect_type = event.event_type

        payload = event.payload
        if effect_type == "TRANSACTION_RECORDED":
            gross = _money(payload, "gross_amount")
            discount = _money(payload, "discount_amount")
            reported_net = _money(payload, "net_amount")
            refund = _money(payload, "refund_amount")
            status = _status(payload.get("status"))
            if discount > gross:
                raise ValueError("discount_amount cannot exceed gross_amount")
            if reported_net != gross - discount:
                raise ValueError("net_amount must equal gross_amount - discount_amount")
            state = {
                "status": status,
                "gross_amount": gross,
                "discount_amount": discount,
                "refund_amount": refund,
            }
        elif state is None:
            raise ValueError("A visible TRANSACTION_RECORDED event is required")
        elif effect_type == "REFUND_RECORDED":
            state["refund_amount"] += _money(payload, "refund_amount", positive=True)
            if "status" in payload:
                state["status"] = _status(payload["status"])
        elif effect_type == "STATUS_CHANGED":
            state["status"] = _status(payload.get("status"))
        else:
            raise ValueError(f"Unsupported projected event type: {effect_type}")

        applied_ids.append(event.event_id)

    if state is None:
        raise ValueError("A visible TRANSACTION_RECORDED event is required")

    net_amount = state["gross_amount"] - state["discount_amount"]
    if state["refund_amount"] > net_amount:
        raise ValueError("Cumulative refund_amount cannot exceed net_amount")
    cancelled = state["status"] in {"CANCELLED", "REFUNDED"}
    actual_revenue = 0 if cancelled else net_amount - state["refund_amount"]

    return TransactionState(
        source_transaction_id=next(iter(transaction_ids)),
        effective_at=effective_at,
        known_at=known_at,
        status=state["status"],
        gross_amount=state["gross_amount"],
        discount_amount=state["discount_amount"],
        refund_amount=state["refund_amount"],
        net_amount=net_amount,
        actual_revenue=actual_revenue,
        cancelled=cancelled,
        event_ids=tuple(applied_ids),
        source_coverage="OBSERVED_EVENTS_ONLY",
    )


def project_transaction_as_of(
    session: Session,
    *,
    source_transaction_id: str,
    effective_at: datetime,
    known_at: datetime,
) -> TransactionState:
    """Return final transaction state at an effective and knowledge cutoff."""
    events = get_transaction_events_as_of(
        session,
        source_transaction_id=source_transaction_id,
        effective_at=effective_at,
        known_at=known_at,
    )
    return project_transaction_events(
        events,
        effective_at=effective_at,
        known_at=known_at,
    )


def _money(payload: dict[str, Any], key: str, *, positive: bool = False) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer amount")
    if value < (1 if positive else 0):
        raise ValueError(f"{key} must be {'positive' if positive else 'non-negative'}")
    return value


def _status(value: Any) -> str:
    if not isinstance(value, str) or value not in TRANSACTION_STATUSES:
        raise ValueError(f"Unsupported transaction status: {value!r}")
    return value
