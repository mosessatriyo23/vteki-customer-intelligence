from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session
from starlette.requests import Request

from api.audit import record_audit_event
from api.database import get_db
from api.models import ModelPredictionRecord, ModelPredictionRun, User
from api.security import require_roles
from api.validation import DBId
from services.data.models.prediction_review import validate_prediction_import

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


@router.post("/runs/import", status_code=status.HTTP_201_CREATED)
def import_prediction_run(
    payload: PredictionImportRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin", "analyst")),
) -> dict[str, Any]:
    try:
        candidate = validate_prediction_import(payload.manifest, payload.records)
    except (ValueError, TypeError, OverflowError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    existing = (
        db.query(ModelPredictionRun)
        .filter(ModelPredictionRun.manifest_hash == candidate.manifest_hash)
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"This Moses manifest is already imported as run {existing.id}",
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
        manifest=payload.manifest,
        submitted_by=actor.id,
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
        correlation_id=request.state.correlation_id,
        event_type="model.prediction_run.imported_for_review",
        actor_id=actor.id,
        entity_type="model_prediction_run",
        entity_id=run.id,
        details={
            "model_version": run.model_version,
            "record_count": run.record_count,
            "review_status": run.review_status,
            "serving_ready": False,
        },
    )
    db.commit()
    db.refresh(run)
    return _run_response(run)


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
        raise HTTPException(status_code=409, detail="This run has already been reviewed")
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
