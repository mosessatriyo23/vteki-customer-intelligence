"""Development Customer360 aggregates. Identity mapping is a current snapshot.

Not a training feature pipeline: historical identity availability is not versioned.
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path


def read(path):
    with Path(path).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def build_profiles(inbound: Path, resolution: Path, cutoff: datetime) -> list[dict]:
    import json

    from services.data.ingestion.validator import sha256

    if cutoff.utcoffset() != timedelta(hours=7):
        raise ValueError("Cutoff must use +07:00 timezone")
    manifest = json.loads(
        (resolution / "resolution_manifest.json").read_text(encoding="utf-8")
    )
    if manifest["source_sha256"] != sha256(inbound / "crm_customers.csv"):
        raise ValueError("Resolution source checksum does not match CRM input")
    for name, expected in manifest["output_sha256"].items():
        if name not in {"mapping.csv", "decisions.csv", "review_queue.csv"}:
            raise ValueError("Unknown resolution output")
        if sha256(resolution / name) != expected:
            raise ValueError("Resolution checksum mismatch")
    if not {"mapping.csv", "decisions.csv", "review_queue.csv"} <= set(
        manifest["output_sha256"]
    ):
        raise ValueError("Resolution manifest incomplete")
    source_rows = read(inbound / "crm_customers.csv")
    sources = {r["crm_customer_id"]: r for r in source_rows}
    rows = read(resolution / "mapping.csv")
    mapping = {r["source_customer_id"]: r["golden_customer_id"] for r in rows}
    if len(mapping) != len(rows) or set(mapping) != set(sources):
        raise ValueError("Identity coverage must exactly match source snapshot")
    needs_review = set()
    for row in read(resolution / "review_queue.csv"):
        for field in ("left_source_id", "right_source_id"):
            needs_review.add(mapping[row[field]])
    profiles = {}
    for source, golden in mapping.items():
        if sources[source]["join_date"] > cutoff.date().isoformat():
            continue
        if golden not in profiles:
            profiles[golden] = dict(
                golden_customer_id=golden,
                cutoff_at=cutoff.isoformat(),
                identity_status=(
                    "REVIEW_REQUIRED" if golden in needs_review else "PROVISIONAL"
                ),
                source_identity_count=0,
                first_join_date=sources[source]["join_date"],
                transaction_count=0,
                retained_revenue=0,
                last_transaction_at="",
                visit_count=0,
                renewal_count=0,
            )
        profile = profiles[golden]
        profile["source_identity_count"] += 1
        profile["first_join_date"] = min(
            profile["first_join_date"], sources[source]["join_date"]
        )
    seen = set()
    for row in read(inbound / "transactions.csv"):
        ref = row["source_customer_ref"]
        if not ref:
            continue  # unassigned revenue is not attributed to invented customers
        if ref not in mapping:
            raise ValueError("Unknown transaction customer reference")
        moment = datetime.fromisoformat(row["transaction_datetime"])
        if moment > cutoff or row["status"] not in {"COMPLETED", "PARTIAL_REFUND"}:
            continue
        fingerprint = tuple(
            row[key]
            for key in (
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
        golden = mapping[ref]
        if golden not in profiles:
            raise ValueError("Transaction precedes customer join")
        profile = profiles[golden]
        profile["transaction_count"] += 1
        profile["retained_revenue"] += int(row["actual_revenue"])
        profile["last_transaction_at"] = max(
            profile["last_transaction_at"], row["transaction_datetime"]
        )
    for name, timestamp, metric in (
        ("customer_visits.csv", "visit_datetime", "visit_count"),
        ("membership_events.csv", "occurred_at", "renewal_count"),
    ):
        for row in read(inbound / name):
            if name == "membership_events.csv" and row["event_type"] != "RENEWAL":
                continue
            if name == "customer_visits.csv" and row["status"] != "COMPLETED":
                continue
            ref = row["source_customer_ref"]
            if ref not in mapping:
                raise ValueError("Unknown event customer reference")
            if datetime.fromisoformat(row[timestamp]) <= cutoff:
                golden = mapping[ref]
                if golden not in profiles:
                    raise ValueError("Event precedes customer join")
                profiles[golden][metric] += 1
    return [profiles[key] for key in sorted(profiles)]
