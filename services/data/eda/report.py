"""Source-only descriptive EDA. No truth, customer PII or predictive claims."""

import csv
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

FINGERPRINT = (
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


def rows(path):
    with path.open(newline="", encoding="utf-8") as stream:
        yield from csv.DictReader(stream)


def summarize(inbound: Path, cutoff: datetime) -> dict:
    """Caller validates inbound. Missing references remain in business totals."""
    if cutoff.utcoffset() != timedelta(hours=7):
        raise ValueError("Cutoff must use +07:00 timezone")
    customers = list(rows(inbound / "crm_customers.csv"))
    eligible = {
        r["crm_customer_id"]
        for r in customers
        if r["join_date"] <= cutoff.date().isoformat()
    }
    missing = {
        field: sum(not r[field] for r in customers)
        for field in ("phone_raw", "email_raw", "member_code")
    }
    statuses: Counter[str] = Counter()
    seen: set[tuple[str, ...]] = set()
    purchases: Counter[str] = Counter()
    totals: Counter[str] = Counter()
    groups: dict[str, defaultdict[str, Counter[str]]] = {
        name: defaultdict(Counter) for name in ("month", "branch", "channel")
    }
    for row in rows(inbound / "transactions.csv"):
        moment = datetime.fromisoformat(row["transaction_datetime"])
        if moment > cutoff:
            continue
        totals["observed_transaction_rows"] += 1
        statuses[row["status"]] += 1
        fingerprint = tuple(row[key] for key in FINGERPRINT)
        if fingerprint in seen:
            totals["fingerprint_replays_removed"] += 1
            continue
        seen.add(fingerprint)
        totals["deduplicated_transaction_rows"] += 1
        ref = row["source_customer_ref"]
        if not ref:
            totals["missing_reference_rows"] += 1
        if row["status"] not in {"COMPLETED", "PARTIAL_REFUND"}:
            continue
        amount = int(row["actual_revenue"])
        totals["qualifying_purchases"] += 1
        totals["retained_revenue_idr"] += amount
        if not ref:
            totals["unattributed_qualifying_purchases"] += 1
            totals["unattributed_retained_revenue_idr"] += amount
        else:
            if ref not in eligible:
                raise ValueError("Unknown or not-yet-joined transaction customer")
            purchases[ref] += 1
        for name, value in (
            ("month", moment.astimezone(cutoff.tzinfo).strftime("%Y-%m")),
            ("branch", row["branch_code"]),
            ("channel", row["channel_code"]),
        ):
            groups[name][value]["purchases"] += 1
            groups[name][value]["retained_revenue_idr"] += amount
    # Explicit zeros keep the output contract stable on empty transaction tables.
    keys = (
        "observed_transaction_rows",
        "fingerprint_replays_removed",
        "deduplicated_transaction_rows",
        "missing_reference_rows",
        "qualifying_purchases",
        "retained_revenue_idr",
        "unattributed_qualifying_purchases",
        "unattributed_retained_revenue_idr",
    )
    return {
        "cutoff_at": cutoff.isoformat(),
        "data_scope": "SYNTHETIC_DEVELOPMENT_SOURCE_IDENTITIES",
        "training_ready": False,
        "crm_snapshot": {
            "source_records": len(customers),
            "missing_fields": missing,
            "time_policy": "current snapshot; not historical field availability",
        },
        "eligible_source_identities": len(eligible),
        "source_purchase_frequency": {
            "never": sum(purchases[s] == 0 for s in eligible),
            "once": sum(purchases[s] == 1 for s in eligible),
            "repeat": sum(purchases[s] >= 2 for s in eligible),
        },
        "totals": {key: totals[key] for key in keys},
        "raw_status_counts": dict(sorted(statuses.items())),
        "groups": {
            name: [{"key": key, **dict(value)} for key, value in sorted(data.items())]
            for name, data in groups.items()
        },
    }


def markdown(report: dict) -> str:
    lines = [
        "# Synthetic development EDA",
        "",
        f"Cutoff: {report['cutoff_at']}",
        "",
        "Not real-world business findings or training-ready data.",
        "",
        "## Transaction totals (integer IDR)",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    lines += [f"| {key} | {value:,} |" for key, value in report["totals"].items()]
    lines += [
        "",
        "## CRM source snapshot completeness",
        "",
        f"Source records: {report['crm_snapshot']['source_records']:,}",
        "",
        "| Missing field | Records |",
        "|---|---:|",
    ]
    lines += [
        f"| {field} | {count:,} |"
        for field, count in report["crm_snapshot"]["missing_fields"].items()
    ]
    lines += [
        "",
        "## Raw transaction status (before fingerprint dedup)",
        "",
        "| Status | Rows |",
        "|---|---:|",
    ]
    lines += [
        f"| {status} | {count:,} |"
        for status, count in report["raw_status_counts"].items()
    ]
    lines += [
        "",
        "## Source-identity purchase frequency",
        "",
        "Counts refer to CRM source records, NOT unique Golden Customers.",
        "",
    ]
    lines += [
        f"- {key}: {value:,}"
        for key, value in report["source_purchase_frequency"].items()
    ]
    for name, values in report["groups"].items():
        lines += [
            "",
            f"## By {name}",
            "",
            "| Key | Purchases | Retained revenue IDR |",
            "|---|---:|---:|",
        ]
        lines += [
            f"| {r['key']} | {r['purchases']:,} | {r['retained_revenue_idr']:,} |"
            for r in values
        ]
    lines += [
        "",
        "## Limitations",
        "",
        "- All findings describe synthetic data, not actual customer behavior.",
        "- Current source snapshot: event-time cutoff does not establish availability-time safety.",
        "- Refund/status history is unavailable; retained revenue uses current values.",
        "- Fingerprints can collapse genuinely identical purchases; not cross-source event resolution.",
        "- Missing references remain in business totals but not customer frequency.",
        "- Identity-resolution/RFM analysis is separate; no ground truth or customer PII is exported.",
        "",
    ]
    return "\n".join(lines)
