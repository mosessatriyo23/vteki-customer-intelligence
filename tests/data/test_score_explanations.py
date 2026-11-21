"""Plain Indonesian descriptions of model contributions, not business causes."""

import copy

import pytest

from services.data.models.score_explanations import explain_contributions


def item(feature="recency_days", value=10, contribution=0.2):
    return dict(
        feature=feature,
        feature_value=value,
        missing=value is None,
        imputed_value=20 if value is None else value,
        log_odds_contribution=contribution,
    )


def test_directions_are_mathematical_not_customer_claims():
    result = explain_contributions(
        [item(), item("tenure_days", 100, -0.3)], target="retail_purchase30"
    )
    assert result["sentences"] == [
        "Dalam perhitungan model, lama sejak aktivitas terakhir mendorong skor pembelian retail dalam 30 hari naik.",
        "Dalam perhitungan model, lama pelanggan tercatat mendorong skor pembelian retail dalam 30 hari turun.",
    ]
    assert "bukan penyebab" in result["notice"]
    assert result["version"] == "score-explanation-id-1.0"


def test_missing_is_disclosed_and_zero_is_not_invented_as_a_reason():
    result = explain_contributions(
        [item(value=None), item("tenure_days", 100, 0)], target="renewal60"
    )
    assert result["sentences"][0].endswith(
        " Data fitur ini kosong; model memakai nilai pengganti."
    )
    assert "skor perpanjangan dalam 60 hari naik" in result["sentences"][0]
    assert len(result["sentences"]) == 1
    assert explain_contributions([], target="renewal60")["sentences"] == []
    assert (
        explain_contributions([item(contribution=0)], target="renewal60")["sentences"]
        == []
    )


def test_input_is_not_changed_and_order_is_preserved():
    source = [item("tenure_days", 100, -0.3), item()]
    before = copy.deepcopy(source)
    result = explain_contributions(source, target="churn90")
    assert source == before
    assert "lama pelanggan tercatat" in result["sentences"][0]
    assert "skor churn dalam 90 hari" in result["sentences"][0]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "0.2", None])
def test_invalid_contribution_rejected(value):
    with pytest.raises(ValueError):
        explain_contributions([item(contribution=value)], target="retail_purchase30")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "10", -1])
def test_invalid_feature_value_rejected(value):
    with pytest.raises(ValueError):
        explain_contributions([item(value=value)], target="retail_purchase30")


def test_unknown_duplicate_or_inconsistent_features_rejected():
    for source in ([item("secret")], [item(), item()], [{**item(), "missing": True}]):
        with pytest.raises(ValueError):
            explain_contributions(source, target="retail_purchase30")
    with pytest.raises(ValueError):
        explain_contributions([item()], target="booking")


def without(record, key):
    return {k: v for k, v in record.items() if k != key}


@pytest.mark.parametrize(
    "record",
    [
        {**item(value=None), "imputed_value": None},
        {**item(value=None), "imputed_value": float("nan")},
        {**item(value=None), "imputed_value": float("inf")},
        {**item(value=None), "imputed_value": -1},
        {**item(value=None), "imputed_value": True},
        {**item(value=None), "imputed_value": "20"},
        without(item(value=None), "imputed_value"),
        without(item(value=None), "feature_value"),
        without(item(), "feature_value"),
        without(item(), "imputed_value"),
        without(item(), "missing"),
        {**item(value=10), "imputed_value": 11},
    ],
)
def test_incomplete_or_inconsistent_imputation_data_is_rejected(record):
    with pytest.raises(ValueError):
        explain_contributions([record], target="retail_purchase30")


@pytest.mark.parametrize(
    "feature",
    [
        "purchase_count_365d",
        "retained_revenue_365d",
        "purchase_count_60d",
        "purchase_count_90d",
        "retained_revenue_90d",
    ],
)
def test_remaining_supported_features_have_readable_labels(feature):
    result = explain_contributions([item(feature)], target="renewal60")
    assert feature not in result["sentences"][0]
    assert "naik" in result["sentences"][0]
