"""Offline, advisory reliance and feature-bucket diagnostics for saved POS propensity calibration.

Reload saved parameters and verify the exact purged test against saved outputs;
never fit, recalibrate, choose thresholds, serve, or read ground truth.
"""

import argparse
import json
import random
from pathlib import Path

from services.data.features.snapshot import VERSION as FEATURE_VERSION
from services.data.ingestion.validator import sha256
from services.data.models import propensity_calibration as calibration
from services.data.models.calibrated_churn_importance import (
    _close,
    _interpolate,
    _probabilities,
)
from services.data.models.churn_experiment import FEATURES
from services.data.models.evaluator import _binary
from services.data.models.model_importance import (
    CORRELATED_GROUP,
    MIN_SEGMENT_N,
    REPEATS,
    SEED,
    SEGMENT_BUCKETS,
    _bucket,
    _check_paths,
    _load,
    _metrics,
    _numbers,
    _raw,
    _segment,
    _spread,
)
from services.data.models.propensity_experiment import (
    _check_target,
    _cutoff_set,
    _read_features,
    _typed_labels,
    _validate,
)
from services.data.models.propensity_labels import join_propensity_training_rows

EXPLAINER_VERSION = "moses-calibrated-pos-propensity-importance-dev-1.0"
EXPLAINER_METHOD = "permutation_importance_calibrated_auc_drop"
STATUS = {**calibration.FLAGS, "refitted": False, "advisory_only": True}
LIMITATIONS = [
    *calibration.LIMITATIONS,
    "Exploratory model reliance on a synthetic reused test cohort; not causal importance",
    "Correlated purchase-count columns share reliance; joint permutation reported separately",
    "Repeated permutations reuse the same test rows; spread is not a confidence interval",
    "Feature-derived segments only; no approved lifecycle or CLV tiers",
    "No refitting, recalibration, threshold tuning or production approval",
]


def _contract(value: dict, target: str) -> None:
    version, horizon = _check_target(target)
    if not isinstance(value, dict) or any(
        value.get(k) is not v for k, v in calibration.FLAGS.items()
    ):
        raise ValueError("Development-only, non-serving calibration contract required")
    for key, expected in (
        ("target", target),
        ("target_version", version),
        ("feature_version", FEATURE_VERSION),
        ("model_version", calibration.MODEL_VERSION),
    ):
        if value.get(key) != expected:
            raise ValueError(f"Unexpected {key}")
    if "label_version" in value and value["label_version"] != version:
        raise ValueError("Unexpected label_version")
    if "horizon_days" in value and value["horizon_days"] != horizon:
        raise ValueError("Unexpected horizon_days")


def _parameters(artifact: dict, target: str) -> tuple[dict, dict]:
    _contract(artifact, target)
    if tuple(artifact.get("features", ())) != FEATURES:
        raise ValueError("Unexpected feature contract")
    logistic = artifact.get("logistic")
    if not isinstance(logistic, dict):
        raise ValueError("Missing logistic parameters")
    count = len(FEATURES)
    intercept = logistic.get("intercept")
    if not isinstance(intercept, list) or len(intercept) != 1:
        raise ValueError("Logistic intercept must be a single-value list")
    scale = _numbers(logistic.get("scaler_scale"), count)
    if any(v <= 0 for v in scale):
        raise ValueError("Scaler scale must be strictly positive")
    model = {
        "intercept": _numbers(intercept, 1)[0],
        "scaler_scale": scale,
        **{
            key: _numbers(logistic.get(key), count)
            for key in ("coef", "scaler_mean", "imputer_medians")
        },
    }
    isotonic = artifact.get("isotonic")
    if not isinstance(isotonic, dict):
        raise ValueError("Missing isotonic status")
    status = isotonic.get("status")
    if status == "identity_fallback_single_class":
        if set(isotonic) != {"status"}:
            raise ValueError("Identity fallback must not contain isotonic thresholds")
    elif status == "fit_on_calibration_only":
        if isotonic.get("out_of_bounds") != "clip":
            raise ValueError("Clipped isotonic interpolation required")
        xs = isotonic.get("x_thresholds")
        if not isinstance(xs, list) or not xs:
            raise ValueError("Nonempty isotonic thresholds required")
        x = _numbers(xs, len(xs))
        y = _numbers(isotonic.get("y_thresholds"), len(x))
        if (
            any(not 0 <= v <= 1 for v in x + y)
            or any(a >= b for a, b in zip(x, x[1:]))
            or any(a > b for a, b in zip(y, y[1:]))
        ):
            raise ValueError("Isotonic thresholds must be ordered probabilities")
        isotonic = {"status": status, "x": x, "y": y}
    else:
        raise ValueError("Unexpected isotonic status")
    return model, isotonic


