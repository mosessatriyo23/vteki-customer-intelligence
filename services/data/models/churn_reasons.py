"""Development-only mapping of exact logistic log-odds contributions to proposed reason codes.

Input is a prediction produced by `services.data.models.churn_inference.predict_rows`.
Each reason is a mathematical attribution of the chosen linear model: the signed
log-odds contribution of one feature. Nothing here is causal, approved, or
customer-facing.

Code naming
-----------
Codes are named strictly for what the seven features actually measure (purchase
recency, purchase frequency over 60/90/365 days, retained revenue over 90/365
days, tenure). No code claims visits, membership expiry, complaints, or spend
decline, because no feature in this model proves them.

Direction, not thresholds
-------------------------
A reason carries a separate `direction` field derived ONLY from the sign of
`log_odds_contribution`: positive means the feature value pushed churn risk UP
relative to the model's training mean in this linear model
(`INCREASES_RISK`), negative means it pushed risk DOWN (`DECREASES_RISK`).
Deliberately no `_LOW`/`_HIGH` suffix is used: such a suffix would read as a
comparison against an approved business threshold, and none exists. Direction is
model influence only, never a statement that a value is above or below any
approved business boundary.

Selection
---------
Reasons are ranked by absolute contribution descending regardless of direction,
and a reason only qualifies when its absolute contribution is at least
`MIN_ABS_CONTRIBUTION` (a development convention, not an approved threshold).
Features whose value was missing and imputed are excluded entirely: an imputed
median must never be presented as an observed fact. They are reported under
`excluded_imputed` with no code. If fewer than `min_reasons` distinct features
qualify, status is `INSUFFICIENT_EXPLANATION` and only the qualifying reasons
are listed; a reason is never duplicated or fabricated to reach the minimum.

Faithfulness
------------
`explain()` rejects any prediction whose `intercept + sum(contributions)` does
not reconstruct the reported `log_odds`, and any prediction whose versions do
not match the currently imported model/feature/label versions.
"""

import argparse
import json
import math
from pathlib import Path

from services.data.features.snapshot import VERSION as FEATURE_VERSION
from services.data.ingestion.validator import sha256
from services.data.models.churn_experiment import FEATURES, MODEL_VERSION
from services.data.models.labels import CHRIST_VERSION

REASON_MAPPING_VERSION = "moses-churn-reason-map-proposed-dev-1.0"
REASON_METHOD = "logistic_exact_log_odds_contribution"
#: Development convention only: a |log-odds| floor below which an attribution is
#: too small to present as a reason. Not an approved business threshold.
MIN_ABS_CONTRIBUTION = 0.05
MIN_REASON_CODES = 3
RECONSTRUCTION_TOLERANCE = 1e-9

#: Fixed allowlist: exactly one proposed code per model feature.
REASON_CODES = {
    "recency_days": "PURCHASE_RECENCY",
    "tenure_days": "TENURE",
    "purchase_count_365d": "PURCHASE_FREQUENCY_365D",
    "retained_revenue_365d": "RETAINED_REVENUE_365D",
    "purchase_count_60d": "PURCHASE_FREQUENCY_60D",
    "purchase_count_90d": "PURCHASE_FREQUENCY_90D",
    "retained_revenue_90d": "RETAINED_REVENUE_90D",
}
INCREASES_RISK = "INCREASES_RISK"
DECREASES_RISK = "DECREASES_RISK"
LIMITATIONS = (
    "Mathematical attribution of a linear model, not causal",
    "Codes proposed pending Christ taxonomy approval; approved_taxonomy=false",
    "No PIT guarantee: feature effective_at/known_at provenance is not carried here",
    "Development-only; not an I-04 prediction handoff and not customer-facing",
)
_REQUIRED_KEYS = (
    "golden_customer_id",
    "cutoff_at",
    "model_version",
    "feature_version",
    "label_version",
    "intercept",
    "log_odds",
    "contributions",
)
_CONTRIBUTION_KEYS = (
    "feature",
    "feature_value",
    "missing",
    "imputed_value",
    "log_odds_contribution",
)


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    return number


def _nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value


