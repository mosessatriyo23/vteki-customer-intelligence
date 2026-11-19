"""Moses-only three-cutoff churn calibration on synthetic development rows.

Chronological folds: train (earliest cutoffs) -> calibration (middle cutoff) ->
test (latest cutoff). The logistic model is fit on train only; an isotonic
calibrator and the decision threshold are fit/chosen on the calibration fold
only. The test fold is scored once and never fitted, tuned, or searched.

Not point-in-time safe, production-calibrated, approved, or usable for serving.
Install requirements-models.txt only in a development environment.
"""

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

from services.data.features.snapshot import FIELDS as FEATURE_FIELDS
from services.data.features.snapshot import VERSION as FEATURE_VERSION
from services.data.ingestion.validator import sha256
from services.data.models.churn_diagnostics import _metrics, _operating, _reliability
from services.data.models.churn_experiment import (
    FEATURES,
    LOCAL_TIMEZONE,
    SEED,
    _matrix,
    _validate,
)
from services.data.models.evaluator import _aware_timestamp, _binary
from services.data.models.labels import CHRIST_VERSION, TRAINING_FIELDS

MODEL_VERSION = "moses-calibrated-churn-dev-1.0"
CALIBRATION_METHOD = "isotonic_regression_fit_on_calibration_fold"
THRESHOLD_RULE = (
    "Declared before any test scoring: maximise F1 on the calibration fold over "
    "the distinct calibration-fold scores (positive iff score >= threshold); "
    "ties go to the highest threshold; fall back to 0.5 when the calibration "
    "fold lacks two classes."
)
TIE_POLICY = (
    "Rows tied on score are spread uniformly across the ranks they occupy, so "
    "capture and lift do not depend on row order within a tie."
)
FIXED_THRESHOLD = 0.5
OUTPUTS = (
    "calibration_evaluation.json",
    "test_predictions.json",
    "calibration_artifact.json",
)
FLAGS = dict(
    training_ready=False,
    experiment_ready=False,
    final_model=False,
    serving_ready=False,
    development_only=True,
)
LIMITATIONS = [
    "Synthetic retrospective identity; no point-in-time (PIT) historical guarantee",
    "Isotonic calibration on a synthetic calibration fold is not production "
    "calibration approval; reliability and ECE are descriptive only",
    "Threshold chosen on the calibration fold only; no production threshold or "
    "serving authorization",
    "Observational comparison only; no causal or campaign-effect claims",
]


def _normalized(rows: list[dict]) -> list[dict]:
    return sorted(
        (
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
        ),
        key=lambda row: (row["cutoff_at"], row["golden_customer_id"]),
    )


def three_fold_split(rows: list[dict]) -> tuple[list, list, list, dict]:
    """Purged chronological train/calibration/test folds.

    Latest cutoff is test, the one before it is calibration, all earlier cutoffs
    are train. A row is purged unless its outcome ended by the next fold's cutoff.
    """
    cutoffs = sorted({datetime.fromisoformat(r["cutoff_at"]) for r in rows})
    if len(cutoffs) < 3:
        raise ValueError(
            "At least three distinct cutoffs are required for train/calibration/test; "
            "no two-fold fallback"
        )
    test_cutoff, calibration_cutoff = cutoffs[-1], cutoffs[-2]
    train_set = {c.isoformat() for c in cutoffs[:-2]}
    train = [
        r
        for r in rows
        if r["cutoff_at"] in train_set
        and datetime.fromisoformat(r["outcome_end_at"]) <= calibration_cutoff
    ]
    calibration = [
        r
        for r in rows
        if r["cutoff_at"] == calibration_cutoff.isoformat()
        and datetime.fromisoformat(r["outcome_end_at"]) <= test_cutoff
    ]
    test = [r for r in rows if r["cutoff_at"] == test_cutoff.isoformat()]
    if not train or not calibration or not test:
        raise ValueError("Purged three-fold split produced an empty fold")
    return (
        train,
        calibration,
        test,
        {
            "train_cutoffs": sorted({r["cutoff_at"] for r in train}),
            "calibration_cutoffs": [calibration_cutoff.isoformat()],
            "test_cutoffs": [test_cutoff.isoformat()],
        },
    )


