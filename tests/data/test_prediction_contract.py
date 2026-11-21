import hashlib
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from services.data.models import prediction_contract as pc

GENERATED_AT = "2026-09-06T12:00:00+07:00"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prediction(customer: str, score: float, cutoff: str = "2026-09-06T00:00:00+07:00"):
    return {
        "golden_customer_id": customer,
        "cutoff_at": cutoff,
        "churn_probability": score,
        "model_version": "m-1",
        "feature_version": "f-1",
        "label_version": "l-1",
        "horizon_days": 90,
        "generated_at": GENERATED_AT,
        "valid_until": None,
    }


def _reason(code: str, direction: str = "INCREASES_RISK", value: float = 0.5):
    return {
        "code": code,
        "direction": direction,
        "feature": "x",
        "log_odds_contribution": value,
        "feature_value": 1.0,
        "missing": False,
    }


def _reasons(customer: str, codes: list[str], status: str | None = None):
    return {
        "golden_customer_id": customer,
        "cutoff_at": "2026-09-06T00:00:00+07:00",
        "model_version": "m-1",
        "feature_version": "f-1",
        "label_version": "l-1",
        "status": status or ("OK" if len(codes) >= 3 else "INSUFFICIENT_EXPLANATION"),
        "reasons": [_reason(c) for c in codes],
        "approved_taxonomy": False,
        "display_text": None,
        "development_only": True,
    }


MIXED = ["PURCHASE_RECENCY", "TENURE", "RETAINED_REVENUE_90D"]
FREQ = ["PURCHASE_FREQUENCY_60D", "PURCHASE_FREQUENCY_90D", "PURCHASE_FREQUENCY_365D"]


def _build(score=0.5, codes=None, status=None):
    codes = MIXED if codes is None else codes
    return pc.build_record(
        _prediction("c1", score),
        _reasons("c1", codes, status),
        generated_at=GENERATED_AT,
    )


@pytest.mark.parametrize(
    "score,band",
    [
        (0.0, "LOW"),
        (0.2999999, "LOW"),
        (0.30, "MEDIUM"),
        (0.5999999, "MEDIUM"),
        (0.60, "HIGH"),
        (0.7999999, "HIGH"),
        (0.80, "VERY_HIGH"),
        (1.0, "VERY_HIGH"),
    ],
)
def test_band_boundaries(score, band):
    assert pc.score_to_band(score) == band
    assert _build(score)["band"] == band


def test_dates_come_from_cutoff_not_publication_or_clock():
    prediction = _prediction("c1", 0.5)
    prediction["generated_at"] = "2026-11-19T12:00:00+07:00"
    record = pc.build_record(
        prediction, _reasons("c1", MIXED), generated_at=prediction["generated_at"]
    )
    assert record["prediction_date"] == "2026-09-06"
    assert record["valid_until"] is None
    assert record["proposed_valid_until"] == "2026-10-06"
    assert record["outcome_window_end"] == "2026-12-05"
    assert record["horizon_days"] == 90


def test_existing_source_expiry_is_preserved_without_missing_blocker():
    prediction = _prediction("c1", 0.5)
    prediction["valid_until"] = "2026-09-10"
    record = pc.build_record(
        prediction, _reasons("c1", MIXED), generated_at=GENERATED_AT
    )
    assert record["valid_until"] == "2026-09-10"
    assert "MISSING_PRODUCER_EXPIRY" not in record["contract_status_reasons"]
    assert record["proposed_valid_until"] == "2026-10-06"


def test_static_fields_do_not_fabricate():
    record = _build(0.42)
    assert record["prediction_type"] == "CHURN"
    assert record["score"] == 0.42
    assert record["calibration_version"] is None
    assert record["score_is_calibrated"] is False
    assert record["calibration_tested_and_did_not_generalize"] is True
    assert record["band_cutoffs_version"] == "frd-requirement-capstone-2.1-dev"
    assert record["development_only"] is True
    assert record["serving_ready"] is False
    assert record["approved"] is False
    assert record["approved_taxonomy"] is False
    assert record["display_text"] is None
    assert record["identity_time_policy"] == "CURRENT_SNAPSHOT_RETROSPECTIVE"
    assert record["frd_distinct_reason_concept_unresolved"] is True
    assert record["model_version"] == "m-1"
    assert record["feature_set_version"] == "f-1"
    assert "clv_amount" not in record
    assert record["reason_codes"][0] == {
        "code": "PURCHASE_RECENCY",
        "direction": "INCREASES_RISK",
        "log_odds_contribution": 0.5,
        "display_text": None,
    }


