"""Stream an audit of the existing inbound baseline and its ground truth.

Usage: python generator/audit_baseline.py [--inbound DIR] [--ground-truth DIR]
No third-party packages; does not regenerate or modify fixture data.
"""

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


def rows(path):
    with path.open(newline="", encoding="utf-8") as stream:
        yield from csv.DictReader(stream)


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def audit(inbound, truth):
    manifest = json.loads((inbound / "generation_manifest.json").read_text(encoding="utf-8"))
    counts = {}
    checksum_mismatches = []
    for folder, expected in ((inbound, manifest["checksums_sha256"]),
                             (truth, manifest["ground_truth_checksums_sha256"])):
        for filename, checksum in expected.items():
            path = folder / filename
            if not path.exists() or digest(path) != checksum:
                checksum_mismatches.append(str(path))
            if path.suffix == ".csv" and path.exists():
                counts[filename] = sum(1 for _ in rows(path))

    trajectory = Counter(row["trajectory"] for row in rows(truth / "customer_latent_trajectories.csv"))
    scenario = Counter(row["identity_scenario"] for row in rows(truth / "identity_mapping.csv"))
    source_ids = {row["crm_customer_id"] for row in rows(inbound / "crm_customers.csv")}
    mapping_ids = {row["source_customer_id"] for row in rows(truth / "identity_mapping.csv")}
    transaction_ids = set()
    status = Counter()
    missing_customer_refs = 0
    empty_customer_refs = 0
    for row in rows(inbound / "transactions.csv"):
        transaction_ids.add(row["source_transaction_id"])
        status[row["status"]] += 1
        ref = row["source_customer_ref"]
        empty_customer_refs += not bool(ref)
        missing_customer_refs += bool(ref) and ref not in source_ids
    orphan_items = sum(row["source_transaction_id"] not in transaction_ids
                       for row in rows(inbound / "transaction_items.csv"))
    return {
        "counts": counts,
        "manifest_volume_mismatches": {name: [counts.get(name + ".csv"), expected]
                                      for name, expected in manifest["volumes"].items()
                                      if counts.get(name + ".csv") != expected},
        "checksum_mismatches": checksum_mismatches,
        "golden_customer_count": sum(trajectory.values()),
        "manifest_golden_customers": manifest["golden_customers"],
        "trajectories": dict(sorted(trajectory.items())),
        "identity_scenarios": dict(sorted(scenario.items())),
        "source_ids_not_mapped": len(source_ids - mapping_ids),
        "mapped_ids_not_in_crm": len(mapping_ids - source_ids),
        "transaction_statuses": dict(sorted(status.items())),
        "transactions_without_customer_ref": empty_customer_refs,
        "transactions_with_unknown_customer_ref": missing_customer_refs,
        "transaction_items_with_unknown_transaction": orphan_items,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inbound", type=Path, default=Path(__file__).resolve().parents[1] / "inbound/2026-09-06")
    parser.add_argument("--ground-truth", type=Path, default=Path(__file__).resolve().parent / "ground_truth")
    args = parser.parse_args()
    print(json.dumps(audit(args.inbound, args.ground_truth), indent=2))
