"""Independent evidence checks for the offline Moses churn diagnostic."""

import json
import random
from datetime import timedelta

import pytest

from services.data.features.snapshot import VERSION as FEATURE_VERSION
from services.data.ingestion.validator import sha256
from services.data.models import churn_diagnostics as diagnostics
from services.data.models.churn_experiment import FEATURES, MODEL_VERSION
from services.data.models.labels import CHRIST_VERSION


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


@pytest.fixture
def experiment(tmp_path):
    source = tmp_path / "experiment"
    source.mkdir()
    identity = dict(
        model_version=MODEL_VERSION,
        feature_version=FEATURE_VERSION,
        label_version=CHRIST_VERSION,
        development_only=True,
        serving_ready=False,
    )
    rows = []
    for i in range(12):
        rows.append(
            dict(
                identity,
                golden_customer_id=f"c{i // 2}",
                cutoff_at=f"2026-0{5 + i % 2}-01T00:00:00+07:00",
                outcome_end_at=f"2026-0{5 + i % 2}-01T00:00:00+07:00",
                churn90=i % 2,
                logistic_probability=0.2 if i % 2 == 0 else 0.8,
                shallow_tree_probability=0.5,
                baseline_probability=float(i % 2),
            )
        )
    for row in rows:
        row["outcome_end_at"] = (
            diagnostics._aware_timestamp(row["cutoff_at"], "cutoff")
            + timedelta(days=90)
        ).isoformat()
    provenance = {"training_rows.csv": "a" * 64, "model_manifest.json": "b" * 64}
    report = dict(
        identity,
        features=list(FEATURES),
        training_ready=False,
        experiment_ready=False,
        final_model=False,
        test_rows=12,
        train_rows=20,
        purged_rows=3,
        train_cutoffs=["2025-01-01T00:00:00+07:00"],
        test_cutoffs=sorted({r["cutoff_at"] for r in rows}),
        input_sha256=provenance,
        input_sha256_after=provenance,
        **{
            name: {"rows": 12, "positives": 6, "negatives": 6}
            for name in ("logistic", "shallow_tree", "baseline")
        },
    )
    write_json(source / "evaluation.json", report)
    write_json(source / "holdout_predictions.json", rows)
    write_json(
        source / "model_parameters.json", dict(identity, features=list(FEATURES))
    )
    manifest = dict(
        model_version=MODEL_VERSION,
        development_only=True,
        serving_ready=False,
        input_sha256=provenance,
        input_sha256_after=provenance,
    )
    write_json(source / "experiment_manifest.json", manifest)
    refresh(source)
    return source


def refresh(source):
    manifest = json.loads((source / "experiment_manifest.json").read_text())
    manifest["output_sha256"] = {
        name: sha256(source / name)
        for name in (
            "evaluation.json",
            "holdout_predictions.json",
            "model_parameters.json",
        )
    }
    write_json(source / "experiment_manifest.json", manifest)


def predictions(source):
    return json.loads((source / "holdout_predictions.json").read_text())


def test_deterministic_report_integrity_and_metrics(experiment, tmp_path):
    first = diagnostics.run(experiment, tmp_path / "one", repeats=40)
    second = diagnostics.run(experiment, tmp_path / "two", repeats=40)
    assert first == second
    assert (tmp_path / "one" / "diagnostics.json").read_bytes() == (
        tmp_path / "two" / "diagnostics.json"
    ).read_bytes()
    logistic = first["models"]["logistic"]
    assert logistic["metrics"]["roc_auc"] == 1
    assert logistic["metrics"]["average_precision"] == 1
    assert logistic["metrics"]["brier_score"] == pytest.approx(0.04)
    assert logistic["operating_metrics"]["precision"] == 1
    assert logistic["operating_metrics"]["recall"] == 1
    assert logistic["operating_metrics"]["f1"] == 1
    assert logistic["operating_metrics"]["specificity"] == 1
    assert logistic["bootstrap_ci95"]["roc_auc"]["lower"] == 1
    assert len(logistic["reliability"]) == 10
    assert sum(b["count"] for b in logistic["reliability"]) == 12
    assert logistic["descriptive_ece"] == pytest.approx(0.2)
    assert first["cohort_coverage"]["unique_customers"] == 6
    assert first["bootstrap"]["unit"] == "golden_customer_id"
    manifest = json.loads((tmp_path / "one" / "diagnostics_manifest.json").read_text())
    assert manifest["input_sha256"] == manifest["input_sha256_after"]
    assert manifest["output_sha256"]["diagnostics.json"] == sha256(
        tmp_path / "one" / "diagnostics.json"
    )
    assert first["serving_ready"] is False
    assert "drift" not in first


def test_cluster_resamples_keep_all_customer_rows(experiment):
    rows = predictions(experiment)
    report = diagnostics.summarize(rows, repeats=20)
    # Every customer has both labels: row bootstrap could produce single-class draws,
    # but cluster bootstrap always has both classes and exactly the same metrics.
    ci = report["models"]["logistic"]["bootstrap_ci95"]["roc_auc"]
    assert ci["valid_repeats"] == 20
    assert ci["lower"] == ci["upper"] == 1


