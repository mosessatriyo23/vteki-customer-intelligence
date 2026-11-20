"""Advisory holdout reliance for saved three-fold calibrated churn artifacts.

Reload logistic preprocessing/weights, then saved clipped isotonic interpolation.
Never fit, recalibrate, select thresholds, approve serving, or read ground truth.
"""

import argparse
import csv
import json
import math
import random
from pathlib import Path

from services.data.features.snapshot import FIELDS as FEATURE_FIELDS
from services.data.features.snapshot import VERSION as FEATURE_VERSION
from services.data.ingestion.validator import sha256
from services.data.models import churn_calibration as calibration
from services.data.models.churn_experiment import FEATURES, _validate
from services.data.models.evaluator import _binary
from services.data.models.labels import CHRIST_VERSION, TRAINING_FIELDS
from services.data.models.model_importance import (
    CORRELATED_GROUP,
    MIN_SEGMENT_N,
    REPEATS,
    SEED,
    SEGMENT_BUCKETS,
    _bucket,
    _check_paths,
    _load,
    _logistic,
    _metrics,
    _numbers,
    _raw,
    _segment,
    _spread,
)

EXPLAINER_VERSION = "moses-calibrated-churn-importance-dev-1.0"
EXPLAINER_METHOD = "permutation_importance_calibrated_auc_drop"
STATUS = {**calibration.FLAGS, "refitted": False, "advisory_only": True}
LIMITATIONS = list(calibration.LIMITATIONS) + [
    "Exploratory, advisory-only model reliance on a synthetic holdout; not causal importance",
    "Correlated purchase-count columns share reliance; joint permutation is reported separately",
    "Repeated permutations reuse the same holdout; spread is not a confidence interval",
    "No refitting, recalibration, threshold tuning, production approval or I-04 handoff",
    "Feature-derived segments only; no approved lifecycle or CLV tiers",
]


def _contract(value: dict) -> None:
    if any(value.get(key) is not flag for key, flag in calibration.FLAGS.items()):
        raise ValueError("Development-only, non-serving calibration contract required")
    for key, expected in (
        ("model_version", calibration.MODEL_VERSION),
        ("feature_version", FEATURE_VERSION),
        ("label_version", CHRIST_VERSION),
    ):
        if value.get(key) != expected:
            raise ValueError(f"Unexpected {key}")


def _parameters(artifact: dict) -> tuple[dict, list[float], list[float]]:
    _contract(artifact)
    if artifact.get("method") != calibration.CALIBRATION_METHOD:
        raise ValueError("Unexpected calibration method")
    if tuple(artifact.get("features", ())) != FEATURES:
        raise ValueError("Unexpected feature contract")
    # The shared reader deliberately rejects calibrated artifacts. Read only the
    # logistic sub-contract here, after independently validating the calibrator.
    isotonic = artifact.get("isotonic")
    if not isinstance(isotonic, dict) or isotonic.get("out_of_bounds") != "clip":
        raise ValueError("Saved isotonic clipped interpolation required")
    x_values = isotonic.get("x_thresholds")
    if not isinstance(x_values, list) or not x_values:
        raise ValueError("Nonempty isotonic thresholds required")
    x = _numbers(x_values, len(x_values))
    y = _numbers(isotonic.get("y_thresholds"), len(x))
    if (
        any(not 0 <= v <= 1 for v in x + y)
        or any(a >= b for a, b in zip(x, x[1:]))
        or any(a > b for a, b in zip(y, y[1:]))
    ):
        raise ValueError("Isotonic thresholds must be ordered probabilities")
    _, logistic = _logistic({k: v for k, v in artifact.items() if k != "isotonic"})
    return logistic, x, y


def _interpolate(scores: list[float], x: list[float], y: list[float]) -> list[float]:
    import numpy as np

    # np.interp clips outside the saved range, including the single-knot case.
    return np.interp(scores, x, y).tolist()


