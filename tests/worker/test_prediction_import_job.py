"""Worker persists a Moses prediction artifact for review, never for serving."""

# ruff: noqa: F811 -- the shared ``artifact`` pytest fixture is injected by name.

import json
import os

os.environ["JWT_SECRET"] = "test-only-secret-that-is-long-enough-for-hmac"
os.environ["DATABASE_URL"] = "sqlite://"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.database import SQLITE_SCHEMA_TRANSLATE_MAP, Base, get_db
from api.decision_inputs import load_serving_score_row
from api.main import app
from api.models import (
    AuditEvent,
    BatchJob,
    GoldenCustomer,
    ModelPredictionRecord,
    ModelPredictionRun,
    Role,
    User,
)
from api.security import hash_password
from services.decision.nba.serving import lookup_scores
from tests.data.test_prediction_review_roundtrip import (  # noqa: F401
    CUSTOMER_ID,
    artifact,
)
from worker import prediction_import
from worker.runner import process_one
from worker.tasks import TASK_HANDLERS

PASSWORD = "correct-horse-battery"


def inline_executor(handler, payload, timeout_seconds, cancellation_requested):
    return handler(payload)


@pytest.fixture
def env(tmp_path, monkeypatch, artifact):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    ).execution_options(schema_translate_map=SQLITE_SCHEMA_TRANSLATE_MAP)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as db:
        roles = {name: Role(name=name) for name in ("admin", "analyst", "operator")}
        db.add_all(roles.values())
        db.flush()
        db.add_all(
            User(
                email=f"{name}@example.com",
                password_hash=hash_password(PASSWORD),
                roles=[role],
            )
            for name, role in roles.items()
        )
        db.add(
            GoldenCustomer(
                golden_customer_id=CUSTOMER_ID,
                first_source_batch_id="batch-1",
                anchor_source_id="source-1",
            )
        )

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.state.audit_session_factory = factory
    monkeypatch.setattr(prediction_import, "SessionLocal", factory)
    monkeypatch.setenv("PREDICTION_IMPORT_ROOT", str(tmp_path))
    try:
        with TestClient(app) as client:
            yield client, factory, tmp_path
    finally:
        app.dependency_overrides.clear()
        del app.state.audit_session_factory
        engine.dispose()


def _headers(client, name):
    login = client.post(
        "/auth/login", json={"email": f"{name}@example.com", "password": PASSWORD}
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _counts(factory):
    with factory() as db:
        return (
            db.scalar(select(func.count()).select_from(ModelPredictionRun)),
            db.scalar(select(func.count()).select_from(ModelPredictionRecord)),
        )


def _enqueue(client, name="admin", artifact_dir="output"):
    return client.post(
        "/model-predictions/runs/import-jobs",
        json={"artifact_dir": artifact_dir},
        headers=_headers(client, name),
    )


def test_handler_is_registered():
    assert TASK_HANDLERS["prediction_import"] is prediction_import.prediction_import


def test_worker_persists_scores_reasons_and_versions_for_review(env, artifact):
    client, factory, _ = env
    queued = _enqueue(client)
    assert queued.status_code == 202, queued.text
    job = queued.json()
    assert job["kind"] == "prediction_import"
    assert job["payload"]["batch_job_id"] == job["id"]

    assert process_one(factory, handler_executor=inline_executor)
    with factory() as db:
        stored_job = db.get(BatchJob, job["id"])
        assert stored_job.status == "completed", stored_job.last_error
        assert stored_job.result["already_imported"] is False
        assert stored_job.result["serving_ready"] is False
        run = db.scalars(select(ModelPredictionRun)).one()
        assert stored_job.result["run_id"] == run.id
        assert run.review_status == "pending_review"
        assert run.model_version == artifact["manifest"]["model_version"]
        assert run.producer_version == artifact["manifest"]["producer_version"]
        assert run.submitted_by == stored_job.created_by
        record = db.scalars(select(ModelPredictionRecord)).one()
        assert record.source_record == artifact["records"][0]
        assert record.source_record["score_explanation"]["sentences"]
        audit = db.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == "model.prediction_run.imported_for_review"
            )
        ).one()
        assert audit.actor_id == stored_job.created_by
        assert audit.details["batch_job_id"] == job["id"]
        score_row = load_serving_score_row(db, CUSTOMER_ID)
        assert score_row is not None
        assert score_row["contract_status"] == "SCHEMA_PARTIAL"
        assert score_row["usage_approved"] is None
        assert lookup_scores(score_row, customer_id=CUSTOMER_ID).usable is False


def test_reimport_is_idempotent_not_duplicated(env):
    client, factory, _ = env
    for _ in range(2):
        assert _enqueue(client).status_code == 202
        assert process_one(factory, handler_executor=inline_executor)
    with factory() as db:
        results = [
            job.result for job in db.scalars(select(BatchJob).order_by(BatchJob.id))
        ]
    assert [r["already_imported"] for r in results] == [False, True]
    assert results[0]["run_id"] == results[1]["run_id"]
    assert _counts(factory) == (1, 1)


