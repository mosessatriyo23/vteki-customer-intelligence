"""Offline Moses feature-distribution diagnostics."""

import csv
import json
from datetime import datetime, timedelta, timezone

import pytest

from services.data.features.snapshot import FIELDS, VERSION
from services.data.ingestion.validator import sha256
from services.data.models.churn_experiment import FEATURES
from services.data.models.feature_drift import run
from services.data.models.labels import CHRIST_VERSION, TRAINING_FIELDS
from services.data.monitoring.drift import population_stability_index

CUTOFFS = [datetime(2024, m, 1, tzinfo=timezone.utc) for m in (1, 7, 9)]


def _write_csv(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _inputs(root, train=(1, 2, 3, 4), current=(1, 2, 3, 4), holdout=100):
    reference, features = root / "reference", root / "current"
    reference.mkdir(parents=True)
    features.mkdir(parents=True)

    def row(value, cutoff, i):
        return {
            **{
                field: value if field == "recency_days" or value is not None else 2
                for field in FEATURES
            },
            "golden_customer_id": f"customer-{i}",
            "cutoff_at": cutoff.isoformat(),
            "feature_version": VERSION,
            "training_ready": "False",
            "identity_time_policy": "CURRENT_SNAPSHOT_RETROSPECTIVE",
            "identity_status": "RESOLVED",
        }

    training = [
        {
            **row(value, CUTOFFS[0], i),
            "outcome_end_at": (CUTOFFS[0] + timedelta(days=90)).isoformat(),
            "horizon_days": 90,
            "label_version": CHRIST_VERSION,
            "outcome_complete": "True",
            "eligible": "True",
            "experiment_ready": "False",
            "churn90": i % 2,
        }
        for i, value in enumerate(train)
    ]
    training.append(
        {
            **training[0],
            "golden_customer_id": "purged",
            "cutoff_at": CUTOFFS[1].isoformat(),
            "outcome_end_at": (CUTOFFS[1] + timedelta(days=90)).isoformat(),
            **{field: 500 for field in FEATURES},
        }
    )
    training.append(
        {
            **training[0],
            "golden_customer_id": "holdout",
            "cutoff_at": CUTOFFS[2].isoformat(),
            "outcome_end_at": (CUTOFFS[2] + timedelta(days=90)).isoformat(),
            **{field: holdout for field in FEATURES},
        }
    )
    _write_csv(reference / "training_rows.csv", TRAINING_FIELDS, training)
    (reference / "model_manifest.json").write_text(
        json.dumps(
            {
                "feature_fields": list(FIELDS),
                "label_version": CHRIST_VERSION,
                "horizon_days": 90,
                "split_policy": "chronological_cutoff_holdout_latest_complete_cutoff",
                "experiment_ready": False,
                "final_model": False,
                "training_rows": len(training),
                "output_sha256": {
                    "training_rows.csv": sha256(reference / "training_rows.csv")
                },
            }
        ),
        encoding="utf-8",
    )
    current_rows = [row(value, CUTOFFS[2], i) for i, value in enumerate(current)]
    _write_csv(features / "features.csv", FIELDS, current_rows)
    (features / "feature_manifest.json").write_text(
        json.dumps(
            {
                "feature_version": VERSION,
                "training_ready": False,
                "rows": len(current_rows),
                "output_sha256": {"features.csv": sha256(features / "features.csv")},
            }
        ),
        encoding="utf-8",
    )
    return reference, features


def _run(root, **kwargs):
    reference, current = _inputs(root, **kwargs)
    return run(reference, current, root / "output")


@pytest.mark.parametrize("reference,current", [([], [1]), ([1], []), ([], [])])
def test_empty_population_rejected_explicitly(reference, current):
    from services.data.models.feature_drift import _feature_report

    with pytest.raises(ValueError, match="nonempty"):
        _feature_report(reference, current)


def test_identical_populations_zero_psi_and_no_readiness(tmp_path):
    report = _run(tmp_path)
    assert report["training_ready"] is False
    assert report["experiment_ready"] is False
    assert report["serving_ready"] is False
    assert report["train_rows"] == 4
    assert report["holdout_rows"] == 1
    assert report["purged_rows"] == 1
    assert list(report["features"]) == list(FEATURES)
    for feature in report["features"].values():
        assert feature["psi"] == pytest.approx(0)
        assert "status" not in feature  # shared alert thresholds are not used here
        assert sum(bin_["reference_count"] for bin_ in feature["bins"]) == 4
        assert sum(bin_["current_count"] for bin_ in feature["bins"]) == 4
        assert sum(
            bin_["reference_fraction"] for bin_ in feature["bins"]
        ) == pytest.approx(1)
        assert feature["current_out_of_reference_range_count"] == 0
    assert (tmp_path / "output" / "feature_drift.json").exists()


def test_shift_missing_constant_and_extreme_values_are_all_counted(tmp_path):
    report = _run(tmp_path, train=(2, 2, 2, 2), current=(None, 0, 2, 1e100))
    recency = report["features"]["recency_days"]
    assert recency["reference_missing_rate"] == 0
    assert recency["current_missing_rate"] == 0.25
    assert recency["current_out_of_reference_range_count"] == 2
    expected = population_stability_index(
        [2, 2, 2, 2], [None, 0, 2, 1e100], recency["bin_edges"]
    )
    assert recency["psi"] == expected["value"]
    assert recency["psi"] > 0
    for actual, shared in zip(recency["bins"], expected["bins"]):
        assert actual["contribution"] == shared["contribution"]
        assert actual["reference_fraction"] == shared["baseline_share"]
        assert actual["current_fraction"] == shared["current_share"]
    assert sum(bin_["current_count"] for bin_ in recency["bins"]) == 4
    assert sum(bin_["reference_count"] for bin_ in recency["bins"]) == 4
    assert (
        report["features"]["tenure_days"]["current_out_of_reference_range_count"] == 2
    )


def test_all_missing_recency_reference_still_reports_bins(tmp_path):
    report = _run(tmp_path, train=(None, None), current=(None, 8))
    recency = report["features"]["recency_days"]
    assert recency["reference_missing_rate"] == 1
    assert recency["current_out_of_reference_range_count"] == 1
    assert sum(b["current_count"] for b in recency["bins"]) == 2


def test_holdout_value_never_changes_reference_boundaries(tmp_path):
    first = _run(tmp_path / "first", holdout=10)["features"]["recency_days"]
    second = _run(tmp_path / "second", holdout=1e100)["features"]["recency_days"]
    assert first == second


@pytest.mark.parametrize(
    "tamper", ["checksum", "count", "version", "header", "negative", "nan", "readiness"]
)
def test_rejects_tampered_current_artifact(tmp_path, tamper):
    reference, current = _inputs(tmp_path)
    manifest_path = current / "feature_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if tamper == "checksum":
        manifest["output_sha256"]["features.csv"] = "bad"
    elif tamper == "count":
        manifest["rows"] += 1
    elif tamper == "version":
        manifest["feature_version"] = "unknown"
    elif tamper == "readiness":
        manifest["training_ready"] = True
    else:
        csv_path = current / "features.csv"
        content = csv_path.read_text()
        if tamper == "header":
            content = content.replace("recency_days", "churn90", 1)
        else:
            content = content.replace(
                ",1,1,1,1,1,1,1",
                f",{'-1' if tamper == 'negative' else 'nan'},1,1,1,1,1,1",
                1,
            )
        csv_path.write_text(content)
        manifest["output_sha256"]["features.csv"] = sha256(csv_path)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        run(reference, current, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_rejects_reference_tamper_and_unsafe_paths(tmp_path):
    reference, current = _inputs(tmp_path)
    manifest_path = reference / "model_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["horizon_days"] = 30
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        run(reference, current, tmp_path / "output")
    manifest["horizon_days"] = 90
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        run(reference, current, reference / "nested")
    with pytest.raises(ValueError):
        run(reference, current, current / "nested")
    with pytest.raises(ValueError):
        run(reference, current, tmp_path / "ground_truth" / "output")