def _probabilities(model: dict, matrix: list[list[float]]) -> list[float]:
    import numpy as np
    from scipy.special import expit

    # Match sklearn's impute -> subtract mean -> divide scale -> dot -> expit
    # arithmetic ordering, not a refit or reconstruction of sklearn estimators.
    values = np.array(matrix, dtype=float)
    values = np.where(np.isnan(values), model["imputer_medians"], values)
    values -= model["scaler_mean"]
    values /= model["scaler_scale"]
    logits = values @ np.array(model["coef"]) + model["intercept"]
    if not np.isfinite(logits).all():
        raise ValueError("Nonfinite logistic scores")
    return expit(logits).tolist()


def evaluate(
    artifact: dict,
    holdout_rows: list[dict],
    *,
    repeats: int = REPEATS,
    seed: int = SEED,
    min_n: int = MIN_SEGMENT_N,
) -> dict:
    """Permute only supplied test rows; every score includes saved calibration."""
    if type(repeats) is not int or repeats < 1:
        raise ValueError("repeats must be a positive integer")
    if type(min_n) is not int or min_n < 1:
        raise ValueError("min_n must be a positive integer")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    if not holdout_rows:
        raise ValueError("Nonempty holdout required")
    model, x, y = _parameters(artifact)
    matrix = [[_raw(row, field) for field in FEATURES] for row in holdout_rows]
    labels = [_binary(row.get("churn90"), "churn90") for row in holdout_rows]

    def scores(values):
        return _interpolate(_probabilities(model, values), x, y)

    probabilities = scores(matrix)
    baseline = _metrics(labels, probabilities)

    def entry(indexes: tuple[int, ...], name: str) -> dict:
        auc_drops: list[float | None] = []
        brier_rises = []
        for repeat in range(repeats):
            order = list(range(len(matrix)))
            random.Random(f"{seed}:{name}:{repeat}").shuffle(order)
            permuted = [list(values) for values in matrix]
            for row, donor in enumerate(order):
                for index in indexes:
                    permuted[row][index] = matrix[donor][index]
            metrics = _metrics(labels, scores(permuted))
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
            key=lambda item: (
                -(item["auc_drop_mean"] or 0),
                -item["brier_increase_mean"],
                item["feature"],
            ),
        ),
        1,
    ):
        item["rank"] = rank
    grouped = [
        {
            "features": list(CORRELATED_GROUP),
            **entry(
                tuple(FEATURES.index(field) for field in CORRELATED_GROUP),
                "|".join(CORRELATED_GROUP),
            ),
        }
    ]
    segments = {}
    for field in SEGMENT_BUCKETS:
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
    return {
        "kind": "calibrated_churn",
        "model_version": calibration.MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "label_version": CHRIST_VERSION,
        "explainer_version": EXPLAINER_VERSION,
        "explainer_method": EXPLAINER_METHOD,
        "score_space": "calibrated_probability",
        "seed": seed,
        "repeats": repeats,
        "min_segment_n": min_n,
        "features": list(FEATURES),
        "label_key": "churn90",
        "holdout_rows": len(labels),
        "holdout_positives": sum(labels),
        **STATUS,
        "baseline": baseline,
        "global_importance": importance,
        "grouped_importance": grouped,
        "segment_definition": {
            field: [name for name, _ in buckets] + ["missing"]
            for field, buckets in SEGMENT_BUCKETS.items()
        },
        "segments": segments,
        "limitations": LIMITATIONS,
    }


def _close(actual, expected) -> bool:
    if actual is None or expected is None:
        return actual is expected
    return (
        not isinstance(expected, bool)
        and isinstance(expected, (int, float))
        and math.isfinite(expected)
        and math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)
    )


