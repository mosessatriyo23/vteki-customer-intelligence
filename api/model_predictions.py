import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.requests import Request

from api.audit import record_audit_event
from api.database import get_db
from api.models import (
    BatchJob,
    Customer,
    GoldenCustomer,
    ModelPredictionRecord,
    ModelPredictionRun,
    SourceIdentityMapping,
    User,
)
from api.security import require_roles
from api.validation import DBId
from services.data.models.prediction_review import (
    PredictionImport,
    validate_prediction_import,
)

# One plain directory name: alphanumeric runs joined by single . _ or -, so
# "..", separators and leading/trailing dots are impossible by schema alone.
ARTIFACT_DIR_PATTERN = r"^[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*$"


def artifact_dir_allowed(name: str) -> bool:
    """Worker-side check: schema-valid name and never a ground-truth folder."""
    return (
        len(name) <= 128
        and re.fullmatch(ARTIFACT_DIR_PATTERN, name) is not None
        and "ground_truth" not in name.lower()
    )


router = APIRouter(prefix="/model-predictions", tags=["Moses prediction review"])


class PredictionImportRequest(BaseModel):
    manifest: dict[str, Any]
    records: list[dict[str, Any]] = Field(min_length=1, max_length=100_000)


class PredictionReviewRequest(BaseModel):
    decision: Literal["reviewed", "rejected"]
    review_note: str = Field(min_length=5, max_length=2000, pattern=r"^[^\x00]*$")


def _run_response(run: ModelPredictionRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "model_version": run.model_version,
        "feature_set_version": run.feature_set_version,
        "label_version": run.label_version,
        "prediction_type": run.prediction_type,
        "producer_version": run.producer_version,
        "manifest_hash": run.manifest_hash,
        "record_count": run.record_count,
        "review_status": run.review_status,
        "submitted_by": run.submitted_by,
        "imported_at": run.imported_at,
        "reviewed_by": run.reviewed_by,
        "reviewed_at": run.reviewed_at,
        "review_note": run.review_note,
        "serving_ready": False,
        "manifest": run.manifest,
    }


@router.get("/runs")
def list_prediction_runs(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "analyst")),
) -> list[dict[str, Any]]:
    runs = (
        db.query(ModelPredictionRun)
        .order_by(ModelPredictionRun.imported_at.desc(), ModelPredictionRun.id.desc())
        .limit(100)
        .all()
    )
    return [_run_response(run) for run in runs]


