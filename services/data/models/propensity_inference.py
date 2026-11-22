"""JSON-only offline propensity reload; POS-only, retrospective, never serving.

Scores every feature snapshot row, not a target-eligible or campaign-eligible
population. No labels, calibration, reason codes, approval, or NBA adapter.
"""

import argparse
import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.data.features.snapshot import FIELDS as FEATURE_FIELDS
from services.data.features.snapshot import VERSION as FEATURE_VERSION
from services.data.ingestion.validator import sha256
from services.data.models.churn_experiment import FEATURES
from services.data.models.evaluator import _aware_timestamp
from services.data.models.propensity_experiment import (
    MODEL_VERSION,
    _check_target,
    limitations,
)
from services.data.models.score_explanations import explain_contributions

LOCAL_TIMEZONE = timezone(timedelta(hours=7))
LIMITATIONS = [
    "Full feature snapshot universe; not target eligibility or campaign eligibility",
    "Retrospective inspection includes training-era rows; not prospective evaluation",
    "No calibration; probabilities are uncalibrated",
    "No reason codes, approval, serving handoff, or NBA adapter",
]
EXPLANATION_VERSION = "moses-propensity-log-odds-dev-1.1"
EXPLANATION_METHOD = (
    "Exact signed log-odds contribution per feature: "
    "(imputed_value - scaler_mean) / scaler_scale * coefficient. "
    "Mathematical decomposition of the logistic score only; not causal and not "
    "a business reason code."
)


def _strict_json(path: Path) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject(value):
        raise ValueError(f"Nonfinite JSON number: {value}")

    def number(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            reject(value)
        return parsed

    result = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=pairs,
        parse_constant=reject,
        parse_float=number,
    )
    if not isinstance(result, dict):
        raise ValueError("Expected a JSON object")
    return result


def _numbers(value, count: int) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != count:
        raise ValueError("Invalid model parameter dimensions")
    result = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError("Model parameters must be numeric")
        try:
            item = float(item)
        except OverflowError as exc:
            raise ValueError("Model parameters must be finite") from exc
        if not math.isfinite(item):
            raise ValueError("Model parameters must be finite")
        result.append(item)
    return tuple(result)


@dataclass(frozen=True)
class PropensityModel:
    target: str
    target_version: str
    horizon_days: int
    intercept: float
    coef: tuple[float, ...]
    imputer_medians: tuple[float, ...]
    scaler_mean: tuple[float, ...]
    scaler_scale: tuple[float, ...]
    parameters_sha256: str
    manifest_sha256: str


def _no_ground_truth(*paths: Path) -> None:
    if any(part.lower() == "ground_truth" for p in paths for part in p.parts):
        raise ValueError("ground_truth paths are not allowed")


def load_model(model_dir: Path, target: str) -> PropensityModel:
    """Load a selected target's non-executable JSON parameters, never sklearn."""
    version, horizon = _check_target(target)
    model_dir = Path(model_dir).resolve()
    _no_ground_truth(model_dir)
    manifest_path = model_dir / "experiment_manifest.json"
    parameter_path = model_dir / "model_parameters.json"
    before = (sha256(manifest_path), sha256(parameter_path))
    manifest = _strict_json(manifest_path)
    hashes = manifest.get("output_sha256")
    if not isinstance(hashes, dict) or hashes.get(parameter_path.name) != before[1]:
        raise ValueError("Model parameter checksum mismatch")
    params = _strict_json(parameter_path)
    for artifact in (manifest, params):
        if (
            artifact.get("model_version") != MODEL_VERSION
            or artifact.get("feature_version") != FEATURE_VERSION
            or artifact.get("target") != target
            or artifact.get("target_version") != version
            or artifact.get("development_only") is not True
            or artifact.get("serving_ready") is not False
        ):
            raise ValueError("Model identity/version/target or readiness mismatch")
    if type(params.get("horizon_days")) is not int or params["horizon_days"] != horizon:
        raise ValueError("Unexpected target horizon")
    if any(
        manifest.get(flag) is not False
        for flag in ("training_ready", "experiment_ready", "final_model")
    ):
        raise ValueError("Development-only manifest required")
    if params.get("features") != list(FEATURES):
        raise ValueError("Unexpected feature contract")
    logistic = params.get("logistic")
    if not isinstance(logistic, dict):
        raise ValueError("Missing logistic parameters")
    count = len(FEATURES)
    vectors = {
        key: _numbers(logistic.get(key), count)
        for key in ("coef", "imputer_medians", "scaler_mean", "scaler_scale")
    }
    if any(v <= 0 for v in vectors["scaler_scale"]):
        raise ValueError("Scaler scale must be positive")
    if any(v < 0 for key in ("imputer_medians", "scaler_mean") for v in vectors[key]):
        raise ValueError("Imputer medians and means must be nonnegative")
    intercept = _numbers(logistic.get("intercept"), 1)[0]
    if before != (sha256(manifest_path), sha256(parameter_path)):
        raise ValueError("Model input changed during load")
    return PropensityModel(
        target,
        version,
        horizon,
        intercept,
        parameters_sha256=before[1],
        manifest_sha256=before[0],
        **vectors,
    )


