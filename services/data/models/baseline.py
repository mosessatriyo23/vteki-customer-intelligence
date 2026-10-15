"""Deterministic stdlib baselines on chrono holdout; not tuned or final."""

import statistics
from datetime import datetime

RECENCY_THRESHOLD_DAYS = 90
CLV_STRATEGY = "median"
MODEL_NAME = "baseline-recency90-median-clv-proposed-dev-1.0"


def _median(values: list[int | float]) -> float:
    if not values:
        return 0.0
    return float(statistics.median(values))


def _mean(values: list[int | float]) -> float:
    if not values:
        return 0.0
    return float(statistics.mean(values))


def temporal_split(
    rows: list[dict],
) -> tuple[list[dict], list[dict], list[str], list[str]]:
    """Purged chronological holdout; latest complete cutoff is the test fold."""
    cutoffs = sorted({datetime.fromisoformat(r["cutoff_at"]) for r in rows})
    if len(cutoffs) < 2:
        raise ValueError(
            "At least two cutoffs are required for chronological train/test"
        )
    holdout = cutoffs[-1]
    train_set = {c.isoformat() for c in cutoffs[:-1]}
    test_set = {holdout.isoformat()}
    # Purge training outcomes that were not complete by holdout feature time.
    # A chronological cutoff split alone still leaks overlapping future labels.
    train_rows = [
        r
        for r in rows
        if r["cutoff_at"] in train_set
        and datetime.fromisoformat(r["outcome_end_at"]) <= holdout
    ]
    test_rows = [r for r in rows if r["cutoff_at"] in test_set]
    if not train_rows or not test_rows:
        raise ValueError("Purged temporal split produced empty train or test set")
    return (
        train_rows,
        test_rows,
        sorted({r["cutoff_at"] for r in train_rows}),
        [holdout.isoformat()],
    )


def predict_churn(recency_days, threshold: int = RECENCY_THRESHOLD_DAYS) -> int:
    if recency_days is None or recency_days == "":
        return 1
    try:
        return 1 if int(recency_days) > threshold else 0
    except (ValueError, TypeError):
        return 1


def evaluate(training_rows: list[dict]) -> dict:
    """Evaluate naive baselines on purged temporal holdout.

    Churn: recency > 90 => churn (fixed threshold, not fitted).
    CLV: constant median (and mean for reporting) from train.
    """
    if not training_rows:
        raise ValueError("No complete eligible training rows to evaluate")
    # Ensure rows are complete/eligible (caller should have filtered).
    for row in training_rows:
        if row.get("churn90") is None or row.get("clv90") is None:
            raise ValueError("Training rows must have complete labels")
    train_rows, test_rows, train_cutoffs, test_cutoffs = temporal_split(training_rows)
    train_clv = [int(r["clv90"]) for r in train_rows]
    clv_median = _median(train_clv)
    clv_mean = _mean(train_clv)
    # Churn confusion
    tp = tn = fp = fn = 0
    for row in test_rows:
        pred = predict_churn(row.get("recency_days"))
        actual = int(row["churn90"])
        if pred == 1 and actual == 1:
            tp += 1
        elif pred == 0 and actual == 0:
            tn += 1
        elif pred == 1 and actual == 0:
            fp += 1
        else:
            fn += 1
    total = len(test_rows)
    accuracy = (tp + tn) / total if total else 0.0
    tpr = tp / (tp + fn) if (tp + fn) else 0.0
    tnr = tn / (tn + fp) if (tn + fp) else 0.0
    balanced_accuracy = (
        (tpr + tnr) / 2
        if (tp + fn) and (tn + fp)
        else (tpr if (tp + fn) else tnr if (tn + fp) else 0.0)
    )
    # CLV MAE against median baseline
    mae = (
        sum(abs(int(r["clv90"]) - clv_median) for r in test_rows) / total
        if total
        else 0.0
    )
    mae_mean = (
        sum(abs(int(r["clv90"]) - clv_mean) for r in test_rows) / total
        if total
        else 0.0
    )
    return dict(
        model=MODEL_NAME,
        experiment_ready=False,
        purged_rows=len(training_rows) - len(train_rows) - len(test_rows),
        recency_threshold_days=RECENCY_THRESHOLD_DAYS,
        clv_predictor=CLV_STRATEGY,
        clv_train_median=clv_median,
        clv_train_mean=clv_mean,
        train_rows=len(train_rows),
        test_rows=len(test_rows),
        train_cutoffs=train_cutoffs,
        test_cutoffs=test_cutoffs,
        churn=dict(
            tp=tp,
            tn=tn,
            fp=fp,
            fn=fn,
            accuracy=accuracy,
            balanced_accuracy=balanced_accuracy,
            tpr=tpr,
            tnr=tnr,
        ),
        clv=dict(
            mae=mae,
            mae_mean_baseline=mae_mean,
            median_baseline=clv_median,
            mean_baseline=clv_mean,
        ),
        counts=dict(
            train=len(train_rows), test=len(test_rows), total=len(training_rows)
        ),
    )
