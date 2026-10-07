import csv
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import func

from api.database import SessionLocal
from api.models import AuditEvent, Customer


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


def fixture_rollup(_: dict[str, Any]) -> dict[str, Any]:
    fixture_dir = Path(__file__).resolve().parents[1] / "fixtures" / "intg_v1"
    row_counts: dict[str, int] = {}
    for path in sorted(fixture_dir.glob("*.csv")):
        with path.open("r", encoding="utf-8-sig", newline="") as fixture:
            row_counts[path.stem] = max(sum(1 for _ in csv.reader(fixture)) - 1, 0)
    return {"fixture": "intg_v1", "row_counts": row_counts}


def campaign_execution(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("channel_simulator") is not True:
        raise ValueError("Campaign execution must use the channel simulator")
    target_segment = payload.get("target_segment")
    if not isinstance(target_segment, str) or not target_segment:
        raise ValueError("Campaign execution requires a target segment")
    ratio = payload.get("ab_test_ratio", 50)
    if not isinstance(ratio, int) or not 0 <= ratio <= 100:
        raise ValueError("A/B test ratio must be between 0 and 100")
    with SessionLocal() as session:
        audience_size = (
            session.query(func.count(Customer.id))
            .filter(Customer.segment == target_segment)
            .scalar()
            or 0
        )
    variant_a = audience_size * ratio // 100
    return {
        "delivery_mode": "simulated",
        "external_delivery": False,
        "channel": payload.get("channel", "unknown"),
        "audience_size": audience_size,
        "variant_a_count": variant_a,
        "variant_b_count": audience_size - variant_a,
    }


TASK_HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "audit_summary": audit_summary,
    "campaign_execution": campaign_execution,
    "fixture_rollup": fixture_rollup,
}