@pytest.mark.parametrize(
    "artifact_dir", ["../output", "/etc", "a/b", "a..b", "x.", "", ".", ".."]
)
def test_endpoint_rejects_unsafe_artifact_names(env, artifact_dir):
    client, factory, _ = env
    assert _enqueue(client, artifact_dir=artifact_dir).status_code == 422
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(BatchJob)) == 0


def test_operator_cannot_enqueue_import(env):
    client, _, _ = env
    assert _enqueue(client, name="operator").status_code == 403


def _job(factory, *, creator, payload, kind="prediction_import"):
    with factory.begin() as db:
        user = db.scalars(
            select(User).where(User.email == f"{creator}@example.com")
        ).one()
        job = BatchJob(kind=kind, payload=payload, created_by=user.id, status="running")
        db.add(job)
        db.flush()
        return job.id


def test_generic_job_without_bound_id_is_refused(env):
    _, factory, _ = env
    _job(factory, creator="admin", payload={"artifact_dir": "output"})
    with pytest.raises(ValueError, match="batch_job_id"):
        prediction_import.prediction_import({"artifact_dir": "output"})
    assert _counts(factory) == (0, 0)


def test_handler_is_picklable_for_spawned_worker():
    import pickle

    assert pickle.loads(pickle.dumps(TASK_HANDLERS["prediction_import"])) is (
        prediction_import.prediction_import
    )


def test_operator_cannot_replay_admin_job_via_generic_jobs(env):
    client, factory, _ = env
    queued = _enqueue(client).json()
    # Admin job finished earlier; an operator copies its payload into /jobs.
    assert process_one(factory, handler_executor=inline_executor)
    replay = client.post(
        "/jobs",
        json={"kind": "prediction_import", "payload": queued["payload"]},
        headers=_headers(client, "operator"),
    )
    assert replay.status_code == 202
    assert process_one(factory, handler_executor=inline_executor)
    with factory() as db:
        replayed = db.get(BatchJob, replay.json()["id"])
        # Generic jobs retry (max_attempts=3); the point is it never imports.
        assert replayed.status in {"queued", "failed"}
        assert "not running" in (replayed.last_error or "")
        audits = db.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == "model.prediction_run.imported_for_review"
            )
        ).all()
        assert len(audits) == 1


def test_copied_id_is_refused_even_while_original_runs(env):
    _, factory, _ = env
    original = _job(factory, creator="admin", payload={})
    payload = {"artifact_dir": "output", "batch_job_id": original}
    with factory.begin() as db:
        db.get(BatchJob, original).payload = payload
    _job(factory, creator="operator", payload=payload)
    with pytest.raises(ValueError, match="another job"):
        prediction_import.prediction_import(payload)
    assert _counts(factory) == (0, 0)


def test_symlinked_ground_truth_directory_is_refused(env):
    _, factory, root = env
    (root / "ground_truth").mkdir()
    try:
        (root / "alias").symlink_to(root / "ground_truth", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    job_id = _job(factory, creator="admin", payload={})
    payload = {"artifact_dir": "alias", "batch_job_id": job_id}
    with factory.begin() as db:
        db.get(BatchJob, job_id).payload = payload
    with pytest.raises(ValueError, match="artifact_dir"):
        prediction_import.prediction_import(payload)


def test_job_created_by_operator_is_refused(env):
    _, factory, _ = env
    job_id = _job(factory, creator="operator", payload={})
    payload = {"artifact_dir": "output", "batch_job_id": job_id}
    with factory.begin() as db:
        db.get(BatchJob, job_id).payload = payload
    with pytest.raises(ValueError, match="role"):
        prediction_import.prediction_import(payload)
    assert _counts(factory) == (0, 0)


def test_payload_must_match_stored_job(env):
    _, factory, _ = env
    job_id = _job(factory, creator="admin", payload={})
    with factory.begin() as db:
        db.get(BatchJob, job_id).payload = {
            "artifact_dir": "other",
            "batch_job_id": job_id,
        }
    with pytest.raises(ValueError, match="payload"):
        prediction_import.prediction_import(
            {"artifact_dir": "output", "batch_job_id": job_id}
        )


def test_unconfigured_root_is_refused(env, monkeypatch):
    _, factory, _ = env
    monkeypatch.delenv("PREDICTION_IMPORT_ROOT")
    job_id = _job(factory, creator="admin", payload={})
    payload = {"artifact_dir": "output", "batch_job_id": job_id}
    with factory.begin() as db:
        db.get(BatchJob, job_id).payload = payload
    with pytest.raises(ValueError, match="PREDICTION_IMPORT_ROOT"):
        prediction_import.prediction_import(payload)


def test_tampered_records_import_nothing(env):
    _, factory, root = env
    path = root / "output" / "records.jsonl"
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    row["score"] = 0.99
    path.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")
    job_id = _job(factory, creator="admin", payload={})
    payload = {"artifact_dir": "output", "batch_job_id": job_id}
    with factory.begin() as db:
        db.get(BatchJob, job_id).payload = payload
    with pytest.raises(ValueError, match="checksum"):
        prediction_import.prediction_import(payload)
    assert _counts(factory) == (0, 0)
