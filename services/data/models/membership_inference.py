"""Development-only, feature-only offline scoring of saved membership experiment JSON.

No fit, calibration, executable deserialization, labels, or serving handoff. Signed
log-odds contributions describe the saved logistic model, not causal reason codes.
"""

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from services.data.models import renewal_membership_experiment as membership
from services.data.models.evaluator import _aware_timestamp
from services.data.models.membership_features import FIELDS
from services.data.models.model_importance import _logistic, _numbers, _scores

EXPLANATION_METHOD = (
    "Exact signed log-odds contribution: "
    "(imputed_value - scaler_mean) / scaler_scale * coefficient; "
    "mathematical decomposition only, not causal and not a business reason code"
)


@dataclass(frozen=True)
class MembershipModel:
    """Validated numeric JSON snapshot, never an executable estimator."""

    model_version: str
    intercept: float
    coef: tuple[float, ...]
    scaler_mean: tuple[float, ...]
    scaler_scale: tuple[float, ...]
    imputer_medians: tuple[float, ...]
    parameters_sha256: str
    manifest_sha256: str
    artifact_sha256: dict[str, str]


def _contract(value: object, *, features: bool = False) -> None:
    if not isinstance(value, dict):
        raise ValueError("Membership artifact must be an object")
    for key, expected in {**membership.IDENTITY, **membership.STATUS}.items():
        if type(value.get(key)) is not type(expected) or value[key] != expected:
            raise ValueError("Unexpected membership identity/status contract")
    if features and value.get("features") != list(membership.FEATURES):
        raise ValueError("Unexpected membership feature contract")


def _safe_path(path: Path) -> Path:
    path = Path(path)
    if any(
        part.lower() == "ground_truth" for part in path.parts + path.resolve().parts
    ):
        raise ValueError("ground_truth paths are not allowed")
    return path.resolve()


def load_model(experiment_dir: Path) -> MembershipModel:
    """Verify saved artifact checksums and contracts; read JSON bytes only.

    Hashes bind the exact bytes parsed here. They detect changes, not authenticate
    an untrusted producer or confer model/serving approval.
    """
    experiment_dir = _safe_path(experiment_dir)
    manifest_bytes = _safe_path(
        experiment_dir / "experiment_manifest.json"
    ).read_bytes()
    manifest = json.loads(manifest_bytes)
    _contract(manifest)
    before, after = manifest.get("input_sha256"), manifest.get("input_sha256_after")
    if (
        not isinstance(before, dict)
        or not isinstance(after, dict)
        or not before
        or not all(isinstance(v, str) for v in before.values())
        or set(before)
        != {
            "propensity_manifest.json",
            "propensity_labels.csv",
            "membership_manifest.json",
            "membership_features.csv",
        }
        or before != after
    ):
        raise ValueError("Membership input checksum contract mismatch")
    hashes = manifest.get("output_sha256")
    if not isinstance(hashes, dict) or set(hashes) != set(membership.OUTPUTS):
        raise ValueError("Unexpected membership artifact checksum contract")
    artifacts, digests = {}, {}
    for name in membership.OUTPUTS:
        raw = _safe_path(experiment_dir / name).read_bytes()
        digests[name] = hashlib.sha256(raw).hexdigest()
        if hashes[name] != digests[name]:
            raise ValueError(f"{name} checksum mismatch")
        artifacts[name] = json.loads(raw)
    parameters = artifacts["model_parameters.json"]
    _contract(parameters, features=True)
    _contract(artifacts["evaluation.json"], features=True)
    predictions = artifacts["holdout_predictions.json"]
    if not isinstance(predictions, list):
        raise ValueError("Holdout predictions must be a list")
    for row in predictions:
        _contract(row)
    # Reuse the same finite scalar/vector and strictly-positive-scale validation
    # and numeric scorer as offline membership importance diagnostics.
    try:
        _, numeric = _logistic(parameters)
    except (OverflowError, TypeError) as exc:
        raise ValueError("Invalid membership numeric parameters") from exc
    return MembershipModel(
        model_version=parameters["model_version"],
        intercept=numeric["intercept"],
        coef=tuple(numeric["coef"]),
        scaler_mean=tuple(numeric["scaler_mean"]),
        scaler_scale=tuple(numeric["scaler_scale"]),
        imputer_medians=tuple(numeric["imputer_medians"]),
        parameters_sha256=digests["model_parameters.json"],
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        artifact_sha256=digests,
    )