BASE_BLOCKERS = {
    "MISSING_PREDICTION_ID",
    "UNAPPROVED_TAXONOMY",
    "UNCALIBRATED",
    "MISSING_BUSINESS_TEXT",
    "MISSING_PRODUCER_EXPIRY",
}


def test_three_mixed_codes_are_partial_and_meet_distinct_concepts():
    record = _build(codes=MIXED)
    assert record["contract_status"] == "SCHEMA_PARTIAL"
    assert set(record["contract_status_reasons"]) == BASE_BLOCKERS
    assert record["reason_count_ok"] is True
    assert record["distinct_reason_concepts"] == 3
    assert record["meets_three_distinct_concepts"] is True


def test_fewer_than_three_reasons_is_not_compliant_but_emitted():
    record = _build(codes=MIXED[:2])
    assert record["contract_status"] == "SCHEMA_PARTIAL"
    assert "INSUFFICIENT_EXPLANATION" in record["contract_status_reasons"]
    assert BASE_BLOCKERS <= set(record["contract_status_reasons"])
    assert len(record["reason_codes"]) == 2


def test_insufficient_status_never_compliant_even_with_three_codes():
    record = _build(codes=MIXED, status="INSUFFICIENT_EXPLANATION")
    assert record["contract_status"] == "SCHEMA_PARTIAL"
    assert "INSUFFICIENT_EXPLANATION" in record["contract_status_reasons"]
    assert BASE_BLOCKERS <= set(record["contract_status_reasons"])


def test_three_frequency_codes_meet_codes_but_not_distinct_concepts():
    record = _build(codes=FREQ)
    assert record["contract_status"] == "SCHEMA_PARTIAL"
    assert record["reason_count_ok"] is True
    assert record["distinct_reason_concepts"] == 1
    assert record["meets_three_distinct_concepts"] is False
    assert pc.distinct_concept_count(FREQ) == 1
    assert pc.distinct_concept_count(FREQ + ["TENURE", "PURCHASE_RECENCY"]) == 3


@pytest.mark.parametrize(
    "bad", [float("nan"), float("inf"), -0.01, 1.01, None, True, "0.5"]
)
def test_invalid_score(bad):
    record = _build(score=bad)
    assert record["contract_status"] == "INVALID_SCORE"
    assert record["score"] is None
    assert record["band"] is None
    with pytest.raises(ValueError):
        pc.to_ai_scores_dict(record)
    json.dumps(record, allow_nan=False)


def test_adapter_refuses_non_compliant():
    with pytest.raises(ValueError):
        pc.to_ai_scores_dict(_build(codes=MIXED[:2]))


def test_adapter_refuses_by_default_even_if_readiness_flags_are_mutated():
    record = _build()
    record.update(
        contract_status="CONTRACT_COMPLIANT",
        development_only=False,
        serving_ready=True,
        approved=True,
    )
    with pytest.raises(ValueError, match="development"):
        pc.to_ai_scores_dict(record)


def test_explicit_development_preview_preserves_structure_and_non_serving_flags():
    record = _build()
    record.update(development_only=False, serving_ready=True, approved=True)
    out = pc.to_ai_scores_dict(record, allow_development=True)
    assert out["development_only"] is True
    assert out["serving_ready"] is False
    assert out["approved"] is False
    assert out["aiscores_compatible"] is False
    assert out["reason_codes"] == record["reason_codes"]
    assert isinstance(out["reason_codes"][0], dict)
    assert "churn_score" not in out


