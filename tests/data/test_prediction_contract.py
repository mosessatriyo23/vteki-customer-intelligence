import hashlib
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from services.data.models import prediction_contract as pc
from services.data.models.score_contract import validate_score_handoff
from services.decision.nba.engine import AIScores

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


def test_dates_come_from_manifest_not_clock():
    record = _build()
    assert record["prediction_date"] == "2026-09-06"
    assert record["valid_until"] == "2026-10-06"
    assert record["outcome_window_end"] == "2026-12-05"
    assert record["horizon_days"] == 90


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


def test_three_mixed_codes_are_compliant_and_meet_distinct_concepts():
    record = _build(codes=MIXED)
    assert record["contract_status"] == "CONTRACT_COMPLIANT"
    assert record["contract_status_reasons"] == []
    assert record["distinct_reason_concepts"] == 3
    assert record["meets_three_distinct_concepts"] is True


def test_fewer_than_three_reasons_is_not_compliant_but_emitted():
    record = _build(codes=MIXED[:2])
    assert record["contract_status"] == "NOT_CONTRACT_COMPLIANT"
    assert record["contract_status_reasons"] == ["FEWER_THAN_3_REASON_CODES"]
    assert len(record["reason_codes"]) == 2


def test_insufficient_status_never_compliant_even_with_three_codes():
    record = _build(codes=MIXED, status="INSUFFICIENT_EXPLANATION")
    assert record["contract_status"] == "NOT_CONTRACT_COMPLIANT"
    assert record["contract_status_reasons"] == ["FEWER_THAN_3_REASON_CODES"]


def test_three_frequency_codes_meet_codes_but_not_distinct_concepts():
    record = _build(codes=FREQ)
    assert record["contract_status"] == "CONTRACT_COMPLIANT"
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


def test_adapter_returns_builtin_types_and_passes_score_contract():
    import numpy as np

    prediction = _prediction("c1", np.float64(0.7))
    record = pc.build_record(
        prediction, _reasons("c1", MIXED), generated_at=GENERATED_AT
    )
    out = pc.to_ai_scores_dict(record)
    assert type(out["churn_score"]) is float
    assert type(out["customer_id"]) is str
    assert out["churn_risk_band"] == "HIGH"
    assert out["reason_codes"] == MIXED
    assert all(type(c) is str for c in out["reason_codes"])
    assert "clv_amount" not in out
    scores = AIScores(
        customer_id=out["customer_id"],
        churn_score=out["churn_score"],
        churn_risk_band=out["churn_risk_band"],
        propensity_purchase=0.5,  # test filler: not produced here
        propensity_renew=0.5,
        clv_amount=0.0,
        clv_tier="INSUFFICIENT_HISTORY",
        lifecycle_stage="ACTIVE",
        score_generated_at=datetime.fromisoformat(out["score_generated_at"]),
        reason_codes=out["reason_codes"],
    )
    result = validate_score_handoff(
        scores,
        expected_customer_id="c1",
        known_at=datetime.fromisoformat("2026-09-07T00:00:00+07:00"),
    )
    assert result.valid, result.errors


# ---- end-to-end layout fixtures -------------------------------------------


def _write(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _make_inputs(
    root: Path,
    *,
    pred_flags=None,
    reason_flags=None,
    customers=("c1", "c2", "c3"),
):
    pdir, rdir = root / "preds", root / "reasons"
    pdir.mkdir()
    rdir.mkdir()
    scores = {"c1": 0.1, "c2": 0.65, "c3": 0.9}
    preds = [_prediction(c, scores[c]) for c in customers]
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
        "model_version": "m-1",
        "feature_version": "f-1",
        "label_version": "l-1",
        "input_sha256": {
            "predictions.json": pmanifest["output_sha256"]["predictions.json"]
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
        "CONTRACT_COMPLIANT": 2,
        "INVALID_SCORE": 0,
        "NOT_CONTRACT_COMPLIANT": 1,
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
