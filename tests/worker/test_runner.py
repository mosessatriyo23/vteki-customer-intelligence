from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.database import Base
from api.models import BatchJob
from worker.runner import process_one


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
    )
    with session_factory() as session:
        job = session.get(BatchJob, 1)
        assert job is not None
        assert job.status == "completed"
        assert job.attempts == 1
        assert job.result == {"source": "test", "rows": 4}
    assert not process_one(session_factory, {"rollup": lambda _: {}})
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
    assert process_one(session_factory, {})
    with session_factory() as session:
        job = session.get(BatchJob, 1)
        assert job is not None
        assert job.status == "failed"
        assert job.attempts == 1
        assert "broken" in (job.last_error or "")
    engine.dispose()
