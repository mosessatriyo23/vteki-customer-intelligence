import logging
import multiprocessing
import pickle
import threading
import time
from datetime import datetime, timezone
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from typing import Any, Callable
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
PROCESS_SHUTDOWN_GRACE_SECONDS = 1.0
_local_pipeline_lock = threading.Lock()


def _invoke_handler(
    connection: Connection,
    handler: Callable[[dict[str, Any]], dict[str, Any]],
    payload: dict[str, Any],
) -> None:
    """Run one importable handler in a child process and return a result."""
    try:
        connection.send(("ok", handler(payload)))
    except BaseException as error:
        try:
            connection.send(("error", type(error).__name__, str(error)[:1000]))
        except (BrokenPipeError, EOFError, OSError, pickle.PicklingError):
            # The parent may have timed out, or the error itself may not serialize.
            pass
    finally:
        connection.close()


def _terminate_process(process: BaseProcess) -> None:
    """Stop a timed-out handler and reap it so the child cannot keep running."""
    if process.is_alive():
        process.terminate()
        process.join(timeout=PROCESS_SHUTDOWN_GRACE_SECONDS)
    if process.is_alive():
        kill = getattr(process, "kill", None)
        if kill is not None:
            kill()
        else:
            process.terminate()
        process.join(timeout=PROCESS_SHUTDOWN_GRACE_SECONDS)


def _execute_handler_with_timeout(
    handler: Callable[[dict[str, Any]], dict[str, Any]],
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    """Run a module-level handler with a hard process deadline.

    A handler that cannot be pickled is rejected rather than run inline, because
    inline execution would bypass the hard timeout and break NFR-01. Production
    handlers must be importable module-level functions returning serializable data.
    """
    if timeout_seconds <= 0:
        raise TimeoutError("Pipeline budget exhausted before handler start")
    try:
        pickle.dumps((handler, payload))
    except (pickle.PicklingError, AttributeError, TypeError, ImportError) as error:
        raise TypeError(
            "Pipeline handlers must be importable/pickleable module-level functions; "
            "inline handlers are not allowed because they cannot be hard-cancelled"
        ) from error

    # Spawn avoids inheriting SQLAlchemy pools or the PostgreSQL advisory-lock
    # connection into the child process. It works consistently on Windows/Linux.
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_invoke_handler,
        args=(sender, handler, payload),
        name="vteki-pipeline-step",
        daemon=True,
    )
    deadline = time.monotonic() + timeout_seconds

    try:
        process.start()
    except BaseException:
        receiver.close()
        sender.close()
        process.close()
        raise
    sender.close()

    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_process(process)
                raise TimeoutError(
                    "Pipeline handler exceeded its "
                    f"{timeout_seconds:.2f}s execution deadline; "
                    "child process terminated"
                )

            if receiver.poll(min(0.1, remaining)):
                try:
                    message = receiver.recv()
                except EOFError as error:
                    process.join(timeout=PROCESS_SHUTDOWN_GRACE_SECONDS)
                    raise RuntimeError(
                        "Pipeline handler exited without returning a result"
                    ) from error

                process.join(timeout=PROCESS_SHUTDOWN_GRACE_SECONDS)
                if process.is_alive():
                    _terminate_process(process)
                if message[0] == "error":
                    raise RuntimeError(
                        f"Pipeline handler raised {message[1]}: {message[2]}"
                    )
                return message[1]

            if not process.is_alive():
                process.join()
                if receiver.poll():
                    continue
                raise RuntimeError("Pipeline handler exited without returning a result")
    finally:
        receiver.close()
        if process.is_alive():
            _terminate_process(process)
        if not process.is_alive():
            process.close()


def run_pipeline(
    steps: tuple[str, ...] = PIPELINE_STEPS,
    handlers: dict[str, Callable[[dict], dict]] = TASK_HANDLERS,
    budget_seconds: float = PIPELINE_BUDGET_SECONDS,
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
    results: dict[str, dict] = {}
    failure: str | None = None
    run_created = False

    try:
        with SessionLocal.begin() as session:
            session.add(PipelineRun(id=run_id, status="running"))
        run_created = True

        for step_name in steps:
            remaining = budget_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError(f"Pipeline exceeded {budget_seconds}-second budget")
            handler = handlers[step_name]
            results[step_name] = _execute_handler_with_timeout(
                handler,
                {"pipeline_run_id": run_id, "timeout_seconds": remaining},
                remaining,
            )
            if time.monotonic() - started > budget_seconds:
                raise TimeoutError(f"Pipeline exceeded {budget_seconds}-second budget")
    except Exception as error:
        failure = str(error)[:1000]
        logger.exception("Pipeline run failed run_id=%s", run_id)
    finally:
        try:
            if run_created:
                with SessionLocal.begin() as session:
                    finished_run = session.get(PipelineRun, run_id)
                    if finished_run is not None:
                        finished_run.status = "failed" if failure else "completed"
                        finished_run.finished_at = datetime.now(timezone.utc)
                        finished_run.step_results = results
                        finished_run.error_summary = failure
        except Exception as error:
            logger.exception("Failed to persist pipeline status run_id=%s", run_id)
            failure = failure or f"Failed to persist pipeline status: {error}"[:1000]
        finally:
            if postgres_lock:
                try:
                    lock_connection.execute(
                        text("SELECT pg_advisory_unlock(:lock_key)"),
                        {"lock_key": PIPELINE_LOCK_KEY},
                    )
                finally:
                    lock_connection.close()
            else:
                lock_connection.close()
                if _local_pipeline_lock.locked():
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