def test_contract_carries_score_sentences_without_changing_approval_or_score():
    prediction = _prediction("c1", 0.42)
    prediction["contributions"] = [
        dict(
            feature="recency_days",
            feature_value=10,
            missing=False,
            imputed_value=10,
            log_odds_contribution=0.2,
        ),
        dict(
            feature="tenure_days",
            feature_value=None,
            missing=True,
            imputed_value=20,
            log_odds_contribution=-0.1,
        ),
    ]
    record = pc.build_record(
        prediction, _reasons("c1", MIXED), generated_at=GENERATED_AT
    )
    explanation = record["score_explanation"]
    assert explanation["version"] == "score-explanation-id-1.0"
    assert "skor churn dalam 90 hari naik" in explanation["sentences"][0]
    assert "nilai pengganti" in explanation["sentences"][1]
    assert record["score"] == 0.42
    assert record["contract_status"] == "SCHEMA_PARTIAL"
    assert record["approved"] is False
    assert record["serving_ready"] is False
    assert record["display_text"] is None
    assert record["producer_version"] == "prediction-contract-dev-v3"
    assert "MISSING_BUSINESS_TEXT" in record["contract_status_reasons"]


def test_explanation_rejects_non_90_day_horizon_instead_of_mislabeling():
    prediction = {**_prediction("c1", 0.42), "horizon_days": 60, "contributions": []}
    with pytest.raises(ValueError, match="90"):
        pc.build_record(prediction, _reasons("c1", MIXED), generated_at=GENERATED_AT)


def test_legacy_prediction_without_contributions_does_not_invent_sentences():
    assert _build()["score_explanation"] is None


@pytest.mark.parametrize("contributions", [None, {}, [{"feature": "recency_days"}]])
def test_present_but_malformed_contributions_are_rejected(contributions):
    prediction = {**_prediction("c1", 0.42), "contributions": contributions}
    with pytest.raises(ValueError):
        pc.build_record(prediction, _reasons("c1", MIXED), generated_at=GENERATED_AT)


# ---- end-to-end layout fixtures -------------------------------------------


def _write(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _make_inputs(
    root: Path,
    *,
    pred_flags=None,
    reason_flags=None,
    customers=("c1", "c2", "c3"),
    contributions=None,
):
    pdir, rdir = root / "preds", root / "reasons"
    pdir.mkdir()
    rdir.mkdir()
    scores = {"c1": 0.1, "c2": 0.65, "c3": 0.9}
    preds = [_prediction(c, scores[c]) for c in customers]
    if contributions is not None:
        for p in preds:
            p["contributions"] = contributions
    _write(pdir / "predictions.json", preds)
    pmanifest = {
        "development_only": True,
        "serving_ready": False,
        "generated_at": GENERATED_AT,
        "model_version": "m-1",
        "feature_version": "f-1",
        "label_version": "l-1",
        "rows": len(preds),
        "output_sha256": {"predictions.json": _sha(pdir / "predictions.json")},
        **(pred_flags or {}),
    }
    _write(pdir / "prediction_manifest.json", pmanifest)
    codes = {"c1": MIXED, "c2": MIXED[:2], "c3": FREQ}
    reasons = [_reasons(c, codes[c]) for c in customers]
    _write(rdir / "reasons.json", reasons)
    rmanifest = {
        "development_only": True,
        "serving_ready": False,
        "approved_taxonomy": False,
        "rows": len(reasons),
        "model_version": "m-1",
        "feature_version": "f-1",
        "label_version": "l-1",
        "input_sha256": {
            "predictions.json": pmanifest["output_sha256"]["predictions.json"],
            "prediction_manifest.json": _sha(pdir / "prediction_manifest.json"),
        },
        "output_sha256": {"reasons.json": _sha(rdir / "reasons.json")},
        **(reason_flags or {}),
    }
    _write(rdir / "reasons_manifest.json", rmanifest)
    return pdir, rdir


def test_run_counts_layout_and_determinism(tmp_path):
    pdir, rdir = _make_inputs(tmp_path)
    out1, out2 = tmp_path / "out1", tmp_path / "out2"
    manifest = pc.run(pdir, rdir, out1)
    pc.run(pdir, rdir, out2)
    assert (out1 / "records.jsonl").read_bytes() == (
        out2 / "records.jsonl"
    ).read_bytes()
    assert (out1 / "contract_manifest.json").read_bytes() == (
        out2 / "contract_manifest.json"
    ).read_bytes()
    assert manifest["rows"] == 3
    assert manifest["counts_by_contract_status"] == {
        "SCHEMA_PARTIAL": 3,
        "INVALID_SCORE": 0,
    }
    assert manifest["counts_by_band"] == {
        "LOW": 1,
        "MEDIUM": 0,
        "HIGH": 1,
        "VERY_HIGH": 1,
    }
    assert manifest["count_meeting_3_reason_codes"] == 2
    assert manifest["count_meeting_3_distinct_concepts"] == 1
    assert manifest["development_only"] is True
    assert manifest["serving_ready"] is False
    assert manifest["clv_fields_produced"] is False
    assert manifest["input_sha256"] == manifest["input_sha256_after"]
    assert manifest["output_sha256"]["records.jsonl"] == _sha(out1 / "records.jsonl")
    lines = (out1 / "records.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    for line in lines:
        json.loads(
            line,
            parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)),
        )


