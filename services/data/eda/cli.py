"""Validate a synthetic inbound batch and publish reproducible descriptive EDA."""

import argparse
import json
from datetime import datetime
from pathlib import Path

from services.data.ingestion.contracts import TABLES
from services.data.ingestion.validator import BatchValidator, sha256

from .report import markdown, summarize


def run(inbound: Path, cutoff: datetime, output_dir: Path) -> dict:
    if output_dir.exists():
        raise ValueError("Use a new output directory; reports must not be overwritten")
    if (
        inbound.resolve() == output_dir.resolve()
        or output_dir.resolve() in inbound.resolve().parents
        or inbound.resolve() in output_dir.resolve().parents
    ):
        raise ValueError("Output directory must be separate from input")
    paths = [
        inbound / "generation_manifest.json",
        *(inbound / name for name in sorted(TABLES)),
    ]
    before = {path.name: sha256(path) for path in paths}
    validation = BatchValidator().validate(inbound)
    if not validation.valid:
        raise ValueError(
            "Inbound validation failed: "
            + json.dumps(validation.errors, sort_keys=True)
        )
    report = summarize(inbound, cutoff)
    if any(sha256(path) != before[path.name] for path in paths):
        raise ValueError("Inputs changed during EDA")
    output_dir.mkdir(parents=True)
    (output_dir / "summary.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "report.md").write_text(markdown(report), encoding="utf-8")
    manifest = {
        "input_sha256": before,
        "output_sha256": {
            name: sha256(output_dir / name) for name in ("summary.json", "report.md")
        },
        "cutoff_at": cutoff.isoformat(),
        "data_scope": report["data_scope"],
        "training_ready": False,
    }
    (output_dir / "eda_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "report_dir": str(output_dir),
        "qualifying_purchases": report["totals"]["qualifying_purchases"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inbound", type=Path, required=True)
    parser.add_argument("--cutoff-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.inbound, args.cutoff_at, args.output_dir)))


if __name__ == "__main__":
    main()
