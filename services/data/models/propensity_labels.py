"""PROPOSED development propensity targets (retail purchase 30d, renewal 60d).

Rules below are proposals awaiting Christ's approval; nothing here is a trained
model, experiment-ready, or reads ``ground_truth``. Booking has no source event
and is explicitly UNSUPPORTED_SOURCE. Renewal is not upgrade.
"""

import argparse
import csv
import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from services.data.customer360.profile import build_profiles, read
from services.data.features.snapshot import FIELDS as FEATURE_FIELDS
from services.data.features.snapshot import validate_cutoffs
from services.data.ingestion.validator import BatchValidator, sha256

RETAIL_VERSION = "moses-retail-purchase30-proposed-dev-1.0"
RENEWAL_VERSION = "moses-membership-renewal60-proposed-dev-1.0"
UNSUPPORTED_SOURCE = "UNSUPPORTED_SOURCE"
BOOKING_TARGET = "service_booking30"

# target name -> (version, horizon days)
TARGETS = {
    "retail_purchase30": (RETAIL_VERSION, 30),
    "renewal60": (RENEWAL_VERSION, 60),
}
QUALIFYING_STATUSES = {"COMPLETED", "PARTIAL_REFUND"}
RENEWAL_EXPIRY_LOOKBACK_DAYS = 30
PROPOSED_RULES = {
    "retail_purchase30": (
        "PROPOSED: positive = >=1 POS transaction (COMPLETED/PARTIAL_REFUND) with "
        ">=1 PRODUCT item in (cutoff, cutoff+30d]. Eligible = >=1 qualifying POS "
        "transaction in (cutoff-365d, cutoff]. Complete iff cutoff+30d <= "
        "observation_end."
    ),
    "renewal60": (
        "PROPOSED: positive = RENEWAL event in (cutoff, cutoff+60d]. Eligible = "
        "latest JOIN/RENEWAL at or before cutoff has expires_at in "
        "(cutoff-30d, cutoff+60d]. Complete iff cutoff+60d <= observation_end. "
        "Upgrade is not labelled."
    ),
    BOOKING_TARGET: UNSUPPORTED_SOURCE + ": no booking source event exists.",
}


def _target_fields(name: str) -> tuple[str, ...]:
    return (
        f"{name}_eligible",
        f"{name}_outcome_complete",
        f"{name}_outcome_end_at",
        name,
    )


FIELDS = (
    "golden_customer_id",
    "cutoff_at",
    "retail_label_version",
    "renewal_label_version",
    *_target_fields("retail_purchase30"),
    *_target_fields("renewal60"),
    "experiment_ready",
)
TRAINING_FIELDS = (
    *FEATURE_FIELDS,
    "target",
    "target_version",
    "horizon_days",
    "outcome_end_at",
    "eligible",
    "outcome_complete",
    "experiment_ready",
    "target_value",
)


def booking_status() -> dict:
    """Booking cannot be derived from SERVICE purchases or completed visits."""
    return dict(
        target=BOOKING_TARGET,
        status=UNSUPPORTED_SOURCE,
        rule=PROPOSED_RULES[BOOKING_TARGET],
    )