def _ratio(a, b):
    return a / b if b else None


def _operating_at(scored, threshold):
    if threshold == FIXED_THRESHOLD:
        return _operating(scored)
    tp = sum(y == 1 and p >= threshold for y, p in scored)
    tn = sum(y == 0 and p < threshold for y, p in scored)
    fp = sum(y == 0 and p >= threshold for y, p in scored)
    fn = sum(y == 1 and p < threshold for y, p in scored)
    return dict(
        threshold=threshold,
        tp=tp,
        tn=tn,
        fp=fp,
        fn=fn,
        precision=_ratio(tp, tp + fp),
        recall=_ratio(tp, tp + fn),
        f1=_ratio(2 * tp, 2 * tp + fp + fn),
        specificity=_ratio(tn, tn + fp),
    )


def select_threshold(scored: list[tuple[int, float]]) -> dict:
    """THRESHOLD_RULE on calibration-fold scores only."""
    positives = sum(y for y, _ in scored)
    if not positives or positives == len(scored):
        return dict(
            threshold=FIXED_THRESHOLD,
            f1=None,
            precision=None,
            recall=None,
            rule=THRESHOLD_RULE,
            note="Calibration fold lacks two classes; fixed 0.5 used, F1 undefined",
        )
    groups: dict[float, list[int]] = {}
    for label, score in scored:
        counts = groups.setdefault(score, [0, 0])
        counts[label] += 1
    best = None
    tp = fp = 0
    for score in sorted(groups, reverse=True):
        fp += groups[score][0]
        tp += groups[score][1]
        f1 = 2 * tp / (2 * tp + fp + (positives - tp))
        if best is None or f1 > best[0]:
            best = (f1, score, tp, fp)
    assert best is not None
    f1, threshold, tp, fp = best
    return dict(
        threshold=float(threshold),
        f1=f1,
        precision=tp / (tp + fp),
        recall=tp / positives,
        rule=THRESHOLD_RULE,
        note=None,
    )


def lift_gains(scored: list[tuple[int, float]]) -> dict:
    """Tie-aware decile gains plus explicit top-10% and top-20% capture/lift."""
    n = len(scored)
    total = sum(y for y, _ in scored)
    base_rate = total / n
    groups: dict[float, list[int]] = {}
    for label, score in scored:
        counts = groups.setdefault(score, [0, 0])
        counts[label] += 1
    ordered = [(sum(groups[s]), groups[s][1]) for s in sorted(groups, reverse=True)]

    def captured(k: float) -> float:
        """Positives expected in the top k rows, splitting a boundary tie."""
        used = got = 0.0
        for size, positives in ordered:
            if used + size <= k:
                used += size
                got += positives
            else:
                got += positives * (k - used) / size
                break
        return got

    def top(fraction: float) -> dict:
        rows = n * fraction
        got = captured(rows)
        return dict(
            fraction=fraction,
            rows=rows,
            captured_positives=got,
            capture_rate=_ratio(got, total),
            lift=(got / rows) / base_rate if total else None,
        )

    deciles = []
    for i in range(10):
        low, high = n * i / 10, n * (i + 1) / 10
        got = captured(high) - captured(low)
        deciles.append(
            dict(
                decile=i + 1,
                rows=high - low,
                positives=got,
                observed_event_rate=got / (high - low),
                lift=(got / (high - low)) / base_rate if total else None,
                cumulative_capture_rate=_ratio(captured(high), total),
            )
        )
    return dict(
        rows=n,
        positives=total,
        base_rate=base_rate,
        tie_policy=TIE_POLICY,
        deciles=deciles,
        top_10_percent=top(0.1),
        top_20_percent=top(0.2),
    )


