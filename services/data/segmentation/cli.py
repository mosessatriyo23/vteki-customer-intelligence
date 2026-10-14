"""CLI for development segmentation snapshots."""

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from .snapshot import FIELDS, build_segments


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inbound", type=Path, required=True)
    parser.add_argument("--resolution", type=Path, required=True)
    parser.add_argument("--cutoff-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--window-days", type=int, default=365)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Use a new output path; snapshots must not be overwritten")
    rows = build_segments(
        args.inbound, args.resolution, args.cutoff_at, args.window_days
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    try:
        with temporary.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(args.output)
    finally:
        temporary.unlink(missing_ok=True)
    print(
        json.dumps(
            {
                "profiles": len(rows),
                "lifecycle_counts": dict(Counter(r["lifecycle"] for r in rows)),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