def _scores(model: dict, isotonic: dict, matrix: list[list[float]]) -> list[float]:
    raw = _probabilities(model, matrix)
    return (
        _interpolate(raw, isotonic["x"], isotonic["y"])
        if isotonic["status"] == "fit_on_calibration_only"
        else raw
    )


def evaluate(
    artifact: dict,
    holdout_rows: list[dict],
    *,
    target: str | None = None,
    repeats: int = REPEATS,
    seed: int = SEED,
    min_n: int = MIN_SEGMENT_N,
) -> dict:
    """Explain saved calibrated probabilities on supplied test rows, without mutation."""
    if (
        type(repeats) is not int
        or repeats < 1
        or type(min_n) is not int
        or min_n < 1
        or type(seed) is not int
    ):
        raise ValueError(
            "repeats and min_n must be positive integers; seed must be an integer"
        )
    if not holdout_rows:
        raise ValueError("Nonempty holdout required")
    target = artifact.get("target") if target is None else target
    if not isinstance(target, str):
        raise ValueError("Unsupported propensity target")
    model, isotonic = _parameters(artifact, target)
    matrix = [[_raw(row, field) for field in FEATURES] for row in holdout_rows]
    labels = [_binary(row.get("target_value"), "target_value") for row in holdout_rows]
    probabilities = _scores(model, isotonic, matrix)
    baseline = _metrics(labels, probabilities)

    def entry(indexes, name):
        auc_drops, brier_rises = [], []
        for repeat in range(repeats):
            order = list(range(len(matrix)))
            random.Random(f"{seed}:{name}:{repeat}").shuffle(order)
            permuted = [list(values) for values in matrix]
            for row, donor in enumerate(order):
                for index in indexes:
                    permuted[row][index] = matrix[donor][index]
            metrics = _metrics(labels, _scores(model, isotonic, permuted))
            auc_drops.append(
                None
                if baseline["roc_auc"] is None or metrics["roc_auc"] is None
                else baseline["roc_auc"] - metrics["roc_auc"]
            )
            brier_rises.append(metrics["brier_score"] - baseline["brier_score"])
        auc_mean, auc_std = _spread(auc_drops)
        brier_mean, brier_std = _spread(brier_rises)
        return dict(
            auc_drop_mean=auc_mean,
            auc_drop_std=auc_std,
            brier_increase_mean=brier_mean,
            brier_increase_std=brier_std,
            repeats=repeats,
        )

    importance = [
        {"feature": field, **entry((index,), field)}
        for index, field in enumerate(FEATURES)
    ]
    for rank, item in enumerate(
        sorted(
            importance,
            key=lambda e: (
                -(e["auc_drop_mean"] or 0),
                -e["brier_increase_mean"],
                e["feature"],
            ),
        ),
        1,
    ):
        item["rank"] = rank
    grouped = [
        {
            "features": list(CORRELATED_GROUP),
            **entry(
                tuple(FEATURES.index(f) for f in CORRELATED_GROUP),
                "|".join(CORRELATED_GROUP),
            ),
        }
    ]
    segments = {}
    for field in SEGMENT_BUCKETS:
        if field not in FEATURES:
            continue
        index = FEATURES.index(field)
        groups: dict[str, list[int]] = {}
        for row, values in enumerate(matrix):
            groups.setdefault(_bucket(field, values[index]), []).append(row)
        segments[field] = [
            {
                "bucket": name,
                **_segment(
                    [labels[i] for i in indexes],
                    [probabilities[i] for i in indexes],
                    min_n,
                ),
            }
            for name, indexes in sorted(groups.items())
        ]
    version, horizon = _check_target(target)
    return {
        "kind": "calibrated_propensity",
        "target": target,
        "target_version": version,
        "label_version": version,
        "horizon_days": horizon,
        "model_version": calibration.MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "explainer_version": EXPLAINER_VERSION,
        "explainer_method": EXPLAINER_METHOD,
        "score_space": "calibrated_probability",
        "calibration_status": isotonic["status"],
        "seed": seed,
        "repeats": repeats,
        "min_segment_n": min_n,
        "features": list(FEATURES),
        "label_key": "target_value",
        "holdout_rows": len(labels),
        "holdout_positives": sum(labels),
        **STATUS,
        "baseline": baseline,
        "global_importance": importance,
        "grouped_importance": grouped,
        "segment_definition": {
            field: [name for name, _ in SEGMENT_BUCKETS[field]] + ["missing"]
            for field in segments
        },
        "segments": segments,
        "limitations": LIMITATIONS,
    }


