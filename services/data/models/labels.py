"""PROPOSED future outcomes, separate from retrospective development features."""

import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from services.data.customer360.profile import build_profiles, read
from services.data.features.snapshot import FIELDS as FEATURE_FIELDS
from services.data.features.snapshot import validate_cutoffs

VERSION = "future-outcomes-proposed-dev-1.0"
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
    inbound: Path, resolution: Path, cutoffs: list[datetime], horizon_days: int = 90
) -> list[dict]:
    """Windows are (cutoff-365d, cutoff] and (cutoff, cutoff+horizon].

    churn90/clv90 are nominal target names; horizon_days is always published.
    Incomplete targets are null, never observed partial-window negatives.
    """
    cutoffs = validate_cutoffs(cutoffs)
    if (
        isinstance(horizon_days, bool)
        or not isinstance(horizon_days, int)
        or horizon_days < 1
    ):
        raise ValueError("horizon_days must be a positive integer")
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
        events.setdefault(mapping[ref], []).append(
            (
                datetime.fromisoformat(row["transaction_datetime"]),
                int(row["actual_revenue"]),
            )
        )
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
            output.append(
                dict(
                    golden_customer_id=golden,
                    cutoff_at=cutoff.isoformat(),
                    label_version=VERSION,
                    horizon_days=horizon_days,
                    outcome_end_at=end.isoformat(),
                    outcome_complete=complete,
                    eligible=eligible,
                    churn90=int(not future) if complete and eligible else None,
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