def run(
    model_dir: Path,
    output_dir: Path,
    *,
    source_dir: Path,
    repeats: int = REPEATS,
    seed: int = SEED,
    min_n: int = MIN_SEGMENT_N,
) -> dict:
    """Verify lineage, rebuild the exact purged three-fold test, and explain it."""
    model_dir, output_dir, source_dir = (
        Path(p).resolve() for p in (model_dir, output_dir, source_dir)
    )
    _check_paths(model_dir, output_dir, [source_dir])
    sources = {
        name: source_dir / name for name in ("model_manifest.json", "training_rows.csv")
    }
    models = {
        name: model_dir / name
        for name in (*calibration.OUTPUTS, "calibration_manifest.json")
    }
    paths = {**sources, **{f"model/{name}": path for name, path in models.items()}}
    before = {name: sha256(path) for name, path in paths.items()}
    manifest = _load(models["calibration_manifest.json"])
    _contract(manifest)
    for name in calibration.OUTPUTS:
        if manifest.get("output_sha256", {}).get(name) != before[f"model/{name}"]:
            raise ValueError(f"{name} checksum mismatch")
    for field in ("input_sha256", "input_sha256_after"):
        if manifest.get(field) != {name: before[name] for name in sources}:
            raise ValueError("Source provenance differs from calibration input")
    source_manifest = _load(sources["model_manifest.json"])
    if (
        source_manifest.get("experiment_ready") is not False
        or source_manifest.get("final_model") is not False
    ):
        raise ValueError("Development-only source manifest required")
    if (
        source_manifest.get("label_version") != CHRIST_VERSION
        or tuple(source_manifest.get("feature_fields", ())) != FEATURE_FIELDS
    ):
        raise ValueError("Unexpected source feature or label contract")
    if (
        source_manifest.get("output_sha256", {}).get("training_rows.csv")
        != before["training_rows.csv"]
    ):
        raise ValueError("Training row checksum mismatch")
    with sources["training_rows.csv"].open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != TRAINING_FIELDS:
            raise ValueError("Unexpected training columns")
        rows = list(reader)
    if len(rows) != source_manifest.get("training_rows"):
        raise ValueError("Training row count mismatch")
    _validate(rows)
    train, cal, test, cutoffs = calibration.three_fold_split(
        calibration._normalized(rows)
    )
    evaluation = _load(models["calibration_evaluation.json"])
    artifact = _load(models["calibration_artifact.json"])
    _contract(evaluation)
    for key, value in cutoffs.items():
        if evaluation.get(key) != value or (
            key != "test_cutoffs" and artifact.get(key) != value
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
    report = evaluate(artifact, test, repeats=repeats, seed=seed, min_n=min_n)
    saved = json.loads(models["test_predictions.json"].read_text(encoding="utf-8"))
    if not isinstance(saved, list) or len(saved) != len(test):
        raise ValueError("Saved prediction count mismatch")
    logistic, x, y = _parameters(artifact)
    matrix = [[_raw(row, field) for field in FEATURES] for row in test]
    raw = _probabilities(logistic, matrix)
    calibrated = _interpolate(raw, x, y)
    for row, prediction, raw_p, cal_p in zip(test, saved, raw, calibrated):
        for key in ("golden_customer_id", "cutoff_at", "outcome_end_at"):
            if prediction.get(key) != row[key]:
                raise ValueError("Saved prediction identity mismatch")
        if (
            prediction.get("churn90") != _binary(row["churn90"], "churn90")
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
        **cutoffs,
        baseline_verified_against="calibration_evaluation.json and test_predictions.json",
    )
    output_dir.mkdir(parents=True)

    def write(name, value):
        (output_dir / name).write_text(
            json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )

    write("importance_report.json", report)
    write(
        "importance_manifest.json",
        {
            **STATUS,
            "explainer_version": EXPLAINER_VERSION,
            "explainer_method": EXPLAINER_METHOD,
            "model_version": calibration.MODEL_VERSION,
            "seed": seed,
            "repeats": repeats,
            "input_sha256": before,
            "input_sha256_after": after,
            "limitations": LIMITATIONS,
            "output_sha256": {
                "importance_report.json": sha256(output_dir / "importance_report.json")
            },
        },
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=REPEATS)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--min-n", type=int, default=MIN_SEGMENT_N)
    args = parser.parse_args()
    report = run(
        args.model_dir,
        args.output_dir,
        source_dir=args.source_dir,
        repeats=args.repeats,
        seed=args.seed,
        min_n=args.min_n,
    )
    print(
        json.dumps(
            {
                "holdout_rows": report["holdout_rows"],
                "serving_ready": False,
                "output": str(args.output_dir),
            }
        )
    )


if __name__ == "__main__":
    main()
