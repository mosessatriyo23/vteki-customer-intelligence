"""Offline, pickle-free loader and scorer for the JSON-only churn_experiment logistic model.

Loads only JSON from an existing experiment directory (no executable artifact).
This is a transparent demo logistic scorer for inspection, not a calibrated,
approved, or production-serving model. There is no I-04 prediction handoff
here: no reason codes, no band, no calibration_version, and no producer
valid_until are fabricated. Explanations below are exact signed log-odds
contributions of the chosen linear model, not causal business reason codes.
"""

import argparse
import csv
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.data.features.snapshot import FIELDS as FEATURE_FIELDS
from services.data.features.snapshot import VERSION as FEATURE_VERSION
from services.data.ingestion.validator import sha256
from services.data.models.churn_experiment import FEATURES, MODEL_VERSION
from services.data.models.labels import CHRIST_VERSION

LOCAL_TIMEZONE = timezone(timedelta(hours=7))
_HORIZON_DAYS = 90
_OUTPUT_NAMES = ("evaluation.json", "holdout_predictions.json", "model_parameters.json")
EXPLANATION_METHOD = (
    "Exact signed log-odds contribution per feature: "
    "(imputed_value - scaler_mean) / scaler_scale * coefficient. "
    "Mathematical decomposition of the logistic score only; not causal and not a business reason code."
)


def _finite_numbers(
    values: object, length: int, *, allow_negative: bool
) -> list[float]:
    if not isinstance(values, list) or len(values) != length:
        raise ValueError("Expected a list of finite numbers of the right shape")
    result = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Model parameter values must be numeric")
        try:
            number = float(value)
        except (OverflowError, ValueError) as exc:
            raise ValueError("Model parameter values must be finite") from exc
        if not math.isfinite(number):
            raise ValueError("Model parameter values must be finite")
        if not allow_negative and number < 0:
            raise ValueError("Model parameter values must be nonnegative")
        result.append(number)
    return result


@dataclass(frozen=True)
class ChurnModel:
    model_dir: Path
    model_version: str
    feature_version: str
    label_version: str
    intercept: float
    coef: tuple[float, ...]
    scaler_mean: tuple[float, ...]
    scaler_scale: tuple[float, ...]
    imputer_medians: tuple[float, ...]
    parameters_sha256: str
    manifest_sha256: str
    artifact_sha256: dict[str, str]
    train_cutoffs: tuple[str, ...]


def load_model(experiment_dir: Path) -> ChurnModel:
    """Load the fitted logistic model from JSON only; verify every artifact checksum first."""
    experiment_dir = Path(experiment_dir)
    paths = {name: experiment_dir / name for name in _OUTPUT_NAMES}
    manifest_path = experiment_dir / "experiment_manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if (
        manifest.get("development_only") is not True
        or manifest.get("serving_ready") is not False
    ):
        raise ValueError("Development-only, non-serving manifest required")
    if manifest.get("model_version") != MODEL_VERSION:
        raise ValueError("Unexpected model version")
    expected_hashes = manifest.get("output_sha256", {})
    raw_bytes: dict[str, bytes] = {}
    for name, path in paths.items():
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if expected_hashes.get(name) != digest:
            raise ValueError(f"{name} checksum mismatch against experiment_manifest")
        raw_bytes[name] = data
    parameters_sha256 = hashlib.sha256(raw_bytes["model_parameters.json"]).hexdigest()
    parameters = json.loads(raw_bytes["model_parameters.json"].decode("utf-8"))
    report = json.loads(raw_bytes["evaluation.json"].decode("utf-8"))
    json.loads(raw_bytes["holdout_predictions.json"].decode("utf-8"))
    if (
        parameters.get("model_version") != MODEL_VERSION
        or parameters.get("feature_version") != FEATURE_VERSION
        or parameters.get("label_version") != CHRIST_VERSION
    ):
        raise ValueError("Model parameters identity/version mismatch")
    if tuple(parameters.get("features", ())) != FEATURES:
        raise ValueError("Unexpected feature contract in model parameters")
    if (
        parameters.get("development_only") is not True
        or parameters.get("serving_ready") is not False
    ):
        raise ValueError("Model parameters must stay development-only and non-serving")
    logistic = parameters.get("logistic")
    if not isinstance(logistic, dict):
        raise ValueError("Missing logistic model parameters")
    count = len(FEATURES)
    coef = _finite_numbers(logistic.get("coef"), count, allow_negative=True)
    intercept_values = logistic.get("intercept")
    if not isinstance(intercept_values, list) or len(intercept_values) != 1:
        raise ValueError("Logistic intercept must be a single-value list")
    intercept = _finite_numbers(intercept_values, 1, allow_negative=True)[0]
    scaler_mean = _finite_numbers(
        logistic.get("scaler_mean"), count, allow_negative=False
    )
    scaler_scale = _finite_numbers(
        logistic.get("scaler_scale"), count, allow_negative=False
    )
    if any(scale <= 0 for scale in scaler_scale):
        raise ValueError("Scaler scale must be strictly positive")
    imputer_medians = _finite_numbers(
        logistic.get("imputer_medians"), count, allow_negative=False
    )
    if (
        report.get("model_version") != MODEL_VERSION
        or report.get("feature_version") != FEATURE_VERSION
        or report.get("label_version") != CHRIST_VERSION
        or report.get("features") != list(FEATURES)
        or report.get("training_ready") is not False
        or report.get("experiment_ready") is not False
        or report.get("final_model") is not False
        or report.get("serving_ready") is not False
    ):
        raise ValueError("Evaluation report model identity/readiness mismatch")
    cutoffs = report.get("train_cutoffs")
    if not isinstance(cutoffs, list) or not cutoffs:
        raise ValueError("Missing training outcome availability boundary")
    for cutoff in cutoffs:
        _aware_timestamp(cutoff, "train_cutoffs")
    train_cutoffs = tuple(cutoffs)
    return ChurnModel(
        model_dir=experiment_dir,
        model_version=MODEL_VERSION,
        feature_version=FEATURE_VERSION,
        label_version=CHRIST_VERSION,
        intercept=intercept,
        coef=tuple(coef),
        scaler_mean=tuple(scaler_mean),
        scaler_scale=tuple(scaler_scale),
        imputer_medians=tuple(imputer_medians),
        parameters_sha256=parameters_sha256,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        artifact_sha256={
            name: hashlib.sha256(data).hexdigest() for name, data in raw_bytes.items()
        },
        train_cutoffs=train_cutoffs,
    )