def _validate_prediction(prediction: object) -> list[dict]:
    if not isinstance(prediction, dict):
        raise ValueError("prediction must be a mapping")
    for key in _REQUIRED_KEYS:
        if key not in prediction:
            raise ValueError(f"prediction is missing required key {key}")
    _nonempty_string(prediction["golden_customer_id"], "golden_customer_id")
    _nonempty_string(prediction["cutoff_at"], "cutoff_at")
    if prediction["model_version"] != MODEL_VERSION:
        raise ValueError("prediction model_version does not match the imported model")
    if prediction["feature_version"] != FEATURE_VERSION:
        raise ValueError("prediction feature_version does not match the imported model")
    if prediction["label_version"] != CHRIST_VERSION:
        raise ValueError("prediction label_version does not match the imported model")
    intercept = _finite(prediction["intercept"], "intercept")
    log_odds = _finite(prediction["log_odds"], "log_odds")
    contributions = prediction["contributions"]
    if not isinstance(contributions, list) or len(contributions) != len(FEATURES):
        raise ValueError("contributions must cover the seven model features once each")
    validated: list[dict] = []
    seen: set[str] = set()
    for item in contributions:
        if not isinstance(item, dict) or set(item) != set(_CONTRIBUTION_KEYS):
            raise ValueError("Unexpected contribution shape")
        feature = item["feature"]
        if feature not in REASON_CODES:
            raise ValueError(f"Unmapped feature in contributions: {feature!r}")
        if feature in seen:
            raise ValueError(f"Duplicate feature in contributions: {feature}")
        seen.add(feature)
        missing = item["missing"]
        if not isinstance(missing, bool):
            raise ValueError("contribution missing flag must be a boolean")
        value = item["feature_value"]
        if missing:
            if value is not None:
                raise ValueError("A missing feature must not carry an observed value")
        else:
            _finite(value, f"{feature} feature_value")
        imputed = _finite(item["imputed_value"], f"{feature} imputed_value")
        if not missing and imputed != value:
            raise ValueError("An observed feature must equal its scored value")
        contribution = _finite(
            item["log_odds_contribution"], f"{feature} log_odds_contribution"
        )
        validated.append({**item, "log_odds_contribution": contribution})
    if seen != set(FEATURES):
        raise ValueError("contributions must cover the seven model features once each")
    total = intercept + math.fsum(item["log_odds_contribution"] for item in validated)
    tolerance = RECONSTRUCTION_TOLERANCE * max(1.0, abs(log_odds), abs(total))
    if abs(total - log_odds) > tolerance:
        raise ValueError(
            "Contributions do not reconstruct log_odds; refusing to explain an "
            "unfaithful prediction"
        )
    return validated


def explain(
    prediction: dict,
    *,
    min_reasons: int = MIN_REASON_CODES,
    min_abs_contribution: float = MIN_ABS_CONTRIBUTION,
) -> dict:
    """Map one prediction's log-odds contributions to proposed reason codes."""
    if not isinstance(min_reasons, int) or isinstance(min_reasons, bool):
        raise ValueError("min_reasons must be a positive integer")
    if min_reasons < 1:
        raise ValueError("min_reasons must be a positive integer")
    floor = _finite(min_abs_contribution, "min_abs_contribution")
    if floor <= 0:
        raise ValueError("min_abs_contribution must be strictly positive")
    contributions = _validate_prediction(prediction)
    reasons: list[dict] = []
    excluded_imputed: list[dict] = []
    excluded_below_threshold: list[dict] = []
    for item in sorted(
        contributions,
        key=lambda c: (-abs(c["log_odds_contribution"]), FEATURES.index(c["feature"])),
    ):
        feature = item["feature"]
        contribution = item["log_odds_contribution"]
        if item["missing"]:
            excluded_imputed.append(
                {
                    "feature": feature,
                    "reason": "value missing; imputed median is not an observed fact",
                    "imputed_value": item["imputed_value"],
                    "log_odds_contribution": contribution,
                }
            )
            continue
        if abs(contribution) < floor:
            excluded_below_threshold.append(
                {
                    "feature": feature,
                    "reason": "absolute contribution below the development floor",
                    "log_odds_contribution": contribution,
                }
            )
            continue
        reasons.append(
            {
                "code": REASON_CODES[feature],
                "feature": feature,
                "direction": INCREASES_RISK if contribution > 0 else DECREASES_RISK,
                "log_odds_contribution": contribution,
                "feature_value": item["feature_value"],
                "missing": False,
                "imputed_value": item["imputed_value"],
                "feature_version": FEATURE_VERSION,
                "method": REASON_METHOD,
                "mapping_version": REASON_MAPPING_VERSION,
            }
        )
    excluded_below_threshold.sort(key=lambda item: FEATURES.index(item["feature"]))
    status = "OK" if len(reasons) >= min_reasons else "INSUFFICIENT_EXPLANATION"
    return {
        "golden_customer_id": prediction["golden_customer_id"],
        "cutoff_at": prediction["cutoff_at"],
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "label_version": CHRIST_VERSION,
        "mapping_version": REASON_MAPPING_VERSION,
        "method": REASON_METHOD,
        "min_reasons": min_reasons,
        "min_abs_contribution": floor,
        "status": status,
        "reasons": reasons,
        "excluded_imputed": excluded_imputed,
        "excluded_below_threshold": excluded_below_threshold,
        "development_only": True,
        "approved_taxonomy": False,
        "display_text": None,
        "limitations": list(LIMITATIONS),
    }