@router.post(
    "/runs/import",
    status_code=status.HTTP_201_CREATED,
    responses={400: {"description": "Prediction artifact is invalid or unregistered"}},
)
def import_prediction_run(
    payload: PredictionImportRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin", "analyst")),
) -> dict[str, Any]:
    try:
        candidate = validate_prediction_import(payload.manifest, payload.records)
        run, created = persist_prediction_import(
            db,
            candidate,
            payload.manifest,
            actor_id=actor.id,
            correlation_id=request.state.correlation_id,
        )
    except (ValueError, TypeError, OverflowError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if not created:
        raise HTTPException(
            status_code=409,
            detail=f"This Moses manifest is already imported as run {run.id}",
        )
    db.commit()
    db.refresh(run)
    return _run_response(run)


def persist_prediction_import(
    db: Session,
    candidate: PredictionImport,
    manifest: dict[str, Any],
    *,
    actor_id: int,
    correlation_id: str,
    audit_details: dict[str, Any] | None = None,
) -> tuple[ModelPredictionRun, bool]:
    """Store a validated artifact as a pending-review run; caller commits.

    Shared by the HTTP import and the prediction_import worker job so both
    write the same rows and audit event. Returns (run, created); an already
    imported manifest returns the existing run with created=False.
    """
    existing = (
        db.query(ModelPredictionRun)
        .filter(ModelPredictionRun.manifest_hash == candidate.manifest_hash)
        .first()
    )
    if existing is not None:
        return existing, False

    golden_ids = {row["customer_id"] for row in candidate.records}
    known_golden_ids = {
        row[0]
        for row in db.query(GoldenCustomer.golden_customer_id)
        .filter(GoldenCustomer.golden_customer_id.in_(golden_ids))
        .all()
    }
    unknown_ids = sorted(golden_ids - known_golden_ids)
    if unknown_ids:
        raise ValueError(
            "Golden Customer IDs are not in the identity registry: "
            + ", ".join(unknown_ids[:5])
        )

    run = ModelPredictionRun(
        model_version=candidate.model_version,
        feature_set_version=candidate.feature_set_version,
        label_version=candidate.label_version,
        prediction_type=candidate.prediction_type,
        producer_version=candidate.producer_version,
        manifest_hash=candidate.manifest_hash,
        record_count=len(candidate.records),
        review_status="pending_review",
        manifest=manifest,
        submitted_by=actor_id,
    )
    db.add(run)
    db.flush()

    for row in candidate.records:
        fingerprint = hashlib.sha256(
            json.dumps(row, sort_keys=True, allow_nan=False).encode("utf-8")
        ).hexdigest()
        db.add(
            ModelPredictionRecord(
                run_id=run.id,
                customer_id=row["customer_id"],
                cutoff_at=row["cutoff_at"],
                prediction_date=row.get("prediction_date"),
                score=row.get("score"),
                band=row.get("band"),
                contract_status=row.get("contract_status", "unknown"),
                reason_codes=row["reason_codes"],
                record_fingerprint=fingerprint,
                source_record=row,
            )
        )

    record_audit_event(
        db,
        correlation_id=correlation_id,
        event_type="model.prediction_run.imported_for_review",
        actor_id=actor_id,
        entity_type="model_prediction_run",
        entity_id=run.id,
        details={
            "model_version": run.model_version,
            "record_count": run.record_count,
            "review_status": run.review_status,
            "serving_ready": False,
            **(audit_details or {}),
        },
    )
    return run, True


class PredictionImportJobRequest(BaseModel):
    # A single directory name under the operator-configured
    # PREDICTION_IMPORT_ROOT; never an arbitrary path.
    artifact_dir: str = Field(max_length=128, pattern=ARTIFACT_DIR_PATTERN)


@router.post("/runs/import-jobs", status_code=status.HTTP_202_ACCEPTED)
def enqueue_prediction_import(
    payload: PredictionImportJobRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin", "analyst")),
) -> dict[str, Any]:
    """Queue a worker import of a Moses artifact; still pending review, never serving.

    Unsafe names (ground truth, missing folders) are refused by the worker and
    recorded as a failed job, keeping this endpoint consistent with its schema.
    """
    job = BatchJob(
        kind="prediction_import",
        payload={"artifact_dir": payload.artifact_dir},
        max_attempts=1,
        created_by=actor.id,
    )
    db.add(job)
    db.flush()
    job.payload = {**job.payload, "batch_job_id": job.id}
    record_audit_event(
        db,
        correlation_id=request.state.correlation_id,
        event_type="model.prediction_import.queued",
        actor_id=actor.id,
        entity_type="batch_job",
        entity_id=job.id,
        details={"artifact_dir": payload.artifact_dir, "serving_ready": False},
    )
    db.commit()
    db.refresh(job)
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "payload": job.payload,
    }


