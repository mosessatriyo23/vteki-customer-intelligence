from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.database import SQLITE_SCHEMA_TRANSLATE_MAP, Base
from api.models import PipelineRun
from worker import scheduler


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
    called = []
    assert scheduler.run_pipeline(
        steps=("extract", "measure"),
        handlers={
            "extract": lambda _: called.append("extract") or {"rows": 4},
            "measure": lambda _: called.append("measure") or {"drift": 0.1},
        },
        budget_seconds=5,
    )
    assert called == ["extract", "measure"]
    with session_factory() as session:
        run = session.query(PipelineRun).one()
        assert run.status == "completed"
        assert run.step_results == {"extract": {"rows": 4}, "measure": {"drift": 0.1}}
        assert run.finished_at is not None
    engine.dispose()


def test_pipeline_does_not_overlap(monkeypatch):
    # The nested call must be rejected while the outer run holds its lock.
    # Do not tie this assertion to wall-clock performance of SQLite/CI runners.
    engine, session_factory = make_session_factory()
    monkeypatch.setattr(scheduler, "engine", engine)
    monkeypatch.setattr(scheduler, "SessionLocal", session_factory)
    nested_result = []

    def nested_step(_):
        nested_result.append(
            scheduler.run_pipeline(steps=(), handlers={}, budget_seconds=60)
        )
        return {"finished": True}

    assert scheduler.run_pipeline(
        steps=("nested",), handlers={"nested": nested_step}, budget_seconds=60
    )
    assert nested_result == [False]
    with session_factory() as session:
        run = session.query(PipelineRun).one()
        assert run.status == "completed"
    engine.dispose()


def test_pipeline_marks_budget_overrun(monkeypatch):
    # Simulated monotonic time removes timing variance across CI hosts.
    engine, session_factory = make_session_factory()
    monkeypatch.setattr(scheduler, "engine", engine)
    monkeypatch.setattr(scheduler, "SessionLocal", session_factory)
    clock = [100.0]
    monkeypatch.setattr(scheduler, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def over_budget_step(_):
        clock[0] += 6.0
        return {"finished": True}

    assert not scheduler.run_pipeline(
        steps=("slow",), handlers={"slow": over_budget_step}, budget_seconds=5
    )
    with session_factory() as session:
        run = session.query(PipelineRun).one()
        assert run.status == "failed"
        assert "budget" in (run.error_summary or "")
    engine.dispose()
