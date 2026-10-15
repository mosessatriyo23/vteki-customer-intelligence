"""Event-time historical features; explicitly NOT availability-time safe training data."""
from datetime import datetime, timedelta
from pathlib import Path

from services.data.segmentation.snapshot import build_segments

VERSION = 'event-time-dev-1.0'
FIELDS = ('golden_customer_id', 'cutoff_at', 'identity_status', 'feature_version',
          'training_ready', 'identity_time_policy', 'recency_days', 'tenure_days',
          'purchase_count_365d', 'retained_revenue_365d', 'purchase_count_60d',
          'purchase_count_90d', 'retained_revenue_90d')


def validate_cutoffs(cutoffs: list[datetime]) -> list[datetime]:
    if not cutoffs:
        raise ValueError('At least one cutoff is required')
    if any(c.utcoffset() != timedelta(hours=7) for c in cutoffs):
        raise ValueError('Cutoffs must use +07:00 timezone')
    if len(set(cutoffs)) != len(cutoffs):
        raise ValueError('Duplicate cutoffs are not allowed')
    return sorted(cutoffs)


def build_features(inbound: Path, resolution: Path, cutoffs: list[datetime]) -> list[dict]:
    rows = []
    for cutoff in validate_cutoffs(cutoffs):
        for segment in build_segments(inbound, resolution, cutoff, window_days=365):
            rows.append(dict(
                golden_customer_id=segment['golden_customer_id'], cutoff_at=cutoff.isoformat(),
                identity_status=segment['identity_status'], feature_version=VERSION,
                training_ready=False, identity_time_policy='CURRENT_SNAPSHOT_RETROSPECTIVE',
                recency_days=segment['recency_days'], tenure_days=segment['tenure_days'],
                purchase_count_365d=segment['frequency'], retained_revenue_365d=segment['monetary'],
                purchase_count_60d=segment['transactions_60d'],
                purchase_count_90d=segment['transactions_90d'],
                retained_revenue_90d=segment['revenue_90d']))
    return rows
