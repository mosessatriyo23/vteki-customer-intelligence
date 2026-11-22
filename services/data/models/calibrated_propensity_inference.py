"""Offline JSON-only calibrated POS scoring; no labels, fitting, reasons or serving.

Dedicated calibrated_predictions.json / calibrated_prediction_manifest.json format:
raw_probability and calibrated_probability are distinct score spaces. The existing
uncalibrated prediction_monitoring runner intentionally cannot consume this bundle.
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from services.data.features.snapshot import FIELDS, VERSION
from services.data.ingestion.validator import sha256
from services.data.models import propensity_calibration as calibration
from services.data.models.calibrated_churn_importance import _probabilities
from services.data.models.calibrated_propensity_importance import (
    _contract,
    _parameters,
    _scores,
)
from services.data.models.churn_experiment import FEATURES
from services.data.models.evaluator import _aware_timestamp
from services.data.models.model_importance import _check_paths, _raw
from services.data.models.propensity_experiment import (
    TARGET_LIMITATIONS,
    _check_target,
    _read_features,
)
from services.data.models.propensity_inference import _no_ground_truth, _strict_json

LIMITATIONS = [
    *calibration.LIMITATIONS,
    "Full feature snapshot universe; not target or campaign eligibility",
    "Retrospective scoring may include training-era rows; not prospective evaluation",
    "Raw probabilities are uncalibrated; only saved isotonic outputs are calibrated",
    "No refitting, recalibration, reason sentences, thresholds or serving handoff",
]
STATUS = {**calibration.FLAGS, "refitted": False, "advisory_only": True}


def predict_rows(
    artifact: dict, rows: list[dict], *, generated_at: datetime
) -> list[dict]:
    """Pure feature-only scoring using the official saved calibration parameters."""
    target = artifact.get("target")
    if not isinstance(target, str):
        raise ValueError("Unsupported propensity target")
    version, horizon = _check_target(target)
    try:
        model, isotonic = _parameters(artifact, target)
    except (OverflowError, TypeError) as exc:
        raise ValueError("Invalid numeric calibration parameters") from exc
    if (
        type(artifact.get("horizon_days")) is not int
        or artifact["horizon_days"] != horizon
    ):
        raise ValueError("Unexpected target horizon")
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at must be aware")
    generated_at = generated_at.astimezone(timezone.utc)
    if not rows:
        raise ValueError("Nonempty feature snapshot required")
    seen, identities, matrix = set(), [], []
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(FIELDS):
            raise ValueError(
                "Rows must exactly match feature contract; labels forbidden"
            )
        customer = row["golden_customer_id"]
        if not isinstance(customer, str) or not customer.strip():
            raise ValueError("Missing golden_customer_id")
        if (
            row["feature_version"] != VERSION
            or row["identity_time_policy"] != "CURRENT_SNAPSHOT_RETROSPECTIVE"
            or row["training_ready"] not in (False, "False")
            or type(row["training_ready"]) not in (bool, str)
        ):
            raise ValueError("Unexpected feature version, policy or readiness")
        cutoff = _aware_timestamp(row["cutoff_at"], "cutoff_at")
        if cutoff > generated_at:
            raise ValueError("cutoff_at must not exceed generated_at")
        identity = (customer, cutoff)
        if identity in seen:
            raise ValueError("Duplicate customer/cutoff")
        seen.add(identity)
        identities.append((customer, cutoff.isoformat()))
        matrix.append([_raw(row, field) for field in FEATURES])
    raw, calibrated = _probabilities(model, matrix), _scores(model, isotonic, matrix)
    return [
        dict(
            golden_customer_id=customer,
            cutoff_at=cutoff,
            target=target,
            target_version=version,
            horizon_days=horizon,
            model_version=calibration.MODEL_VERSION,
            feature_version=VERSION,
            calibration_status=isotonic["status"],
            generated_at=generated_at.isoformat(),
            raw_probability=raw_p,
            calibrated_probability=cal_p,
            valid_until=None,
            **STATUS,
            limitations=[*LIMITATIONS, *TARGET_LIMITATIONS[target]],
        )
        for (customer, cutoff), raw_p, cal_p in zip(identities, raw, calibrated)
    ]


def run(
    model_dir: Path,
    features_dir: Path,
    target: str,
    output_dir: Path,
    *,
    generated_at: datetime | None = None,
) -> dict:
    """Verify bundle and feature hashes before/after scoring into a new directory."""
    version, horizon = _check_target(target)
    model_dir, features_dir, output_dir = (
        Path(p).resolve() for p in (model_dir, features_dir, output_dir)
    )
    _no_ground_truth(model_dir, features_dir, output_dir)
    _check_paths(model_dir, output_dir, [features_dir])
    inputs = {
        name: model_dir / name
        for name in (*calibration.OUTPUTS, "calibration_manifest.json")
    }
    inputs.update(
        {
            name: features_dir / name
            for name in ("features.csv", "feature_manifest.json")
        }
    )
    before = {name: sha256(path) for name, path in inputs.items()}
    manifest = _strict_json(inputs["calibration_manifest.json"])
    _contract(manifest, target)
    if (
        not isinstance(manifest.get("input_sha256"), dict)
        or not manifest["input_sha256"]
    ):
        raise ValueError("Missing calibration provenance")
    if manifest["input_sha256"] != manifest.get("input_sha256_after"):
        raise ValueError("Calibration input provenance changed")
    if not isinstance(manifest.get("output_sha256"), dict) or any(
        manifest["output_sha256"].get(name) != before[name]
        for name in calibration.OUTPUTS
    ):
        raise ValueError("Calibration bundle checksum mismatch")
    artifact = _strict_json(inputs["calibration_artifact.json"])
    _contract(artifact, target)
    feature_manifest = _strict_json(inputs["feature_manifest.json"])
    feature_hashes = feature_manifest.get("output_sha256")
    if (
        feature_manifest.get("feature_version") != VERSION
        or feature_manifest.get("training_ready") is not False
        or not isinstance(feature_hashes, dict)
        or feature_hashes.get("features.csv") != before["features.csv"]
    ):
        raise ValueError("Unexpected feature manifest version, readiness or checksum")
    rows = _read_features(inputs["features.csv"])
    if (
        type(feature_manifest.get("rows")) is not int
        or len(rows) != feature_manifest["rows"]
    ):
        raise ValueError("Feature row count mismatch")
    cutoffs = feature_manifest.get("cutoffs")
    if not isinstance(cutoffs, list) or not cutoffs:
        raise ValueError("Missing feature cutoffs")
    expected = {_aware_timestamp(c, "cutoffs") for c in cutoffs}
    if len(expected) != len(cutoffs) or expected != {
        _aware_timestamp(row["cutoff_at"], "cutoff_at") for row in rows
    }:
        raise ValueError("Feature cutoff mismatch")
    generated_at = generated_at or datetime.now(timezone.utc)
    predictions = predict_rows(artifact, rows, generated_at=generated_at)
    identity = dict(
        target=target,
        target_version=version,
        horizon_days=horizon,
        model_version=calibration.MODEL_VERSION,
        feature_version=VERSION,
        model_artifact_sha256=before["calibration_artifact.json"],
        model_manifest_sha256=before["calibration_manifest.json"],
    )
    for prediction in predictions:
        prediction.update(identity)
    after = {name: sha256(path) for name, path in inputs.items()}
    if before != after:
        raise ValueError("Input changed during prediction")
    predictions_bytes = (
        json.dumps(predictions, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    predictions_hash = hashlib.sha256(predictions_bytes).hexdigest()
    result = dict(
        **identity,
        **STATUS,
        format_version="moses-calibrated-pos-predictions-dev-1.0",
        score_fields=["raw_probability", "calibrated_probability"],
        calibration_status=artifact["isotonic"]["status"],
        rows=len(predictions),
        generated_at=predictions[0]["generated_at"],
        valid_until=None,
        input_sha256=before,
        input_sha256_after=after,
        calibration_input_sha256=manifest["input_sha256"],
        scored_features_match_calibration=all(
            manifest["input_sha256"].get(name) == before[name]
            for name in ("features.csv", "feature_manifest.json")
        ),
        output_sha256={"calibrated_predictions.json": predictions_hash},
        limitations=[*LIMITATIONS, *TARGET_LIMITATIONS[target]],
    )
    manifest_bytes = (
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    # Serialize everything before touching disk so a failure leaves no partial dir.
    output_dir.mkdir(parents=True)
    (output_dir / "calibrated_predictions.json").write_bytes(predictions_bytes)
    (output_dir / "calibrated_prediction_manifest.json").write_bytes(manifest_bytes)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("model-dir", "features-dir", "output-dir"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    result = run(args.model_dir, args.features_dir, args.target, args.output_dir)
    print(json.dumps({k: result[k] for k in ("target", "rows", "serving_ready")}))


if __name__ == "__main__":
    main()
