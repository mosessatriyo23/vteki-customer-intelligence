"""Atomic serving publish boundary for a validated source batch.

Source ingestion is a separate committed stage.  This transaction controls
Customer 360 and RFM serving snapshots together, never one without the other.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import sessionmaker

from api.models import IngestionBatch, RegistryVersion
from services.data.customer360.persistence import save_profile_snapshots
from services.data.segmentation.persistence import save_segmentation_snapshots


def _key(record: dict[str, Any]) -> tuple[str, datetime]:
    cutoff = record["cutoff_at"]
    value = datetime.fromisoformat(cutoff) if isinstance(cutoff, str) else cutoff
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("cutoff_at: timezone-aware timestamp required")
    return record["golden_customer_id"], value.astimezone(timezone.utc)


def publish_serving_snapshots(
    session_factory: sessionmaker,
    *,
    profiles: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    batch_id: str,
    registry_version: str,
    c360_rule_version: str = "c360-development-v1",
) -> dict[str, Any]:
    """Commit both snapshot tables or roll back both on any exception.

    Prevents publishing outputs of unrecognized source batches or registry
    versions. Matching Golden IDs/cutoff sets are required, and snapshots are
    still marked provisional unless separately approved by governance.
    """
    if not profiles or not segments:
        raise ValueError("Both profile and segmentation snapshots must be nonempty")
    profile_keys = {_key(p) for p in profiles}
    segment_keys = {_key(s) for s in segments}
    if (
        profile_keys != segment_keys
        or len(profile_keys) != len(profiles)
        or len(segment_keys) != len(segments)
    ):
        raise ValueError("Customer 360 and RFM Golden ID/cutoff sets must match")
    with session_factory.begin() as session:
        batch = session.get(IngestionBatch, batch_id)
        if batch is None or batch.status != "PUBLISHED":
            raise ValueError("Source batch must be PUBLISHED before serving publish")
        if session.get(RegistryVersion, registry_version) is None:
            raise ValueError("Unknown identity registry version")
        profile_count = save_profile_snapshots(
            profiles, batch_id, registry_version, session,
            rule_version=c360_rule_version, commit=False,
        )
        segment_count = save_segmentation_snapshots(
            segments, batch_id, registry_version, session, commit=False,
        )
    return {
        "status": "PUBLISHED",
        "source_batch_id": batch_id,
        "identity_registry_version": registry_version,
        "profile_count": profile_count,
        "segmentation_count": segment_count,
        "governance_status": "PROVISIONAL",
    }
