"""Source-only identity CLI; output is not a Customer360 profile or production model."""

import argparse
import csv
import json
from pathlib import Path

from .resolver import VERSION, preserve_existing_ids, resolve_csv

MAPPING_FIELDS = ("source_customer_id", "golden_customer_id", "resolver_version")
DECISION_FIELDS = (
    "left_source_id",
    "right_source_id",
    "decision",
    "heuristic_score",
    "reason",
)


def run(
    source: Path,
    output_dir: Path,
    synthetic_aliases: bool = False,
    prior_mapping: Path | None = None,
) -> dict:
    if (
        output_dir.resolve() == source.resolve().parent
        or output_dir.resolve() in source.resolve().parents
    ):
        raise ValueError("Output directory must not contain or overwrite source input")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(
            "Use a new empty output directory; published runs must not be overwritten"
        )
    if prior_mapping and output_dir.resolve() in prior_mapping.resolve().parents:
        raise ValueError("Output directory must not contain the prior registry")
    from services.data.ingestion.validator import sha256

    source_hash = sha256(source)
    prior_hash = sha256(prior_mapping) if prior_mapping else None
    result = resolve_csv(source, synthetic_aliases=synthetic_aliases)
    if prior_mapping:
        with prior_mapping.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != MAPPING_FIELDS:
                raise ValueError(
                    "Prior registry must use resolver mapping schema, not ground truth"
                )
            rows = list(reader)
        prior = {row["source_customer_id"]: row["golden_customer_id"] for row in rows}
        if len(prior) != len(rows):
            raise ValueError("Duplicate source ID in registry")
        preserve_existing_ids(result, prior)
    if sha256(source) != source_hash or (
        prior_mapping and sha256(prior_mapping) != prior_hash
    ):
        raise ValueError("Input changed during resolution")
    output_dir.mkdir(parents=True, exist_ok=True)
    result["review_queue"] = [
        row for row in result["decisions"] if row["decision"] == "REVIEW"
    ]
    schemas = {
        "mapping": MAPPING_FIELDS,
        "decisions": DECISION_FIELDS,
        "review_queue": DECISION_FIELDS,
    }
    temporary: list[tuple[Path, Path]] = []
    try:
        for name, fields in schemas.items():
            target = output_dir / (name + ".csv")
            temp = target.with_suffix(".csv.tmp")
            with temp.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
                writer.writeheader()
                writer.writerows(result[name])
            temporary.append((temp, target))
        oversized_temp = output_dir / "oversized_blocks.json.tmp"
        oversized_temp.write_text(
            json.dumps(result["oversized_blocks"], indent=2) + "\n", encoding="utf-8"
        )
        temporary.append((oversized_temp, output_dir / "oversized_blocks.json"))
        for temp, target in temporary:
            temp.replace(target)
    finally:
        for temp, _ in temporary:
            temp.unlink(missing_ok=True)
    manifest = {
        "resolver_version": VERSION,
        "source_sha256": source_hash,
        "synthetic_aliases": synthetic_aliases,
        "prior_registry_sha256": prior_hash,
        "output_sha256": {
            name + ".csv": sha256(output_dir / (name + ".csv")) for name in schemas
        },
        "review_pairs": len(result["review_queue"]),
        "score_semantics": "heuristic, not calibrated probability",
    }
    (output_dir / "resolution_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "sources": len(result["mapping"]),
        "golden_clusters": len({r["golden_customer_id"] for r in result["mapping"]}),
        "candidate_pairs": len(result["decisions"]),
        "review_pairs": len(result["review_queue"]),
        "oversized_blocks": len(result["oversized_blocks"]),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--synthetic-aliases",
        action="store_true",
        help="Fixture-only +srcNN alias policy for allowlisted synthetic domains",
    )
    parser.add_argument(
        "--prior-mapping",
        type=Path,
        help="Reviewed resolver mapping; never synthetic ground truth",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.source, args.output_dir, args.synthetic_aliases, args.prior_mapping
            )
        )
    )


if __name__ == "__main__":
    main()
