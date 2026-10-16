"""Golden-customer descriptive EDA without PII or evaluation ground truth."""

from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from services.data.ingestion.contracts import TABLES
from services.data.ingestion.validator import BatchValidator, sha256
from services.data.segmentation.snapshot import RULE_VERSION, build_segments

REPORT_VERSION = "golden-eda-1.0"
OUTPUT_FILES = ("summary.json", "report.md")
RFM_METRICS = (
    "recency_days",
    "frequency",
    "monetary",
    "r_score",
    "f_score",
    "m_score",
)
LIFECYCLE_METRICS = (
    "tenure_days",
    "transactions_60d",
    "transactions_90d",
    "revenue_90d",
)


def _quantile(values: list[int], probability: float) -> int | float:
    """Return a deterministic linear quantile (the common type-7 definition)."""
    position = (len(values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    value = values[lower] + (values[upper] - values[lower]) * (position - lower)
    return int(value) if value.is_integer() else value


def distribution(values: Iterable[int | None]) -> dict:
    """Describe numeric values, excluding nulls while reporting their count."""
    materialized = list(values)
    observed = sorted(value for value in materialized if value is not None)
    result: dict[str, Any] = {
        "count": len(observed),
        "missing": len(materialized) - len(observed),
        "min": None,
        "max": None,
        "quantiles": {key: None for key in ("p25", "p50", "p75")},
    }
    if observed:
        result.update(
            {
                "min": observed[0],
                "max": observed[-1],
                "quantiles": {
                    "p25": _quantile(observed, 0.25),
                    "p50": _quantile(observed, 0.50),
                    "p75": _quantile(observed, 0.75),
                },
            }
        )
    return result


def summarize_segments(segments: list[dict], cutoff: datetime) -> dict:
    """Build aggregate-only Golden Customer statistics from recomputed segments."""
    identity_counts = Counter(row["identity_status"] for row in segments)
    lifecycle_counts = Counter(row["lifecycle"] for row in segments)
    by_status = []
    for status in sorted(identity_counts):
        rows = [row for row in segments if row["identity_status"] == status]
        by_status.append(
            {
                "identity_status": status,
                "customers": len(rows),
                "purchase_frequency": distribution(row["frequency"] for row in rows),
                "total_purchases": sum(row["frequency"] for row in rows),
                "retained_revenue_idr": distribution(row["monetary"] for row in rows),
                "total_retained_revenue_idr": sum(row["monetary"] for row in rows),
            }
        )
    return {
        "report_version": REPORT_VERSION,
        "cutoff_at": cutoff.isoformat(),
        "data_scope": "SYNTHETIC_DEVELOPMENT_GOLDEN_CUSTOMERS",
        "training_ready": False,
        "customer_count": len(segments),
        "rfm": {
            metric: distribution(row[metric] for row in segments)
            for metric in RFM_METRICS
        },
        "lifecycle": {
            "counts": dict(sorted(lifecycle_counts.items())),
            "numeric": {
                metric: distribution(row[metric] for row in segments)
                for metric in LIFECYCLE_METRICS
            },
            "rule_version": RULE_VERSION,
        },
        "identity_status": {
            "counts": dict(sorted(identity_counts.items())),
            "purchase_frequency_and_revenue": by_status,
        },
        "privacy": {
            "aggregate_only": True,
            "customer_identifiers_exported": False,
            "pii_exported": False,
        },
    }


def markdown(summary: dict) -> str:
    """Render the aggregate summary as a compact human-readable report."""
    lines = [
        "# Golden Customer descriptive EDA",
        "",
        f"Cutoff: {summary['cutoff_at']}",
        "",
        "Synthetic development data only. This is descriptive, aggregate, and not training-ready.",
        "No customer identifiers or PII are exported.",
        "",
        f"Golden Customers: {summary['customer_count']:,}",
        "",
        "## RFM distributions",
        "",
        "| Metric | Count | Missing | Min | P25 | P50 | P75 | Max |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for metric, stats in summary["rfm"].items():
        quantiles = stats["quantiles"]
        lines.append(
            f"| {metric} | {stats['count']} | {stats['missing']} | {stats['min']} | "
            f"{quantiles['p25']} | {quantiles['p50']} | {quantiles['p75']} | "
            f"{stats['max']} |"
        )
    lines += ["", "## Lifecycle counts", ""]
    lines += [
        f"- {name}: {count:,}" for name, count in summary["lifecycle"]["counts"].items()
    ]
    lines += ["", "## Identity status", ""]
    lines += [
        f"- {name}: {count:,}"
        for name, count in summary["identity_status"]["counts"].items()
    ]
    lines += [
        "",
        "| Status | Customers | Purchases | Retained revenue IDR | Frequency P50 | Revenue P50 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in summary["identity_status"]["purchase_frequency_and_revenue"]:
        lines.append(
            f"| {row['identity_status']} | {row['customers']} | "
            f"{row['total_purchases']} | {row['total_retained_revenue_idr']} | "
            f"{row['purchase_frequency']['quantiles']['p50']} | "
            f"{row['retained_revenue_idr']['quantiles']['p50']} |"
        )
    lines += [
        "",
        "## Limitations",
        "",
        "- Identity status is provisional resolver output, not verified identity truth.",
        "- RFM and lifecycle are recomputed from the validated source batch at the cutoff.",
        "- Current source and resolver snapshots do not establish point-in-time feature availability.",
        "- Revenue is integer IDR retained revenue under the segmentation status policy.",
        "- Quantiles use linear interpolation and exclude null recency values.",
        "",
    ]
    return "\n".join(lines)


SOURCE_FILES = (*sorted(TABLES), "generation_manifest.json")
RESOLVER_FILES = (
    "resolution_manifest.json",
    "mapping.csv",
    "decisions.csv",
    "review_queue.csv",
)


def _hash_known(root: Path, names: tuple[str, ...]) -> dict[str, str]:
    return {name: sha256(root / name) for name in names}


def _assert_safe_output(inbound: Path, resolution: Path, output_dir: Path) -> None:
    output = output_dir.resolve()
    for source in (inbound.resolve(), resolution.resolve()):
        if output == source or output in source.parents or source in output.parents:
            raise ValueError("Output directory must be separate from all inputs")
    if output_dir.exists():
        raise ValueError("Use a new output directory; reports must not be overwritten")


def run(inbound: Path, resolution: Path, cutoff: datetime, output_dir: Path) -> dict:
    """Validate inputs, recompute Golden segments, and publish an immutable report."""
    inbound = Path(inbound)
    resolution = Path(resolution)
    output_dir = Path(output_dir)
    _assert_safe_output(inbound, resolution, output_dir)

    source_before = _hash_known(inbound, SOURCE_FILES)
    resolver_before = _hash_known(resolution, RESOLVER_FILES)
    validation = BatchValidator().validate(inbound)
    if not validation.valid:
        raise ValueError(f"Inbound batch validation failed: {validation.errors}")

    segments = build_segments(inbound, resolution, cutoff)
    summary = summarize_segments(segments, cutoff)
    rendered = markdown(summary)
    source_after = _hash_known(inbound, SOURCE_FILES)
    resolver_after = _hash_known(resolution, RESOLVER_FILES)
    if source_after != source_before or resolver_after != resolver_before:
        raise ValueError("Source or resolver inputs changed during analysis")

    output_dir.mkdir(parents=True)
    try:
        (output_dir / "summary.json").write_text(
            json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        (output_dir / "report.md").write_text(rendered, encoding="utf-8")
        manifest = {
            "report_version": REPORT_VERSION,
            "cutoff_at": cutoff.isoformat(),
            "source_sha256_before": source_before,
            "source_sha256_after": source_after,
            "resolver_sha256_before": resolver_before,
            "resolver_sha256_after": resolver_after,
            "batch_validation": {
                "valid": validation.valid,
                "schema_version": validation.schema_version,
                "row_counts": validation.row_counts,
            },
            "output_sha256": {name: sha256(output_dir / name) for name in OUTPUT_FILES},
            "privacy": "aggregate_only_no_customer_ids_or_pii",
        }
        (output_dir / "eda_manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        for name in (*OUTPUT_FILES, "eda_manifest.json"):
            (output_dir / name).unlink(missing_ok=True)
        output_dir.rmdir()
        raise
    return summary


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--inbound", type=Path, required=True)
    parser.add_argument("--resolution", type=Path, required=True)
    parser.add_argument("--cutoff-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = run(args.inbound, args.resolution, args.cutoff_at, args.output_dir)
    print(
        json.dumps(
            {"customers": summary["customer_count"], "output_dir": str(args.output_dir)}
        )
    )


if __name__ == "__main__":
    main()
