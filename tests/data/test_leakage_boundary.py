"""Synthetic event-time evidence across feature, label, fit and score boundaries."""

import argparse
from datetime import date, datetime, timedelta, timezone

import pytest

from generator.generate import run as generate
from services.data.features.snapshot import FIELDS as FEATURE_FIELDS
from services.data.features.snapshot import build_features
from services.data.identity.cli import run as resolve
from services.data.models.churn_experiment import FEATURES as CHURN_FEATURES
from services.data.models.churn_experiment import evaluate as fit_churn
from services.data.models.labels import FIELDS as CHURN_LABEL_FIELDS
from services.data.models.labels import (
    TRAINING_FIELDS,
    build_labels,
    join_training_rows,
)
from services.data.models.propensity_experiment import FEATURES as PROPENSITY_FEATURES
from services.data.models.propensity_experiment import evaluate as fit_propensity
from services.data.models.propensity_experiment import run as fit_propensity_files
from services.data.models.propensity_inference import load_model, predict_rows
from services.data.models.propensity_labels import FIELDS as PROPENSITY_LABEL_FIELDS
from services.data.models.propensity_labels import build_propensity_labels
from tests.data.test_churn_experiment import rows as churn_cohort
from tests.data.test_data_leakage import append_source_row, read_csv
from tests.data.test_propensity_experiment import joined as propensity_cohort
from tests.data.test_propensity_experiment import write_inputs


@pytest.fixture
def source(tmp_path):
    inbound, resolution = tmp_path / "inbound", tmp_path / "resolution"
    generate(
        argparse.Namespace(
            seed=20260906,
            customers=20,
            as_of_date=date(2026, 9, 6),
            output_dir=inbound,
            ground_truth_dir=tmp_path / "evaluation_only",
        )
    )
    resolve(inbound / "crm_customers.csv", resolution, synthetic_aliases=True)
    return inbound, resolution


