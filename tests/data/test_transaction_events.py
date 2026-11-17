from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from services.data.ingestion.transaction_events import project_transaction_events

BASE = datetime(2026, 11, 1, tzinfo=timezone.utc)


def event(
    event_id: int,
    event_type: str,
    *,
    occurred_minutes: int = 0,
    available_minutes: int = 0,
    payload: dict | None = None,
    corrects_event_id: int | None = None,
):
    occurred_at = BASE + timedelta(minutes=occurred_minutes)
    available_at = BASE + timedelta(minutes=available_minutes)
    return SimpleNamespace(
        event_id=event_id,
        source_transaction_id="tx-1",
        event_type=event_type,
        occurred_at=occurred_at,
        available_at=available_at,
        recorded_at=available_at,
        payload=payload or {},
        corrects_event_id=corrects_event_id,
    )


def recorded():
    return event(
        1,
        "TRANSACTION_RECORDED",
        payload={
            "status": "COMPLETED",
            "gross_amount": 1_000,
            "discount_amount": 100,
            "net_amount": 900,
            "refund_amount": 0,
            "actual_revenue": 900,
        },
    )


def project(events, *, effective_minutes=20, known_minutes=20):
    return project_transaction_events(
        events,
        effective_at=BASE + timedelta(minutes=effective_minutes),
        known_at=BASE + timedelta(minutes=known_minutes),
    )


def test_projection_sums_multiple_refunds_without_double_counting():
    state = project(
        [
            recorded(),
            event(
                2,
                "REFUND_RECORDED",
                occurred_minutes=1,
                available_minutes=1,
                payload={"refund_amount": 100, "status": "PARTIAL_REFUND"},
            ),
            event(
                3,
                "REFUND_RECORDED",
                occurred_minutes=2,
                available_minutes=2,
                payload={"refund_amount": 50},
            ),
        ]
    )

    assert state.status == "PARTIAL_REFUND"
    assert state.gross_amount == 1_000
    assert state.discount_amount == 100
    assert state.net_amount == 900
    assert state.refund_amount == 150
    assert state.actual_revenue == 750
    assert state.source_coverage == "OBSERVED_EVENTS_ONLY"


def test_correction_chain_replaces_original_refund_independent_of_input_order():
    events = [
        recorded(),
        event(
            2,
            "REFUND_RECORDED",
            occurred_minutes=1,
            available_minutes=1,
            payload={"refund_amount": 100},
        ),
        event(
            3,
            "CORRECTION",
            occurred_minutes=2,
            available_minutes=2,
            payload={"refund_amount": 80},
            corrects_event_id=2,
        ),
        event(
            4,
            "CORRECTION",
            occurred_minutes=3,
            available_minutes=3,
            payload={"refund_amount": 60},
            corrects_event_id=3,
        ),
        event(
            5,
            "REFUND_RECORDED",
            occurred_minutes=4,
            available_minutes=4,
            payload={"refund_amount": 50},
        ),
    ]

    forward = project(events)
    reverse = project(list(reversed(events)))

    assert forward == reverse
    assert forward.refund_amount == 110
    assert forward.actual_revenue == 790
    assert 2 not in forward.event_ids
    assert 3 not in forward.event_ids
    assert 4 in forward.event_ids


def test_late_correction_does_not_change_earlier_known_projection():
    events = [
        recorded(),
        event(
            2,
            "REFUND_RECORDED",
            occurred_minutes=1,
            available_minutes=1,
            payload={"refund_amount": 100},
        ),
        event(
            3,
            "CORRECTION",
            occurred_minutes=1,
            available_minutes=5,
            payload={"refund_amount": 70},
            corrects_event_id=2,
        ),
    ]

    before = project(events, known_minutes=4)
    after = project(events, known_minutes=6)

    assert before.refund_amount == 100
    assert after.refund_amount == 70


def test_late_refund_is_excluded_until_platform_knows_it():
    refund = event(
        2,
        "REFUND_RECORDED",
        occurred_minutes=1,
        available_minutes=5,
        payload={"refund_amount": 100},
    )
    events = [recorded(), refund]

    before_receipt = project(events, effective_minutes=10, known_minutes=4)
    after_receipt = project(events, effective_minutes=10, known_minutes=6)

    assert before_receipt.refund_amount == 0
    assert refund.event_id not in before_receipt.event_ids
    assert after_receipt.refund_amount == 100
    assert refund.event_id in after_receipt.event_ids


def test_status_change_is_excluded_before_its_effective_cutoff():
    status = event(
        2,
        "STATUS_CHANGED",
        occurred_minutes=5,
        available_minutes=1,
        payload={"status": "CANCELLED"},
    )
    events = [recorded(), status]

    before_effective = project(events, effective_minutes=4, known_minutes=10)
    at_effective = project(events, effective_minutes=5, known_minutes=10)

    assert before_effective.status == "COMPLETED"
    assert status.event_id not in before_effective.event_ids
    assert at_effective.status == "CANCELLED"
    assert at_effective.cancelled


def test_transaction_baseline_correction_preserves_intervening_refund_and_status():
    events = [
        recorded(),
        event(
            2,
            "REFUND_RECORDED",
            occurred_minutes=1,
            available_minutes=1,
            payload={"refund_amount": 125},
        ),
        event(
            3,
            "STATUS_CHANGED",
            occurred_minutes=2,
            available_minutes=2,
            payload={"status": "PARTIAL_REFUND"},
        ),
        event(
            4,
            "CORRECTION",
            occurred_minutes=3,
            available_minutes=3,
            payload={
                "status": "COMPLETED",
                "gross_amount": 1_200,
                "discount_amount": 100,
                "net_amount": 1_100,
                "refund_amount": 0,
            },
            corrects_event_id=1,
        ),
    ]

    state = project(events)

    assert state == project(list(reversed(events)))
    assert state.gross_amount == 1_200
    assert state.discount_amount == 100
    assert state.net_amount == 1_100
    assert state.refund_amount == 125
    assert state.status == "PARTIAL_REFUND"
    assert state.actual_revenue == 975
    assert state.event_ids == (4, 2, 3)


def test_equal_availability_order_is_deterministic_for_status_changes():
    available_at = BASE + timedelta(minutes=1)
    events = [
        recorded(),
        SimpleNamespace(
            event_id=2,
            source_transaction_id="tx-1",
            event_type="STATUS_CHANGED",
            occurred_at=available_at,
            available_at=available_at,
            recorded_at=available_at,
            payload={"status": "CANCELLED"},
            corrects_event_id=None,
        ),
        SimpleNamespace(
            event_id=3,
            source_transaction_id="tx-1",
            event_type="STATUS_CHANGED",
            occurred_at=available_at,
            available_at=available_at,
            recorded_at=available_at,
            payload={"status": "COMPLETED"},
            corrects_event_id=None,
        ),
    ]

    assert project(events).status == "COMPLETED"
    assert project(list(reversed(events))).status == "COMPLETED"


def test_correction_forks_are_rejected():
    events = [
        recorded(),
        event(
            2,
            "REFUND_RECORDED",
            occurred_minutes=1,
            available_minutes=1,
            payload={"refund_amount": 100},
        ),
        event(
            3,
            "CORRECTION",
            occurred_minutes=2,
            available_minutes=2,
            payload={"refund_amount": 80},
            corrects_event_id=2,
        ),
        event(
            4,
            "CORRECTION",
            occurred_minutes=3,
            available_minutes=3,
            payload={"refund_amount": 70},
            corrects_event_id=2,
        ),
    ]

    with pytest.raises(ValueError, match="branches"):
        project(events)