def _block(scored, selected):
    table, ece = _reliability(scored)
    return dict(
        metrics=_metrics(scored),
        operating_at_fixed_threshold=_operating_at(scored, FIXED_THRESHOLD),
        operating_at_selected_threshold=_operating_at(scored, selected),
        reliability=table,
        expected_calibration_error=ece,
        lift_gains=lift_gains(scored),
    )


def evaluate(rows: list[dict]) -> tuple[dict, list[dict], dict]:
    """Fit on train, calibrate and pick a threshold on calibration, score test."""
    import sklearn
    from sklearn.impute import SimpleImputer
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    _validate(rows)
    rows = _normalized(rows)
    train, calibration, test, cutoffs = three_fold_split(rows)
    y_train = [_binary(r["churn90"], "churn90") for r in train]
    if len(set(y_train)) != 2:
        raise ValueError("Training fold requires two classes")
    y_cal = [_binary(r["churn90"], "churn90") for r in calibration]
    y_test = [_binary(r["churn90"], "churn90") for r in test]
    model = make_pipeline(
        SimpleImputer(strategy="median", keep_empty_features=True),
        StandardScaler(),
        LogisticRegression(random_state=SEED, max_iter=1000),
    )
    model.fit(_matrix(train), y_train)
    raw_cal = model.predict_proba(_matrix(calibration))[:, 1].tolist()
    isotonic = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    isotonic.fit(raw_cal, y_cal)
    calibrated_cal = isotonic.predict(raw_cal).tolist()
    selection = {
        "uncalibrated": select_threshold(list(zip(y_cal, raw_cal))),
        "calibrated": select_threshold(list(zip(y_cal, calibrated_cal))),
    }
    # Test fold is touched only below, after calibrator and thresholds are fixed.
    raw_test = model.predict_proba(_matrix(test))[:, 1].tolist()
    calibrated_test = isotonic.predict(raw_test).tolist()
    scores = {"uncalibrated": raw_test, "calibrated": calibrated_test}
    selected = selection["calibrated"]["threshold"]
    report = {
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "label_version": CHRIST_VERSION,
        "features": list(FEATURES),
        **FLAGS,
        "calibration_method": CALIBRATION_METHOD,
        "threshold_rule": THRESHOLD_RULE,
        "selected_threshold": selected,
        "selected_threshold_source": "calibration_fold",
        "train_rows": len(train),
        "calibration_rows": len(calibration),
        "test_rows": len(test),
        "purged_rows": len(rows) - len(train) - len(calibration) - len(test),
        **cutoffs,
        "calibration_selection": selection,
        "test": {
            name: _block(
                list(zip(y_test, values)),
                selection[name]["threshold"],
            )
            for name, values in scores.items()
        },
        "limitations": LIMITATIONS,
    }
    if any("segment" in row for row in test):
        segments: dict[str, list[int]] = {}
        for index, row in enumerate(test):
            value = row.get("segment")
            key = "(missing)" if value in (None, "") else str(value)
            segments.setdefault(key, []).append(index)
        report["segments"] = {
            key: {
                "rows": len(indexes),
                "positives": sum(y_test[i] for i in indexes),
                **{
                    name: {
                        "metrics": _metrics([(y_test[i], values[i]) for i in indexes]),
                        "operating_at_selected_threshold": _operating_at(
                            [(y_test[i], values[i]) for i in indexes],
                            selection[name]["threshold"],
                        ),
                    }
                    for name, values in scores.items()
                },
            }
            for key, indexes in sorted(segments.items())
        }
    predictions = [
        {
            "golden_customer_id": row["golden_customer_id"],
            "cutoff_at": row["cutoff_at"],
            "outcome_end_at": row["outcome_end_at"],
            "churn90": label,
            "model_version": MODEL_VERSION,
            "feature_version": FEATURE_VERSION,
            "label_version": CHRIST_VERSION,
            "development_only": True,
            "serving_ready": False,
            "raw_probability": float(raw),
            "calibrated_probability": float(calibrated),
        }
        for row, label, raw, calibrated in zip(test, y_test, raw_test, calibrated_test)
    ]
    fitted = model.named_steps["logisticregression"]
    artifact = {
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "label_version": CHRIST_VERSION,
        "features": list(FEATURES),
        **FLAGS,
        "seed": SEED,
        "sklearn_version": sklearn.__version__,
        "serialization": "JSON inspection only",
        "train_cutoffs": cutoffs["train_cutoffs"],
        "calibration_cutoffs": cutoffs["calibration_cutoffs"],
        "method": CALIBRATION_METHOD,
        "logistic": {
            "imputer_medians": model.named_steps["simpleimputer"].statistics_.tolist(),
            "scaler_mean": model.named_steps["standardscaler"].mean_.tolist(),
            "scaler_scale": model.named_steps["standardscaler"].scale_.tolist(),
            "coef": fitted.coef_[0].tolist(),
            "intercept": fitted.intercept_.tolist(),
        },
        "isotonic": {
            "x_thresholds": isotonic.X_thresholds_.tolist(),
            "y_thresholds": isotonic.y_thresholds_.tolist(),
            "out_of_bounds": "clip",
        },
        "thresholds": selection,
        "selected_threshold": selected,
        "threshold_rule": THRESHOLD_RULE,
    }
    return report, predictions, artifact


