"""Moses-only fitted propensity comparison on synthetic retrospective rows.

Two PROPOSED targets (retail_purchase30, renewal60) are trained and reported
independently; no model, score, or reason is shared. Booking is
UNSUPPORTED_SOURCE. Not point-in-time safe, calibrated, approved, or usable for
serving. Install requirements-models.txt only in a development environment.
"""

import argparse
import csv
import json
import math
from datetime import timedelta
from pathlib import Path

from services.data.features.snapshot import FIELDS as FEATURE_FIELDS
from services.data.features.snapshot import VERSION as FEATURE_VERSION
from services.data.ingestion.validator import sha256
from services.data.models.baseline import temporal_split
from services.data.models.churn_diagnostics import _metrics, _operating, _reliability
from services.data.models.churn_experiment import (
    FEATURES,
    LOCAL_TIMEZONE,
    SEED,
    _matrix,
)
from services.data.models.evaluator import _aware_timestamp, _binary
from services.data.models.propensity_labels import (
    BOOKING_TARGET,
    TARGETS,
    UNSUPPORTED_SOURCE,
    join_propensity_training_rows,
)
from services.data.models.propensity_labels import (
    FIELDS as LABEL_FIELDS,
)

MODEL_VERSION = "moses-fitted-propensity-dev-1.0"
# Development conventions fixed before any holdout was seen; never tuned.
RULES = {
    "retail_purchase30": "recency_days <= 30 -> 1 else 0",
    "renewal60": "purchase_count_90d >= 1 -> 1 else 0",
}
MODELS = ("logistic", "base_rate", "fixed_rule")
OUTPUTS = ("evaluation.json", "holdout_predictions.json", "model_parameters.json")
COMMON_LIMITATIONS = [
    "Synthetic development cohort only; not population or production performance",
    "Retrospective identity; features are not point-in-time (PIT) safe",
    "Raw probabilities are uncalibrated; reliability and ECE are descriptive only",
    "Target labels are PROPOSED pending Christ's approval",
    "Observational comparison only; no causal or campaign-effect claims",
    "Fixed threshold 0.5 only; no holdout threshold tuning; fixed rule is an "
    "untuned development convention",
    "Not I-04 compliant; no reason codes are produced; valid_until is null",
    "Features are POS-purchase behavior only; no membership attributes are used",
]
TARGET_LIMITATIONS = {
    "retail_purchase30": [
        "Features overlap the label's own purchase behavior (the outcome is a "
        "purchase event), so performance may reflect habit rather than propensity"
    ],
    "renewal60": [
        "No membership attributes (expiry, tier, membership tenure) are available, "
        "so the strongest renewal signal is absent; do not read this as a "
        "membership model",
        "Renewal is not upgrade; upgrade is not labelled or modelled",
    ],
}
FEATURE_FLAGS = ("training_ready", "experiment_ready")


def _check_target(target: str) -> tuple[str, int]:
    if target == BOOKING_TARGET:
        raise ValueError(f"{BOOKING_TARGET} is {UNSUPPORTED_SOURCE}")
    if target not in TARGETS:
        raise ValueError(f"Unknown propensity target: {target!r}")
    return TARGETS[target]


def limitations(target: str) -> list[str]:
    return [*COMMON_LIMITATIONS, *TARGET_LIMITATIONS[target]]


def _validate(rows: list[dict], target: str) -> None:
    version, horizon = _check_target(target)
    if not rows:
        raise ValueError("No training rows")
    seen = set()
    for row in rows:
        cutoff = _aware_timestamp(row.get("cutoff_at"), "cutoff_at")
        end = _aware_timestamp(row.get("outcome_end_at"), "outcome_end_at")
        customer = row.get("golden_customer_id")
        key = (customer, cutoff)
        if not customer or key in seen:
            raise ValueError("Duplicate customer/cutoff or missing customer")
        seen.add(key)
        if (
            row.get("target") != target
            or row.get("target_version") != version
            or row.get("horizon_days") not in (horizon, str(horizon))
            or end != cutoff + timedelta(days=horizon)
        ):
            raise ValueError("Unexpected target, version, or outcome window")
        if row.get("feature_version") != FEATURE_VERSION:
            raise ValueError("Unexpected feature version")
        if row.get("identity_time_policy") != "CURRENT_SNAPSHOT_RETROSPECTIVE":
            raise ValueError("Unexpected identity time policy")
        for field in ("eligible", "outcome_complete"):
            if row.get(field) is not True and row.get(field) != "True":
                raise ValueError(f"{field} must be True")
        for field in FEATURE_FLAGS:
            if row.get(field) is not False and row.get(field) != "False":
                raise ValueError(f"{field} must be False")
        _binary(row.get("target_value"), "target_value")
    _matrix(rows)


