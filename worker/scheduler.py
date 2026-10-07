import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import text

from api.database import SessionLocal, engine
from api.models import PipelineRun
from worker.tasks import TASK_HANDLERS

logger = logging.getLogger(__name__)
PIPELINE_BUDGET_SECONDS = 60 * 60
PIPELINE_LOCK_KEY = 7_188_420_261
PIPELINE_STEPS = ("fixture_rollup", "audit_summary")
_local_pipeline_lock = threading.Lock()


def run_pipeline(
    steps: tuple[str, ...] = PIPELINE_STEPS,
    handlers: dict[str, Callable[[dict], dict]] = TASK_HANDLERS,
    budget_seconds: int = PIPELINE_BUDGET_SECONDS,
) -> bool:
    lock_connection = engine.connect()
    postgres_lock = False
    if engine.dialect.name == "postgresql":
        postgres_lock = bool(
            lock_connection.execute(
                text("SELECT pg_try_advisory_lock(:lock_key)"),
                {"lock_key": PIPELINE_LOCK_KEY},
            ).scalar()
        )
        if not postgres_lock:
            lock_connection.close()
            logger.info("Skipping pipeline run because another worker holds its lock")
            return False
    elif not _local_pipeline_lock.acquire(blocking=False):
        lock_connection.close()
        return False

    run_id = str(uuid4())
    started = time.monotonic()
    with SessionLocal.begin() as session:
        pipeline_run = PipelineRun(id=run_id, status="running")
        session.add(pipeline_run)

    results: dict[str, dict] = {}
    failure: str | None = None
    try:
        for step_name in steps:
            remaining = budget_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError(f"Pipeline exceeded {budget_seconds}-second budget")
            handler = handlers[step_name]
            results[step_name] = handler(
                {"pipeline_run_id": run_id, "timeout_seconds": remaining}
            )
            if time.monotonic() - started > budget_seconds:
                raise TimeoutError(f"Pipeline exceeded {budget_seconds}-second budget")
    except Exception as error:
        failure = str(error)[:1000]
        logger.exception("Pipeline run failed run_id=%s", run_id)
    finally:
        with SessionLocal.begin() as session:
            finished_run = session.get(PipelineRun, run_id)
            if finished_run is not None:
                finished_run.status = "failed" if failure else "completed"
                finished_run.finished_at = datetime.now(timezone.utc)
                finished_run.step_results = results
                finished_run.error_summary = failure
        if postgres_lock:
            try:
                lock_connection.execute(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": PIPELINE_LOCK_KEY},
                )
            finally:
                lock_connection.close()
        elif _local_pipeline_lock.locked():
            _local_pipeline_lock.release()
    return failure is None


def start_scheduler(interval_minutes: int = 15) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        run_pipeline,
        "interval",
        minutes=max(interval_minutes, 1),
        id="scheduled-pipeline",
        next_run_time=datetime.now(timezone.utc),
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )
    scheduler.start()
    return scheduler