def test_run_writes_score_sentences_without_changing_readiness(tmp_path):
    contributions = [
        dict(
            feature="recency_days",
            feature_value=10,
            missing=False,
            imputed_value=10,
            log_odds_contribution=0.2,
        )
    ]
    pdir, rdir = _make_inputs(tmp_path, contributions=contributions)
    pc.run(pdir, rdir, tmp_path / "out")
    lines = (
        (tmp_path / "out" / "records.jsonl").read_text(encoding="utf-8").splitlines()
    )
    records = [json.loads(line) for line in lines]
    assert len(records) == 3
    for record in records:
        assert record["score_explanation"]["sentences"]
        assert record["contract_status"] == "SCHEMA_PARTIAL"
        assert record["approved"] is False
        assert record["serving_ready"] is False


def test_run_does_not_use_clock(tmp_path, monkeypatch):
    pdir, rdir = _make_inputs(tmp_path)

    class NoClockDatetime(datetime):
        @classmethod
        def now(cls, *a, **k):
            raise AssertionError("now() called")

        @classmethod
        def utcnow(cls):
            raise AssertionError("utcnow() called")

        @classmethod
        def today(cls):
            raise AssertionError("today() called")

    class NoClockDate(date):
        @classmethod
        def today(cls):
            raise AssertionError("today() called")

    monkeypatch.setattr(pc, "datetime", NoClockDatetime)
    monkeypatch.setattr(pc, "date", NoClockDate)
    pc.run(pdir, rdir, tmp_path / "out")


@pytest.mark.parametrize(
    "pred_flags,reason_flags",
    [
        ({"development_only": False}, None),
        ({"serving_ready": True}, None),
        (None, {"development_only": False}),
        (None, {"serving_ready": True}),
        (None, {"approved_taxonomy": True}),
    ],
)
def test_run_requires_dev_only_non_serving_manifests(
    tmp_path, pred_flags, reason_flags
):
    pdir, rdir = _make_inputs(
        tmp_path, pred_flags=pred_flags, reason_flags=reason_flags
    )
    with pytest.raises(ValueError):
        pc.run(pdir, rdir, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_run_refuses_ground_truth_path(tmp_path):
    root = tmp_path / "ground_truth"
    root.mkdir()
    pdir, rdir = _make_inputs(root)
    with pytest.raises(ValueError, match="ground_truth"):
        pc.run(pdir, rdir, tmp_path / "out")


def test_run_refuses_existing_and_overlapping_output(tmp_path):
    pdir, rdir = _make_inputs(tmp_path)
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError):
        pc.run(pdir, rdir, existing)
    with pytest.raises(ValueError):
        pc.run(pdir, rdir, pdir / "nested")
    with pytest.raises(ValueError):
        pc.run(pdir, rdir, tmp_path)