def test_future_events_do_not_cross_feature_label_or_inference_boundary(
    source, tmp_path
):
    inbound, resolution = source
    cutoff = datetime.fromisoformat("2026-06-01T12:00:00+07:00")
    end = cutoff + timedelta(days=90)
    later = end + timedelta(seconds=1)
    before = build_features(inbound, resolution, [cutoff, later])
    labels_before = build_labels(inbound, resolution, [cutoff], christ_events=True)
    propensity_before = build_propensity_labels(inbound, resolution, [cutoff])
    assert labels_before and propensity_before
    mapping = {
        row["source_customer_id"]: row["golden_customer_id"]
        for row in read_csv(resolution / "mapping.csv")
    }
    template = next(
        row
        for row in read_csv(inbound / "transactions.csv")
        if row["source_customer_ref"] in mapping
        and row["status"] == "COMPLETED"
        and datetime.fromisoformat(row["transaction_datetime"]) <= cutoff
    )
    golden = mapping[template["source_customer_ref"]]
    item = next(
        row
        for row in read_csv(inbound / "transaction_items.csv")
        if row["source_transaction_id"] == template["source_transaction_id"]
    )
    for index, moment in enumerate((cutoff + timedelta(days=1), end, later)):
        transaction_id = f"boundary-transaction-{index}"
        append_source_row(
            inbound,
            "transactions.csv",
            {
                **template,
                "source_transaction_id": transaction_id,
                "transaction_datetime": moment.isoformat(),
                "source_system": "ECOM",
                "channel_code": "WEB_STORE",
                "branch_code": "",
                "gross_amount": "999999999",
                "net_amount": "999999999",
                "discount_amount": "0",
                "refund_amount": "0",
                "actual_revenue": "999999999",
            },
        )
        append_source_row(
            inbound,
            "transaction_items.csv",
            {
                **item,
                "source_item_id": f"boundary-item-{index}",
                "source_transaction_id": transaction_id,
                "qty": "1",
                "unit_price": "999999999",
                "line_amount": "999999999",
            },
        )
    visit = next(
        row
        for row in read_csv(inbound / "customer_visits.csv")
        if row["source_customer_ref"] in mapping
    )
    append_source_row(
        inbound,
        "customer_visits.csv",
        {
            **visit,
            "visit_id": "boundary-visit",
            "source_transaction_id": "",
            "source_customer_ref": template["source_customer_ref"],
            "visit_datetime": end.isoformat(),
            "status": "COMPLETED",
        },
    )
    renewal = next(
        row
        for row in read_csv(inbound / "membership_events.csv")
        if row["source_customer_ref"] in mapping
    )
    append_source_row(
        inbound,
        "membership_events.csv",
        {
            **renewal,
            "event_id": "boundary-renewal",
            "previous_event_id": "",
            "source_customer_ref": template["source_customer_ref"],
            "event_type": "RENEWAL",
            "occurred_at": end.isoformat(),
            "period_start": end.date().isoformat(),
            "expires_at": (end + timedelta(days=365)).isoformat(),
        },
    )
    after = build_features(inbound, resolution, [cutoff, later])

    def at_cutoff(rows):
        return [row for row in rows if row["cutoff_at"] == cutoff.isoformat()]

    assert at_cutoff(after) == at_cutoff(before)
    labels_after = build_labels(inbound, resolution, [cutoff], christ_events=True)
    joined_before = join_training_rows(at_cutoff(before), labels_before)
    joined_after = join_training_rows(at_cutoff(after), labels_after)
    assert joined_before and joined_after
    assert set().union(*(set(row) for row in joined_after)) == set(TRAINING_FIELDS)
    assert [[row[field] for field in CHURN_FEATURES] for row in joined_before] == [
        [row[field] for field in CHURN_FEATURES] for row in joined_after
    ]
    # Labels see T+1d and the inclusive 90d endpoint, but NOT endpoint+1s.
    previous_label = next(
        row for row in labels_before if row["golden_customer_id"] == golden
    )
    current_label = next(
        row for row in labels_after if row["golden_customer_id"] == golden
    )
    assert current_label["clv90"] == previous_label["clv90"] + 2 * 999999999
    previous = next(
        row
        for row in before
        if row["cutoff_at"] == later.isoformat() and row["golden_customer_id"] == golden
    )
    current = next(
        row
        for row in after
        if row["cutoff_at"] == later.isoformat() and row["golden_customer_id"] == golden
    )
    assert current["purchase_count_90d"] > previous["purchase_count_90d"]
    assert current["retained_revenue_90d"] > previous["retained_revenue_90d"]

    # Fit a real propensity artifact, then score the generated feature snapshot.
    labels_dir, features_dir = write_inputs(tmp_path / "fit-inputs")
    fit_propensity_files(
        labels_dir, features_dir, "retail_purchase30", tmp_path / "model"
    )
    model = load_model(tmp_path / "model", "retail_purchase30")
    generated_at = datetime(2026, 11, 20, tzinfo=timezone.utc)
    assert predict_rows(
        model, at_cutoff(before), generated_at=generated_at
    ) == predict_rows(model, at_cutoff(after), generated_at=generated_at)


@pytest.mark.parametrize("target", ["retail_purchase30", "renewal60"])
def test_fitted_predictor_allowlist_excludes_outcomes_and_ground_truth(target):
    churn_report = fit_churn(churn_cohort())[0]
    propensity_report = fit_propensity(propensity_cohort(target), target)[0]
    for report, features in (
        (churn_report, CHURN_FEATURES),
        (propensity_report, PROPENSITY_FEATURES),
    ):
        assert report["features"] == list(features)
        assert set(features) <= set(FEATURE_FIELDS) <= set(TRAINING_FIELDS)
        assert set(features).isdisjoint(
            set(CHURN_LABEL_FIELDS) - {"golden_customer_id", "cutoff_at"}
        )
        assert set(features).isdisjoint(
            set(PROPENSITY_LABEL_FIELDS) - {"golden_customer_id", "cutoff_at"}
        )
        assert all("ground_truth" not in field.lower() for field in features)
