"""Offline score monitoring has no eligibility or model-promotion authority."""

import hashlib
import json
import math

import pytest

from services.data.models.prediction_monitoring import build_report, run


def rows(scores, cutoff):
    return [
        dict(
            cutoff_at=cutoff,
            golden_customer_id=str(i),
            target="retail_purchase30",
            model_version="dev-test",
            model_artifact_sha256="a" * 64,
            feature_version="fv-test",
            target_version="tv-test",
            development_only=True,
            serving_ready=False,
            uncalibrated_probability=score,
        )
        for i, score in enumerate(scores)
    ]


BASE = "2026-03-01T00:00:00+07:00"
CURRENT = "2026-06-01T00:00:00+07:00"


def test_identical_scores_stable_and_counts_are_exact():
    report = build_report(
        rows([0, 0.5, 1], BASE) + rows([0, 0.5, 1], CURRENT), BASE, CURRENT
    )
    assert report["psi"]["value"] == 0
    assert report["baseline_volume"] == report["current_volume"] == 3
    assert sum(b["current_count"] for b in report["psi"]["bins"]) == 3
    assert report["alerts"] == []
    assert report["band_mix"] is None
    assert report["segment_performance"] is None
    for flag in (
        "training_ready",
        "experiment_ready",
        "final_model",
        "serving_ready",
        "calibration_final",
        "approved",
        "targeting_allowed",
    ):
        assert report[flag] is False


def test_shift_generates_advisory_not_automatic_retraining():
    report = build_report(
        rows([0.05] * 10, BASE) + rows([0.95] * 20, CURRENT), BASE, CURRENT
    )
    assert report["psi"]["value"] > 0.25
    assert report["current_volume"] == 20
    assert report["alerts"][0]["status"] == "RETRAIN_RECOMMENDED"
    assert report["automatic_action"] is False


@pytest.mark.parametrize("score", [-0.1, 1.1, True, None, math.nan, math.inf, "0.5"])
def test_invalid_score_is_refused(score):
    with pytest.raises(ValueError):
        build_report(rows([score], BASE) + rows([0.5], CURRENT), BASE, CURRENT)


@pytest.mark.parametrize(
    "field,value",
    [
        ("serving_ready", True),
        ("development_only", False),
        ("model_artifact_sha256", "b" * 64),
        ("target", "renewal60"),
    ],
)
def test_untrusted_or_incompatible_rows_refused(field, value):
    data = rows([0.5], BASE) + rows([0.5], CURRENT)
    data[-1][field] = value
    with pytest.raises(ValueError):
        build_report(data, BASE, CURRENT)


def test_duplicate_customer_cutoff_is_refused():
    with pytest.raises(ValueError, match="Duplicate"):
        build_report(rows([0.5], BASE) * 2 + rows([0.5], CURRENT), BASE, CURRENT)


def test_empty_or_reversed_period_is_refused():
    for baseline, current in ((BASE, BASE), (CURRENT, BASE)):
        with pytest.raises(ValueError):
            build_report(rows([0.5], BASE) + rows([0.5], CURRENT), baseline, current)
    with pytest.raises(ValueError):
        build_report(rows([0.5], BASE), BASE, CURRENT)


def test_missing_identity_is_refused():
    for field in ("golden_customer_id", "model_version"):
        data = rows([0.5], BASE) + rows([0.5], CURRENT)
        data[0][field] = ""
        with pytest.raises(ValueError, match="Missing"):
            build_report(data, BASE, CURRENT)


def write_input(tmp_path, *, rows_override=None, manifest_override=None):
    source = tmp_path / "source"
    source.mkdir()
    data = (
        rows_override
        if rows_override is not None
        else rows([0.2], BASE) + rows([0.8], CURRENT)
    )
    payload = json.dumps(data).encode()
    (source / "predictions.json").write_bytes(payload)
    manifest = dict(
        development_only=True,
        serving_ready=False,
        rows=len(data),
        target="retail_purchase30",
        model_version="dev-test",
        feature_version="fv-test",
        target_version="tv-test",
        input_sha256={"model_parameters.json": "a" * 64},
        output_sha256={"predictions.json": hashlib.sha256(payload).hexdigest()},
    )
    if manifest_override:
        manifest.update(manifest_override)
    (source / "prediction_manifest.json").write_text(json.dumps(manifest))
    return source


def test_run_writes_hashed_report_and_preserves_input(tmp_path):
    source = write_input(tmp_path)
    output = tmp_path / "output"
    report = run(source, BASE, CURRENT, output)
    assert json.loads((output / "monitoring_report.json").read_text()) == json.loads(
        json.dumps(report)
    )
    assert (
        report["input_sha256"]["predictions.json"]
        == hashlib.sha256((source / "predictions.json").read_bytes()).hexdigest()
    )
    assert (
        report["input_sha256"]["prediction_manifest.json"]
        == hashlib.sha256(
            (source / "prediction_manifest.json").read_bytes()
        ).hexdigest()
    )
    assert report["serving_ready"] is False


@pytest.mark.parametrize(
    "alter,error",
    [
        ("checksum", "checksum"),
        ("identity", "identity"),
        ("model_hash", "model artifact"),
        ("row_count", "row count"),
        ("serving", "development-only"),
        ("bad_mapping", "Malformed"),
        ("duplicate_key", "Duplicate JSON key"),
        ("bad_prediction", "list of objects"),
    ],
)
def test_run_refuses_invalid_inputs(tmp_path, alter, error):
    source = write_input(tmp_path)
    manifest_path = source / "prediction_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if alter == "checksum":
        manifest["output_sha256"]["predictions.json"] = "b" * 64
    elif alter == "identity":
        manifest["target"] = "renewal60"
    elif alter == "model_hash":
        manifest["input_sha256"]["model_parameters.json"] = "b" * 64
    elif alter == "row_count":
        manifest["rows"] = 1
    elif alter == "serving":
        manifest["serving_ready"] = True
    elif alter == "bad_mapping":
        manifest["output_sha256"] = []
    elif alter == "duplicate_key":
        manifest_path.write_text(
            manifest_path.read_text().replace(
                '"serving_ready": false',
                '"serving_ready": true, "serving_ready": false',
            )
        )
    elif alter == "bad_prediction":
        data = json.dumps([1]).encode()
        (source / "predictions.json").write_bytes(data)
        manifest["output_sha256"]["predictions.json"] = hashlib.sha256(data).hexdigest()
    if alter != "duplicate_key":
        manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match=error):
        run(source, BASE, CURRENT, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_run_refuses_existing_output_and_ground_truth_paths(tmp_path):
    source = write_input(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    with pytest.raises(ValueError, match="new output"):
        run(source, BASE, CURRENT, output)
    assert list(output.iterdir()) == []
    with pytest.raises(ValueError, match="ground_truth"):
        run(source, BASE, CURRENT, tmp_path / "ground_truth" / "output")


def test_third_cutoff_is_not_silently_ignored():
    data = (
        rows([0.1], BASE)
        + rows([0.9], CURRENT)
        + rows([0.5], "2026-09-01T00:00:00+07:00")
    )
    with pytest.raises(ValueError, match="outside"):
        build_report(data, BASE, CURRENT)
