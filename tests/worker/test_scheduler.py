import time

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.database import Base
from api.models import PipelineRun
from worker import scheduler


def make_session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    ).execution_options(
        schema_translate_map={
            "core": None,
            "gov": None,
            "stg": None,
            "feat": None,
            "ml": None,
            "dec": None,
            "act": None,
            "msr": None,
        }
    )
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


def test_pipeline_does_not_overlap_and_marks_budget_overrun(monkeypatch):
    engine, session_factory = make_session_factory()
    monkeypatch.setattr(scheduler, "engine", engine)
    monkeypatch.setattr(scheduler, "SessionLocal", session_factory)
    nested_result = []

    def slow_step(_):
        nested_result.append(
            scheduler.run_pipeline(steps=(), handlers={}, budget_seconds=1)
        )
        time.sleep(0.02)
        return {"finished": True}

    assert not scheduler.run_pipeline(
        steps=("slow",), handlers={"slow": slow_step}, budget_seconds=0.005
    )
    assert nested_result == [False]
    with session_factory() as session:
        run = session.query(PipelineRun).one()
        assert run.status == "failed"
        assert "budget" in (run.error_summary or "")
    engine.dispose()
