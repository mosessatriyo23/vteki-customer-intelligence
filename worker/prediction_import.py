"""Worker job: persist a Moses prediction artifact into the review tables.

Reads ``contract_manifest.json`` + ``records.jsonl`` from one directory under
the operator-configured ``PREDICTION_IMPORT_ROOT``, validates them with the
same pure validator as the HTTP import, and stores them as a
``pending_review`` run. It never schedules itself, never marks scores as
serving-ready and never approves usage; NBA still reads nothing from a run
that has not passed the (still undecided) usage approval.
"""

import json
import os
from pathlib import Path
from typing import Any

from api.database import SessionLocal
from api.model_predictions import artifact_dir_allowed, persist_prediction_import
from api.models import BatchJob, User
from services.data.models.prediction_review import validate_prediction_import

ALLOWED_ROLES = {"admin", "analyst"}
MAX_ARTIFACT_BYTES = 200 * 1024 * 1024


def _artifact_dir(name: object) -> Path:
    root_value = os.getenv("PREDICTION_IMPORT_ROOT")
    if not root_value:
        raise ValueError("PREDICTION_IMPORT_ROOT is not configured")
    if not isinstance(name, str) or not artifact_dir_allowed(name):
        raise ValueError("artifact_dir is not an allowed directory name")
    root = Path(root_value).resolve()
    directory = (root / name).resolve()
    if (
        directory.parent != root
        or not directory.is_dir()
        or not artifact_dir_allowed(directory.name)
    ):
        raise ValueError("artifact_dir does not resolve to an allowed folder")
    return directory


def _read(directory: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    paths = []
    for name in ("contract_manifest.json", "records.jsonl"):
        resolved = (directory / name).resolve()
        if resolved.parent != directory or not resolved.is_file():
            raise ValueError(f"{name} is missing from the artifact")
        if resolved.stat().st_size > MAX_ARTIFACT_BYTES:
            raise ValueError(f"{name} is too large to import")
        paths.append(resolved)
    manifest = json.loads(paths[0].read_text(encoding="utf-8"))
    records = [
        json.loads(line)
        for line in paths[1].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return manifest, records


def prediction_import(payload: dict[str, Any]) -> dict[str, Any]:
    job_id = payload.get("batch_job_id")
    if isinstance(job_id, bool) or not isinstance(job_id, int):
        raise ValueError("prediction_import requires its batch_job_id")

    with SessionLocal.begin() as session:
        job = session.get(BatchJob, job_id)
        if job is None or job.kind != "prediction_import":
            raise ValueError("Prediction import job was not found")
        if job.payload != payload:
            raise ValueError("Job payload does not match the stored job")
        # The handler only receives the payload, so bind it to the job the
        # runner actually claimed: the bound job must be running, and no other
        # job (e.g. a copy posted through the generic /jobs API) may carry it.
        if job.status != "running":
            raise ValueError("Bound prediction import job is not running")
        copies = [
            other.id
            for other in session.query(BatchJob).filter(
                BatchJob.kind == "prediction_import",
                BatchJob.status.in_(("queued", "running", "cancel_requested")),
                BatchJob.id != job_id,
            )
            if (other.payload or {}).get("batch_job_id") == job_id
        ]
        if copies:
            raise ValueError("Payload is also claimed by another job; refused")
        creator = session.get(User, job.created_by) if job.created_by else None
        if creator is None or not ALLOWED_ROLES & {r.name for r in creator.roles}:
            raise ValueError("Job creator lacks an admin/analyst role")

        manifest, records = _read(_artifact_dir(payload.get("artifact_dir")))
        candidate = validate_prediction_import(manifest, records)
        run, created = persist_prediction_import(
            session,
            candidate,
            manifest,
            actor_id=creator.id,
            correlation_id=str(payload.get("correlation_id") or f"batch-job-{job_id}"),
            audit_details={"batch_job_id": job_id},
        )
        session.flush()
        return {
            "run_id": run.id,
            "already_imported": not created,
            "record_count": run.record_count,
            "review_status": run.review_status,
            "model_version": run.model_version,
            "producer_version": run.producer_version,
            "serving_ready": False,
        }
