"""Moses-only fitted churn comparison on synthetic retrospective development rows.

Not point-in-time safe, calibrated, approved, or usable for serving decisions.
Install requirements-models.txt only in a development environment.
"""

import argparse
import csv
import json
import math
from datetime import timedelta, timezone
from pathlib import Path

from services.data.features.snapshot import FIELDS as FEATURE_FIELDS
from services.data.features.snapshot import VERSION as FEATURE_VERSION
from services.data.ingestion.validator import sha256
from services.data.models.baseline import predict_churn, temporal_split
from services.data.models.evaluator import _aware_timestamp, _binary
from services.data.models.labels import CHRIST_VERSION, TRAINING_FIELDS

MODEL_VERSION = "moses-fitted-churn-dev-1.0"
FEATURES = (
    "recency_days",
    "tenure_days",
    "purchase_count_365d",
    "retained_revenue_365d",
    "purchase_count_60d",
    "purchase_count_90d",
    "retained_revenue_90d",
)
SEED = 42
LOCAL_TIMEZONE = timezone(timedelta(hours=7))


def _matrix(rows: list[dict]) -> list[list[float]]:
    matrix = []
    for row in rows:
        values = []
        for field in FEATURES:
            value = row.get(field)
            if field == "recency_days" and (value is None or value == ""):
                values.append(float("nan"))  # eligible event-only cohort
                continue
            if isinstance(value, bool) or value is None or value == "":
                raise ValueError(f"{field} must be finite numeric")
            try:
                number = float(value)
            except (ValueError, TypeError, OverflowError) as exc:
                raise ValueError(f"{field} must be finite numeric") from exc
            if not math.isfinite(number) or number < 0:
                raise ValueError(f"{field} must be finite nonnegative numeric")
            values.append(number)
        matrix.append(values)
    return matrix


def _validate(rows: list[dict]) -> None:
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
        if end != cutoff + timedelta(days=90) or row.get("horizon_days") not in (
            90,
            "90",
        ):
            raise ValueError("Outcome window must be exactly 90 days")
        if (
            row.get("feature_version") != FEATURE_VERSION
            or row.get("label_version") != CHRIST_VERSION
        ):
            raise ValueError("Unexpected feature or label version")
        if row.get("identity_time_policy") != "CURRENT_SNAPSHOT_RETROSPECTIVE":
            raise ValueError("Unexpected identity time policy")
        for field in ("eligible", "outcome_complete"):
            if row.get(field) is not True and row.get(field) != "True":
                raise ValueError(f"{field} must be True")
        for field in ("training_ready", "experiment_ready"):
            if row.get(field) is not False and row.get(field) != "False":
                raise ValueError(f"{field} must be False")
        _binary(row.get("churn90"), "churn90")
    _matrix(rows)


def _metrics(actual, scores, *, binary=False):
    from sklearn.metrics import (
        average_precision_score,
        brier_score_loss,
        confusion_matrix,
        roc_auc_score,
    )

    predicted = [int(score >= 0.5) for score in scores]
    tn, fp, fn, tp = (
        int(n) for n in confusion_matrix(actual, predicted, labels=[0, 1]).ravel()
    )
    return {
        "rows": len(actual),
        "positives": sum(actual),
        "negatives": len(actual) - sum(actual),
        "roc_auc": (
            float(roc_auc_score(actual, scores)) if len(set(actual)) == 2 else None
        ),
        "average_precision": (
            float(average_precision_score(actual, scores)) if sum(actual) else None
        ),
        "brier_score": float(brier_score_loss(actual, scores)),
        "confusion": {"threshold": 0.5, "tp": tp, "tn": tn, "fp": fp, "fn": fn},
        "score_definition": (
            "fixed recency > 90; binary" if binary else "raw uncalibrated probability"
        ),
    }


