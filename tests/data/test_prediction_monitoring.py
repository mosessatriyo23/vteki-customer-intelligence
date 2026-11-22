"""Offline score monitoring has no eligibility or model-promotion authority."""

import hashlib
import json
import math
from datetime import datetime, timezone

import pytest

from services.data.models import calibrated_propensity_inference, propensity_calibration
from services.data.models.prediction_monitoring import build_report, run
from tests.data.test_propensity_calibration import CUTOFFS, TARGETS
from tests.data.test_propensity_experiment import write_inputs


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


def _with_calibrated(items, calibrated):
    return [
        {**item, "calibrated_probability": value}
        for item, value in zip(items, calibrated)
    ]


def test_default_score_field_is_unchanged():
    report = build_report(rows([0.5], BASE) + rows([0.5], CURRENT), BASE, CURRENT)
    assert report["score_field"] == "uncalibrated_probability"


def test_calibrated_field_is_monitored_only_when_explicitly_requested():
    base = _with_calibrated(rows([0.1, 0.2], BASE), [0.9, 0.9])
    current = _with_calibrated(rows([0.1, 0.2], CURRENT), [0.9, 0.9])
    raw = build_report(base + current, BASE, CURRENT)
    calibrated = build_report(
        base + current, BASE, CURRENT, score_field="calibrated_probability"
    )
    assert calibrated["score_field"] == "calibrated_probability"
    assert calibrated["psi"] != raw["psi"]
    assert all(calibrated[flag] is False for flag in ("approved", "serving_ready"))


@pytest.mark.parametrize("field", ["churn_score", "", None, "uncalibrated"])
def test_unknown_score_field_is_refused(field):
    with pytest.raises(ValueError, match="score_field"):
        build_report(
            rows([0.5], BASE) + rows([0.5], CURRENT), BASE, CURRENT, score_field=field
        )


def test_requested_field_missing_from_a_row_is_refused_not_substituted():
    with pytest.raises(ValueError, match="calibrated_probability"):
        build_report(
            rows([0.5], BASE) + rows([0.5], CURRENT),
            BASE,
            CURRENT,
            score_field="calibrated_probability",
        )


def test_unavailable_reasons_exactly_explain_null_sections():
    report = build_report(rows([0.5], BASE) + rows([0.5], CURRENT), BASE, CURRENT)
    reasons = report["unavailable_reasons"]
    assert set(reasons) == {"band_mix", "segment_performance"}
    assert all(isinstance(r, str) and r.strip() for r in reasons.values())
    assert report["band_mix"] is None and report["segment_performance"] is None


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


def test_naive_cutoff_is_refused():
    naive = "2026-06-01T00:00:00"
    with pytest.raises(ValueError, match="aware timestamp"):
        build_report(rows([0.5], BASE) + rows([0.5], naive), BASE, naive)


def test_mixed_model_identity_is_refused():
    data = rows([0.5], BASE) + rows([0.5], CURRENT)
    data[-1]["model_version"] = "other"
    with pytest.raises(ValueError, match="one model/target identity"):
        build_report(data, BASE, CURRENT)


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