def predict_rows(
    model: MembershipModel, rows: list[dict], *, generated_at: datetime
) -> list[dict]:
    """Score exact membership feature rows; never accept outcomes as input.

    Missing membership values use saved training medians. No shared business-label
    formatter is used: these are raw, uncalibrated renewal60 probabilities only.
    """
    if not isinstance(generated_at, datetime) or generated_at.utcoffset() is None:
        raise ValueError("generated_at must be an aware timestamp")
    generated_at = generated_at.astimezone(membership.LOCAL_TIMEZONE)
    seen: set[tuple[str, datetime]] = set()
    cutoffs: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(FIELDS):
            raise ValueError(
                "Rows must exactly match membership feature FIELDS; no labels"
            )
        customer = row["golden_customer_id"]
        if not isinstance(customer, str) or not customer.strip():
            raise ValueError("golden_customer_id must be a nonempty string")
        if row["feature_version"] != membership.MEMBERSHIP_FEATURE_VERSION:
            raise ValueError("Unexpected membership feature version")
        if membership._flag(row["training_ready"], "training_ready"):
            raise ValueError("training_ready must be False")
        membership._flag(row["has_membership_history"], "has_membership_history")
        cutoff = _aware_timestamp(row["cutoff_at"], "cutoff_at")
        if cutoff > generated_at:
            raise ValueError("cutoff_at must be <= generated_at")
        key = customer, cutoff
        if key in seen:
            raise ValueError("Duplicate customer/cutoff key")
        seen.add(key)
        cutoffs.append(cutoff.astimezone(membership.LOCAL_TIMEZONE).isoformat())
    matrix = membership._matrix(rows)
    # The dataclass is public and mutable via replace(): revalidate numeric shape,
    # finiteness and strictly positive scale before scoring.
    count = len(membership.FEATURES)
    try:
        numeric: dict = {
            "intercept": _numbers([model.intercept], 1)[0],
            "coef": _numbers(list(model.coef), count),
            "scaler_mean": _numbers(list(model.scaler_mean), count),
            "scaler_scale": _numbers(list(model.scaler_scale), count),
            "imputer_medians": _numbers(list(model.imputer_medians), count),
        }
    except (OverflowError, TypeError) as exc:
        raise ValueError("Invalid membership numeric parameters") from exc
    if any(value <= 0 for value in numeric["scaler_scale"]):
        raise ValueError("Scaler scale must be strictly positive")
    probabilities = _scores(numeric, matrix)
    results = []
    for row, cutoff_text, values, probability in zip(
        rows, cutoffs, matrix, probabilities
    ):
        contributions = []
        log_odds = numeric["intercept"]
        for index, (field, raw) in enumerate(zip(membership.FEATURES, values)):
            missing = math.isnan(raw)
            imputed = numeric["imputer_medians"][index] if missing else raw
            contribution = (
                (imputed - numeric["scaler_mean"][index])
                / numeric["scaler_scale"][index]
                * numeric["coef"][index]
            )
            if not math.isfinite(contribution):
                raise ValueError("Membership contribution must be finite")
            log_odds += contribution
            contributions.append(
                dict(
                    feature=field,
                    feature_value=None if missing else raw,
                    missing=missing,
                    imputed_value=imputed,
                    log_odds_contribution=contribution,
                )
            )
        results.append(
            {
                **membership.IDENTITY,
                **membership.STATUS,
                "model_version": model.model_version,
                "golden_customer_id": row["golden_customer_id"],
                "cutoff_at": cutoff_text,
                "generated_at": generated_at.isoformat(),
                "identity_time_policy": "CURRENT_SNAPSHOT_RETROSPECTIVE",
                "limitations": list(membership.LIMITATIONS),
                "refitted": False,
                "model_artifact_sha256": model.parameters_sha256,
                "manifest_sha256": model.manifest_sha256,
                "intercept": numeric["intercept"],
                "log_odds": log_odds,
                "raw_probability": probability,
                "contributions": contributions,
                "explanation_method": EXPLANATION_METHOD,
            }
        )
    return results
