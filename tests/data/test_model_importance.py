"""Holdout-only permutation reliance and feature-derived segment diagnostics."""

import copy
import json

import pytest

from services.data.models.model_importance import evaluate, run

FEATURES = [
    "recency_days",
    "tenure_days",
    "purchase_count_365d",
    "retained_revenue_365d",
    "purchase_count_60d",
    "purchase_count_90d",
    "retained_revenue_90d",
]
PARAMS = {
    "features": FEATURES,
    "development_only": True,
    "serving_ready": False,
    "logistic": {
        "imputer_medians": [1] * 7,
        "scaler_mean": [0] * 7,
        "scaler_scale": [1] * 7,
        "coef": [-2, 0, 0, 0, 0, 0, 0],
        "intercept": [2],
    },
}


def rows():
    return [
        {
            **dict.fromkeys(FEATURES, 0),
            "recency_days": i % 2 * 2,
            "label": 1 - i % 2,
            "tenure_days": 20,
        }
        for i in range(200)
    ]


def test_permutation_is_holdout_only_deterministic_and_does_not_mutate():
    holdout = rows()
    original = copy.deepcopy(holdout)
    first = evaluate(PARAMS, holdout, "label", repeats=10)
    assert first == evaluate(PARAMS, holdout, "label", repeats=10)
    assert holdout == original
    importance = {item["feature"]: item for item in first["global_importance"]}
    assert importance["recency_days"]["auc_drop_mean"] > 0.3
    assert importance["tenure_days"]["auc_drop_mean"] == 0
    assert importance["recency_days"]["brier_increase_mean"] > 0
    assert importance["recency_days"]["rank"] == 1
    assert first["grouped_importance"][0]["features"] == [
        "purchase_count_60d",
        "purchase_count_90d",
        "purchase_count_365d",
    ]
    assert first["explainer_method"] == "permutation_importance_auc_drop"
    json.dumps(first, allow_nan=False)


def test_segments_single_class_and_small_sample():
    holdout = rows()
    holdout[0]["recency_days"] = None
    result = evaluate(PARAMS, holdout, "label", min_n=100, repeats=2)
    recency = {s["bucket"]: s for s in result["segments"]["recency_days"]}
    assert recency["missing"]["roc_auc"] is None
    assert recency["missing"]["auc_reason"] == "n_below_min_n_and_single_class"
    assert recency["missing"]["small_segment"] is True
    assert recency["<=30"]["n"] == 199
    assert recency["missing"]["brier_score"] is not None
    json.dumps(result, allow_nan=False)


def test_single_class_holdout_has_null_importance_auc():
    holdout = rows()
    for row in holdout:
        row["label"] = 0
    result = evaluate(PARAMS, holdout, "label", repeats=2)
    assert result["global_importance"][0]["auc_drop_mean"] is None
    assert result["baseline"]["roc_auc"] is None


def test_reject_label_as_feature_and_unexpected_feature_contract():
    parameters = copy.deepcopy(PARAMS)
    parameters["features"][0] = "label"
    with pytest.raises(ValueError, match="feature contract"):
        evaluate(parameters, rows(), "label")


def test_reject_unknown_predictor_contract():
    parameters = copy.deepcopy(PARAMS)
    parameters["features"][0] = "lifecycle_label"
    with pytest.raises(ValueError, match="feature contract"):
        evaluate(parameters, rows(), "label")


@pytest.mark.parametrize("repeats", [0, -1, True, 1.5])
def test_invalid_repeat_count(repeats):
    with pytest.raises(ValueError, match="repeats"):
        evaluate(PARAMS, rows(), "label", repeats=repeats)


def test_refuse_overwrite_ground_truth_and_overlap(tmp_path):
    model = tmp_path / "model"
    source = tmp_path / "source"
    model.mkdir()
    source.mkdir()
    existing = tmp_path / "existing"
    existing.mkdir()
    for output, expected in (
        (existing, "new output"),
        (tmp_path / "ground_truth" / "out", "ground_truth"),
        (source / "out", "separate"),
    ):
        with pytest.raises(ValueError, match=expected):
            run("churn", model, output, source_dir=source)
    with pytest.raises(ValueError, match="ground_truth"):
        run(
            "churn",
            tmp_path / "ground_truth" / "model",
            tmp_path / "new",
            source_dir=source,
        )
