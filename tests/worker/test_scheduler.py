import time as wall_time

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.database import SQLITE_SCHEMA_TRANSLATE_MAP, Base
from api.models import PipelineRun
from worker import scheduler


def extract_handler(_: dict) -> dict:
    return {"rows": 4}


def measure_handler(_: dict) -> dict:
    return {"drift": 0.1}


def blocking_handler(_: dict) -> dict:
    """Importable handler used to verify that the watchdog kills a stuck process."""
    wall_time.sleep(20)
    return {"finished": True}


def make_session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    ).execution_options(schema_translate_map=SQLITE_SCHEMA_TRANSLATE_MAP)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_pipeline_runs_steps_in_order_and_persists_results(monkeypatch):
    engine, session_factory = make_session_factory()
    monkeypatch.setattr(scheduler, "engine", engine)
    monkeypatch.setattr(scheduler, "SessionLocal", session_factory)
    assert scheduler.run_pipeline(
        steps=("extract", "measure"),
        handlers={"extract": extract_handler, "measure": measure_handler},
        budget_seconds=10,
    )
    with session_factory() as session:
        run = session.query(PipelineRun).one()
        assert run.status == "completed"
        assert list(run.step_results) == ["extract", "measure"]
        assert run.step_results == {"extract": {"rows": 4}, "measure": {"drift": 0.1}}
        assert run.finished_at is not None
    engine.dispose()


def test_pipeline_skips_when_local_run_lock_is_held(monkeypatch):
    engine, session_factory = make_session_factory()
    monkeypatch.setattr(scheduler, "engine", engine)
    monkeypatch.setattr(scheduler, "SessionLocal", session_factory)
    assert scheduler._local_pipeline_lock.acquire(blocking=False)
    try:
        assert not scheduler.run_pipeline(steps=(), handlers={}, budget_seconds=2)
    finally:
        scheduler._local_pipeline_lock.release()
    with session_factory() as session:
        assert session.query(PipelineRun).count() == 0
    engine.dispose()


def test_pipeline_records_hard_timeout_and_terminates_child(monkeypatch):
    engine, session_factory = make_session_factory()
    monkeypatch.setattr(scheduler, "engine", engine)
    monkeypatch.setattr(scheduler, "SessionLocal", session_factory)
    started = wall_time.perf_counter()
    assert not scheduler.run_pipeline(
        steps=("blocked",), handlers={"blocked": blocking_handler}, budget_seconds=1.5
    )
    elapsed = wall_time.perf_counter() - started
    assert elapsed < 10
    with session_factory() as session:
        run = session.query(PipelineRun).one()
        assert run.status == "failed"
        assert "deadline" in (run.error_summary or "")
        assert "terminated" in (run.error_summary or "")
    engine.dispose()


def test_pipeline_rejects_non_importable_handler(monkeypatch):
    engine, session_factory = make_session_factory()
    monkeypatch.setattr(scheduler, "engine", engine)
    monkeypatch.setattr(scheduler, "SessionLocal", session_factory)
    assert not scheduler.run_pipeline(
        steps=("inline",),
        handlers={"inline": lambda _: {"not_safe": True}},
        budget_seconds=2,
    )
    with session_factory() as session:
        run = session.query(PipelineRun).one()
        assert run.status == "failed"
        assert "module-level functions" in (run.error_summary or "")
    engine.dispose()