def build_propensity_labels(
    inbound: Path, resolution: Path, cutoffs: list[datetime]
) -> list[dict]:
    cutoffs = validate_cutoffs(cutoffs)
    manifest = json.loads(
        (inbound / "generation_manifest.json").read_text(encoding="utf-8")
    )
    observation_end = datetime.combine(
        date.fromisoformat(manifest["as_of_date"]),
        time.max,
        tzinfo=timezone(timedelta(hours=7)),
    )
    profiles = {c: build_profiles(inbound, resolution, c) for c in cutoffs}
    mapping = {
        r["source_customer_id"]: r["golden_customer_id"]
        for r in read(resolution / "mapping.csv")
    }
    product_ids = {
        r["source_transaction_id"]
        for r in read(inbound / "transaction_items.csv")
        if r["item_type"] == "PRODUCT"
    }
    # fingerprint -> [golden, time, has_product]; replays merge product evidence.
    pos: dict[tuple, list] = {}
    for row in read(inbound / "transactions.csv"):
        ref = row["source_customer_ref"]
        if not ref:
            continue
        if ref not in mapping:
            raise ValueError("Unknown transaction customer reference")
        if row["status"] not in QUALIFYING_STATUSES or row["source_system"] != "POS":
            continue
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
        entry = pos.setdefault(
            fingerprint,
            [mapping[ref], datetime.fromisoformat(row["transaction_datetime"]), False],
        )
        entry[2] = entry[2] or row["source_transaction_id"] in product_ids
    pos_by_golden: dict[str, list[tuple[datetime, bool]]] = {}
    for golden, moment, has_product in pos.values():
        pos_by_golden.setdefault(golden, []).append((moment, has_product))

    member_by_golden: dict[str, list[dict]] = {}
    for row in read(inbound / "membership_events.csv"):
        ref = row["source_customer_ref"]
        if not ref:
            continue
        if ref not in mapping:
            raise ValueError("Unknown customer reference in membership_events.csv")
        if row["event_type"] not in {"JOIN", "RENEWAL"}:
            continue
        member_by_golden.setdefault(mapping[ref], []).append(
            dict(
                type=row["event_type"],
                at=datetime.fromisoformat(row["occurred_at"]),
                expires=datetime.fromisoformat(row["expires_at"]),
            )
        )

    output = []
    for cutoff in cutoffs:
        retail_end = cutoff + timedelta(days=30)
        renewal_end = cutoff + timedelta(days=60)
        for profile in profiles[cutoff]:
            golden = profile["golden_customer_id"]
            history = pos_by_golden.get(golden, [])
            retail_eligible = any(
                cutoff - timedelta(days=365) < t <= cutoff for t, _ in history
            )
            retail_complete = retail_end <= observation_end
            retail_positive = any(
                cutoff < t <= retail_end and product for t, product in history
            )
            events = member_by_golden.get(golden, [])
            prior = [e for e in events if e["at"] <= cutoff]
            latest = max(prior, key=lambda e: (e["at"], e["expires"]), default=None)
            renewal_eligible = latest is not None and (
                cutoff - timedelta(days=RENEWAL_EXPIRY_LOOKBACK_DAYS)
                < latest["expires"]
                <= renewal_end
            )
            renewal_complete = renewal_end <= observation_end
            renewal_positive = any(
                e["type"] == "RENEWAL" and cutoff < e["at"] <= renewal_end
                for e in events
            )
            output.append(
                dict(
                    golden_customer_id=golden,
                    cutoff_at=cutoff.isoformat(),
                    retail_label_version=RETAIL_VERSION,
                    renewal_label_version=RENEWAL_VERSION,
                    retail_purchase30_eligible=retail_eligible,
                    retail_purchase30_outcome_complete=retail_complete,
                    retail_purchase30_outcome_end_at=retail_end.isoformat(),
                    retail_purchase30=(
                        int(retail_positive)
                        if retail_complete and retail_eligible
                        else None
                    ),
                    renewal60_eligible=renewal_eligible,
                    renewal60_outcome_complete=renewal_complete,
                    renewal60_outcome_end_at=renewal_end.isoformat(),
                    renewal60=(
                        int(renewal_positive)
                        if renewal_complete and renewal_eligible
                        else None
                    ),
                    experiment_ready=False,
                )
            )
    return output


def join_propensity_training_rows(
    features: list[dict], labels: list[dict], target: str
) -> list[dict]:
    """Join complete, eligible rows for one target; exact key match required."""
    if target == BOOKING_TARGET:
        raise ValueError(f"{BOOKING_TARGET} is {UNSUPPORTED_SOURCE}")
    if target not in TARGETS:
        raise ValueError(f"Unknown propensity target: {target!r}")
    version, horizon = TARGETS[target]

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
    rows = []
    for key in sorted(feature_index, key=lambda k: (k[1], k[0])):
        label = label_index[key]
        if (
            label[f"{target}_outcome_complete"] is True
            and label[f"{target}_eligible"] is True
        ):
            rows.append(
                {
                    **feature_index[key],
                    "target": target,
                    "target_version": version,
                    "horizon_days": horizon,
                    "outcome_end_at": label[f"{target}_outcome_end_at"],
                    "eligible": True,
                    "outcome_complete": True,
                    "experiment_ready": False,
                    "target_value": label[target],
                }
            )
    return rows


def _counts(labels: list[dict], target: str) -> dict:
    eligible = [r for r in labels if r[f"{target}_eligible"]]
    complete = [r for r in labels if r[f"{target}_outcome_complete"]]
    scored = [r for r in labels if r[target] is not None]
    return dict(
        total=len(labels),
        eligible=len(eligible),
        complete=len(complete),
        positives=sum(r[target] == 1 for r in scored),
        incomplete=len(labels) - len(complete),
        ineligible=len(labels) - len(eligible),
    )


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
    labels = build_propensity_labels(inbound, resolution, cutoffs)
    if any(sha256(p) != before[str(p.resolve())] for p in paths):
        raise ValueError("Inputs changed during propensity label run")
    output_dir.mkdir(parents=True)
    with (output_dir / "propensity_labels.csv").open(
        "x", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(labels)
    counts = {name: _counts(labels, name) for name in TARGETS}
    manifest = dict(
        target_versions={name: version for name, (version, _) in TARGETS.items()},
        horizon_days={name: days for name, (_, days) in TARGETS.items()},
        cutoffs=[c.isoformat() for c in cutoffs],
        training_ready=False,
        experiment_ready=False,
        final_model=False,
        development_only=True,
        booking=booking_status(),
        proposed_rules=PROPOSED_RULES,
        row_counts=counts,
        input_sha256=before,
        output_sha256={
            "propensity_labels.csv": sha256(output_dir / "propensity_labels.csv")
        },
    )
    (output_dir / "propensity_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return dict(label_rows=len(labels), row_counts=counts, experiment_ready=False)


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
