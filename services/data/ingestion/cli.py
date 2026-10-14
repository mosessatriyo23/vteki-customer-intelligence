"""CLI: validate and optionally load one schema-v2 inbound batch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .staging import IngestionStaging
from .validator import BatchValidator


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inbound", type=Path, required=True)
    parser.add_argument("--sqlite-staging", type=Path, help="Development-only staging database")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.sqlite_staging:
        result = IngestionStaging(args.sqlite_staging).ingest(args.inbound)
    else:
        result = BatchValidator().validate(args.inbound).to_dict()
    serialized = json.dumps(result, indent=2, sort_keys=True)
    print(serialized)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(serialized + "\n", encoding="utf-8")
    valid = result.get("valid", result.get("status") in {"LOADED", "ALREADY_LOADED"})
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
