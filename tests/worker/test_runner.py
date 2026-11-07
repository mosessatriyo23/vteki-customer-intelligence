from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.database import SQLITE_SCHEMA_TRANSLATE_MAP, Base
from api.models import BatchJob
from worker.runner import (
    JOB_LEASE_SECONDS,
    process_one,
    recover_expired_jobs,
)


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    ).execution_options(schema_translate_map=SQLITE_SCHEMA_TRANSLATE_MAP)

    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def inline_executor(handler, payload, timeout_seconds):
    """Run handlers directly in unit tests without spawning a subprocess."""
    return handler(payload)


def test_worker_processes_job_and_persists_result():
    engine, session_factory = make_session_factory()

    with session_factory() as session:
        session.add(
            BatchJob(
                kind="rollup",
                payload={"source": "test"},
                max_attempts=2,
                available_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

    assert process_one(
        session_factory,
        {"rollup": lambda payload: {"source": payload["source"], "rows": 4}},
        handler_executor=inline_executor,
    )

    with session_factory() as session:
        job = session.get(BatchJob, 1)
        assert job is not None
        assert job.status == "completed"
        assert job.attempts == 1
        assert job.result == {"source": "test", "rows": 4}
        assert job.started_at is None
        assert job.lease_until is None
        assert job.claim_token is None

    assert not process_one(
        session_factory,
        {"rollup": lambda _: {}},
        handler_executor=inline_executor,
    )
    engine.dispose()


def test_worker_marks_job_failed_after_last_attempt():
    engine, session_factory = make_session_factory()

    with session_factory() as session:
        session.add(
            BatchJob(
                kind="broken",
                payload={},
                max_attempts=1,
                available_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

    assert process_one(
        session_factory,
        {},
        handler_executor=inline_executor,
    )

    with session_factory() as session:
        job = session.get(BatchJob, 1)
        assert job is not None
        assert job.status == "failed"
        assert job.attempts == 1
        assert "broken" in (job.last_error or "")
        assert job.started_at is None
        assert job.lease_until is None
        assert job.claim_token is None

    engine.dispose()


def test_worker_recovers_expired_job():
    engine, session_factory = make_session_factory()
    now = datetime.now(timezone.utc)

    with session_factory() as session:
        session.add(
            BatchJob(
                kind="rollup",
                payload={"correlation_id": "recovery-test"},
                status="running",
                attempts=1,
                max_attempts=3,
                started_at=now - timedelta(hours=1),
                lease_until=now - timedelta(seconds=10),
                claim_token="expired-claim",
                available_at=now - timedelta(hours=1),
            )
        )
        session.commit()

    recovered = recover_expired_jobs(session_factory)

    assert recovered == 1

    with session_factory() as session:
        job = session.get(BatchJob, 1)
        assert job is not None
        assert job.status == "queued"
        assert job.started_at is None
        assert job.lease_until is None
        assert job.claim_token is None
        assert job.attempts == 1
        assert job.available_at is not None
        assert job.available_at.replace(tzinfo=timezone.utc) > now

    engine.dispose()


def test_worker_fails_expired_job_after_last_attempt():
    engine, session_factory = make_session_factory()
    now = datetime.now(timezone.utc)

    with session_factory() as session:
        session.add(
            BatchJob(
                kind="rollup",
                payload={},
                status="running",
                attempts=3,
                max_attempts=3,
                started_at=now - timedelta(hours=1),
                lease_until=now - timedelta(seconds=10),
                claim_token="expired-claim",
                available_at=now - timedelta(hours=1),
            )
        )
        session.commit()

    recovered = recover_expired_jobs(session_factory)

    assert recovered == 1

    with session_factory() as session:
        job = session.get(BatchJob, 1)
        assert job is not None
        assert job.status == "failed"
        assert job.started_at is None
        assert job.lease_until is None
        assert job.claim_token is None
        assert "lease expired" in (job.last_error or "").lower()

    engine.dispose()


def test_worker_does_not_recover_active_lease():
    engine, session_factory = make_session_factory()
    now = datetime.now(timezone.utc)

    with session_factory() as session:
        session.add(
            BatchJob(
                kind="rollup",
                payload={},
                status="running",
                attempts=1,
                max_attempts=3,
                started_at=now,
                lease_until=now + timedelta(minutes=30),
                claim_token="active-claim",
                available_at=now,
            )
        )
        session.commit()

    recovered = recover_expired_jobs(session_factory)

    assert recovered == 0

    with session_factory() as session:
        job = session.get(BatchJob, 1)
        assert job is not None
        assert job.status == "running"
        assert job.lease_until is not None
        assert job.claim_token == "active-claim"

    engine.dispose()


def test_worker_uses_sixty_minute_timeout():
    engine, session_factory = make_session_factory()
    now = datetime.now(timezone.utc)

    with session_factory() as session:
        session.add(
            BatchJob(
                kind="rollup",
                payload={},
                max_attempts=2,
                available_at=now,
            )
        )
        session.commit()

    received = {}

    def checking_executor(handler, payload, timeout_seconds):
        received["timeout"] = timeout_seconds
        return handler(payload)

    assert JOB_LEASE_SECONDS == 3600
    assert process_one(
        session_factory,
        {"rollup": lambda _: {"ok": True}},
        handler_executor=checking_executor,
    )
    assert received["timeout"] == 3600

    with session_factory() as session:
        job = session.get(BatchJob, 1)
        assert job is not None
        assert job.status == "completed"

    engine.dispose()


def test_worker_retries_after_executor_timeout():
    engine, session_factory = make_session_factory()

    with session_factory() as session:
        session.add(
            BatchJob(
                kind="rollup",
                payload={},
                max_attempts=2,
                available_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

    def timeout_executor(handler, payload, timeout_seconds):
        raise TimeoutError("Job exceeded execution timeout")

    assert process_one(
        session_factory,
        {"rollup": lambda _: {"ok": True}},
        handler_executor=timeout_executor,
        job_timeout_seconds=30,
    )

    with session_factory() as session:
        job = session.get(BatchJob, 1)
        assert job is not None
        assert job.status == "queued"
        assert job.attempts == 1
        assert "timeout" in (job.last_error or "").lower()
        assert job.started_at is None
        assert job.lease_until is None
        assert job.claim_token is None

    engine.dispose()


def test_stale_worker_cannot_complete_reclaimed_job():
    engine, session_factory = make_session_factory()

    with session_factory() as session:
        session.add(
            BatchJob(
                kind="rollup",
                payload={},
                max_attempts=3,
                available_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

    def reclaiming_executor(handler, payload, timeout_seconds):
        # Simulate recovery and a newer worker claiming the same job.
        with session_factory() as session:
            job = session.get(BatchJob, 1)
            assert job is not None
            job.claim_token = "new-worker-claim"
            job.status = "running"
            session.commit()

        return {"result": "from stale worker"}

    assert process_one(
        session_factory,
        {"rollup": lambda _: {"ok": True}},
        handler_executor=reclaiming_executor,
    )

    with session_factory() as session:
        job = session.get(BatchJob, 1)
        assert job is not None
        assert job.status == "running"
        assert job.claim_token == "new-worker-claim"
        assert job.result is None

    engine.dispose()
