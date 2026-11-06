import logging
import os
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from api.audit import record_audit_event
from api.database import SessionLocal
from api.models import BatchJob
from worker.scheduler import _execute_handler_with_timeout, start_scheduler
from worker.tasks import TASK_HANDLERS

logger = logging.getLogger(__name__)

TaskHandler = Callable[[dict], dict]
TaskExecutor = Callable[[TaskHandler, dict, int], dict]

JOB_LEASE_SECONDS = 60 * 60


def recover_expired_jobs(
    session_factory: sessionmaker[Session] = SessionLocal,
) -> int:
    """Recover jobs left running after their worker lease expires."""
    now = datetime.now(timezone.utc)
    recovered = 0

    with session_factory() as session:
        statement = (
            select(BatchJob)
            .where(
                BatchJob.status == "running",
                BatchJob.lease_until.is_not(None),
                BatchJob.lease_until <= now,
            )
            .order_by(BatchJob.lease_until, BatchJob.id)
            .with_for_update(skip_locked=True)
        )

        jobs = session.scalars(statement).all()

        for job in jobs:
            correlation_id = str(
                (job.payload or {}).get("correlation_id") or f"batch-job-{job.id}"
            )

            if job.attempts >= job.max_attempts:
                job.status = "failed"
                event_type = "batch.failed"
            else:
                job.status = "queued"
                job.available_at = now + timedelta(seconds=min(2**job.attempts, 300))
                event_type = "batch.recovered"

            job.last_error = (
                job.last_error or "Worker lease expired before job completion."
            )[:1000]
            job.started_at = None
            job.lease_until = None
            job.claim_token = None

            record_audit_event(
                session,
                correlation_id=correlation_id,
                event_type=event_type,
                actor_id=job.created_by,
                entity_type="batch_job",
                entity_id=job.id,
                details={
                    "kind": job.kind,
                    "attempt": job.attempts,
                    "max_attempts": job.max_attempts,
                    "reason": "lease_expired",
                    "new_status": job.status,
                },
            )
            recovered += 1

        session.commit()

    if recovered:
        logger.warning("Recovered %s expired batch job(s)", recovered)

    return recovered


def process_one(
    session_factory: sessionmaker[Session] = SessionLocal,
    handlers: dict[str, TaskHandler] = TASK_HANDLERS,
    handler_executor: TaskExecutor = _execute_handler_with_timeout,
    job_timeout_seconds: int = JOB_LEASE_SECONDS,
) -> bool:
    """Process one queued job with a lease and a hard execution timeout."""
    if job_timeout_seconds <= 0:
        raise ValueError("job_timeout_seconds must be greater than zero")

    recover_expired_jobs(session_factory)

    now = datetime.now(timezone.utc)
    claim_token = str(uuid4())

    with session_factory() as session:
        statement = (
            select(BatchJob)
            .where(
                BatchJob.status == "queued",
                BatchJob.available_at <= now,
            )
            .order_by(BatchJob.created_at, BatchJob.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )

        job = session.scalar(statement)

        if job is None:
            return False

        job.status = "running"
        job.attempts += 1
        job.last_error = None
        job.started_at = now
        job.lease_until = now + timedelta(seconds=job_timeout_seconds)
        job.claim_token = claim_token

        job_id = job.id
        kind = job.kind
        payload = dict(job.payload or {})
        correlation_id = str(payload.get("correlation_id") or f"batch-job-{job_id}")
        actor_id = job.created_by
        attempt = job.attempts

        record_audit_event(
            session,
            correlation_id=correlation_id,
            event_type="batch.started",
            actor_id=actor_id,
            entity_type="batch_job",
            entity_id=job_id,
            details={
                "kind": kind,
                "attempt": attempt,
                "lease_seconds": job_timeout_seconds,
            },
        )

        session.commit()

    try:
        handler = handlers[kind]
        result = handler_executor(handler, payload, job_timeout_seconds)

    except Exception as error:
        logger.exception("Batch job failed id=%s kind=%s", job_id, kind)

        with session_factory() as session:
            job = session.get(BatchJob, job_id)

            # A worker whose claim has expired must not overwrite a newer attempt.
            if (
                job is not None
                and job.status == "running"
                and job.claim_token == claim_token
            ):
                job.last_error = str(error)[:1000]
                job.started_at = None
                job.lease_until = None
                job.claim_token = None

                if job.attempts >= job.max_attempts:
                    job.status = "failed"
                    event_type = "batch.failed"
                else:
                    job.status = "queued"
                    job.available_at = datetime.now(timezone.utc) + timedelta(
                        seconds=min(2**job.attempts, 300)
                    )
                    event_type = "batch.retry_scheduled"

                record_audit_event(
                    session,
                    correlation_id=correlation_id,
                    event_type=event_type,
                    actor_id=job.created_by,
                    entity_type="batch_job",
                    entity_id=job_id,
                    details={
                        "kind": kind,
                        "attempt": job.attempts,
                        "error": job.last_error,
                    },
                )

                session.commit()

        return True

    with session_factory() as session:
        job = session.get(BatchJob, job_id)

        # Only the worker holding the current claim may complete the job.
        if (
            job is not None
            and job.status == "running"
            and job.claim_token == claim_token
        ):
            job.result = result
            job.status = "completed"
            job.last_error = None
            job.started_at = None
            job.lease_until = None
            job.claim_token = None

            record_audit_event(
                session,
                correlation_id=correlation_id,
                event_type="batch.completed",
                actor_id=job.created_by,
                entity_type="batch_job",
                entity_id=job_id,
                details={"kind": kind, "result": result},
            )

            session.commit()

    return True


def run_worker(poll_seconds: float = 2.0) -> None:
    scheduler = start_scheduler(int(os.getenv("PIPELINE_INTERVAL_MINUTES", "15")))

    try:
        while True:
            if not process_one():
                time.sleep(poll_seconds)
    finally:
        scheduler.shutdown(wait=False)