@router.get("/runs/{run_id}/records")
def list_prediction_records(
    run_id: DBId,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "analyst")),
) -> dict[str, Any]:
    run = db.get(ModelPredictionRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Prediction review run not found")
    query = (
        db.query(ModelPredictionRecord)
        .filter(ModelPredictionRecord.run_id == run_id)
        .order_by(ModelPredictionRecord.id)
    )
    records = query.offset(offset).limit(limit).all()
    record_customer_ids = {record.customer_id for record in records}
    golden_status = (
        {
            row.golden_customer_id: row.status
            for row in db.query(GoldenCustomer)
            .filter(GoldenCustomer.golden_customer_id.in_(record_customer_ids))
            .all()
        }
        if record_customer_ids
        else {}
    )
    application_customers = (
        {
            customer.golden_customer_id: customer
            for customer in db.query(Customer)
            .filter(
                Customer.golden_customer_id.in_(record_customer_ids),
                Customer.is_demo.is_(False),
            )
            .all()
        }
        if record_customer_ids
        else {}
    )
    candidate_rows = (
        db.query(SourceIdentityMapping, Customer)
        .join(
            Customer, Customer.customer_code == SourceIdentityMapping.source_customer_id
        )
        .join(
            GoldenCustomer,
            GoldenCustomer.golden_customer_id
            == SourceIdentityMapping.golden_customer_id,
        )
        .filter(
            SourceIdentityMapping.golden_customer_id.in_(record_customer_ids),
            GoldenCustomer.status == "APPROVED",
            Customer.is_demo.is_(False),
            Customer.golden_customer_id.is_(None),
        )
        .all()
        if record_customer_ids
        else []
    )
    candidates_by_golden: dict[str, list[dict[str, Any]]] = {}
    for mapping, customer in candidate_rows:
        candidates_by_golden.setdefault(mapping.golden_customer_id, []).append(
            {
                "id": customer.id,
                "customer_code": customer.customer_code,
                "full_name": customer.full_name,
            }
        )
    mapping_candidates = {
        golden_id: candidates[0]
        for golden_id, candidates in candidates_by_golden.items()
        if len(candidates) == 1
    }
    return {
        "run_id": run_id,
        "review_status": run.review_status,
        "serving_ready": False,
        "total": run.record_count,
        "limit": limit,
        "offset": offset,
        "records": [
            {
                "id": record.id,
                "customer_id": record.customer_id,
                "cutoff_at": record.cutoff_at,
                "prediction_date": record.prediction_date,
                "score": record.score,
                "band": record.band,
                "contract_status": record.contract_status,
                "reason_codes": record.reason_codes,
                "source_record": record.source_record,
                "identity_status": golden_status.get(record.customer_id),
                "application_customer": (
                    {
                        "id": application_customers[record.customer_id].id,
                        "customer_code": application_customers[
                            record.customer_id
                        ].customer_code,
                        "full_name": application_customers[
                            record.customer_id
                        ].full_name,
                    }
                    if record.customer_id in application_customers
                    else None
                ),
                "mapping_candidate": (
                    mapping_candidates.get(record.customer_id)
                    if record.customer_id not in application_customers
                    else None
                ),
            }
            for record in records
        ],
    }


@router.post("/runs/{run_id}/review")
def review_prediction_run(
    run_id: DBId,
    payload: PredictionReviewRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin", "analyst")),
) -> dict[str, Any]:
    run = db.get(ModelPredictionRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Prediction review run not found")
    if run.review_status != "pending_review":
        raise HTTPException(
            status_code=409, detail="This run has already been reviewed"
        )
    if run.submitted_by == actor.id:
        raise HTTPException(
            status_code=409,
            detail="A different reviewer must inspect this run",
        )

    run.review_status = payload.decision
    run.reviewed_by = actor.id
    run.reviewed_at = datetime.now(timezone.utc)
    run.review_note = payload.review_note
    record_audit_event(
        db,
        correlation_id=request.state.correlation_id,
        event_type=f"model.prediction_run.{payload.decision}",
        actor_id=actor.id,
        entity_type="model_prediction_run",
        entity_id=run.id,
        details={
            "model_version": run.model_version,
            "submitted_by": run.submitted_by,
            "review_status": run.review_status,
            "serving_ready": False,
            "review_note": run.review_note,
        },
    )
    db.commit()
    db.refresh(run)
    return _run_response(run)
