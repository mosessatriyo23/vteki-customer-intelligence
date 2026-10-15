"""Persistence adapter for RFM and lifecycle snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import RFMLifecycleSnapshot


def save_segmentation_snapshots(
    segments: list[dict[str, Any]],
    batch_id: str,
    registry_version: str,
    session: Session,
) -> int:
    """Persists RFM and Lifecycle snapshots into persistent storage.

    Enforces unique constraint:
    (golden_customer_id, cutoff_at, identity_registry_version, rule_version)
    """
    now = datetime.now(timezone.utc)
    persisted_count = 0

    for s in segments:
        cutoff_dt = datetime.fromisoformat(s["cutoff_at"])
        rule_version = s.get("rule_version", "lifecycle-proposed-1.0")

        stmt = select(RFMLifecycleSnapshot).where(
            RFMLifecycleSnapshot.golden_customer_id == s["golden_customer_id"],
            RFMLifecycleSnapshot.cutoff_at == cutoff_dt,
            RFMLifecycleSnapshot.identity_registry_version == registry_version,
            RFMLifecycleSnapshot.rule_version == rule_version,
        )
        existing = session.scalars(stmt).first()

        if existing:
            existing.generated_at = now
            existing.source_batch_id = batch_id
            existing.identity_status = s["identity_status"]
            existing.recency_days = s.get("recency_days")
            existing.frequency = int(s["frequency"])
            existing.monetary = int(s["monetary"])
            existing.rfm_window_days = int(s.get("rfm_window_days", 365))
            existing.r_score = int(s["r_score"])
            existing.f_score = int(s["f_score"])
            existing.m_score = int(s["m_score"])
            existing.rfm_code = str(s["rfm_code"])
            existing.tenure_days = int(s["tenure_days"])
            existing.transactions_60d = int(s["transactions_60d"])
            existing.transactions_90d = int(s["transactions_90d"])
            existing.revenue_90d = int(s["revenue_90d"])
            existing.lifecycle = str(s["lifecycle"])
        else:
            snapshot = RFMLifecycleSnapshot(
                golden_customer_id=s["golden_customer_id"],
                cutoff_at=cutoff_dt,
                generated_at=now,
                identity_registry_version=registry_version,
                rule_version=rule_version,
                source_batch_id=batch_id,
                identity_status=s["identity_status"],
                recency_days=s.get("recency_days"),
                frequency=int(s["frequency"]),
                monetary=int(s["monetary"]),
                rfm_window_days=int(s.get("rfm_window_days", 365)),
                r_score=int(s["r_score"]),
                f_score=int(s["f_score"]),
                m_score=int(s["m_score"]),
                rfm_code=str(s["rfm_code"]),
                tenure_days=int(s["tenure_days"]),
                transactions_60d=int(s["transactions_60d"]),
                transactions_90d=int(s["transactions_90d"]),
                revenue_90d=int(s["revenue_90d"]),
                lifecycle=str(s["lifecycle"]),
            )
            session.add(snapshot)
        persisted_count += 1

    session.commit()
    return persisted_count
