"""Publish development-only labels and deterministic temporal baselines."""

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

from services.data.features.snapshot import FIELDS as FEATURE_FIELDS
from services.data.features.snapshot import build_features, validate_cutoffs
from services.data.ingestion.contracts import TABLES
from services.data.ingestion.validator import BatchValidator, sha256

from .baseline import evaluate
from .labels import FIELDS as LABEL_FIELDS
from .labels import TRAINING_FIELDS, VERSION, build_labels, join_training_rows


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict]) -> None:
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run(
    inbound: Path,
    resolution: Path,
    output_dir: Path,
    cutoffs: list[datetime],
    horizon_days: int = 90,
) -> dict:
    cutoffs = validate_cutoffs(cutoffs)
    if output_dir.exists():
        raise ValueError(
            "Use a new output directory; existing runs cannot be overwritten"
        )
    for input_dir in (inbound, resolution):
        output = output_dir.resolve()
        source = input_dir.resolve()
        if output == source or output in source.parents or source in output.parents:
            raise ValueError("Output directory must be separate from inputs")
    paths = [
        inbound / "generation_manifest.json",
        *(inbound / name for name in sorted(TABLES)),
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
    before = {str(path.resolve()): sha256(path) for path in paths}
    report = BatchValidator().validate(inbound)
    if not report.valid:
        raise ValueError(
            "Inbound validation failed: " + json.dumps(report.errors, sort_keys=True)
        )
    labels = build_labels(inbound, resolution, cutoffs, horizon_days)
    features = build_features(inbound, resolution, cutoffs)
    training_rows = join_training_rows(features, labels)
    metrics = evaluate(training_rows)
    if any(sha256(path) != before[str(path.resolve())] for path in paths):
        raise ValueError("Inputs changed during model development run")
    output_dir.mkdir(parents=True)
    _write_csv(output_dir / "labels.csv", LABEL_FIELDS, labels)
    _write_csv(output_dir / "training_rows.csv", TRAINING_FIELDS, training_rows)
    (output_dir / "metrics.json").write_text(
        json.dumps(metrics, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    outputs = {
        name: sha256(output_dir / name)
        for name in ("labels.csv", "training_rows.csv", "metrics.json")
    }
    manifest = dict(
        label_version=VERSION,
        feature_fields=list(FEATURE_FIELDS),
        horizon_days=horizon_days,
        experiment_ready=False,
        final_model=False,
        split_policy="chronological_cutoff_holdout_latest_complete_cutoff",
        label_rows=len(labels),
        training_rows=len(training_rows),
        cutoffs=[c.isoformat() for c in cutoffs],
        input_sha256=before,
        output_sha256=outputs,
        limitations=[
            "Current identity snapshot applied retrospectively",
            "Transaction status and refunds lack historical availability versions",
            "Development baseline only; not a final model or production experiment",
        ],
    )
    # Completion marker is last.
    (output_dir / "model_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return dict(
        label_rows=len(labels),
        training_rows=len(training_rows),
        train_rows=metrics["train_rows"],
        test_rows=metrics["test_rows"],
        experiment_ready=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inbound", type=Path, required=True)
    parser.add_argument("--resolution", type=Path, required=True)
    parser.add_argument(
        "--cutoff-at", type=datetime.fromisoformat, action="append", required=True
    )
    parser.add_argument("--horizon-days", type=int, default=90)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.inbound,
                args.resolution,
                args.output_dir,
                args.cutoff_at,
                args.horizon_days,
            )
        )
    )


if __name__ == "__main__":
    main()
