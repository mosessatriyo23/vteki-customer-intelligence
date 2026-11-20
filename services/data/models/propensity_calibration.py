"""Development-only PROPOSED propensity calibration with three POS snapshots.

Train December 2025, calibrate March 2026, test June 2026 independently per
retail_purchase30 or renewal60. No booking, serving, or final calibration claim.
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

from services.data.features.snapshot import VERSION as FEATURE_VERSION
from services.data.ingestion.validator import sha256
from services.data.models.churn_calibration import (
    FLAGS as CHURN_FLAGS,
)
from services.data.models.churn_calibration import (
    THRESHOLD_RULE,
    _block,
    _normalized,
    select_threshold,
)
from services.data.models.churn_experiment import FEATURES, SEED, _matrix
from services.data.models.evaluation_disclaimer import SYNTHETIC_DATA_DISCLAIMER
from services.data.models.evaluator import _binary
from services.data.models.propensity_experiment import (
    TARGET_LIMITATIONS,
    _check_target,
    _cutoff_set,
    _load,
    _read_features,
    _typed_labels,
    _validate,
)
from services.data.models.propensity_labels import (
    PROPOSED_RULES,
    booking_status,
    join_propensity_training_rows,
)

MODEL_VERSION = "moses-calibrated-pos-propensity-dev-1.0"
FLAGS = {**CHURN_FLAGS, "calibration_final": False}
OUTPUTS = (
    "calibration_evaluation.json",
    "test_predictions.json",
    "calibration_artifact.json",
)
LIMITATIONS = [
    "PROPOSED labels pending Christ's approval; not production approved",
    "Synthetic retrospective identity; not point-in-time (PIT) safe",
    "POS-purchase features only; no membership expiry, tier or tenure predictors",
    "Development isotonic calibration only; not final or production calibration",
    "Calibration-fold threshold only; no production threshold authorization",
    "Test results retained even when calibration worsens Brier or ECE",
    "Observational only; no causal or campaign-effect claims",
    "Not I-04 compliant; no reason codes; valid_until is null",
    "The June test cohort was inspected in earlier experiments; this is a reused "
    "cohort, not an independent holdout, and does not establish generalization",
]


def _check_cutoffs(cutoffs):
    cutoffs = sorted(cutoffs)
    if len(cutoffs) != 3:
        raise ValueError("Exactly three cutoffs required; no two-fold fallback")
    if [(c.year, c.month) for c in cutoffs] != [(2025, 12), (2026, 3), (2026, 6)]:
        raise ValueError("Expected December 2025 / March 2026 / June 2026 cutoffs")
    return cutoffs


def three_fold_split(rows):
    """Purge each earlier row unless its own outcome ends by next fold cutoff."""
    rows = _normalized(rows)
    cutoffs = _check_cutoffs({datetime.fromisoformat(r["cutoff_at"]) for r in rows})
    folds, purged = [], {}
    for index, name in enumerate(("train", "calibration", "test")):
        candidates = [
            r for r in rows if datetime.fromisoformat(r["cutoff_at"]) == cutoffs[index]
        ]
        kept = [
            r
            for r in candidates
            if index == 2
            or datetime.fromisoformat(r["outcome_end_at"]) <= cutoffs[index + 1]
        ]
        purged[name] = len(candidates) - len(kept)
        if not kept:
            raise ValueError("Purged three-fold split produced an empty fold")
        folds.append(kept)
    return (
        *folds,
        {
            "train_cutoffs": [cutoffs[0].isoformat()],
            "calibration_cutoffs": [cutoffs[1].isoformat()],
            "test_cutoffs": [cutoffs[2].isoformat()],
            "purged_counts": purged,
        },
    )


def evaluate(rows: list[dict], target: str) -> tuple[dict, list[dict], dict]:
    """Fit preprocessing/logistic on train, isotonic/thresholds on calibration."""
    import sklearn
    from sklearn.impute import SimpleImputer
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    version, horizon = _check_target(target)
    _validate(rows, target)
    train, calibration, test, info = three_fold_split(rows)
    labels = [
        [_binary(r["target_value"], "target_value") for r in fold]
        for fold in (train, calibration, test)
    ]
    y_train, y_cal, y_test = labels
    if len(set(y_train)) != 2:
        raise ValueError("Training fold requires two classes")
    model = make_pipeline(
        SimpleImputer(strategy="median", keep_empty_features=True),
        StandardScaler(),
        LogisticRegression(random_state=SEED, max_iter=1000),
    )
    model.fit(_matrix(train), y_train)
    raw_cal = model.predict_proba(_matrix(calibration))[:, 1].tolist()
    isotonic = None
    isotonic_artifact = {"status": "identity_fallback_single_class"}
    if len(set(y_cal)) == 2:
        isotonic = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        isotonic.fit(raw_cal, y_cal)
        isotonic_artifact = {
            "status": "fit_on_calibration_only",
            "x_thresholds": isotonic.X_thresholds_.tolist(),
            "y_thresholds": isotonic.y_thresholds_.tolist(),
            "out_of_bounds": "clip",
        }
    calibrated_cal = (
        isotonic.predict(raw_cal).tolist() if isotonic is not None else raw_cal
    )
    selection = {
        "uncalibrated": select_threshold(list(zip(y_cal, raw_cal))),
        "calibrated": select_threshold(list(zip(y_cal, calibrated_cal))),
    }
    # All fitting and selection are complete before any test scoring.
    raw_test = model.predict_proba(_matrix(test))[:, 1].tolist()
    calibrated_test = (
        isotonic.predict(raw_test).tolist() if isotonic is not None else raw_test
    )
    identity = dict(
        target=target,
        target_version=version,
        label_version=version,
        horizon_days=horizon,
        feature_version=FEATURE_VERSION,
        model_version=MODEL_VERSION,
        **FLAGS,
    )
    test_blocks = {
        name: _block(list(zip(y_test, values)), selection[name]["threshold"])
        for name, values in (
            ("uncalibrated", raw_test),
            ("calibrated", calibrated_test),
        )
    }
    report = {
        **identity,
        **info,
        "features": list(FEATURES),
        "synthetic_data_disclaimer": SYNTHETIC_DATA_DISCLAIMER,
        "label_status": "PROPOSED",
        "proposed_rule": PROPOSED_RULES[target],
        "booking": booking_status(),
        "valid_until": None,
        "folds": {
            name: {"rows": len(y), "positives": sum(y), "negatives": len(y) - sum(y)}
            for name, y in zip(("train", "calibration", "test"), labels)
        },
        "train_rows": len(train),
        "calibration_rows": len(calibration),
        "test_rows": len(test),
        "purged_rows": sum(info["purged_counts"].values()),
        "threshold_rule": THRESHOLD_RULE,
        "selected_threshold": selection["calibrated"]["threshold"],
        "selected_threshold_source": "calibration_fold",
        "calibration_selection": selection,
        "calibration_status": isotonic_artifact["status"],
        "test": test_blocks,
        "test_calibration_minus_raw": {
            "brier_score": test_blocks["calibrated"]["metrics"]["brier_score"]
            - test_blocks["uncalibrated"]["metrics"]["brier_score"],
            "expected_calibration_error": test_blocks["calibrated"][
                "expected_calibration_error"
            ]
            - test_blocks["uncalibrated"]["expected_calibration_error"],
            "interpretation": (
                "Positive delta means worse; no approval or model selection from "
                "test. A better calibrated score does not establish that the "
                "underlying model is useful or that it generalizes."
            ),
        },
        "limitations": [*LIMITATIONS, *TARGET_LIMITATIONS[target]],
    }
    predictions = [
        {
            **identity,
            "golden_customer_id": row["golden_customer_id"],
            "cutoff_at": row["cutoff_at"],
            "outcome_end_at": row["outcome_end_at"],
            "target_value": y,
            "raw_probability": float(raw),
            "calibrated_probability": float(cal),
        }
        for row, y, raw, cal in zip(test, y_test, raw_test, calibrated_test)
    ]
    fitted = model.named_steps["logisticregression"]
    artifact = {
        **identity,
        "features": list(FEATURES),
        "seed": SEED,
        "sklearn_version": sklearn.__version__,
        "serialization": "JSON inspection only; not a loadable serving model",
        "train_cutoffs": info["train_cutoffs"],
        "calibration_cutoffs": info["calibration_cutoffs"],
        "logistic": {
            "imputer_medians": model.named_steps["simpleimputer"].statistics_.tolist(),
            "scaler_mean": model.named_steps["standardscaler"].mean_.tolist(),
            "scaler_scale": model.named_steps["standardscaler"].scale_.tolist(),
            "coef": fitted.coef_[0].tolist(),
            "intercept": fitted.intercept_.tolist(),
        },
        "isotonic": isotonic_artifact,
        "thresholds": selection,
        "threshold_rule": THRESHOLD_RULE,
        "limitations": report["limitations"],
    }
    return report, predictions, artifact


def run(labels_dir: Path, features_dir: Path, target: str, output_dir: Path) -> dict:
    version, _ = _check_target(target)
    labels_dir, features_dir, output_dir = (
        Path(p).resolve() for p in (labels_dir, features_dir, output_dir)
    )
    if output_dir.exists():
        raise ValueError("Use a new output directory")
    for path in (labels_dir, features_dir, output_dir):
        if any(p.lower() == "ground_truth" for p in path.parts):
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
    lm, fm = (
        _load(paths[name])
        for name in ("propensity_manifest.json", "feature_manifest.json")
    )
    if (
        lm.get("development_only") is not True
        or lm.get("training_ready") is not False
        or lm.get("experiment_ready") is not False
        or lm.get("final_model") is not False
        or fm.get("training_ready") is not False
    ):
        raise ValueError("Development-only manifests required")
    if (
        lm.get("target_versions", {}).get(target) != version
        or fm.get("feature_version") != FEATURE_VERSION
    ):
        raise ValueError("Unexpected label or feature version")
    if (
        lm.get("output_sha256", {}).get("propensity_labels.csv")
        != before["propensity_labels.csv"]
        or fm.get("output_sha256", {}).get("features.csv") != before["features.csv"]
    ):
        raise ValueError("Input checksum mismatch")
    cutoffs = _cutoff_set(lm.get("cutoffs"))
    if cutoffs != _cutoff_set(fm.get("cutoffs")):
        raise ValueError("Feature and label cutoffs must match")
    _check_cutoffs(cutoffs)
    features = _read_features(paths["features.csv"])
    labels = _typed_labels(paths["propensity_labels.csv"], target, version)
    if len(features) != fm.get("rows"):
        raise ValueError("Feature row count mismatch")
    for rows in (features, labels):
        if _cutoff_set(r["cutoff_at"] for r in rows) != cutoffs:
            raise ValueError("Actual rows must match manifest cutoffs")
    report, predictions, artifact = evaluate(
        join_propensity_training_rows(features, labels, target), target
    )
    after = {name: sha256(path) for name, path in paths.items()}
    if after != before:
        raise ValueError("Input changed during calibration")
    report.update(input_sha256=before, input_sha256_after=after)
    # Serialize everything strictly before creating the destination.
    serialized = [
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
        for value in (report, predictions, artifact)
    ]
    output_dir.mkdir(parents=True)
    for name, value in zip(OUTPUTS, serialized):
        (output_dir / name).write_text(value, encoding="utf-8")
    manifest = {
        "model_version": MODEL_VERSION,
        "target": target,
        "target_version": version,
        "feature_version": FEATURE_VERSION,
        **FLAGS,
        "input_sha256": before,
        "input_sha256_after": after,
        "output_sha256": {name: sha256(output_dir / name) for name in OUTPUTS},
        "limitations": report["limitations"],
    }
    (output_dir / "calibration_manifest.json").write_text(
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
    report = run(args.labels_dir, args.features_dir, args.target, args.output_dir)
    print(
        json.dumps(
            {
                "target": report["target"],
                "serving_ready": False,
                "output": str(args.output_dir),
            },
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