def test_run_rejects_checksum_and_join_mismatch(tmp_path):
    pdir, rdir = _make_inputs(tmp_path)
    reasons = json.loads((rdir / "reasons.json").read_text(encoding="utf-8"))
    (rdir / "reasons.json").write_text(json.dumps(reasons[:-1]), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        pc.run(pdir, rdir, tmp_path / "out")


def test_run_rejects_row_set_mismatch(tmp_path):
    pdir, rdir = _make_inputs(tmp_path)
    reasons = json.loads((rdir / "reasons.json").read_text(encoding="utf-8"))
    reasons[0]["golden_customer_id"] = "other"
    _write(rdir / "reasons.json", reasons)
    manifest = json.loads((rdir / "reasons_manifest.json").read_text(encoding="utf-8"))
    manifest["output_sha256"]["reasons.json"] = _sha(rdir / "reasons.json")
    _write(rdir / "reasons_manifest.json", manifest)
    with pytest.raises(ValueError, match="join"):
        pc.run(pdir, rdir, tmp_path / "out")


def _refresh_hashes(pdir, rdir):
    pman_path = pdir / "prediction_manifest.json"
    pman = json.loads(pman_path.read_text())
    pman["output_sha256"]["predictions.json"] = _sha(pdir / "predictions.json")
    _write(pman_path, pman)
    rman_path = rdir / "reasons_manifest.json"
    rman = json.loads(rman_path.read_text())
    rman["input_sha256"] = {
        "predictions.json": _sha(pdir / "predictions.json"),
        "prediction_manifest.json": _sha(pman_path),
    }
    rman["output_sha256"]["reasons.json"] = _sha(rdir / "reasons.json")
    _write(rman_path, rman)


def test_source_reasons_summary_total_is_a_required_row_count(tmp_path):
    pdir, rdir = _make_inputs(tmp_path)
    path = rdir / "reasons_manifest.json"
    manifest = json.loads(path.read_text())
    manifest["summary"] = {"total": manifest.pop("rows")}
    _write(path, manifest)
    assert pc.run(pdir, rdir, tmp_path / "out")["rows"] == 3


def test_tampered_prediction_manifest_lineage_is_rejected(tmp_path):
    pdir, rdir = _make_inputs(tmp_path)
    path = pdir / "prediction_manifest.json"
    manifest = json.loads(path.read_text())
    manifest["new_metadata"] = "tampered"
    _write(path, manifest)
    with pytest.raises(ValueError, match="prediction_manifest.json.*checksum"):
        pc.run(pdir, rdir, tmp_path / "out")


@pytest.mark.parametrize(
    "field,value",
    [
        ("cutoff_at", "2026-09-05T00:00:00+07:00"),
        ("horizon_days", 180),
        ("generated_at", "2026-09-07T12:00:00+07:00"),
    ],
)
def test_mixed_or_inconsistent_prediction_metadata_is_rejected(tmp_path, field, value):
    pdir, rdir = _make_inputs(tmp_path)
    path = pdir / "predictions.json"
    predictions = json.loads(path.read_text())
    predictions[0][field] = value
    _write(path, predictions)
    if field == "cutoff_at":
        path = rdir / "reasons.json"
        reasons = json.loads(path.read_text())
        reasons[0][field] = value
        _write(path, reasons)
    _refresh_hashes(pdir, rdir)
    with pytest.raises(ValueError, match="mixed|generated_at"):
        pc.run(pdir, rdir, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("generated_at", ["2026-09-06T12:00:00", "2026-09-06"])
def test_naive_publication_timestamp_is_rejected(generated_at):
    prediction = _prediction("c1", 0.5)
    prediction["generated_at"] = generated_at
    with pytest.raises(ValueError, match="aware"):
        pc.build_record(prediction, _reasons("c1", MIXED), generated_at=generated_at)


@pytest.mark.parametrize("which", ["prediction", "reasons"])
@pytest.mark.parametrize("rows", [None, True, 99])
def test_row_counts_are_required_and_validated(tmp_path, which, rows):
    pdir, rdir = _make_inputs(tmp_path)
    path = (pdir if which == "prediction" else rdir) / f"{which}_manifest.json"
    manifest = json.loads(path.read_text())
    manifest["rows"] = rows
    _write(path, manifest)
    _refresh_hashes(pdir, rdir)
    with pytest.raises(ValueError, match="row count"):
        pc.run(pdir, rdir, tmp_path / "out")


@pytest.mark.parametrize("payload", [{}, None, "bad", [None]])
def test_reason_list_validation(tmp_path, payload):
    pdir, rdir = _make_inputs(tmp_path)
    _write(rdir / "reasons.json", payload)
    _refresh_hashes(pdir, rdir)
    with pytest.raises(ValueError, match="reasons|reason"):
        pc.run(pdir, rdir, tmp_path / "out")


@pytest.mark.parametrize("payload", [{}, None, "bad", [None]])
def test_nested_reason_list_validation(payload):
    reasons = _reasons("c1", MIXED)
    reasons["reasons"] = payload
    with pytest.raises(ValueError, match="reason"):
        pc.build_record(_prediction("c1", 0.5), reasons, generated_at=GENERATED_AT)
