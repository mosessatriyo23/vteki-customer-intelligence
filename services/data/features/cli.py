"""Publish versioned, validated development historical features."""

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

from services.data.ingestion.contracts import TABLES
from services.data.ingestion.validator import BatchValidator, sha256

from .snapshot import FIELDS, VERSION, build_features, validate_cutoffs


def run(
    inbound: Path, resolution: Path, output_dir: Path, cutoffs: list[datetime]
) -> dict:
    cutoffs = validate_cutoffs(cutoffs)
    if output_dir.exists():
        raise ValueError(
            "Use a new output directory; existing runs cannot be overwritten"
        )
    for input_dir in (inbound, resolution):
        if (
            output_dir.resolve() == input_dir.resolve()
            or output_dir.resolve() in input_dir.resolve().parents
            or input_dir.resolve() in output_dir.resolve().parents
        ):
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
    rows = build_features(inbound, resolution, cutoffs)
    if any(sha256(path) != before[str(path.resolve())] for path in paths):
        raise ValueError("Inputs changed during feature construction")
    output_dir.mkdir(parents=True)
    # Manifest is the completion marker. A crash can leave an incomplete directory.
    with (output_dir / "features.csv").open(
        "x", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    manifest = dict(
        feature_version=VERSION,
        training_ready=False,
        rows=len(rows),
        cutoffs=[c.isoformat() for c in cutoffs],
        input_sha256=before,
        output_sha256={"features.csv": sha256(output_dir / "features.csv")},
        limitations=[
            "Current identity snapshot applied retrospectively",
            "No event ingestion/availability timestamps",
            "Transaction status and refunds lack historical versions",
        ],
    )
    (output_dir / "feature_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return {"rows": len(rows), "cutoffs": len(cutoffs), "training_ready": False}


def main():
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