def evaluate(rows: list[dict]) -> tuple[dict, list[dict], dict]:
    """Fit fixed estimators on purged train only; score one unchanged holdout."""
    import sklearn
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.tree import DecisionTreeClassifier

    _validate(rows)
    # Normalize representations before reusing the baseline's string-keyed split.
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
    y_train = [_binary(r["churn90"], "churn90") for r in train]
    if len(set(y_train)) != 2:
        raise ValueError("Training fold requires two classes")
    y_test = [_binary(r["churn90"], "churn90") for r in test]
    x_train, x_test = _matrix(train), _matrix(test)
    logistic = make_pipeline(
        SimpleImputer(strategy="median", keep_empty_features=True),
        StandardScaler(),
        LogisticRegression(random_state=SEED, max_iter=1000),
    )
    tree = make_pipeline(
        SimpleImputer(strategy="median", keep_empty_features=True),
        DecisionTreeClassifier(max_depth=3, min_samples_leaf=2, random_state=SEED),
    )
    logistic.fit(x_train, y_train)
    tree.fit(x_train, y_train)
    logistic_scores = logistic.predict_proba(x_test)[:, 1].tolist()
    tree_scores = tree.predict_proba(x_test)[:, 1].tolist()
    baseline_scores = [
        float(predict_churn(None if math.isnan(values[0]) else values[0]))
        for values in x_test
    ]
    report = {
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "label_version": CHRIST_VERSION,
        "features": list(FEATURES),
        "training_ready": False,
        "experiment_ready": False,
        "final_model": False,
        "development_only": True,
        "serving_ready": False,
        "train_rows": len(train),
        "test_rows": len(test),
        "purged_rows": len(rows) - len(train) - len(test),
        "train_cutoffs": train_cutoffs,
        "test_cutoffs": test_cutoffs,
        "logistic": _metrics(y_test, logistic_scores),
        "shallow_tree": _metrics(y_test, tree_scores),
        "baseline": _metrics(y_test, baseline_scores, binary=True),
        "limitations": [
            "Synthetic retrospective identity; no point-in-time historical guarantee",
            "Raw probabilities are not calibrated; no test-set threshold tuning",
            "Observational comparison only; no causal claims or serving approval",
        ],
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
            "logistic_probability": float(ls),
            "shallow_tree_probability": float(ts),
            "baseline_probability": bs,
        }
        for row, label, ls, ts, bs in zip(
            test, y_test, logistic_scores, tree_scores, baseline_scores
        )
    ]
    fitted = logistic.named_steps["logisticregression"]
    tree_fitted = tree.named_steps["decisiontreeclassifier"]
    parameters = {
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "label_version": CHRIST_VERSION,
        "features": list(FEATURES),
        "development_only": True,
        "serving_ready": False,
        "seed": SEED,
        "sklearn_version": sklearn.__version__,
        "serialization": "JSON inspection only; not a loadable or serving model",
        "logistic": {
            "imputer_medians": logistic.named_steps[
                "simpleimputer"
            ].statistics_.tolist(),
            "scaler_mean": logistic.named_steps["standardscaler"].mean_.tolist(),
            "scaler_scale": logistic.named_steps["standardscaler"].scale_.tolist(),
            "coef": fitted.coef_[0].tolist(),
            "intercept": fitted.intercept_.tolist(),
        },
        "shallow_tree": {
            "max_depth": 3,
            "min_samples_leaf": 2,
            "imputer_medians": tree.named_steps["simpleimputer"].statistics_.tolist(),
            "children_left": tree_fitted.tree_.children_left.tolist(),
            "children_right": tree_fitted.tree_.children_right.tolist(),
            "feature": tree_fitted.tree_.feature.tolist(),
            "threshold": tree_fitted.tree_.threshold.tolist(),
            "value": tree_fitted.tree_.value.tolist(),
        },
    }
    return report, predictions, parameters


def run(source: Path, output_dir: Path) -> dict:
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
    report, predictions, parameters = evaluate(rows)
    after = {name: sha256(path) for name, path in paths.items()}
    if after != before:
        raise ValueError("Input changed during experiment")
    report["input_sha256"] = before
    report["input_sha256_after"] = after
    output_dir.mkdir(parents=True)
    output_names = (
        "evaluation.json",
        "holdout_predictions.json",
        "model_parameters.json",
    )
    for name, value in zip(output_names, (report, predictions, parameters)):
        (output_dir / name).write_text(
            json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    experiment_manifest = {
        "model_version": MODEL_VERSION,
        "development_only": True,
        "serving_ready": False,
        "input_sha256": before,
        "input_sha256_after": after,
        "output_sha256": {name: sha256(output_dir / name) for name in output_names},
    }
    (output_dir / "experiment_manifest.json").write_text(
        json.dumps(experiment_manifest, indent=2, sort_keys=True) + "\n",
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
            {"training_ready": result["training_ready"], "output": str(args.output_dir)}
        )
    )


if __name__ == "__main__":
    main()