def _raw(row: dict, field: str) -> float | None:
    value = row[field]
    if field == "recency_days" and (value is None or value == ""):
        return None
    if isinstance(value, bool) or value is None or value == "":
        raise ValueError(f"{field} must be finite nonnegative numeric")
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be finite nonnegative numeric") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{field} must be finite nonnegative numeric")
    return value


def predict_rows(
    model: PropensityModel, rows: list[dict], *, generated_at: datetime
) -> list[dict]:
    """Pure feature-only scoring; no eligibility filtering or future-use claim."""
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at must be aware")
    generated_at = generated_at.astimezone(LOCAL_TIMEZONE)
    results, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(FEATURE_FIELDS):
            raise ValueError(
                "Rows must exactly match feature contract; labels forbidden"
            )
        customer = row["golden_customer_id"]
        if not isinstance(customer, str) or not customer.strip():
            raise ValueError("Missing golden_customer_id")
        if row["identity_status"] not in {
            "PROVISIONAL",
            "REVIEW_REQUIRED",
            "APPROVED",
            "REJECTED",
            "UNKNOWN",
        }:
            raise ValueError("Unexpected identity_status")
        if (
            row["feature_version"] != FEATURE_VERSION
            or row["identity_time_policy"] != "CURRENT_SNAPSHOT_RETROSPECTIVE"
        ):
            raise ValueError("Unexpected feature version or identity time policy")
        if row["training_ready"] is not False and row["training_ready"] != "False":
            raise ValueError("training_ready must be False")
        cutoff = _aware_timestamp(row["cutoff_at"], "cutoff_at").astimezone(
            LOCAL_TIMEZONE
        )
        if cutoff > generated_at:
            raise ValueError("cutoff_at must not be in future")
        key = (customer, cutoff.isoformat())
        if key in seen:
            raise ValueError("Duplicate customer/cutoff")
        seen.add(key)
        log_odds = model.intercept
        contributions = []
        for i, field in enumerate(FEATURES):
            raw = _raw(row, field)
            imputed = model.imputer_medians[i] if raw is None else raw
            contribution = (
                (imputed - model.scaler_mean[i]) / model.scaler_scale[i]
            ) * model.coef[i]
            if not math.isfinite(contribution):
                raise ValueError("Nonfinite model contribution")
            log_odds += contribution
            contributions.append(
                dict(
                    feature=field,
                    feature_value=raw,
                    missing=raw is None,
                    imputed_value=imputed,
                    log_odds_contribution=contribution,
                )
            )
        if not math.isfinite(log_odds):
            raise ValueError("Nonfinite log odds")
        probability = (
            1 / (1 + math.exp(-log_odds))
            if log_odds >= 0
            else math.exp(log_odds) / (1 + math.exp(log_odds))
        )
        results.append(
            dict(
                golden_customer_id=customer,
                cutoff_at=cutoff.isoformat(),
                target=model.target,
                target_version=model.target_version,
                horizon_days=model.horizon_days,
                model_version=MODEL_VERSION,
                feature_version=FEATURE_VERSION,
                generated_at=generated_at.isoformat(),
                uncalibrated_probability=probability,
                intercept=model.intercept,
                log_odds=log_odds,
                feature_contributions=contributions,
                explanation_method=EXPLANATION_METHOD,
                explanation_version=EXPLANATION_VERSION,
                score_explanation=explain_contributions(
                    contributions, target=model.target
                ),
                development_only=True,
                serving_ready=False,
                valid_until=None,
                model_artifact_sha256=model.parameters_sha256,
                limitations=[*limitations(model.target), *LIMITATIONS],
            )
        )
    return results