def _aware_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an aware timestamp")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be an aware timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{field} must be an aware timestamp")
    return result


def _raw_value(row: dict, field: str) -> float:
    value = row.get(field)
    if field == "recency_days" and (value is None or value == ""):
        return math.nan
    if isinstance(value, bool) or value is None or value == "":
        raise ValueError(f"{field} must be finite numeric")
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{field} must be finite numeric") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{field} must be finite nonnegative numeric")
    return number


def _validate_row(row: dict, model: ChurnModel, *, generated_at: datetime) -> datetime:
    if not isinstance(row, dict) or set(row) != set(FEATURE_FIELDS):
        raise ValueError("Rows must exactly match the feature contract")
    customer = row.get("golden_customer_id")
    if not isinstance(customer, str) or not customer.strip():
        raise ValueError("golden_customer_id must be a nonempty string")
    if row.get("identity_status") not in {
        "PROVISIONAL",
        "REVIEW_REQUIRED",
        "APPROVED",
        "REJECTED",
        "UNKNOWN",
    }:
        raise ValueError("Unexpected identity_status")
    if row.get("feature_version") != model.feature_version:
        raise ValueError("Unexpected feature_version")
    if row.get("training_ready") is not False and row.get("training_ready") != "False":
        raise ValueError("training_ready must be False")
    if row.get("identity_time_policy") != "CURRENT_SNAPSHOT_RETROSPECTIVE":
        raise ValueError("Unexpected identity_time_policy")
    if "churn90" in row:
        raise ValueError("Ground truth labels are not allowed as predictor input")
    cutoff = _aware_timestamp(row.get("cutoff_at"), "cutoff_at").astimezone(
        LOCAL_TIMEZONE
    )
    if cutoff.utcoffset() != timedelta(hours=7):
        raise ValueError("cutoff_at must normalize to +07:00")
    if cutoff > generated_at:
        raise ValueError("cutoff_at must not be in the future of generated_at")
    if model.train_cutoffs:
        boundary = max(
            datetime.fromisoformat(c) + timedelta(days=_HORIZON_DAYS)
            for c in model.train_cutoffs
        )
        if cutoff < boundary:
            raise ValueError(
                "cutoff_at must be at or after the last training outcome availability boundary"
            )
    for field in FEATURES:
        _raw_value(row, field)
    return cutoff