def _summary(results: list[dict]) -> dict:
    distribution: dict[str, int] = {}
    for result in results:
        for reason in result["reasons"][:3]:
            distribution[reason["code"]] = distribution.get(reason["code"], 0) + 1
    return {
        "total": len(results),
        "OK": sum(result["status"] == "OK" for result in results),
        "INSUFFICIENT_EXPLANATION": sum(
            result["status"] == "INSUFFICIENT_EXPLANATION" for result in results
        ),
        "top3_code_distribution": dict(sorted(distribution.items())),
    }


def run(predictions_dir: Path, output_dir: Path) -> dict:
    """Map an inference output directory to a new reasons output directory."""
    if Path(output_dir).exists():
        raise ValueError("Use a new output directory")
    predictions_dir = Path(predictions_dir).resolve()
    output_dir = Path(output_dir).resolve()
    if any(
        part.lower() == "ground_truth"
        for part in predictions_dir.parts + output_dir.parts
    ):
        raise ValueError("ground_truth paths are not allowed")
    if (
        output_dir == predictions_dir
        or output_dir in predictions_dir.parents
        or predictions_dir in output_dir.parents
    ):
        raise ValueError("Keep input and output directories separate")
    paths = {
        name: predictions_dir / name
        for name in ("prediction_manifest.json", "predictions.json")
    }
    before = {name: sha256(path) for name, path in paths.items()}
    manifest = json.loads(paths["prediction_manifest.json"].read_text(encoding="utf-8"))
    if (
        manifest.get("development_only") is not True
        or manifest.get("serving_ready") is not False
    ):
        raise ValueError("Development-only, non-serving prediction manifest required")
    if (
        manifest.get("output_sha256", {}).get("predictions.json")
        != before["predictions.json"]
    ):
        raise ValueError("predictions.json checksum mismatch against manifest")
    predictions = json.loads(paths["predictions.json"].read_text(encoding="utf-8"))
    if not isinstance(predictions, list) or not predictions:
        raise ValueError("predictions.json must hold a nonempty list")
    if "rows" in manifest and manifest["rows"] != len(predictions):
        raise ValueError("Prediction row count mismatch against manifest")
    results = [explain(prediction) for prediction in predictions]
    after = {name: sha256(path) for name, path in paths.items()}
    if after != before:
        raise ValueError("Input changed during reason mapping")
    output_dir.mkdir(parents=True)
    (output_dir / "reasons.json").write_text(
        json.dumps(results, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    out_manifest = dict(
        model_version=MODEL_VERSION,
        feature_version=FEATURE_VERSION,
        label_version=CHRIST_VERSION,
        mapping_version=REASON_MAPPING_VERSION,
        method=REASON_METHOD,
        min_reasons=MIN_REASON_CODES,
        min_abs_contribution=MIN_ABS_CONTRIBUTION,
        development_only=True,
        approved_taxonomy=False,
        serving_ready=False,
        input_sha256=before,
        input_sha256_after=after,
        output_sha256={"reasons.json": sha256(output_dir / "reasons.json")},
        summary=_summary(results),
        limitations=list(LIMITATIONS),
    )
    (output_dir / "reasons_manifest.json").write_text(
        json.dumps(out_manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return out_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Proposed, development-only reasons")
    parser.add_argument("--predictions-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.predictions_dir, args.output_dir)
    print(json.dumps({"summary": result["summary"], "serving_ready": False}))


if __name__ == "__main__":
    main()