def run(
    model_dir: Path,
    features_dir: Path,
    target: str,
    output_dir: Path,
    *,
    generated_at: datetime | None = None,
) -> dict:
    _check_target(target)
    paths = tuple(Path(p).resolve() for p in (model_dir, features_dir, output_dir))
    model_dir, features_dir, output_dir = paths
    _no_ground_truth(*paths)
    if output_dir.exists():
        raise ValueError("Use a new output directory")
    for source in (model_dir, features_dir):
        if source in output_dir.parents or output_dir in source.parents:
            raise ValueError("Keep inputs and output separate")
    model = load_model(model_dir, target)
    inputs = {
        "feature_manifest.json": features_dir / "feature_manifest.json",
        "features.csv": features_dir / "features.csv",
        "experiment_manifest.json": model_dir / "experiment_manifest.json",
        "model_parameters.json": model_dir / "model_parameters.json",
    }
    before = {name: sha256(path) for name, path in inputs.items()}
    if (
        before["experiment_manifest.json"] != model.manifest_sha256
        or before["model_parameters.json"] != model.parameters_sha256
    ):
        raise ValueError("Model input changed after load")
    manifest = _strict_json(inputs["feature_manifest.json"])
    if (
        manifest.get("feature_version") != FEATURE_VERSION
        or manifest.get("training_ready") is not False
    ):
        raise ValueError("Unexpected feature manifest version or readiness")
    hashes = manifest.get("output_sha256")
    if (
        not isinstance(hashes, dict)
        or hashes.get("features.csv") != before["features.csv"]
    ):
        raise ValueError("Feature checksum mismatch")
    with inputs["features.csv"].open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != FEATURE_FIELDS:
            raise ValueError("Unexpected feature columns")
        rows = list(reader)
    if type(manifest.get("rows")) is not int or len(rows) != manifest["rows"]:
        raise ValueError("Feature row count mismatch")
    cutoffs = manifest.get("cutoffs")
    if not isinstance(cutoffs, list) or not cutoffs:
        raise ValueError("Missing feature cutoffs")
    expected = {_aware_timestamp(c, "cutoffs") for c in cutoffs}
    if len(expected) != len(cutoffs) or expected != {
        _aware_timestamp(r["cutoff_at"], "cutoff_at") for r in rows
    }:
        raise ValueError("Feature cutoff mismatch")
    generated_at = generated_at or datetime.now(LOCAL_TIMEZONE)
    predictions = predict_rows(model, rows, generated_at=generated_at)
    after = {name: sha256(path) for name, path in inputs.items()}
    if after != before:
        raise ValueError("Input changed during prediction")
    output_dir.mkdir(parents=True)
    prediction_path = output_dir / "predictions.json"
    prediction_path.write_text(
        json.dumps(predictions, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    result = dict(
        target=target,
        target_version=model.target_version,
        horizon_days=model.horizon_days,
        model_version=MODEL_VERSION,
        feature_version=FEATURE_VERSION,
        explanation_version=EXPLANATION_VERSION,
        development_only=True,
        serving_ready=False,
        valid_until=None,
        rows=len(predictions),
        generated_at=generated_at.astimezone(LOCAL_TIMEZONE).isoformat(),
        input_sha256=before,
        input_sha256_after=after,
        output_sha256={"predictions.json": sha256(prediction_path)},
        limitations=[*limitations(target), *LIMITATIONS],
    )
    (output_dir / "prediction_manifest.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--features-dir", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.model_dir, args.features_dir, args.target, args.output_dir)
    print(
        json.dumps(
            {"target": result["target"], "rows": result["rows"], "serving_ready": False}
        )
    )


if __name__ == "__main__":
    main()