def _fixed_rule(target: str, values: list[float]) -> float:
    if target == "retail_purchase30":
        recency = values[FEATURES.index("recency_days")]
        return float(not math.isnan(recency) and recency <= 30)
    return float(values[FEATURES.index("purchase_count_90d")] >= 1)


def _summary(actual: list[int], scores: list[float]) -> dict:
    scored = list(zip(actual, scores))
    table, ece = _reliability(scored)
    return dict(
        rows=len(actual),
        positives=sum(actual),
        negatives=len(actual) - sum(actual),
        metrics=_metrics(scored),
        operating_metrics=_operating(scored),
        reliability=table,
        descriptive_ece=ece,
    )


def evaluate(rows: list[dict], target: str) -> tuple[dict, list[dict], dict]:
    """Fit on the purged earlier fold of one target; score the later holdout."""
    import sklearn
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    version, horizon = _check_target(target)
    _validate(rows, target)
    # Normalize representations; temporal_split purges on each row's own
    # outcome_end_at, so the per-target horizon is respected (not fixed at 90d).
    rows = sorted(
        [
            {
                **row,
                "cutoff_at": _aware_timestamp(row["cutoff_at"], "cutoff_at")
                .astimezone(LOCAL_TIMEZONE)
                .isoformat(),
                "outcome_end_at": _aware_timestamp(
                    row["outcome_end_at"], "outcome_end_at"
                )
                .astimezone(LOCAL_TIMEZONE)
                .isoformat(),
            }
            for row in rows
        ],
        key=lambda row: (row["cutoff_at"], row["golden_customer_id"]),
    )
    train, test, train_cutoffs, test_cutoffs = temporal_split(rows)
    y_train = [_binary(r["target_value"], "target_value") for r in train]
    if len(set(y_train)) != 2:
        raise ValueError("Training fold requires two classes")
    y_test = [_binary(r["target_value"], "target_value") for r in test]
    x_train, x_test = _matrix(train), _matrix(test)
    model = make_pipeline(
        SimpleImputer(strategy="median", keep_empty_features=True),
        StandardScaler(),
        LogisticRegression(random_state=SEED, max_iter=1000),
    )
    model.fit(x_train, y_train)
    base_rate = sum(y_train) / len(y_train)
    scores = {
        "logistic": [float(p) for p in model.predict_proba(x_test)[:, 1]],
        "base_rate": [base_rate] * len(test),
        "fixed_rule": [_fixed_rule(target, values) for values in x_test],
    }
    identity = dict(
        target=target,
        target_version=version,
        horizon_days=horizon,
        feature_version=FEATURE_VERSION,
        model_version=MODEL_VERSION,
    )
    notes = limitations(target)
    report = {
        **identity,
        "label_version": version,
        "features": list(FEATURES),
        "training_ready": False,
        "experiment_ready": False,
        "final_model": False,
        "development_only": True,
        "serving_ready": False,
        "valid_until": None,
        "train_rows": len(train),
        "test_rows": len(test),
        "purged_rows": len(rows) - len(train) - len(test),
        "train_cutoffs": train_cutoffs,
        "test_cutoffs": test_cutoffs,
        "train_base_rate": base_rate,
        "comparator_rules": {
            "base_rate": "constant train-fold positive rate",
            "fixed_rule": RULES[target],
        },
        "models": {name: _summary(y_test, scores[name]) for name in MODELS},
        "limitations": notes,
    }
    predictions = [
        {
            "golden_customer_id": row["golden_customer_id"],
            "cutoff_at": row["cutoff_at"],
            "outcome_end_at": row["outcome_end_at"],
            "target_value": label,
            **identity,
            "development_only": True,
            "serving_ready": False,
            **{f"{name}_probability": scores[name][i] for name in MODELS},
        }
        for i, (row, label) in enumerate(zip(test, y_test))
    ]
    fitted = model.named_steps["logisticregression"]
    parameters = {
        **identity,
        "features": list(FEATURES),
        "development_only": True,
        "serving_ready": False,
        "seed": SEED,
        "sklearn_version": sklearn.__version__,
        "serialization_note": "JSON inspection only; not a loadable or serving model",
        "logistic": {
            "imputer_medians": model.named_steps["simpleimputer"].statistics_.tolist(),
            "scaler_mean": model.named_steps["standardscaler"].mean_.tolist(),
            "scaler_scale": model.named_steps["standardscaler"].scale_.tolist(),
            "coef": fitted.coef_[0].tolist(),
            "intercept": fitted.intercept_.tolist(),
        },
        "base_rate": {"train_base_rate": base_rate},
        "fixed_rule": {"rule": RULES[target], "tuned": False},
    }
    return report, predictions, parameters


