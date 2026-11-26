"""Review imports reject unorderable and duplicate cutoff instants before DB writes."""

import hashlib
import json

import pytest

from services.data.models.prediction_review import validate_prediction_import

CUSTOMER = "6b3ddba4-0825-4e58-a392-d183b71023d0"


def bundle(cutoffs):
    versions = dict(
        model_version="model-v1", feature_set_version="fv1", label_version="lv1"
    )
    rows = [
        dict(
            **versions,
            customer_id=CUSTOMER,
            cutoff_at=cutoff,
            score=0.5,
            reason_codes=[],
            serving_ready=False,
            approved=False,
        )
        for cutoff in cutoffs
    ]
    payload = ("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n").encode()
    manifest = dict(
        **versions,
        prediction_type="CHURN",
        producer_version="test-producer",
        development_only=True,
        serving_ready=False,
        approved=False,
        prediction_id_produced=False,
        rows=len(rows),
        output_sha256={"records.jsonl": hashlib.sha256(payload).hexdigest()},
    )
    return manifest, rows


@pytest.mark.parametrize(
    "cutoff",
    ["not-a-date", "", "2026-11-01", "2026-11-01T00:00:00", "2026-13-01T00:00:00Z"],
)
def test_invalid_or_naive_cutoff_rejected(cutoff):
    with pytest.raises(ValueError, match="cutoff"):
        validate_prediction_import(*bundle([cutoff]))


@pytest.mark.parametrize(
    "second", ["2026-11-01T07:00:00+07:00", "2026-11-01T00:00:00Z"]
)
def test_same_customer_same_instant_rejected_across_offsets(second):
    with pytest.raises(ValueError, match="Duplicate"):
        validate_prediction_import(*bundle(["2026-11-01T00:00:00+00:00", second]))


def test_distinct_instants_remain_distinct_and_original_evidence_unchanged():
    manifest, rows = bundle(["2026-11-01T00:00:00Z", "2026-11-01T07:00:01+07:00"])
    before = json.dumps([manifest, rows], sort_keys=True)
    result = validate_prediction_import(manifest, rows)
    assert result.records == tuple(rows)
    assert json.dumps([manifest, rows], sort_keys=True) == before


def test_space_separated_aware_cutoff_from_producer_is_accepted():
    manifest, rows = bundle(["2026-11-01 00:00:00+00:00"])
    assert validate_prediction_import(manifest, rows).records == tuple(rows)


def test_same_instant_different_customer_is_allowed():
    manifest, rows = bundle(["2026-11-01T00:00:00Z", "2026-11-01T07:00:00+07:00"])
    rows[1]["customer_id"] = "6b3ddba4-0825-4e58-a392-d183b71023d1"
    payload = ("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n").encode()
    manifest["output_sha256"]["records.jsonl"] = hashlib.sha256(payload).hexdigest()
    assert len(validate_prediction_import(manifest, rows).records) == 2