@pytest.fixture
def calibrated_source(tmp_path):
    labels, features = write_inputs(tmp_path, cutoffs=CUTOFFS)
    model = tmp_path / "model"
    propensity_calibration.run(labels, features, TARGETS[0], model)
    source = tmp_path / "calibrated-source"
    calibrated_propensity_inference.run(
        model,
        features,
        TARGETS[0],
        source,
        generated_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
    )
    prediction_path = source / "calibrated_predictions.json"
    manifest_path = source / "calibrated_prediction_manifest.json"
    data = [
        row
        for row in json.loads(prediction_path.read_text())
        if row["cutoff_at"] in CUTOFFS[1:]
    ]
    payload = json.dumps(data).encode()
    prediction_path.write_bytes(payload)
    manifest = json.loads(manifest_path.read_text())
    manifest["rows"] = len(data)
    manifest["output_sha256"]["calibrated_predictions.json"] = hashlib.sha256(
        payload
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    return source


def _rewrite_calibrated(source, *, row_change=None, manifest_change=None):
    predictions_path = source / "calibrated_predictions.json"
    manifest_path = source / "calibrated_prediction_manifest.json"
    data = json.loads(predictions_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    if row_change:
        field, value = row_change
        data[0][field] = value
        payload = json.dumps(data).encode()
        predictions_path.write_bytes(payload)
        manifest["output_sha256"]["calibrated_predictions.json"] = hashlib.sha256(
            payload
        ).hexdigest()
    if manifest_change:
        field, value = manifest_change
        manifest[field] = value
    manifest_path.write_text(json.dumps(manifest))


@pytest.mark.parametrize("score_field", ["raw_probability", "calibrated_probability"])
def test_calibrated_runner_consumes_real_bundle(
    calibrated_source, tmp_path, score_field
):
    report = run(
        calibrated_source,
        CUTOFFS[1],
        CUTOFFS[2],
        tmp_path / "monitoring",
        score_field=score_field,
    )
    assert report["score_field"] == score_field
    assert report["baseline_volume"] > 0 and report["current_volume"] > 0
    assert (
        report["input_sha256"]["calibrated_predictions.json"]
        == hashlib.sha256(
            (calibrated_source / "calibrated_predictions.json").read_bytes()
        ).hexdigest()
    )
    assert json.loads(
        (tmp_path / "monitoring" / "monitoring_report.json").read_text()
    ) == json.loads(json.dumps(report))
    assert report["serving_ready"] is False


@pytest.mark.parametrize(
    "row_change,manifest_change",
    [
        (("model_artifact_sha256", "b" * 64), None),
        (("model_manifest_sha256", "b" * 64), None),
        (("calibration_status", "forged"), None),
        (("approved", True), None),
        (("raw_probability", None), None),
        (("calibrated_probability", None), None),
        (None, ("format_version", "other")),
        (None, ("score_fields", ["calibrated_probability"])),
        (None, ("model_manifest_sha256", "b" * 64)),
        (None, ("input_sha256_after", {})),
        (None, ("approved", True)),
        (None, ("targeting_allowed", True)),
        (None, ("horizon_days", None)),
        (("horizon_days", None), ("horizon_days", None)),
    ],
)
def test_calibrated_runner_rejects_tampering_even_with_rehashed_manifest(
    calibrated_source, tmp_path, row_change, manifest_change
):
    _rewrite_calibrated(
        calibrated_source, row_change=row_change, manifest_change=manifest_change
    )
    with pytest.raises(ValueError):
        run(
            calibrated_source,
            CUTOFFS[1],
            CUTOFFS[2],
            tmp_path / "monitoring",
            score_field="calibrated_probability",
        )
    assert not (tmp_path / "monitoring").exists()


def test_missing_horizon_in_entire_bundle_is_rejected(calibrated_source, tmp_path):
    prediction_path = calibrated_source / "calibrated_predictions.json"
    manifest_path = calibrated_source / "calibrated_prediction_manifest.json"
    data = json.loads(prediction_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    for row in data:
        row.pop("horizon_days")
    manifest.pop("horizon_days")
    payload = json.dumps(data).encode()
    prediction_path.write_bytes(payload)
    manifest["output_sha256"]["calibrated_predictions.json"] = hashlib.sha256(
        payload
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="horizon"):
        run(
            calibrated_source,
            CUTOFFS[1],
            CUTOFFS[2],
            tmp_path / "missing-horizon",
            score_field="calibrated_probability",
        )
    assert not (tmp_path / "missing-horizon").exists()


def test_cli_score_field_option(calibrated_source, tmp_path):
    import subprocess
    import sys

    command = [
        sys.executable,
        "-m",
        "services.data.models.prediction_monitoring",
        "--predictions-dir",
        str(calibrated_source),
        "--baseline-cutoff",
        CUTOFFS[1],
        "--current-cutoff",
        CUTOFFS[2],
        "--output-dir",
        str(tmp_path / "cli"),
        "--score-field",
        "calibrated_probability",
    ]
    done = subprocess.run(command, capture_output=True, text=True, check=True)
    assert json.loads(done.stdout)["serving_ready"] is False
    report = json.loads((tmp_path / "cli" / "monitoring_report.json").read_text())
    assert report["score_field"] == "calibrated_probability"


def test_calibrated_bundle_requires_explicit_score_field(calibrated_source, tmp_path):
    with pytest.raises(FileNotFoundError):
        run(calibrated_source, CUTOFFS[1], CUTOFFS[2], tmp_path / "default")
    source = write_input(tmp_path)
    with pytest.raises(FileNotFoundError):
        run(source, BASE, CURRENT, tmp_path / "explicit", score_field="raw_probability")


def test_third_cutoff_is_not_silently_ignored():
    data = (
        rows([0.1], BASE)
        + rows([0.9], CURRENT)
        + rows([0.5], "2026-09-01T00:00:00+07:00")
    )
    with pytest.raises(ValueError, match="outside"):
        build_report(data, BASE, CURRENT)