def _typed_labels(path: Path, target: str, version: str) -> list[dict]:
    """Parse only the chosen target's columns; the other target is never read."""
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != LABEL_FIELDS:
            raise ValueError("Unexpected label columns")
        raw = list(reader)
    side = "retail" if target == "retail_purchase30" else "renewal"

    def flag(value):
        if value not in ("True", "False"):
            raise ValueError("Label flags must be True or False")
        return value == "True"

    rows = []
    for row in raw:
        if row[f"{side}_label_version"] != version:
            raise ValueError("Label version does not match target version")
        if row["experiment_ready"] != "False":
            raise ValueError("experiment_ready must be False")
        value = row[target]
        rows.append(
            {
                "golden_customer_id": row["golden_customer_id"],
                "cutoff_at": row["cutoff_at"],
                f"{target}_eligible": flag(row[f"{target}_eligible"]),
                f"{target}_outcome_complete": flag(row[f"{target}_outcome_complete"]),
                f"{target}_outcome_end_at": row[f"{target}_outcome_end_at"],
                target: None if value == "" else _binary(value, target),
            }
        )
    return rows


def _read_features(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != FEATURE_FIELDS:
            raise ValueError("Unexpected feature columns")
        return list(reader)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _cutoff_set(values) -> set:
    return {_aware_timestamp(v, "cutoff") for v in values or ()}


def run(labels_dir: Path, features_dir: Path, target: str, output_dir: Path) -> dict:
    version, _ = _check_target(target)
    labels_dir, features_dir, output_dir = (
        Path(labels_dir),
        Path(features_dir),
        Path(output_dir),
    )
    if output_dir.exists():
        raise ValueError("Use a new output directory")
    labels_dir, features_dir, output_dir = (
        p.resolve() for p in (labels_dir, features_dir, output_dir)
    )
    if any(
        part.lower() == "ground_truth"
        for path in (labels_dir, features_dir, output_dir)
        for part in path.parts
    ):
        raise ValueError("ground_truth paths are not allowed")
    for source in (labels_dir, features_dir):
        if (
            source == output_dir
            or source in output_dir.parents
            or output_dir in source.parents
        ):
            raise ValueError("Keep inputs and output separate")
    paths = {
        "propensity_manifest.json": labels_dir / "propensity_manifest.json",
        "propensity_labels.csv": labels_dir / "propensity_labels.csv",
        "feature_manifest.json": features_dir / "feature_manifest.json",
        "features.csv": features_dir / "features.csv",
    }
    before = {name: sha256(path) for name, path in paths.items()}
    label_manifest = _load(paths["propensity_manifest.json"])
    feature_manifest = _load(paths["feature_manifest.json"])
    if (
        label_manifest.get("development_only") is not True
        or label_manifest.get("experiment_ready") is not False
        or label_manifest.get("final_model") is not False
        or feature_manifest.get("training_ready") is not False
    ):
        raise ValueError("Development-only manifests required")
    if label_manifest.get("target_versions", {}).get(target) != version:
        raise ValueError("Unexpected label version for target")
    if feature_manifest.get("feature_version") != FEATURE_VERSION:
        raise ValueError("Unexpected feature version")
    if (
        label_manifest.get("output_sha256", {}).get("propensity_labels.csv")
        != before["propensity_labels.csv"]
        or feature_manifest.get("output_sha256", {}).get("features.csv")
        != before["features.csv"]
    ):
        raise ValueError("Input checksum mismatch")
    if _cutoff_set(label_manifest.get("cutoffs")) != _cutoff_set(
        feature_manifest.get("cutoffs")
    ):
        raise ValueError("Feature and label cutoffs must match")
    features = _read_features(paths["features.csv"])
    if len(features) != feature_manifest.get("rows"):
        raise ValueError("Feature row count mismatch")
    labels = _typed_labels(paths["propensity_labels.csv"], target, version)
    rows = join_propensity_training_rows(features, labels, target)
    report, predictions, parameters = evaluate(rows, target)
    after = {name: sha256(path) for name, path in paths.items()}
    if after != before:
        raise ValueError("Input changed during experiment")
    report["input_sha256"] = before
    report["input_sha256_after"] = after
    output_dir.mkdir(parents=True)
    for name, value in zip(OUTPUTS, (report, predictions, parameters)):
        (output_dir / name).write_text(
            json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    manifest = {
        "model_version": MODEL_VERSION,
        "target": target,
        "target_version": version,
        "feature_version": FEATURE_VERSION,
        "development_only": True,
        "training_ready": False,
        "experiment_ready": False,
        "final_model": False,
        "serving_ready": False,
        "limitations": report["limitations"],
        "input_sha256": before,
        "input_sha256_after": after,
        "output_sha256": {name: sha256(output_dir / name) for name in OUTPUTS},
    }
    (output_dir / "experiment_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels-dir", type=Path, required=True)
    parser.add_argument("--features-dir", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.labels_dir, args.features_dir, args.target, args.output_dir)
    print(
        json.dumps(
            {
                "target": result["target"],
                "serving_ready": result["serving_ready"],
                "output": str(args.output_dir),
            }
        )
    )


if __name__ == "__main__":
    main()
