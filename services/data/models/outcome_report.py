"""Deterministic, development-only aggregates of outcome labels."""

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

LIFECYCLE_STATUSES = {
    "NEW",
    "ACTIVE",
    "LOYAL",
    "AT_RISK",
    "DORMANT",
    "CHURNED",
    "REACTIVATED",
    "OCCASIONAL",
    "NEVER_TRANSACTED",
    "UNCLASSIFIED",
}


def _strict_bool(value: object, field: str) -> bool:
    if type(value) is bool:
        return value
    if value in ("True", "true", "1", 1):
        return True
    if value in ("False", "false", "0", 0):
        return False
    raise ValueError(f"{field} must be a strict boolean")


def _keys(rows: list[dict], name: str) -> set[tuple[str, str]]:
    keys = []
    for row in rows:
        if not row.get("golden_customer_id") or not row.get("cutoff_at"):
            raise ValueError(f"{name} requires golden_customer_id and cutoff_at")
        keys.append((row["golden_customer_id"], row["cutoff_at"]))
    if len(keys) != len(set(keys)):
        raise ValueError(f"Duplicate {name} golden_customer_id/cutoff key")
    return set(keys)


def summarize_outcomes(labels: list[dict], segments: list[dict]) -> dict[str, object]:
    """Validate paired label/segment snapshots and summarize without identifiers."""
    label_keys = _keys(labels, "labels")
    segment_keys = _keys(segments, "segments")
    if label_keys != segment_keys:
        raise ValueError("Labels and segments keys must match exactly")
    segment_by_key = {
        (row["golden_customer_id"], row["cutoff_at"]): row for row in segments
    }
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    lifecycle: dict[str, Counter[str]] = defaultdict(Counter)
    for row in labels:
        key = (row["golden_customer_id"], row["cutoff_at"])
        complete = row.get("outcome_complete")
        eligible = row.get("eligible")
        if type(complete) is not bool or type(eligible) is not bool:
            raise ValueError("outcome_complete and eligible must be strict booleans")
        churn = row.get("churn90")
        if churn is not None and (type(churn) is not int or churn not in (0, 1)):
            raise ValueError("churn must be 0, 1, or null")
        if (not complete or not eligible) and churn is not None:
            raise ValueError("incomplete or ineligible outcomes must have null churn")
        if complete and eligible and churn is None:
            raise ValueError("complete eligible outcomes require a churn label")
        counts[row["cutoff_at"]]["complete" if complete else "incomplete"] += 1
        counts[row["cutoff_at"]]["eligible" if eligible else "ineligible"] += 1
        counts[row["cutoff_at"]][f"churn_{churn if churn is not None else 'null'}"] += 1
        segment = segment_by_key[key]
        status = (
            segment.get("lifecycle")
            or segment.get("lifecycle_status")
            or "UNCLASSIFIED"
        )
        if status not in LIFECYCLE_STATUSES:
            raise ValueError(f"Unknown lifecycle status: {status}")
        lifecycle[row["cutoff_at"]][status] += 1
    return {
        "report_version": "outcome-diagnostics-dev-1.0",
        "development_only": True,
        "training_ready": False,
        "experiment_ready": False,
        "final_model": False,
        "limitations": [
            "current identity snapshot availability unproven",
            "business review pending",
        ],
        "outcomes_by_cutoff": {
            cutoff: dict(sorted(counts[cutoff].items())) for cutoff in sorted(counts)
        },
        "lifecycle_by_cutoff": {
            cutoff: dict(sorted(lifecycle[cutoff].items()))
            for cutoff in sorted(lifecycle)
        },
    }


def _read_csv(path: Path, *, labels: bool = False) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        if labels:
            row["outcome_complete"] = _strict_bool(
                row.get("outcome_complete"), "outcome_complete"
            )
            row["eligible"] = _strict_bool(row.get("eligible"), "eligible")
            value = row.get("churn90")
            if value == "":
                row["churn90"] = None
            elif value in {"0", "1"}:
                row["churn90"] = int(value)
            else:
                raise ValueError("churn must be 0, 1, or null")
    return rows


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(labels_path: Path, segments_path: Path, output_dir: Path) -> dict[str, object]:
    labels_path, segments_path, output_dir = map(
        lambda p: Path(p).resolve(), (labels_path, segments_path, output_dir)
    )
    for source in (labels_path, segments_path):
        if "ground_truth" in {part.lower() for part in source.parts}:
            raise ValueError("ground_truth paths are not allowed")
    if output_dir.exists():
        raise ValueError("Output directory must be new and immutable")
    sources = (labels_path, segments_path)
    if any(
        source == output_dir
        or source in output_dir.parents
        or output_dir in source.parents
        for source in sources
    ):
        raise ValueError("Keep input files and output directory separate")
    before = {str(path): _digest(path) for path in sources}
    labels, segments = _read_csv(labels_path, labels=True), _read_csv(segments_path)
    report = summarize_outcomes(labels, segments)
    if before != {str(path): _digest(path) for path in sources}:
        raise ValueError("Inputs changed during report generation")
    output_dir.mkdir(parents=True)
    report_path = output_dir / "report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest = {
        "input_sha256": {path.name: before[str(path)] for path in sources},
        "output_sha256": {"report.json": _digest(report_path)},
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--segments", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run(args.labels, args.segments, args.output_dir)


if __name__ == "__main__":
    main()
