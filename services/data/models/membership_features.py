"""PROPOSED event-time membership features, not availability-time safe training data.

Only events observed by the cutoff contribute. Identity uses the current resolution
snapshot retrospectively, like other Moses features; historical identity availability
is NOT established. Emit every Golden customer, including no-history defaults.
"""

import argparse
import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

from services.data.customer360.profile import build_profiles, read
from services.data.features.snapshot import validate_cutoffs
from services.data.ingestion.validator import BatchValidator, sha256

MEMBERSHIP_FEATURE_VERSION = "moses-membership-features-proposed-dev-1.0"
TIERS = {tier: i for i, tier in enumerate(("BRONZE", "SILVER", "GOLD", "PLATINUM"))}
DEFAULTS = dict(
    has_membership_history=False,
    current_tier_ordinal=None,
    days_since_last_membership_event=None,
    days_to_expiry=None,
    membership_tenure_days=None,
    renewal_count_365d=0,
    tier_upgraded_last_event=False,
)
FIELDS = (
    "golden_customer_id",
    "cutoff_at",
    "feature_version",
    "training_ready",
    *DEFAULTS,
)


def build_membership_features(
    inbound: Path, resolution: Path, cutoffs: list[datetime]
) -> list[dict]:
    """Use earliest visible JOIN for Golden-level tenure, across resolved chains.

    Day differences use timedelta.days (floor, including negative expiry deltas).
    Equal event times break ties by expiry then event ID for deterministic results.
    """
    cutoffs = validate_cutoffs(cutoffs)
    mapping = {
        row["source_customer_id"]: row["golden_customer_id"]
        for row in read(resolution / "mapping.csv")
    }
    by_golden: dict[str, list[dict]] = {}
    for row in read(inbound / "membership_events.csv"):
        ref = row["source_customer_ref"]
        if ref not in mapping:
            raise ValueError("Unknown customer reference in membership_events.csv")
        if row["event_type"] not in {"JOIN", "RENEWAL"}:
            continue
        by_golden.setdefault(mapping[ref], []).append(
            dict(
                row,
                at=datetime.fromisoformat(row["occurred_at"]),
                expires=datetime.fromisoformat(row["expires_at"]),
            )
        )
    output = []
    for cutoff in cutoffs:
        for profile in build_profiles(inbound, resolution, cutoff):
            golden = profile["golden_customer_id"]
            prior = [e for e in by_golden.get(golden, []) if e["at"] <= cutoff]
            values = DEFAULTS.copy()
            if prior:
                latest = max(
                    prior, key=lambda e: (e["at"], e["expires"], e["event_id"])
                )
                joins = [e["at"] for e in prior if e["event_type"] == "JOIN"]
                previous = next(
                    (e for e in prior if e["event_id"] == latest["previous_event_id"]),
                    None,
                )
                values.update(
                    has_membership_history=True,
                    current_tier_ordinal=TIERS[latest["membership_tier"]],
                    days_since_last_membership_event=(cutoff - latest["at"]).days,
                    days_to_expiry=(latest["expires"] - cutoff).days,
                    membership_tenure_days=(
                        (cutoff - min(joins)).days if joins else None
                    ),
                    renewal_count_365d=sum(
                        e["event_type"] == "RENEWAL"
                        and cutoff - timedelta(days=365) < e["at"]
                        for e in prior
                    ),
                    tier_upgraded_last_event=(
                        latest["event_type"] == "RENEWAL"
                        and previous is not None
                        and TIERS[latest["membership_tier"]]
                        > TIERS[previous["membership_tier"]]
                    ),
                )
            output.append(
                dict(
                    golden_customer_id=golden,
                    cutoff_at=cutoff.isoformat(),
                    feature_version=MEMBERSHIP_FEATURE_VERSION,
                    training_ready=False,
                    **values,
                )
            )
    return output


def join_membership_features(
    propensity_features: list[dict], membership_rows: list[dict]
) -> list[dict]:
    """Left join dense or sparse membership rows without replacing POS versioning."""

    def index(rows):
        result = {}
        for row in rows:
            key = (row["golden_customer_id"], row["cutoff_at"])
            if key in result:
                raise ValueError("Duplicate customer/cutoff key")
            result[key] = row
        return result

    features, members = index(propensity_features), index(membership_rows)
    if not members.keys() <= features.keys():
        raise ValueError("Membership keys must be a subset of propensity feature keys")
    return [
        dict(
            row,
            **{name: members.get(key, DEFAULTS)[name] for name in DEFAULTS},
            membership_feature_version=MEMBERSHIP_FEATURE_VERSION,
            training_ready=False,
        )
        for key, row in features.items()
    ]


def run(
    inbound: Path, resolution: Path, output_dir: Path, cutoffs: list[datetime]
) -> dict:
    cutoffs = validate_cutoffs(cutoffs)
    for path in (inbound, resolution, output_dir):
        if any(part.lower() == "ground_truth" for part in path.resolve().parts):
            raise ValueError("ground_truth paths are not allowed")
    for path in (inbound, resolution):
        if not path.is_dir():
            raise ValueError(f"Input directory does not exist: {path}")
    if output_dir.exists():
        raise ValueError(
            "Use a new output directory; existing runs cannot be overwritten"
        )
    out = output_dir.resolve()
    for source in (inbound.resolve(), resolution.resolve()):
        if out == source or out in source.parents or source in out.parents:
            raise ValueError("Output directory must be separate from inputs")
    paths = [
        *(
            inbound / name
            for name in (
                "generation_manifest.json",
                "crm_customers.csv",
                "transactions.csv",
                "transaction_items.csv",
                "membership_events.csv",
            )
        ),
        *(
            resolution / name
            for name in (
                "mapping.csv",
                "decisions.csv",
                "review_queue.csv",
                "resolution_manifest.json",
            )
        ),
    ]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        raise ValueError("Missing input files: " + ", ".join(missing))
    before = {str(p.resolve()): sha256(p) for p in paths}
    report = BatchValidator().validate(inbound)
    if not report.valid:
        raise ValueError(
            "Inbound validation failed: " + json.dumps(report.errors, sort_keys=True)
        )
    rows = build_membership_features(inbound, resolution, cutoffs)
    if any(sha256(p) != before[str(p.resolve())] for p in paths):
        raise ValueError("Inputs changed during membership feature run")
    output_dir.mkdir(parents=True)
    csv_path = output_dir / "membership_features.csv"
    with csv_path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    manifest = dict(
        feature_version=MEMBERSHIP_FEATURE_VERSION,
        training_ready=False,
        development_only=True,
        identity_time_policy="CURRENT_SNAPSHOT_RETROSPECTIVE",
        cutoffs=[c.isoformat() for c in cutoffs],
        row_count=len(rows),
        coverage=(
            sum(r["has_membership_history"] for r in rows) / len(rows) if rows else 0.0
        ),
        input_sha256=before,
        output_sha256={csv_path.name: sha256(csv_path)},
    )
    (output_dir / "membership_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return dict(rows=len(rows), training_ready=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inbound", type=Path, required=True)
    parser.add_argument("--resolution", type=Path, required=True)
    parser.add_argument(
        "--cutoff-at", type=datetime.fromisoformat, action="append", required=True
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(run(args.inbound, args.resolution, args.output_dir, args.cutoff_at))
    )


if __name__ == "__main__":
    main()
