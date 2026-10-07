import logging
import os
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from api.audit import record_audit_event
from api.database import SessionLocal
from api.models import BatchJob
from worker.scheduler import start_scheduler
from worker.tasks import TASK_HANDLERS

logger = logging.getLogger(__name__)
TaskHandler = Callable[[dict], dict]


def process_one(
    session_factory: sessionmaker[Session] = SessionLocal,
    handlers: dict[str, TaskHandler] = TASK_HANDLERS,
) -> bool:
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        statement = (
            select(BatchJob)
            .where(BatchJob.status == "queued", BatchJob.available_at <= now)
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
        session.commit()
        job_id, kind, payload = job.id, job.kind, dict(job.payload)
        correlation_id = str(payload.get("correlation_id") or f"batch-job-{job_id}")
        record_audit_event(
            session,
            correlation_id=correlation_id,
            event_type="batch.started",
            actor_id=job.created_by,
            entity_type="batch_job",
            entity_id=job_id,
            details={"kind": kind, "attempt": job.attempts},
        )
        session.commit()

    try:
        handler = handlers[kind]
        result = handler(payload)
    except Exception as error:
        logger.exception("Batch job failed id=%s kind=%s", job_id, kind)
        with session_factory() as session:
            job = session.get(BatchJob, job_id)
            if job is not None:
                job.last_error = str(error)[:1000]
                if job.attempts >= job.max_attempts:
                    job.status = "failed"
                else:
                    job.status = "queued"
                    job.available_at = datetime.now(timezone.utc) + timedelta(
                        seconds=min(2**job.attempts, 300)
                    )
                record_audit_event(
                    session,
                    correlation_id=correlation_id,
                    event_type=(
                        "batch.failed"
                        if job.status == "failed"
                        else "batch.retry_scheduled"
                    ),
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
        if job is not None:
            job.result = result
            job.status = "completed"
            job.last_error = None
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