def run(
    model_dir: Path,
    output_dir: Path,
    *,
    labels_dir: Path,
    features_dir: Path,
    target: str,
    repeats: int = REPEATS,
    seed: int = SEED,
    min_n: int = MIN_SEGMENT_N,
) -> dict:
    """Verify source lineage, fold identity and saved test parity before writing."""
    version, _ = _check_target(target)
    model_dir, output_dir, labels_dir, features_dir = (
        Path(p).resolve() for p in (model_dir, output_dir, labels_dir, features_dir)
    )
    _check_paths(model_dir, output_dir, [labels_dir, features_dir])
    sources = {
        "propensity_manifest.json": labels_dir / "propensity_manifest.json",
        "propensity_labels.csv": labels_dir / "propensity_labels.csv",
        "feature_manifest.json": features_dir / "feature_manifest.json",
        "features.csv": features_dir / "features.csv",
    }
    models = {
        name: model_dir / name
        for name in (*calibration.OUTPUTS, "calibration_manifest.json")
    }
    paths = {**sources, **{f"model/{name}": path for name, path in models.items()}}
    before = {name: sha256(path) for name, path in paths.items()}
    manifest = _load(models["calibration_manifest.json"])
    _contract(manifest, target)
    for name in calibration.OUTPUTS:
        if manifest.get("output_sha256", {}).get(name) != before[f"model/{name}"]:
            raise ValueError(f"{name} checksum mismatch")
    source_hashes = {name: before[name] for name in sources}
    for field in ("input_sha256", "input_sha256_after"):
        if manifest.get(field) != source_hashes:
            raise ValueError("Source provenance differs from calibration input")
    lm, fm = (
        _load(sources["propensity_manifest.json"]),
        _load(sources["feature_manifest.json"]),
    )
    if (
        lm.get("development_only") is not True
        or lm.get("training_ready") is not False
        or lm.get("experiment_ready") is not False
        or lm.get("final_model") is not False
        or fm.get("training_ready") is not False
    ):
        raise ValueError("Development-only source manifests required")
    if (
        lm.get("target_versions", {}).get(target) != version
        or fm.get("feature_version") != FEATURE_VERSION
    ):
        raise ValueError("Unexpected source target or feature version")
    if (
        lm.get("output_sha256", {}).get("propensity_labels.csv")
        != before["propensity_labels.csv"]
        or fm.get("output_sha256", {}).get("features.csv") != before["features.csv"]
    ):
        raise ValueError("Input checksum mismatch")
    cutoffs = _cutoff_set(lm.get("cutoffs"))
    if cutoffs != _cutoff_set(fm.get("cutoffs")):
        raise ValueError("Feature and label cutoffs must match")
    calibration._check_cutoffs(cutoffs)
    features = _read_features(sources["features.csv"])
    labels = _typed_labels(sources["propensity_labels.csv"], target, version)
    if len(features) != fm.get("rows"):
        raise ValueError("Feature row count mismatch")
    for rows in (features, labels):
        if _cutoff_set(r["cutoff_at"] for r in rows) != cutoffs:
            raise ValueError("Actual rows must match manifest cutoffs")
    rows = join_propensity_training_rows(features, labels, target)
    _validate(rows, target)
    train, cal, test, info = calibration.three_fold_split(rows)
    evaluation = _load(models["calibration_evaluation.json"])
    artifact = _load(models["calibration_artifact.json"])
    _contract(evaluation, target)
    _parameters(artifact, target)
    for key, value in info.items():
        if evaluation.get(key) != value or (
            key in ("train_cutoffs", "calibration_cutoffs")
            and artifact.get(key) != value
        ):
            raise ValueError("Rebuilt fold cutoffs differ from calibration")
    for key, count in (
        ("train_rows", len(train)),
        ("calibration_rows", len(cal)),
        ("test_rows", len(test)),
        ("purged_rows", len(rows) - len(train) - len(cal) - len(test)),
    ):
        if evaluation.get(key) != count:
            raise ValueError("Rebuilt fold counts differ from calibration")
    for field in ("input_sha256", "input_sha256_after"):
        if evaluation.get(field) != manifest[field]:
            raise ValueError("Evaluation input provenance mismatch")
    if (
        evaluation.get("features") != list(FEATURES)
        or evaluation.get("calibration_status") != artifact["isotonic"]["status"]
    ):
        raise ValueError("Evaluation calibration identity mismatch")
    report = evaluate(
        artifact, test, target=target, repeats=repeats, seed=seed, min_n=min_n
    )
    saved = json.loads(models["test_predictions.json"].read_text(encoding="utf-8"))
    if not isinstance(saved, list) or len(saved) != len(test):
        raise ValueError("Saved prediction count mismatch")
    model, isotonic = _parameters(artifact, target)
    matrix = [[_raw(row, field) for field in FEATURES] for row in test]
    raw = _probabilities(model, matrix)
    calibrated = _scores(model, isotonic, matrix)
    for row, prediction, raw_p, cal_p in zip(test, saved, raw, calibrated):
        _contract(prediction, target)
        for key in ("golden_customer_id", "cutoff_at", "outcome_end_at"):
            if prediction.get(key) != row[key]:
                raise ValueError("Saved prediction identity mismatch")
        if (
            prediction.get("target_value")
            != _binary(row["target_value"], "target_value")
            or not _close(raw_p, prediction.get("raw_probability"))
            or not _close(cal_p, prediction.get("calibrated_probability"))
        ):
            raise ValueError("Reloaded prediction differs from saved test prediction")
    for metric, value in report["baseline"].items():
        if not _close(
            value,
            evaluation.get("test", {})
            .get("calibrated", {})
            .get("metrics", {})
            .get(metric),
        ):
            raise ValueError(
                "Reloaded baseline differs from saved calibrated evaluation"
            )
    after = {name: sha256(path) for name, path in paths.items()}
    if after != before:
        raise ValueError("Input changed during importance run")
    report.update(
        input_sha256=before,
        input_sha256_after=after,
        **info,
        baseline_verified_against="calibration_evaluation.json and test_predictions.json",
    )
    output_dir.mkdir(parents=True)
    (output_dir / "importance_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    output_manifest = {
        **STATUS,
        "target": target,
        "target_version": version,
        "model_version": calibration.MODEL_VERSION,
        "explainer_version": EXPLAINER_VERSION,
        "explainer_method": EXPLAINER_METHOD,
        "seed": seed,
        "repeats": repeats,
        "input_sha256": before,
        "input_sha256_after": after,
        "limitations": LIMITATIONS,
        "output_sha256": {
            "importance_report.json": sha256(output_dir / "importance_report.json")
        },
    }
    (output_dir / "importance_manifest.json").write_text(
        json.dumps(output_manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("model-dir", "labels-dir", "features-dir", "output-dir"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--repeats", type=int, default=REPEATS)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--min-n", type=int, default=MIN_SEGMENT_N)
    args = parser.parse_args()
    report = run(
        args.model_dir,
        args.output_dir,
        labels_dir=args.labels_dir,
        features_dir=args.features_dir,
        target=args.target,
        repeats=args.repeats,
        seed=args.seed,
        min_n=args.min_n,
    )
    print(
        json.dumps(
            {
                "target": report["target"],
                "holdout_rows": report["holdout_rows"],
                "serving_ready": False,
                "output": str(args.output_dir),
            }
        )
    )


if __name__ == "__main__":
    main()
