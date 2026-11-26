"""Database adapters for the pure NBA decision services."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from api.models import (
    CampaignContactHistory,
    ModelPredictionRecord,
    ModelPredictionRun,
)
from services.decision.policy.fatigue import ContactRecord

CHURN_PREDICTION_TYPE = "CHURN"


def _aware_instant(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def load_serving_score_row(db: Session, customer_ref: str) -> dict[str, Any] | None:
    """Return the latest stored prediction row for the exact customer identity.

    The service applies the independent-review and completeness gates. Missing
    score fields remain ``None`` so an incomplete Moses contract fails closed.
    """
    # cutoff_at is stored as text, so SQL cannot order it chronologically. Load
    # only this customer's CHURN history (small, indexed by customer_id) and
    # order by the parsed instant here.
    candidates = (
        db.query(ModelPredictionRecord, ModelPredictionRun)
        .join(ModelPredictionRun, ModelPredictionRun.id == ModelPredictionRecord.run_id)
        .filter(
            ModelPredictionRecord.customer_id == customer_ref,
            ModelPredictionRun.prediction_type == CHURN_PREDICTION_TYPE,
        )
        .all()
    )
    keyed: list[tuple[tuple[datetime, datetime, int], Any, Any]] = []
    for record, run in candidates:
        cutoff = _aware_instant(record.cutoff_at)
        if cutoff is None:
            # An unorderable row could be the newest one; never score around it.
            return None
        imported = run.imported_at
        if imported.tzinfo is None:
            imported = imported.replace(tzinfo=timezone.utc)
        keyed.append(((cutoff, imported, record.id), record, run))
    if not keyed:
        return None

    _, record, run = max(keyed, key=lambda item: item[0])
    # The newest record decides; an older clean run must not hide it. A
    # non-serving newest row is returned WITH its contract_status so the pure
    # service rejects it as "present, not approved" instead of "missing".
    source = record.source_record if isinstance(record.source_record, dict) else {}
    raw_reasons = record.reason_codes if isinstance(record.reason_codes, list) else []
    reason_codes = [
        item.get("code") if isinstance(item, dict) else item for item in raw_reasons
    ]
    return {
        "customer_id": record.customer_id,
        "churn_score": record.score,
        "churn_risk_band": record.band,
        "propensity_purchase": source.get("propensity_purchase"),
        "propensity_renew": source.get("propensity_renew"),
        "clv_amount": source.get("clv_amount"),
        "clv_tier": source.get("clv_tier"),
        "lifecycle_stage": source.get("lifecycle_stage"),
        # Christ's contract derives score age from the prediction cutoff, never
        # from import time (which could incorrectly renew an old score).
        "score_generated_at": record.cutoff_at,
        "reason_codes": reason_codes,
        "contract_status": record.contract_status,
        "model_version": run.model_version,
        "review_status": run.review_status,
        "reviewed_by": run.reviewed_by,
        "submitted_by": run.submitted_by,
        # The current import handoff is explicitly non-serving and has no separate
        # usage approval field. Missing approval must remain unknown/fail-closed.
        "usage_approved": None,
        "model_author": (
            run.manifest.get("model_author")
            if isinstance(run.manifest, dict)
            and isinstance(run.manifest.get("model_author"), int)
            and not isinstance(run.manifest.get("model_author"), bool)
            else None
        ),
        "score_explanation": source.get("score_explanation"),
    }


def load_contact_history(
    db: Session, *, customer_db_id: int, customer_ref: str
) -> list[ContactRecord]:
    """Load persisted campaign contacts for the exact application customer."""
    rows = (
        db.query(CampaignContactHistory)
        .filter(CampaignContactHistory.customer_id == customer_db_id)
        .order_by(CampaignContactHistory.sent_at.asc(), CampaignContactHistory.id.asc())
        .all()
    )
    return [
        ContactRecord(
            customer_id=customer_ref,
            action_id=row.action_id,
            channel=row.channel,
            sent_at=row.sent_at,
            is_commercial=row.is_commercial,
        )
        for row in rows
    ]