def run(source: Path, output_dir: Path) -> dict:
    source, output_dir = Path(source), Path(output_dir)
    if output_dir.exists():
        raise ValueError("Use a new output directory")
    source, output_dir = source.resolve(), output_dir.resolve()
    if any(part.lower() == "ground_truth" for part in source.parts + output_dir.parts):
        raise ValueError("ground_truth paths are not allowed")
    if (
        source == output_dir
        or source in output_dir.parents
        or output_dir in source.parents
    ):
        raise ValueError("Keep input and output separate")
    paths = {
        name: source / name for name in ("model_manifest.json", "training_rows.csv")
    }
    before = {name: sha256(path) for name, path in paths.items()}
    manifest = json.loads(paths["model_manifest.json"].read_text(encoding="utf-8"))
    if (
        manifest.get("experiment_ready") is not False
        or manifest.get("final_model") is not False
    ):
        raise ValueError("Development-only manifest required")
    if (
        manifest.get("label_version") != CHRIST_VERSION
        or tuple(manifest.get("feature_fields", ())) != FEATURE_FIELDS
    ):
        raise ValueError("Unexpected label or feature contract")
    if (
        manifest.get("output_sha256", {}).get("training_rows.csv")
        != before["training_rows.csv"]
    ):
        raise ValueError("Training row checksum mismatch")
    with paths["training_rows.csv"].open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != TRAINING_FIELDS:
            raise ValueError("Unexpected training row columns")
        rows = list(reader)
    if len(rows) != manifest.get("training_rows"):
        raise ValueError("Training row count mismatch")
    report, predictions, artifact = evaluate(rows)
    after = {name: sha256(path) for name, path in paths.items()}
    if after != before:
        raise ValueError("Input changed during calibration")
    report["input_sha256"] = before
    report["input_sha256_after"] = after
    output_dir.mkdir(parents=True)
    for name, value in zip(OUTPUTS, (report, predictions, artifact)):
        (output_dir / name).write_text(
            json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    completion = {
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "label_version": CHRIST_VERSION,
        **FLAGS,
        "input_sha256": before,
        "input_sha256_after": after,
        "output_sha256": {name: sha256(output_dir / name) for name in OUTPUTS},
    }
    (output_dir / "calibration_manifest.json").write_text(
        json.dumps(completion, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.source, args.output_dir)
    print(
        json.dumps(
            {"serving_ready": result["serving_ready"], "output": str(args.output_dir)}
        )
    )


if __name__ == "__main__":
    main()
