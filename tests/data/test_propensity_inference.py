"""Offline reload contract: feature snapshots, not target-eligible populations."""

import csv
import json
import math
from datetime import datetime, timezone

import pytest

from services.data.features.snapshot import FIELDS, VERSION
from services.data.ingestion.validator import sha256
from services.data.models.churn_experiment import FEATURES
from services.data.models.propensity_experiment import MODEL_VERSION
from services.data.models.propensity_inference import load_model, predict_rows, run
from services.data.models.propensity_labels import TARGETS
from services.data.models.score_explanations import explain_contributions

TARGET = "retail_purchase30"
NOW = datetime(2026, 11, 19, tzinfo=timezone.utc)


def write_json(path, value):
    path.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")


@pytest.fixture
def artifacts(tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    identity = dict(
        model_version=MODEL_VERSION,
        feature_version=VERSION,
        target=TARGET,
        target_version=TARGETS[TARGET][0],
        horizon_days=30,
        development_only=True,
        serving_ready=False,
    )
    params = dict(
        **identity,
        features=list(FEATURES),
        logistic=dict(
            imputer_medians=[2.0] * 7,
            scaler_mean=[1.0] * 7,
            scaler_scale=[2.0] * 7,
            coef=[0.1] * 7,
            intercept=[-0.3],
        ),
    )
    write_json(model / "model_parameters.json", params)
    write_json(
        model / "experiment_manifest.json",
        dict(
            **identity,
            training_ready=False,
            experiment_ready=False,
            final_model=False,
            output_sha256={
                "model_parameters.json": sha256(model / "model_parameters.json")
            },
        ),
    )
    features = tmp_path / "features"
    features.mkdir()
    row = dict.fromkeys(FIELDS, 3)
    row.update(
        golden_customer_id="g-1",
        cutoff_at="2026-03-01T00:00:00+07:00",
        identity_status="PROVISIONAL",
        feature_version=VERSION,
        training_ready=False,
        identity_time_policy="CURRENT_SNAPSHOT_RETROSPECTIVE",
        recency_days="",
    )
    with (features / "features.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerow(row)
    write_json(
        features / "feature_manifest.json",
        dict(
            feature_version=VERSION,
            training_ready=False,
            rows=1,
            cutoffs=[row["cutoff_at"]],
            output_sha256={"features.csv": sha256(features / "features.csv")},
        ),
    )
    return model, features, row


def update_params(model, change):
    path = model / "model_parameters.json"
    params = json.loads(path.read_text())
    change(params)
    write_json(path, params)
    manifest_path = model / "experiment_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["output_sha256"][path.name] = sha256(path)
    write_json(manifest_path, manifest)


def test_known_imputation_and_development_output(artifacts):
    model, _, row = artifacts
    result = predict_rows(load_model(model, TARGET), [row], generated_at=NOW)[0]
    assert result["uncalibrated_probability"] == pytest.approx(
        1 / (1 + math.exp(-0.35))
    )
    assert result["target"] == TARGET
    assert result["valid_until"] is None
    assert result["development_only"] is True
    assert result["serving_ready"] is False
    assert "eligible" not in result and "reasons" not in result


@pytest.mark.parametrize("target", ["retail_purchase30", "renewal60"])
def test_local_contributions_reconstruct_uncalibrated_score(artifacts, target):
    model_dir, _, row = artifacts
    if target != TARGET:
        path = model_dir / "model_parameters.json"
        params = json.loads(path.read_text(encoding="utf-8"))
        params.update(target=target, target_version=TARGETS[target][0], horizon_days=60)
        params["logistic"]["coef"][0] = -0.2
        write_json(path, params)
        manifest_path = model_dir / "experiment_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update(target=target, target_version=TARGETS[target][0])
        manifest["output_sha256"][path.name] = sha256(path)
        write_json(manifest_path, manifest)
    output = predict_rows(load_model(model_dir, target), [row], generated_at=NOW)[0]
    contributions = output["feature_contributions"]
    assert [entry["feature"] for entry in contributions] == list(FEATURES)
    assert contributions[0]["missing"] is True
    assert contributions[0]["feature_value"] is None
    assert contributions[0]["imputed_value"] == 2.0
    # Hand-calculated from fixture: missing (2-1)/2, observed (3-1)/2.
    expected_first = 0.05 if target == TARGET else -0.1
    expected_log_odds = 0.35 if target == TARGET else 0.2
    assert [entry["log_odds_contribution"] for entry in contributions] == pytest.approx(
        [expected_first, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1], abs=1e-12
    )
    for entry in contributions[1:]:
        assert entry["missing"] is False
        assert entry["feature_value"] == 3.0
        assert entry["imputed_value"] == 3.0
    assert output["intercept"] == -0.3
    assert output["log_odds"] == pytest.approx(expected_log_odds, abs=1e-12)
    assert output["uncalibrated_probability"] == pytest.approx(
        1 / (1 + math.exp(-expected_log_odds)), abs=1e-12
    )
    total = output["intercept"] + sum(
        entry["log_odds_contribution"] for entry in contributions
    )
    assert total == pytest.approx(output["log_odds"], abs=1e-12)
    assert output["uncalibrated_probability"] == pytest.approx(
        1 / (1 + math.exp(-total)), abs=1e-12
    )
    assert output["explanation_method"].startswith("Exact signed log-odds")
    assert output["explanation_version"] == "moses-propensity-log-odds-dev-1.1"
    assert "reason_codes" not in output
    assert output["serving_ready"] is False


@pytest.mark.parametrize("target", ["retail_purchase30", "renewal60"])
def test_score_explanation_comes_from_shared_formatter(artifacts, target):
    model_dir, _, row = artifacts
    if target != TARGET:
        update_params(
            model_dir,
            lambda p: p.update(
                target=target, target_version=TARGETS[target][0], horizon_days=60
            ),
        )
        manifest_path = model_dir / "experiment_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update(target=target, target_version=TARGETS[target][0])
        write_json(manifest_path, manifest)
    output = predict_rows(load_model(model_dir, target), [row], generated_at=NOW)[0]
    explanation = output["score_explanation"]
    assert explanation == explain_contributions(
        output["feature_contributions"], target=target
    )
    assert explanation["version"] == "score-explanation-id-1.0"
    assert len(explanation["sentences"]) == len(FEATURES)
    label = {
        "retail_purchase30": "pembelian retail dalam 30 hari",
        "renewal60": "perpanjangan dalam 60 hari",
    }[target]
    assert all(label in sentence for sentence in explanation["sentences"])


def test_score_explanation_discloses_missing_imputed_feature(artifacts):
    model_dir, _, row = artifacts
    output = predict_rows(load_model(model_dir, TARGET), [row], generated_at=NOW)[0]
    imputed = [e for e in output["feature_contributions"] if e["missing"]]
    assert [e["feature"] for e in imputed] == ["recency_days"]
    flagged = [
        s
        for s in output["score_explanation"]["sentences"]
        if "Data fitur ini kosong" in s
    ]
    assert len(flagged) == 1 and "lama sejak aktivitas terakhir" in flagged[0]


def test_score_explanation_does_not_change_scoring(artifacts):
    model_dir, _, row = artifacts
    output = predict_rows(load_model(model_dir, TARGET), [row], generated_at=NOW)[0]
    assert output["log_odds"] == pytest.approx(0.35, abs=1e-12)
    assert output["development_only"] is True
    assert output["serving_ready"] is False


def test_reload_matches_sklearn_fitted_parameters(artifacts):
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    model_dir, _, row = artifacts
    pipeline = make_pipeline(
        SimpleImputer(strategy="median", keep_empty_features=True),
        StandardScaler(),
        LogisticRegression(),
    )
    x = [[float(i + j) for j in range(7)] for i in range(8)]
    x[0][0] = math.nan
    pipeline.fit(x, [0, 0, 1, 0, 1, 0, 1, 1])
    update_params(
        model_dir,
        lambda p: p.update(
            logistic=dict(
                imputer_medians=pipeline[0].statistics_.tolist(),
                scaler_mean=pipeline[1].mean_.tolist(),
                scaler_scale=pipeline[1].scale_.tolist(),
                coef=pipeline[2].coef_[0].tolist(),
                intercept=pipeline[2].intercept_.tolist(),
            )
        ),
    )
    actual = predict_rows(load_model(model_dir, TARGET), [row], generated_at=NOW)[0]
    expected = pipeline.predict_proba([[math.nan, *[3.0] * 6]])[0, 1]
    assert abs(actual["uncalibrated_probability"] - expected) < 1e-12


@pytest.mark.parametrize(
    "target", ["renewal60", "service_booking30", "booking30", "unknown"]
)
def test_wrong_or_unsupported_target(artifacts, target):
    with pytest.raises(ValueError):
        load_model(artifacts[0], target)


@pytest.mark.parametrize(
    "field,value",
    [
        ("coef", [1]),
        ("intercept", [1, 2]),
        ("scaler_scale", [0] * 7),
        ("scaler_mean", [True] * 7),
        ("imputer_medians", ["2"] * 7),
        ("coef", [1e309] * 7),
    ],
)
def test_invalid_parameters(artifacts, field, value):
    model = artifacts[0]
    # JSON numeric overflow is legal syntax, but not a finite model value.
    if field == "coef" and value[0] == math.inf:
        path = model / "model_parameters.json"
        text = path.read_text().replace('"coef": [0.1', '"coef": [1e999')
        path.write_text(text)
        manifest_path = model / "experiment_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["output_sha256"][path.name] = sha256(path)
        write_json(manifest_path, manifest)
    else:
        update_params(model, lambda p: p["logistic"].update({field: value}))
    with pytest.raises(ValueError):
        load_model(model, TARGET)


@pytest.mark.parametrize(
    "bad", ['{"target": NaN}', '{"target": "a", "target": "b"}', "[]"]
)
def test_strict_json_manifest(artifacts, bad):
    model = artifacts[0]
    (model / "experiment_manifest.json").write_text(bad)
    with pytest.raises(ValueError):
        load_model(model, TARGET)


@pytest.mark.parametrize(
    "change",
    [
        dict(target_value=1),
        dict(identity_status="bogus"),
        dict(identity_time_policy="PIT"),
        dict(cutoff_at="2027-01-01T00:00:00+07:00"),
        dict(cutoff_at="2026-01-01"),
        dict(tenure_days=""),
        dict(purchase_count_90d="nan"),
    ],
)
def test_feature_only_identity_time_and_numeric_restrictions(artifacts, change):
    model, _, row = artifacts
    with pytest.raises(ValueError):
        predict_rows(load_model(model, TARGET), [{**row, **change}], generated_at=NOW)


def test_run_needs_no_labels_and_preserves_inputs(artifacts, tmp_path):
    model, features, _ = artifacts
    # Deliberately invalid labels must never be opened.
    (features / "propensity_labels.csv").write_text("not labels")
    result = run(model, features, TARGET, tmp_path / "out", generated_at=NOW)
    assert result["rows"] == 1
    assert result["input_sha256"] == result["input_sha256_after"]
    assert "propensity_labels.csv" not in result["input_sha256"]
    predictions = json.loads((tmp_path / "out" / "predictions.json").read_text())
    assert predictions[0]["score_explanation"] == explain_contributions(
        predictions[0]["feature_contributions"], target=TARGET
    )
    assert result["explanation_version"] == "moses-propensity-log-odds-dev-1.1"
    saved_manifest = json.loads(
        (tmp_path / "out" / "prediction_manifest.json").read_text()
    )
    assert saved_manifest == result


def test_checksum_tamper(artifacts, tmp_path):
    model, features, _ = artifacts
    (features / "features.csv").write_text("tampered")
    with pytest.raises(ValueError, match="checksum"):
        run(model, features, TARGET, tmp_path / "out", generated_at=NOW)
    (model / "model_parameters.json").write_text("{}")
    with pytest.raises(ValueError, match="checksum"):
        load_model(model, TARGET)


@pytest.mark.parametrize("destination", ["existing", "overlap", "ground_truth"])
def test_output_refusals(artifacts, tmp_path, destination):
    model, features, _ = artifacts
    output = {
        "existing": features,
        "overlap": features / "new",
        "ground_truth": tmp_path / "ground_truth" / "out",
    }[destination]
    with pytest.raises(ValueError):
        run(model, features, TARGET, output, generated_at=NOW)


def test_mutation_during_scoring_rejected(artifacts, tmp_path, monkeypatch):
    from services.data.models import propensity_inference

    original = propensity_inference.predict_rows
    model, features, _ = artifacts

    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        with (features / "feature_manifest.json").open("a") as stream:
            stream.write(" ")
        return result

    monkeypatch.setattr(propensity_inference, "predict_rows", mutate)
    with pytest.raises(ValueError, match="changed"):
        run(model, features, TARGET, tmp_path / "out", generated_at=NOW)
    assert not (tmp_path / "out").exists()
