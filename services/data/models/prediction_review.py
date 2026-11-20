"""Pure validation for the read-only Moses prediction review handoff."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class PredictionImport:
    model_version: str
    feature_set_version: str
    label_version: str
    prediction_type: str
    producer_version: str
    manifest_hash: str
    records: tuple[dict[str, Any], ...]


def _finite_score(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and 0 <= value <= 1
    )


def validate_prediction_import(
    manifest: dict[str, Any], records: list[dict[str, Any]]
) -> PredictionImport:
    """Accept only the explicitly non-serving Moses contract artifact.

    This review handoff preserves source versions and per-record evidence. It
    never marks records serving-ready or authorizes use in the NBA engine.
    """
    if not isinstance(manifest, dict) or not isinstance(records, list) or not records:
        raise ValueError("A manifest and a non-empty record list are required")
    if manifest.get("development_only") is not True:
        raise ValueError("Only development-only artifacts can enter this review queue")
    if manifest.get("serving_ready") is not False or manifest.get("approved") is not False:
        raise ValueError("Serving-ready or approved artifacts are not accepted by this importer")
    if manifest.get("prediction_id_produced") is not False:
        raise ValueError("Unexpected prediction identity contract; review its adapter first")
    if len(records) > 100_000:
        raise ValueError("At most 100,000 records can be imported at once")
    if manifest.get("rows") != len(records):
        raise ValueError("Record count does not match the source manifest")

    versions = {
        "model_version": manifest.get("model_version"),
        "feature_set_version": manifest.get("feature_set_version"),
        "label_version": manifest.get("label_version"),
    }
    for key, value in versions.items():
        if not isinstance(value, str) or not value.strip() or len(value) > 128:
            raise ValueError(f"{key} is missing or invalid")

    prediction_type = manifest.get("prediction_type")
    producer_version = manifest.get("producer_version")
    if not isinstance(prediction_type, str) or not prediction_type.strip():
        raise ValueError("prediction_type is missing")
    if not isinstance(producer_version, str) or not producer_version.strip():
        raise ValueError("producer_version is missing")

    canonical_lines: list[str] = []
    seen: set[tuple[str, str]] = set()
    for row in records:
        if not isinstance(row, dict):
            raise ValueError("Every prediction record must be an object")
        if any(row.get(key) != value for key, value in versions.items()):
            raise ValueError("A row's model or data version differs from its manifest")
        customer_id = row.get("customer_id")
        cutoff_at = row.get("cutoff_at")
        if not isinstance(customer_id, str) or not isinstance(cutoff_at, str):
            raise ValueError("Every row needs its Golden Customer ID and cutoff")
        try:
            UUID(customer_id)
        except ValueError as error:
            raise ValueError("customer_id must be a Golden Customer UUID") from error
        key = (customer_id, cutoff_at)
        if key in seen:
            raise ValueError("Duplicate customer and cutoff in imported predictions")
        seen.add(key)

        score = row.get("score")
        if score is not None and not _finite_score(score):
            raise ValueError("Prediction scores must be finite numbers between 0 and 1")
        reason_codes = row.get("reason_codes")
        if not isinstance(reason_codes, list):
            raise ValueError("Every row must preserve its source reason_codes list")
        if row.get("serving_ready") is not False or row.get("approved") is not False:
            raise ValueError("Rows must remain explicitly non-serving and unapproved")
        canonical_lines.append(json.dumps(row, sort_keys=True, allow_nan=False))

    record_bytes = ("\n".join(canonical_lines) + "\n").encode("utf-8")
    hashes = manifest.get("output_sha256")
    if not isinstance(hashes, dict):
        raise ValueError("Manifest output_sha256 is missing or invalid")
    expected_hash = hashes.get("records.jsonl")
    if not isinstance(expected_hash, str) or hashlib.sha256(record_bytes).hexdigest() != expected_hash:
        raise ValueError("Prediction records checksum does not match the Moses manifest")

    manifest_hash = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, allow_nan=False).encode("utf-8")
    ).hexdigest()
    return PredictionImport(
        model_version=versions["model_version"],
        feature_set_version=versions["feature_set_version"],
        label_version=versions["label_version"],
        prediction_type=prediction_type,
        producer_version=producer_version,
        manifest_hash=manifest_hash,
        records=tuple(records),
    )
