"""Offline JSON-only calibrated churn reload; no fitting or serving authorization."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from services.data.features.snapshot import FIELDS, VERSION
from services.data.models import churn_calibration as calibration
from services.data.models.calibrated_churn_importance import (
    _contract,
    _interpolate,
    _parameters,
    _probabilities,
)
from services.data.models.churn_experiment import FEATURES
from services.data.models.churn_inference import (
    LOCAL_TIMEZONE,
    _aware_timestamp,
    _raw_value,
)
from services.data.models.evaluation_disclaimer import SYNTHETIC_DATA_DISCLAIMER
from services.data.models.labels import CHRIST_VERSION

LIMITATIONS = [
    *calibration.LIMITATIONS,
    "Calibration tested on the synthetic holdout did not generalize; do not infer improvement",
    "Offline inspection only, not approved for serving or an I-04 prediction handoff",
    "No refitting, threshold selection, reason codes, bands or validity guarantee",
]


@dataclass(frozen=True)
class CalibratedChurnModel:
    """Saved inspection artifact; score only the original verified JSON bytes."""

    artifact: dict
    artifact_bytes: bytes
    model_artifact_sha256: str
    manifest_sha256: str


def _cutoffs(artifact: dict) -> list[datetime]:
    result: list[datetime] = []
    for field in ("train_cutoffs", "calibration_cutoffs"):
        values = artifact.get(field)
        if not isinstance(values, list) or not values:
            raise ValueError(f"Nonempty {field} required")
        result.extend(_aware_timestamp(value, field) for value in values)
    return result


def _provenance(value: dict) -> dict:
    before = value.get("input_sha256")
    if (
        not isinstance(before, dict)
        or set(before) != {"model_manifest.json", "training_rows.csv"}
        or any(
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
            for digest in before.values()
        )
        or before != value.get("input_sha256_after")
    ):
        raise ValueError("Calibration input before/after provenance mismatch")
    return before


def load_model(model_dir: Path) -> CalibratedChurnModel:
    """Hash the exact bytes decoded; verify the whole bundle and saved provenance.

    Checksums detect inconsistent bundles, not authenticity against an attacker
    able to replace both artifacts and manifest. No source labels are loaded.
    """
    model_dir = Path(model_dir)
    names = (*calibration.OUTPUTS, "calibration_manifest.json")
    raw = {name: (model_dir / name).read_bytes() for name in names}
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in raw.items()}
    manifest = json.loads(raw["calibration_manifest.json"])
    if not isinstance(manifest, dict):
        raise ValueError("Calibration manifest must be an object")
    _contract(manifest)
    provenance = _provenance(manifest)
    expected = manifest.get("output_sha256")
    if not isinstance(expected, dict):
        raise ValueError("Missing bundle checksums")
    for name in calibration.OUTPUTS:
        if expected.get(name) != hashes[name]:
            raise ValueError(f"{name} checksum mismatch")
    artifact = json.loads(raw["calibration_artifact.json"])
    evaluation = json.loads(raw["calibration_evaluation.json"])
    predictions = json.loads(raw["test_predictions.json"])
    if not isinstance(artifact, dict) or not isinstance(evaluation, dict):
        raise ValueError("Artifact and evaluation must be objects")
    if not isinstance(predictions, list):
        raise ValueError("Saved predictions must be a list")
    _parameters(artifact)
    _contract(evaluation)
    if _provenance(evaluation) != provenance:
        raise ValueError("Evaluation/manifest input provenance mismatch")
    for field in ("train_cutoffs", "calibration_cutoffs"):
        if artifact.get(field) != evaluation.get(field):
            raise ValueError("Artifact/evaluation cutoff mismatch")
    _cutoffs(artifact)
    # Detect changes during loading without parsing a different read than we hash.
    if any((model_dir / name).read_bytes() != data for name, data in raw.items()):
        raise ValueError("Model bundle changed during loading")
    return CalibratedChurnModel(
        artifact=artifact,
        artifact_bytes=raw["calibration_artifact.json"],
        model_artifact_sha256=hashes["calibration_artifact.json"],
        manifest_sha256=hashes["calibration_manifest.json"],
    )


def predict_rows(
    model: CalibratedChurnModel, rows: list[dict], *, generated_at: datetime
) -> list[dict]:
    """Apply saved logistic preprocessing and clipped isotonic mapping, never fit."""
    if hashlib.sha256(model.artifact_bytes).hexdigest() != model.model_artifact_sha256:
        raise ValueError("Model artifact bytes checksum mismatch")
    artifact = json.loads(model.artifact_bytes)
    if model.artifact != artifact:
        raise ValueError("Model artifact changed after loading")
    # Score the fresh private parse, not the caller's mutable inspection dictionary.
    logistic, x, y = _parameters(artifact)
    boundary = max(_cutoffs(artifact)) + timedelta(days=90)
    generated = _aware_timestamp(generated_at.isoformat(), "generated_at").astimezone(
        LOCAL_TIMEZONE
    )
    seen: set[tuple[str, datetime]] = set()
    cutoffs = []
    matrix = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(FIELDS):
            raise ValueError("Rows must exactly match the feature contract; no labels")
        customer = row["golden_customer_id"]
        if not isinstance(customer, str) or not customer.strip():
            raise ValueError("golden_customer_id must be a nonempty string")
        if row["identity_status"] not in {
            "PROVISIONAL",
            "REVIEW_REQUIRED",
            "APPROVED",
            "REJECTED",
            "UNKNOWN",
        }:
            raise ValueError("Unexpected identity_status")
        if row["feature_version"] != VERSION:
            raise ValueError("Unexpected feature_version")
        if row["training_ready"] is not False and row["training_ready"] != "False":
            raise ValueError("training_ready must be False")
        if row["identity_time_policy"] != "CURRENT_SNAPSHOT_RETROSPECTIVE":
            raise ValueError("Unexpected identity_time_policy")
        cutoff = _aware_timestamp(row["cutoff_at"], "cutoff_at").astimezone(
            LOCAL_TIMEZONE
        )
        if cutoff > generated:
            raise ValueError("cutoff_at must not be in the future of generated_at")
        if cutoff < boundary:
            raise ValueError(
                "cutoff_at precedes training/calibration outcome availability"
            )
        key = (customer, cutoff)
        if key in seen:
            raise ValueError("Duplicate customer/cutoff in prediction rows")
        seen.add(key)
        cutoffs.append(cutoff)
        matrix.append([_raw_value(row, field) for field in FEATURES])
    if not rows:
        return []
    raw = _probabilities(logistic, matrix)
    calibrated = _interpolate(raw, x, y)
    return [
        {
            "golden_customer_id": row["golden_customer_id"],
            "cutoff_at": cutoff.isoformat(),
            "generated_at": generated.isoformat(),
            "horizon_days": 90,
            "model_version": calibration.MODEL_VERSION,
            "feature_version": VERSION,
            "label_version": CHRIST_VERSION,
            **calibration.FLAGS,
            "raw_probability": raw_p,
            "calibrated_probability": calibrated_p,
            "model_artifact_sha256": model.model_artifact_sha256,
            "manifest_sha256": model.manifest_sha256,
            "limitations": list(LIMITATIONS),
            "disclaimer": SYNTHETIC_DATA_DISCLAIMER,
        }
        for row, cutoff, raw_p, calibrated_p in zip(rows, cutoffs, raw, calibrated)
    ]
