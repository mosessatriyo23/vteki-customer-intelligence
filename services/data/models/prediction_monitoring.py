"""Offline score-distribution monitoring over development predictions.

PSI and volume only. Band mix and per-segment performance are reported as
None: no approved band thresholds or segment-label join exist yet. Alerts are
advisory; nothing here retrains, promotes, or serves a model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from services.data.models.evaluator import _aware_timestamp
from services.data.monitoring.drift import population_stability_index

# Ten equal-width probability bins; a fixed, documented dev choice.
BIN_EDGES = tuple(i / 10 for i in range(1, 10))
IDENTITY = (
    "target",
    "model_version",
    "model_artifact_sha256",
    "feature_version",
    "target_version",
)
FLAGS = (
    "training_ready",
    "experiment_ready",
    "final_model",
    "serving_ready",
    "calibration_final",
    "approved",
    "targeting_allowed",
)


def _strict_loads(data: bytes) -> object:
    def pairs(items):
        result: dict = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject(value):
        raise ValueError(f"Nonfinite JSON number: {value}")

    try:
        return json.loads(
            data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=reject
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Malformed JSON input") from exc


SCORE_FIELDS = ("uncalibrated_probability", "raw_probability", "calibrated_probability")


def _score(value: object, field: str = "uncalibrated_probability") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number")
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{field} must be within [0, 1]")
    return float(value)


def build_report(
    rows: list[dict],
    baseline_cutoff: str,
    current_cutoff: str,
    *,
    score_field: str = "uncalibrated_probability",
) -> dict:
    if score_field not in SCORE_FIELDS:
        raise ValueError("Unsupported score_field")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("Predictions must be a list of objects")
    baseline_at = _aware_timestamp(baseline_cutoff, "baseline_cutoff")
    current_at = _aware_timestamp(current_cutoff, "current_cutoff")
    if baseline_at >= current_at:
        raise ValueError("baseline_cutoff must be earlier than current_cutoff")
    identity = None
    seen = set()
    scores: dict[object, list[float]] = {baseline_at: [], current_at: []}
    for row in rows:
        if (
            row.get("development_only") is not True
            or row.get("serving_ready") is not False
        ):
            raise ValueError(
                "Only development-only, non-serving predictions are allowed"
            )
        current_identity = tuple(row.get(field) for field in IDENTITY)
        if not all(isinstance(value, str) and value for value in current_identity):
            raise ValueError("Missing prediction identity")
        if (
            not isinstance(row.get("golden_customer_id"), str)
            or not row["golden_customer_id"]
        ):
            raise ValueError("Missing customer identity")
        if identity is None:
            identity = current_identity
        if current_identity != identity:
            raise ValueError("Predictions must come from one model/target identity")
        cutoff = _aware_timestamp(row.get("cutoff_at"), "cutoff_at")
        key = (row.get("golden_customer_id"), cutoff)
        if key in seen:
            raise ValueError("Duplicate customer/cutoff prediction")
        seen.add(key)
        value = _score(row.get(score_field), score_field)
        if cutoff not in scores:
            raise ValueError("Prediction cutoff is outside baseline/current periods")
        scores[cutoff].append(value)
    if not scores[baseline_at] or not scores[current_at]:
        raise ValueError("Baseline and current cutoffs must both have predictions")
    assert identity is not None  # populated by either nonempty period above
    psi = population_stability_index(scores[baseline_at], scores[current_at], BIN_EDGES)
    alerts = (
        [
            {
                "metric": "PSI",
                "status": psi["status"],
                "value": psi["value"],
                "advisory_only": True,
            }
        ]
        if psi["status"] != "STABLE"
        else []
    )
    return {
        "target": identity[0],
        "model_version": identity[1],
        "model_artifact_sha256": identity[2],
        "feature_version": identity[3],
        "target_version": identity[4],
        "baseline_cutoff": baseline_at.isoformat(),
        "current_cutoff": current_at.isoformat(),
        "baseline_volume": len(scores[baseline_at]),
        "current_volume": len(scores[current_at]),
        "score_field": score_field,
        "psi": psi,
        "alerts": alerts,
        "band_mix": None,
        "segment_performance": None,
        "unavailable_reasons": {
            "band_mix": "No approved score-band thresholds",
            "segment_performance": "No approved segment mapping/outcome join in this module",
        },
        "automatic_action": False,
        "limitations": [
            "Synthetic development predictions; not production monitoring",
            "Score distribution drift only; not outcome performance",
            "Alerts are advisory and never trigger retraining or serving",
        ],
        **{flag: False for flag in FLAGS},
    }


CALIBRATED_FORMAT = "moses-calibrated-pos-predictions-dev-1.0"
CALIBRATED_FLAGS = {
    **{flag: False for flag in FLAGS if flag not in ("approved", "targeting_allowed")},
    "development_only": True,
    "refitted": False,
    "advisory_only": True,
}


def _check_calibrated(manifest: dict, rows: list[dict]) -> None:
    """Dedicated calibrated bundle contract; never inferred from legacy files."""
    if manifest.get("format_version") != CALIBRATED_FORMAT:
        raise ValueError("Unsupported calibrated prediction format")
    if manifest.get("score_fields") != ["raw_probability", "calibrated_probability"]:
        raise ValueError("Unexpected calibrated manifest score fields")
    if any(manifest.get(k) is not v for k, v in CALIBRATED_FLAGS.items()) or any(
        manifest.get(k, False) is not False for k in ("approved", "targeting_allowed")
    ):
        raise ValueError("Unsafe calibrated manifest flags")
    horizon = manifest.get("horizon_days")
    if type(horizon) is not int or horizon <= 0:
        raise ValueError("Missing or invalid calibrated horizon")
    inputs = manifest.get("input_sha256")
    if not isinstance(inputs, dict) or inputs != manifest.get("input_sha256_after"):
        raise ValueError("Calibrated input provenance changed")
    status = manifest.get("calibration_status")
    if not isinstance(status, str) or not status:
        raise ValueError("Missing calibration status")
    pairs = (
        ("model_artifact_sha256", "calibration_artifact.json"),
        ("model_manifest_sha256", "calibration_manifest.json"),
    )
    for field, name in pairs:
        if (
            not isinstance(manifest.get(field), str)
            or inputs.get(name) != manifest[field]
        ):
            raise ValueError(f"Calibrated {field} does not match input provenance")
    for row in rows:
        if any(row.get(k) is not v for k, v in CALIBRATED_FLAGS.items()) or any(
            row.get(k, False) is not False for k in ("approved", "targeting_allowed")
        ):
            raise ValueError("Unsafe calibrated prediction flags")
        for field in manifest["score_fields"]:
            _score(row.get(field), field)
        if row.get("calibration_status") != status:
            raise ValueError("Calibrated prediction status does not match manifest")
        if any(row.get(field) != manifest[field] for field, _ in pairs):
            raise ValueError("Calibrated prediction hash does not match manifest")
        if row.get("horizon_days") != manifest.get("horizon_days"):
            raise ValueError("Calibrated prediction horizon does not match manifest")


def run(
    predictions_dir: Path,
    baseline_cutoff: str,
    current_cutoff: str,
    output_dir: Path,
    *,
    score_field: str = "uncalibrated_probability",
) -> dict:
    if score_field not in SCORE_FIELDS:
        raise ValueError("Unsupported score_field")
    calibrated = score_field != "uncalibrated_probability"
    predictions_dir, output_dir = (
        Path(predictions_dir).resolve(),
        Path(output_dir).resolve(),
    )
    if any(
        part.lower() == "ground_truth"
        for path in (predictions_dir, output_dir)
        for part in path.parts
    ):
        raise ValueError("ground_truth paths are not allowed")
    if output_dir.exists():
        raise ValueError("Use a new output directory")
    if predictions_dir in output_dir.parents or output_dir in predictions_dir.parents:
        raise ValueError("Keep inputs and output separate")
    prediction_name = (
        "calibrated_predictions.json" if calibrated else "predictions.json"
    )
    manifest_name = (
        "calibrated_prediction_manifest.json"
        if calibrated
        else "prediction_manifest.json"
    )
    manifest_path = predictions_dir / manifest_name
    prediction_path = predictions_dir / prediction_name
    manifest_bytes = manifest_path.read_bytes()
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    manifest = _strict_loads(manifest_bytes)
    if not isinstance(manifest, dict) or not isinstance(
        manifest.get("output_sha256"), dict
    ):
        raise ValueError("Malformed prediction manifest")
    if (
        manifest.get("development_only") is not True
        or manifest.get("serving_ready") is not False
    ):
        raise ValueError("Only development-only, non-serving manifests are allowed")
    data = prediction_path.read_bytes()
    before = hashlib.sha256(data).hexdigest()
    if manifest["output_sha256"].get(prediction_name) != before:
        raise ValueError("Prediction checksum mismatch")
    rows = _strict_loads(data)
    if not isinstance(rows, list):
        raise ValueError("Predictions must be a list of objects")
    report = build_report(
        rows, baseline_cutoff, current_cutoff, score_field=score_field
    )
    if type(manifest.get("rows")) is not int or manifest["rows"] != len(rows):
        raise ValueError("Prediction row count mismatch")
    if calibrated:
        _check_calibrated(manifest, rows)
    # This runner supports propensity manifests only; do not silently accept
    # other model families without their own artifact-hash contract.
    inputs = manifest.get("input_sha256")
    artifact_name = (
        "calibration_artifact.json" if calibrated else "model_parameters.json"
    )
    if not isinstance(inputs, dict) or not isinstance(inputs.get(artifact_name), str):
        raise ValueError("Missing model artifact hash in manifest")
    model_hash = inputs[artifact_name]
    if model_hash != report["model_artifact_sha256"]:
        raise ValueError("Prediction model artifact does not match manifest")
    if any(
        manifest.get(field) != report[field]
        for field in IDENTITY
        if field != "model_artifact_sha256"
    ):
        raise ValueError("Prediction identity does not match manifest")
    if (
        hashlib.sha256(prediction_path.read_bytes()).hexdigest() != before
        or hashlib.sha256(manifest_path.read_bytes()).hexdigest() != manifest_hash
    ):
        raise ValueError("Input changed during monitoring")
    output_dir.mkdir(parents=True)
    report["input_sha256"] = {
        prediction_name: before,
        manifest_name: manifest_hash,
    }
    (output_dir / "monitoring_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions-dir", type=Path, required=True)
    parser.add_argument("--baseline-cutoff", required=True)
    parser.add_argument("--current-cutoff", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--score-field", choices=SCORE_FIELDS, default="uncalibrated_probability"
    )
    args = parser.parse_args()
    report = run(
        args.predictions_dir,
        args.baseline_cutoff,
        args.current_cutoff,
        args.output_dir,
        score_field=args.score_field,
    )
    print(
        json.dumps(
            {
                "psi": report["psi"]["value"],
                "status": report["psi"]["status"],
                "serving_ready": False,
            }
        )
    )


if __name__ == "__main__":
    main()
