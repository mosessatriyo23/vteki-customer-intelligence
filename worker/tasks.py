from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import func

from api.audit import record_audit_event
from api.database import SessionLocal
from api.decision_inputs import load_contact_history, load_serving_score_row
from api.models import (
    AuditEvent,
    BatchJob,
    Campaign,
    CampaignContactHistory,
    CampaignMeasurement,
    Customer,
    User,
)
from services.decision.campaign.pipeline import AudienceMember, run_campaign
from services.decision.nba.serving import evaluate_customer


def audit_summary(_: dict[str, Any]) -> dict[str, Any]:
    with SessionLocal() as session:
        total = session.query(func.count(AuditEvent.id)).scalar() or 0
        failures = (
            session.query(func.count(AuditEvent.id))
            .filter(AuditEvent.status_code >= 400)
            .scalar()
            or 0
        )
    return {"total_requests": total, "failed_requests": failures}


def campaign_execution(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("channel_simulator") is not True:
        raise ValueError("Campaign execution must use the channel simulator")
    campaign_id = payload.get("campaign_id")
    job_id = payload.get("batch_job_id")
    if isinstance(campaign_id, bool) or not isinstance(campaign_id, int):
        raise ValueError("Campaign execution requires an integer campaign_id")
    if isinstance(job_id, bool) or not isinstance(job_id, int):
        raise ValueError("Campaign execution requires its batch_job_id")

    with SessionLocal.begin() as session:
        campaign = session.get(Campaign, campaign_id)
        job = session.get(BatchJob, job_id)
        if campaign is None or job is None:
            raise ValueError("Campaign or execution job was not found")
        if campaign.execution_job_id != job_id:
            raise ValueError("Execution job does not belong to this campaign")
        if campaign.status != "Active" or campaign.approved_by is None:
            raise ValueError(
                "Campaign requires recorded human approval before execution"
            )
        if campaign.approved_at is None:
            raise ValueError("Campaign approval timestamp is missing")
        approver = session.get(User, campaign.approved_by)
        if approver is None:
            raise ValueError("Campaign approver account was not found")
        target_segment = campaign.target_segment
        if not target_segment:
            raise ValueError("Campaign execution requires a target segment")

        customer_query = session.query(Customer).filter(
            Customer.segment == target_segment,
            Customer.is_demo.is_(False),
        )
        if campaign.target_customer_id is not None:
            customer_query = customer_query.filter(
                Customer.id == campaign.target_customer_id
            )
        customers = customer_query.order_by(Customer.id).all()
        correlation_id = str(
            payload.get("correlation_id")
            or campaign.correlation_id
            or f"campaign-job-{job_id}"
        )
        audience: list[AudienceMember] = []
        customer_by_ref: dict[str, Customer] = {}
        for customer in customers:
            customer_ref = customer.golden_customer_id or customer.customer_code
            customer_by_ref[customer_ref] = customer
            score_row = load_serving_score_row(session, customer_ref)
            decision = evaluate_customer(
                customer_ref=customer_ref,
                correlation_id=correlation_id,
                score_row=score_row,
                consent_doc=None,
                complaint_tickets=None,
                contact_history=load_contact_history(
                    session,
                    customer_db_id=customer.id,
                    customer_ref=customer_ref,
                ),
                eligibility=None,
                product_suitability=None,
                score_explanation=(
                    score_row.get("score_explanation")
                    if score_row is not None
                    else None
                ),
            )
            audience.append(
                AudienceMember(
                    customer_ref=customer_ref,
                    decision=decision,
                    # Unknown consent is explicit and never grants delivery.
                    consent_doc={
                        "customer_id": customer_ref,
                        "global_consent": {"status": "UNKNOWN"},
                        "channels": {},
                    },
                    fact_package={},
                )
            )

        result = run_campaign(
            campaign={
                "campaign_id": f"CMP-{campaign.id}",
                "channel": campaign.channel,
                "approved_by": approver.email,
                "random_seed": campaign.id,
                "conversion_window_days": 30,
            },
            audience=audience,
            correlation_id=correlation_id,
            outcomes=None,
        )
        job_result = result.to_job_result()
        job_result["target_mode"] = (
            "single_customer" if campaign.target_customer_id is not None else "segment"
        )
        job_result["target_customer_id"] = campaign.target_customer_id
        job_result["measurement"] = result.measurement

        for contact in result.contact_rows:
            customer = customer_by_ref.get(str(contact["customer_id"]))
            if customer is None:
                continue
            existing = (
                session.query(CampaignContactHistory)
                .filter(
                    CampaignContactHistory.execution_job_id == job_id,
                    CampaignContactHistory.customer_id == customer.id,
                )
                .first()
            )
            if existing is None:
                session.add(
                    CampaignContactHistory(
                        execution_job_id=job_id,
                        campaign_id=campaign.id,
                        customer_id=customer.id,
                        customer_ref=str(contact["customer_id"]),
                        action_id=str(contact["action_id"]),
                        channel=str(contact["channel"]),
                        sent_at=datetime.fromisoformat(str(contact["sent_at"])),
                        is_commercial=bool(contact["is_commercial"]),
                    )
                )

        measurement_rows = list(result.measurement_rows)
        if not measurement_rows:
            measurement_rows = [
                {
                    "metric_name": "campaign_outcomes",
                    "observed_value": None,
                    "incremental_value": None,
                }
            ]
        for row in measurement_rows:
            existing = (
                session.query(CampaignMeasurement)
                .filter(
                    CampaignMeasurement.execution_job_id == job_id,
                    CampaignMeasurement.metric_name == row["metric_name"],
                )
                .first()
            )
            if existing is None:
                session.add(
                    CampaignMeasurement(
                        campaign_id=campaign.id,
                        execution_job_id=job_id,
                        metric_name=row["metric_name"],
                        observed_value=row["observed_value"],
                        incremental_value=row["incremental_value"],
                        measurement_status=result.measurement_status,
                        source_mode="simulated",
                    )
                )
            else:
                existing.observed_value = row["observed_value"]
                existing.incremental_value = row["incremental_value"]
                existing.measurement_status = result.measurement_status
                existing.source_mode = "simulated"

        for event in result.audit_events():
            details = {**event["details"], "execution_job_id": job_id}
            record_audit_event(
                session,
                correlation_id=correlation_id,
                event_type=event["event_type"],
                actor_id=campaign.approved_by,
                entity_type=event["entity_type"],
                entity_id=event["entity_id"],
                details=details,
            )
        if result.measurement is None:
            record_audit_event(
                session,
                correlation_id=correlation_id,
                event_type="campaign.measurement_awaiting_outcomes",
                actor_id=campaign.approved_by,
                entity_type="campaign",
                entity_id=f"CMP-{campaign.id}",
                details={
                    "execution_job_id": job_id,
                    "measurement_status": result.measurement_status,
                    "source_mode": "simulated",
                },
            )

        return job_result


TASK_HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "audit_summary": audit_summary,
    "campaign_execution": campaign_execution,
}
