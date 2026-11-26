"""Database adapters for the pure NBA decision services."""

from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import and_
from sqlalchemy.orm import Session

from api.models import (
    CampaignContactHistory,
    Customer,
    GoldenCustomer,
    ModelPredictionRecord,
    ModelPredictionRun,
    SourceIdentityMapping,
)
from services.decision.policy.fatigue import ContactRecord

CHURN_PREDICTION_TYPE = "CHURN"


def load_approved_customer_golden_refs(
    db: Session, customers: Iterable[Customer]
) -> dict[int, str]:
    """Return only exact, currently approved app-customer to Golden ID mappings.

    Customer.customer_code is used solely to verify the exact source identity
    mapping; it is never returned as a score lookup key.
    """
    customer_rows = list(customers)
    if not customer_rows:
        return {}

    customer_ids = [customer.id for customer in customer_rows]
    rows = (
        db.query(Customer.id, Customer.golden_customer_id)
        .join(
            GoldenCustomer,
            GoldenCustomer.golden_customer_id == Customer.golden_customer_id,
        )
        .join(
            SourceIdentityMapping,
            and_(
                SourceIdentityMapping.source_customer_id == Customer.customer_code,
                SourceIdentityMapping.golden_customer_id == Customer.golden_customer_id,
            ),
        )
        .filter(
            Customer.id.in_(customer_ids),
            Customer.is_demo.is_(False),
            GoldenCustomer.status == "APPROVED",
        )
        .all()
    )
    return {int(customer_id): str(golden_id) for customer_id, golden_id in rows}


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
        # Explicit admin decision, separate from review. Imports default to NULL;
        # author identity comes from the trusted decision, never the manifest.
        "usage_approved": run.usage_approved,
        "usage_decided_by": run.usage_decided_by,
        "usage_decided_at": run.usage_decided_at,
        "model_author": run.model_author,
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