def predict_rows(
    model: ChurnModel, rows: list[dict], *, generated_at: datetime
) -> list[dict]:
    """Score raw feature rows against the loaded, non-serving logistic model."""
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at must be an aware timestamp")
    generated_at = generated_at.astimezone(LOCAL_TIMEZONE)
    seen: set[tuple[str, str]] = set()
    results = []
    for row in rows:
        cutoff = _validate_row(row, model, generated_at=generated_at)
        key = (row["golden_customer_id"], cutoff.isoformat())
        if key in seen:
            raise ValueError("Duplicate customer/cutoff in prediction rows")
        seen.add(key)
        contributions = []
        log_odds = model.intercept
        for index, field in enumerate(FEATURES):
            raw = _raw_value(row, field)
            missing = math.isnan(raw)
            imputed = model.imputer_medians[index] if missing else raw
            standardized = (imputed - model.scaler_mean[index]) / model.scaler_scale[
                index
            ]
            contribution = standardized * model.coef[index]
            if not math.isfinite(contribution):
                raise ValueError(f"{field} contribution is not finite")
            log_odds += contribution
            contributions.append(
                {
                    "feature": field,
                    "feature_value": None if missing else raw,
                    "missing": missing,
                    "imputed_value": imputed,
                    "log_odds_contribution": contribution,
                }
            )
        if not math.isfinite(log_odds):
            raise ValueError("log-odds score is not finite")
        # Numerically stable sigmoid; avoids overflow for large-magnitude log-odds.
        if log_odds >= 0:
            probability = 1.0 / (1.0 + math.exp(-log_odds))
        else:
            exp_value = math.exp(log_odds)
            probability = exp_value / (1.0 + exp_value)
        results.append(
            {
                "golden_customer_id": row["golden_customer_id"],
                "cutoff_at": cutoff.isoformat(),
                "model_version": model.model_version,
                "feature_version": model.feature_version,
                "label_version": model.label_version,
                "horizon_days": _HORIZON_DAYS,
                "generated_at": generated_at.isoformat(),
                "valid_until": None,
                "training_ready": False,
                "experiment_ready": False,
                "serving_ready": False,
                "serving_blockers": ["calibration_absent", "not_approved_for_serving"],
                "model_artifact_sha256": model.parameters_sha256,
                "intercept": model.intercept,
                "log_odds": log_odds,
                "churn_probability": probability,
                "contributions": contributions,
                "explanation_method": EXPLANATION_METHOD,
            }
        )
    return results


def run(
    model_dir: Path, features_dir: Path, output_dir: Path, generated_at: datetime
) -> dict:
    if output_dir.exists():
        raise ValueError("Use a new output directory")
    model_dir, features_dir, output_dir = (
        Path(model_dir).resolve(),
        Path(features_dir).resolve(),
        Path(output_dir).resolve(),
    )
    parts = model_dir.parts + features_dir.parts + output_dir.parts
    if any(part.lower() == "ground_truth" for part in parts):
        raise ValueError("ground_truth paths are not allowed")
    for other in (model_dir, features_dir):
        if (
            output_dir == other
            or output_dir in other.parents
            or other in output_dir.parents
        ):
            raise ValueError("Keep input and output directories separate")
    model = load_model(model_dir)
    feature_paths = {
        name: features_dir / name for name in ("feature_manifest.json", "features.csv")
    }
    before = {name: sha256(path) for name, path in feature_paths.items()}
    feature_manifest = json.loads(
        feature_paths["feature_manifest.json"].read_text(encoding="utf-8")
    )
    if feature_manifest.get("feature_version") != model.feature_version:
        raise ValueError("Feature manifest version does not match the loaded model")
    if feature_manifest.get("training_ready") is not False:
        raise ValueError("Feature manifest must be training_ready=False")
    if (
        feature_manifest.get("output_sha256", {}).get("features.csv")
        != before["features.csv"]
    ):
        raise ValueError("features.csv checksum mismatch against feature_manifest")
    with feature_paths["features.csv"].open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != FEATURE_FIELDS:
            raise ValueError("Unexpected feature columns")
        rows = list(reader)
    if len(rows) != feature_manifest.get("rows"):
        raise ValueError("Feature row count mismatch")
    predictions = predict_rows(model, rows, generated_at=generated_at)
    after = {name: sha256(path) for name, path in feature_paths.items()}
    if after != before:
        raise ValueError("Input changed during prediction")
    model_files = {
        "experiment_manifest.json": model.manifest_sha256,
        **model.artifact_sha256,
    }
    if any(sha256(model_dir / name) != digest for name, digest in model_files.items()):
        raise ValueError("Model artifacts changed during prediction")
    output_dir.mkdir(parents=True)
    (output_dir / "predictions.json").write_text(
        json.dumps(predictions, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    manifest = dict(
        model_version=model.model_version,
        feature_version=model.feature_version,
        label_version=model.label_version,
        development_only=True,
        serving_ready=False,
        training_ready=False,
        experiment_ready=False,
        generated_at=generated_at.astimezone(LOCAL_TIMEZONE).isoformat(),
        model_artifact_sha256=model.parameters_sha256,
        rows=len(predictions),
        input_sha256=before,
        input_sha256_after=after,
        output_sha256={"predictions.json": sha256(output_dir / "predictions.json")},
        limitations=[
            "Transparent demo logistic scorer for inspection only; not approved for serving",
            "No calibration artifact; probabilities are raw, uncalibrated model outputs",
            "Explanations are mathematical log-odds contributions, not causal reason codes",
            "Offline only; this is not an I-04 prediction handoff",
        ],
    )
    (output_dir / "prediction_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--features-dir", type=Path, required=True)
    parser.add_argument("--generated-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.model_dir, args.features_dir, args.output_dir, args.generated_at)
    print(
        json.dumps({"rows": result["rows"], "serving_ready": result["serving_ready"]})
    )


if __name__ == "__main__":
    main()
