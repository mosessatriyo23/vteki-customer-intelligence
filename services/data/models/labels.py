"""PROPOSED future outcomes, separate from retrospective development features."""

import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from services.data.customer360.profile import build_profiles, read
from services.data.features.snapshot import FIELDS as FEATURE_FIELDS
from services.data.features.snapshot import validate_cutoffs

VERSION = "future-outcomes-proposed-dev-1.0"
CHRIST_VERSION = "christ-churn90-three-events-dev-1.1"
FIELDS = (
    "golden_customer_id",
    "cutoff_at",
    "label_version",
    "horizon_days",
    "outcome_end_at",
    "outcome_complete",
    "eligible",
    "churn90",
    "clv90",
    "experiment_ready",
)
TRAINING_FIELDS = (*FEATURE_FIELDS, *(f for f in FIELDS if f not in FEATURE_FIELDS))


def build_labels(
    inbound: Path,
    resolution: Path,
    cutoffs: list[datetime],
    horizon_days: int = 90,
    *,
    christ_events: bool = False,
) -> list[dict]:
    """Build separate legacy-proxy or Christ-event development labels.

    Windows are (cutoff-365d, cutoff] and (cutoff, cutoff+horizon]. When
    christ_events is true, churn is negated by qualifying POS transactions,
    completed physical visits, and membership renewals. CLV remains clv90.
    Incomplete targets are null, never observed partial-window negatives.
    """
    cutoffs = validate_cutoffs(cutoffs)
    if (
        isinstance(horizon_days, bool)
        or not isinstance(horizon_days, int)
        or horizon_days < 1
    ):
        raise ValueError("horizon_days must be a positive integer")
    if christ_events and horizon_days != 90:
        raise ValueError("Christ churn contract requires horizon_days=90")
    manifest = json.loads(
        (inbound / "generation_manifest.json").read_text(encoding="utf-8")
    )
    observation_end = datetime.combine(
        date.fromisoformat(manifest["as_of_date"]),
        time.max,
        tzinfo=timezone(timedelta(hours=7)),
    )
    # Validate resolver checksums and exact source coverage even for label-only use.
    profiles = {c: build_profiles(inbound, resolution, c) for c in cutoffs}
    mapping = {
        r["source_customer_id"]: r["golden_customer_id"]
        for r in read(resolution / "mapping.csv")
    }
    events: dict[str, list[tuple[datetime, int]]] = {}
    activity_events: dict[str, list[datetime]] = {}
    seen = set()
    for row in read(inbound / "transactions.csv"):
        ref = row["source_customer_ref"]
        if not ref:
            continue
        if ref not in mapping:
            raise ValueError("Unknown transaction customer reference")
        if row["status"] not in {"COMPLETED", "PARTIAL_REFUND"}:
            continue
        # Same conservative source-only replay policy as feature snapshots.
        fingerprint = tuple(
            row[k]
            for k in (
                "source_customer_ref",
                "source_system",
                "branch_code",
                "channel_code",
                "transaction_datetime",
                "gross_amount",
                "discount_amount",
                "net_amount",
                "status",
            )
        )
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        occurred_at = datetime.fromisoformat(row["transaction_datetime"])
        events.setdefault(mapping[ref], []).append(
            (occurred_at, int(row["actual_revenue"]))
        )
        activity_events.setdefault(mapping[ref], []).append(occurred_at)

    if christ_events:
        for filename, timestamp_field, accepted in (
            ("customer_visits.csv", "visit_datetime", {"COMPLETED"}),
            ("membership_events.csv", "occurred_at", {"RENEWAL"}),
        ):
            for row in read(inbound / filename):
                ref = row["source_customer_ref"]
                if not ref:
                    continue
                if ref not in mapping:
                    raise ValueError(f"Unknown customer reference in {filename}")
                kind = row[
                    "status" if filename == "customer_visits.csv" else "event_type"
                ]
                if kind not in accepted:
                    continue
                occurred_at = datetime.fromisoformat(row[timestamp_field])
                activity_events.setdefault(mapping[ref], []).append(occurred_at)
    else:
        activity_events = {
            customer: [moment for moment, _ in customer_events]
            for customer, customer_events in events.items()
        }
    output = []
    for cutoff in cutoffs:
        end = cutoff + timedelta(days=horizon_days)
        complete = end <= observation_end
        for profile in profiles[cutoff]:
            golden = profile["golden_customer_id"]
            history = events.get(golden, [])
            eligible = any(
                cutoff - timedelta(days=365) < t <= cutoff for t, _ in history
            )
            future = [amount for t, amount in history if cutoff < t <= end]
            future_activity = any(
                cutoff < t <= end for t in activity_events.get(golden, [])
            )
            output.append(
                dict(
                    golden_customer_id=golden,
                    cutoff_at=cutoff.isoformat(),
                    label_version=(CHRIST_VERSION if christ_events else VERSION),
                    horizon_days=horizon_days,
                    outcome_end_at=end.isoformat(),
                    outcome_complete=complete,
                    eligible=eligible,
                    churn90=int(not future_activity) if complete and eligible else None,
                    clv90=sum(future) if complete else None,
                    experiment_ready=False,
                )
            )
    return output


def join_training_rows(features: list[dict], labels: list[dict]) -> list[dict]:
    """Join complete, eligible outcomes only; never mutate the feature records."""

    def index(rows):
        result = {}
        for row in rows:
            key = (row["golden_customer_id"], row["cutoff_at"])
            if key in result:
                raise ValueError("Duplicate customer/cutoff key")
            result[key] = row
        return result

    feature_index, label_index = index(features), index(labels)
    if feature_index.keys() != label_index.keys():
        raise ValueError("Feature/label keys must exactly match")
    return [
        {**feature_index[key], **label_index[key]}
        for key in sorted(feature_index, key=lambda k: (k[1], k[0]))
        if label_index[key]["outcome_complete"] is True
        and label_index[key]["eligible"] is True
    ]
