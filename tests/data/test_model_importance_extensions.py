"""Importance coverage using the actual exploratory membership artifact format."""

import copy
import json

import pytest

from services.data.ingestion.validator import sha256
from services.data.models import model_importance as importance
from services.data.models import renewal_membership_experiment as membership
from tests.data.test_renewal_membership_experiment import write_inputs


def test_calibration_artifact_is_not_silently_treated_as_raw_logistic():
    from tests.data.test_model_importance import PARAMS, rows

    parameters = copy.deepcopy(PARAMS)
    parameters["isotonic"] = {
        "x_thresholds": [0, 1],
        "y_thresholds": [0, 1],
        "out_of_bounds": "clip",
    }
    with pytest.raises(ValueError, match="calibrated"):
        importance.evaluate(parameters, rows(), "label", repeats=1)


def fitted_membership(tmp_path):
    labels, members = write_inputs(tmp_path)
    model = tmp_path / "model"
    membership.run(labels, members, model)
    return labels, members, model


def test_membership_importance_reproduces_saved_predictions_without_refitting(
    tmp_path, monkeypatch
):
    labels, members, model = fitted_membership(tmp_path)
    before = {
        str(p): sha256(p)
        for directory in (labels, members, model)
        for p in directory.iterdir()
    }

    def no_fit(*args, **kwargs):
        raise AssertionError("Importance must never fit")

    monkeypatch.setattr(membership, "evaluate", no_fit)
    from sklearn.linear_model import LogisticRegression

    monkeypatch.setattr(LogisticRegression, "fit", no_fit)
    report = importance.run(
        "renewal60_membership",
        model,
        tmp_path / "importance",
        labels_dir=labels,
        membership_dir=members,
        repeats=2,
        min_n=2,
    )
    predictions = json.loads((model / "holdout_predictions.json").read_text())
    scores = [p["logistic_probability"] for p in predictions]
    outcomes = [p["target_value"] for p in predictions]
    assert report["baseline"] == pytest.approx(importance._metrics(outcomes, scores))
    assert report["features"] == list(membership.FEATURES)
    assert report["label_key"] == "target_value"
    assert report["holdout_rows"] == 8
    assert report["grouped_importance"] == []
    assert report["segments"] == {}
    assert report["segment_definition"] == {}
    assert report["exploratory"] is True
    assert report["post_holdout_inspection"] is True
    assert report["independent_confirmation"] is False
    assert "not independent confirmation" in " ".join(report["limitations"])
    assert all(
        item["feature"] in membership.FEATURES for item in report["global_importance"]
    )
    assert report["input_sha256"] == report["input_sha256_after"]
    assert {
        str(p): sha256(p)
        for directory in (labels, members, model)
        for p in directory.iterdir()
    } == before
    manifest = json.loads(
        (tmp_path / "importance" / "importance_manifest.json").read_text()
    )
    assert manifest["exploratory"] is True
    assert manifest["independent_confirmation"] is False
    assert manifest["output_sha256"]["importance_report.json"] == sha256(
        tmp_path / "importance" / "importance_report.json"
    )


def test_membership_evaluate_uses_native_signed_missing_and_boolean_conversion(
    tmp_path,
):
    labels, members, model = fitted_membership(tmp_path)
    parameters = json.loads((model / "model_parameters.json").read_text())
    rows = membership.join_rows(
        membership._read_csv(
            members / "membership_features.csv", membership.MEMBERSHIP_FIELDS
        ),
        membership._read_csv(labels / "propensity_labels.csv", membership.LABEL_FIELDS),
    )[8:]
    original = copy.deepcopy(rows)
    first = importance.evaluate(parameters, rows, "target_value", repeats=2)
    assert first == importance.evaluate(parameters, rows, "target_value", repeats=2)
    assert rows == original
    bad = copy.deepcopy(rows)
    bad[0]["tier_upgraded_last_event"] = "maybe"
    with pytest.raises(ValueError, match="tier_upgraded_last_event"):
        importance.evaluate(parameters, bad, "target_value", repeats=2)


@pytest.mark.parametrize(
    "artifact",
    [
        "membership_manifest.json",
        "propensity_manifest.json",
        "model_parameters.json",
        "evaluation.json",
    ],
)
def test_membership_rejects_tampered_artifacts_before_output(tmp_path, artifact):
    labels, members, model = fitted_membership(tmp_path)
    directory = (
        members
        if artifact == "membership_manifest.json"
        else labels if artifact == "propensity_manifest.json" else model
    )
    path = directory / artifact
    value = json.loads(path.read_text())
    if artifact.endswith("manifest.json"):
        value["development_only"] = False
    else:
        value["tampered"] = True
    path.write_text(json.dumps(value))
    output = tmp_path / "importance"
    with pytest.raises(ValueError):
        importance.run(
            "renewal60_membership",
            model,
            output,
            labels_dir=labels,
            membership_dir=members,
            repeats=1,
        )
    assert not output.exists()


def test_membership_rejects_output_overlap_and_overwrite(tmp_path):
    labels, members, model = fitted_membership(tmp_path)
    for output, message in (
        (members / "out", "separate"),
        (tmp_path / "ground_truth" / "out", "ground_truth"),
        (model, "new output"),
    ):
        with pytest.raises(ValueError, match=message):
            importance.run(
                "renewal60_membership",
                model,
                output,
                labels_dir=labels,
                membership_dir=members,
                repeats=1,
            )


def test_membership_rejects_inputs_changed_during_scoring(tmp_path, monkeypatch):
    labels, members, model = fitted_membership(tmp_path)
    real = importance.evaluate

    def mutate(*args, **kwargs):
        result = real(*args, **kwargs)
        with (members / "membership_features.csv").open("a") as stream:
            stream.write("\n")
        return result

    monkeypatch.setattr(importance, "evaluate", mutate)
    with pytest.raises(ValueError, match="changed"):
        importance.run(
            "renewal60_membership",
            model,
            tmp_path / "out",
            labels_dir=labels,
            membership_dir=members,
            repeats=1,
        )
    assert not (tmp_path / "out").exists()


def test_membership_contract_cannot_be_selected_by_feature_names_alone(tmp_path):
    _, _, model = fitted_membership(tmp_path)
    parameters = json.loads((model / "model_parameters.json").read_text())
    parameters["model_version"] = "unknown"
    with pytest.raises(ValueError, match="feature contract|membership"):
        importance.evaluate(
            parameters, [{"target_value": 1}], "target_value", repeats=1
        )