def test_missing_class_and_insufficient_clusters_have_no_fake_ci(experiment):
    rows = predictions(experiment)
    for row in rows:
        row["churn90"] = 1
    result = diagnostics.summarize(rows, repeats=20)["models"]["logistic"]
    for name in ("roc_auc", "average_precision"):
        assert result["bootstrap_ci95"][name]["lower"] is None
        assert result["bootstrap_ci95"][name]["upper"] is None
    one_customer = rows[:2]
    for row in one_customer:
        row["golden_customer_id"] = "only"
    result = diagnostics.summarize(one_customer, repeats=20)
    assert (
        result["models"]["logistic"]["bootstrap_ci95"]["brier_score"]["lower"] is None
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("logistic_probability", -0.1),
        ("shallow_tree_probability", 1.1),
        ("baseline_probability", float("nan")),
        ("logistic_probability", True),
        ("churn90", True),
        ("churn90", 2),
        ("label_version", "other"),
        ("model_version", "other"),
        ("feature_version", "other"),
    ],
)
def test_invalid_predictions_rejected(experiment, tmp_path, field, value):
    rows = predictions(experiment)
    rows[0][field] = value
    write_json(experiment / "holdout_predictions.json", rows)
    refresh(experiment)
    with pytest.raises(ValueError):
        diagnostics.run(experiment, tmp_path / "out", repeats=20)
    assert not (tmp_path / "out").exists()


def test_duplicates_rejected_but_customer_repetition_allowed(experiment, tmp_path):
    rows = predictions(experiment)
    rows[1] = rows[0]
    write_json(experiment / "holdout_predictions.json", rows)
    refresh(experiment)
    with pytest.raises(ValueError, match="Duplicate"):
        diagnostics.run(experiment, tmp_path / "out", repeats=20)


@pytest.mark.parametrize(
    "name", ["evaluation.json", "model_parameters.json", "holdout_predictions.json"]
)
def test_every_checksum_verified(experiment, tmp_path, name):
    with (experiment / name).open("a") as stream:
        stream.write(" ")
    with pytest.raises(ValueError, match="checksum"):
        diagnostics.run(experiment, tmp_path / "out", repeats=20)


@pytest.mark.parametrize(
    "mutation", ["count", "input_after", "parameters_version", "unsafe_hash"]
)
def test_inconsistent_evidence_rejected(experiment, tmp_path, mutation):
    name = "evaluation.json"
    data = json.loads((experiment / name).read_text())
    if mutation == "count":
        data["test_rows"] = 13
    elif mutation == "input_after":
        data["input_sha256_after"] = {"changed": "c" * 64}
    elif mutation == "parameters_version":
        name = "model_parameters.json"
        data = json.loads((experiment / name).read_text())
        data["feature_version"] = "wrong"
    else:
        name = "experiment_manifest.json"
        data = json.loads((experiment / name).read_text())
        data["output_sha256"]["../escape"] = "x"
    write_json(experiment / name, data)
    if mutation != "unsafe_hash":
        refresh(experiment)
    with pytest.raises(ValueError):
        diagnostics.run(experiment, tmp_path / "out", repeats=20)


def test_no_overlaps_ground_truth_or_existing_output(experiment, tmp_path):
    for output in (
        experiment / "nested",
        experiment,
        tmp_path,
        tmp_path / "ground_truth" / "out",
    ):
        with pytest.raises(ValueError):
            diagnostics.run(experiment, output, repeats=20)
    with pytest.raises(ValueError):
        diagnostics.run(
            tmp_path / "ground_truth" / "source", tmp_path / "new", repeats=20
        )


def test_inputs_changed_during_diagnostics_rejected(experiment, tmp_path, monkeypatch):
    summarize = diagnostics.summarize

    def changing(rows, **kwargs):
        report = summarize(rows, **kwargs)
        with (experiment / "evaluation.json").open("a") as stream:
            stream.write(" ")
        return report

    monkeypatch.setattr(diagnostics, "summarize", changing)
    with pytest.raises(ValueError, match="Input changed"):
        diagnostics.run(experiment, tmp_path / "out", repeats=20)
    assert not (tmp_path / "out").exists()


def test_reliability_endpoints_empty_bins_and_default_repeats(experiment):
    rows = predictions(experiment)
    for i, row in enumerate(rows):
        row["logistic_probability"] = (0.0, 0.1, 1.0)[i % 3]
    report = diagnostics.summarize(rows)
    assert report["bootstrap"]["repeats"] == 200
    bins = report["models"]["logistic"]["reliability"]
    assert bins[0]["count"] == bins[1]["count"] == bins[9]["count"] == 4
    assert bins[2]["mean_score"] is None
    assert bins[2]["observed_event_rate"] is None
    assert bins[9]["upper_inclusive"] is True


def test_minimum_repeats_and_order_independence(experiment):
    rows = predictions(experiment)
    with pytest.raises(ValueError):
        diagnostics.summarize(rows, repeats=19)
    expected = diagnostics.summarize(rows, repeats=20)
    random.Random(3).shuffle(rows)
    assert diagnostics.summarize(rows, repeats=20) == expected
