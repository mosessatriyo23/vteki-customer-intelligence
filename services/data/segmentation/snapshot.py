"""Development RFM/lifecycle snapshots; not identity point-in-time training features."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from services.data.customer360.profile import build_profiles, read

RULE_VERSION = 'lifecycle-proposed-1.0'
FIELDS = ('golden_customer_id', 'cutoff_at', 'identity_status', 'recency_days',
          'frequency', 'monetary', 'rfm_window_days', 'r_score', 'f_score', 'm_score',
          'rfm_code', 'tenure_days', 'transactions_60d', 'transactions_90d',
          'revenue_90d', 'lifecycle', 'rule_version')


def score(value: int, boundaries: tuple[int, ...], reverse: bool = False) -> int:
    result = 1 + sum(value >= boundary for boundary in boundaries)
    return 6 - result if reverse else result


def lifecycle(tenure: int, recency: int | None, count60: int, count90: int,
              revenue90: int, reactivated: bool) -> str:
    """Mutually exclusive PROPOSED priority, with explicit never-transacted fallback."""
    if reactivated:
        return 'REACTIVATED'
    if tenure >= 60 and count90 >= 5 and revenue90 >= 500_000:
        return 'LOYAL'
    if tenure <= 30:
        return 'NEW'
    if recency is None:
        return 'NEVER_TRANSACTED'
    if recency > 365:
        return 'CHURNED'
    if recency > 180:
        return 'DORMANT'
    if recency > 90:
        return 'AT_RISK'
    if count60 >= 3:
        return 'ACTIVE'
    return 'OCCASIONAL'


def build_segments(inbound: Path, resolution: Path, cutoff: datetime,
                   window_days: int = 365) -> list[dict]:
    if window_days < 90:
        raise ValueError('RFM window must be >=90 days')
    profiles = build_profiles(inbound, resolution, cutoff)  # coverage/hash validation
    mapping = {r['source_customer_id']: r['golden_customer_id'] for r in read(resolution / 'mapping.csv')}
    events: dict[str, list[tuple[datetime, int]]] = {p['golden_customer_id']: [] for p in profiles}
    seen = set()
    for row in read(inbound / 'transactions.csv'):
        ref = row['source_customer_ref']
        moment = datetime.fromisoformat(row['transaction_datetime'])
        if not ref or moment > cutoff or row['status'] not in {'COMPLETED', 'PARTIAL_REFUND'}:
            continue
        fingerprint = tuple(row[key] for key in (
            'source_customer_ref', 'source_system', 'branch_code', 'channel_code',
            'transaction_datetime', 'gross_amount', 'discount_amount', 'net_amount', 'status'))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        events[mapping[ref]].append((moment, int(row['actual_revenue'])))
    output = []
    for profile in profiles:
        history = sorted(events[profile['golden_customer_id']])
        tenure = (cutoff.date() - datetime.fromisoformat(profile['first_join_date']).date()).days
        recency = (cutoff.date() - history[-1][0].date()).days if history else None
        in_window = [(t, amount) for t, amount in history if cutoff - timedelta(days=window_days) < t <= cutoff]
        recent60 = [(t, amount) for t, amount in history if cutoff - timedelta(days=60) < t <= cutoff]
        recent90 = [(t, amount) for t, amount in history if cutoff - timedelta(days=90) < t <= cutoff]
        # Purchase within last 30 days after >180 days without a qualifying purchase.
        # First-ever purchases are not reactivation; visits/renewals are not substituted.
        reactivated = any(
            cutoff - timedelta(days=30) < history[i][0] <= cutoff
            and history[i][0] - history[i-1][0] > timedelta(days=180)
            for i in range(1, len(history)))
        frequency = len(in_window)
        monetary = sum(amount for _, amount in in_window)
        r = score(recency, (31, 61, 91, 181), reverse=True) if recency is not None else 1
        f = score(frequency, (1, 3, 6, 12))
        m = score(monetary, (1, 500_000, 2_000_000, 5_000_000))
        revenue90 = sum(amount for _, amount in recent90)
        output.append(dict(golden_customer_id=profile['golden_customer_id'], cutoff_at=cutoff.isoformat(),
                           identity_status=profile['identity_status'], recency_days=recency,
                           frequency=frequency, monetary=monetary, rfm_window_days=window_days,
                           r_score=r, f_score=f, m_score=m, rfm_code=f'{r}{f}{m}', tenure_days=tenure,
                           transactions_60d=len(recent60), transactions_90d=len(recent90),
                           revenue_90d=revenue90,
                           lifecycle=lifecycle(tenure, recency, len(recent60), len(recent90), revenue90, reactivated),
                           rule_version=RULE_VERSION))
    return output
