"""Development-only producer of FRD-K04-shaped PROPOSED churn prediction records.

Joins the offline churn predictions (`churn_inference`) with the proposed reason
output (`churn_reasons`). Nothing is fabricated or approved here:

* ``score`` is the raw, uncalibrated logistic probability. ``calibration_version``
  is null and ``score_is_calibrated`` is false: isotonic calibration was tested and
  did not generalize (docs/moses_data_ai/CALIBRATION_FINDING_DEV_2026-11-19.md).
* ``band`` uses the FRD/Capstone churn cut-offs held as constants below.
* Reference dates derive from row ``cutoff_at``; publication never refreshes expiry.
* ``reason_codes`` only come from the reasons output; no display text is invented.
* CLV fields and ``prediction_id`` are not produced.

Not a serving artifact: ``development_only`` true, ``serving_ready`` false,
``approved`` false.
"""

import argparse
import hashlib
import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path

PREDICTION_TYPE = "CHURN"
BAND_CUTOFFS_VERSION = "frd-requirement-capstone-2.1-dev"
#: (exclusive upper bound, band); the last band is open-ended [0.80, 1].
BAND_CUTOFFS = ((0.30, "LOW"), (0.60, "MEDIUM"), (0.80, "HIGH"))
TOP_BAND = "VERY_HIGH"
BANDS = ("LOW", "MEDIUM", "HIGH", "VERY_HIGH")
VALID_DAYS = 30
MIN_REASON_CODES = 3
MIN_DISTINCT_CONCEPTS = 3
IDENTITY_TIME_POLICY = "CURRENT_SNAPSHOT_RETROSPECTIVE"
PRODUCER_VERSION = "prediction-contract-dev-v2"
SCHEMA_PARTIAL = "SCHEMA_PARTIAL"
INVALID_SCORE = "INVALID_SCORE"
STATUSES = (SCHEMA_PARTIAL, INVALID_SCORE)
FEWER_THAN_3 = "FEWER_THAN_3_REASON_CODES"
CALIBRATION_NOTE = (
    "Isotonic calibration was tested and did not generalize "
    "(docs/moses_data_ai/CALIBRATION_FINDING_DEV_2026-11-19.md); score is raw."
)
#: Business-concept grouping; the three frequency windows may be one concept.
CONCEPT_MAP = {
    "PURCHASE_FREQUENCY_60D": "PURCHASE_FREQUENCY",
    "PURCHASE_FREQUENCY_90D": "PURCHASE_FREQUENCY",
    "PURCHASE_FREQUENCY_365D": "PURCHASE_FREQUENCY",
}
LIMITATIONS = (
    "Development-only synthetic proposal; not approved, not serving-ready",
    "Score is a raw uncalibrated logistic probability; calibration did not generalize",
    "Band cut-offs are FRD/Capstone values pending baseline-review decision",
    "Reason codes are proposed log-odds attributions; taxonomy not approved; no display text",
    "No prediction_id and no CLV fields are produced here",
    "FRD distinct-reason concept rule is unresolved; both flags are reported",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def score_to_band(score: float) -> str:
    for upper, band in BAND_CUTOFFS:
        if score < upper:
            return band
    return TOP_BAND


def distinct_concept_count(codes: list[str]) -> int:
    return len({CONCEPT_MAP.get(code, code) for code in codes})


def _valid_score(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value) and 0 <= value <= 1
    except (OverflowError, TypeError, ValueError):
        return False


def _aware_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an aware timestamp")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be an aware timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{field} must be an aware timestamp")
    return result


def _reason_entry(reason: dict) -> dict:
    if not isinstance(reason, dict):
        raise ValueError("reason entry must be an object")
    code, direction = reason.get("code"), reason.get("direction")
    contribution = reason.get("log_odds_contribution")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("reason code must be a nonempty string")
    if direction not in ("INCREASES_RISK", "DECREASES_RISK"):
        raise ValueError("reason direction must be INCREASES_RISK or DECREASES_RISK")
    if (
        isinstance(contribution, bool)
        or not isinstance(contribution, (int, float))
        or not math.isfinite(contribution)
    ):
        raise ValueError("reason log_odds_contribution must be finite")
    return {
        "code": code,
        "direction": direction,
        "log_odds_contribution": float(contribution),
        "display_text": None,
    }


def build_record(prediction: dict, reasons: dict, *, generated_at: str) -> dict:
    """Build one proposed K-04 record from one prediction and its reason result."""
    customer = prediction["golden_customer_id"]
    cutoff = prediction["cutoff_at"]
    if (reasons["golden_customer_id"], reasons["cutoff_at"]) != (customer, cutoff):
        raise ValueError("prediction/reasons join key mismatch")
    horizon = prediction["horizon_days"]
    if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon <= 0:
        raise ValueError("horizon_days must be a positive integer")
    publication = _aware_timestamp(generated_at, "generated_at")
    if prediction.get("generated_at") != generated_at:
        raise ValueError("row generated_at differs from prediction manifest")
    reference = _aware_timestamp(cutoff, "cutoff_at")
    if reference > publication:
        raise ValueError("cutoff_at must not be after generated_at")
    prediction_date: date = reference.date()
    if not isinstance(reasons.get("reasons"), list):
        raise ValueError("reasons must be a list")
    entries = [_reason_entry(item) for item in reasons["reasons"]]
    codes = [entry["code"] for entry in entries]
    concepts = distinct_concept_count(codes)
    raw = prediction["churn_probability"]
    score_ok = _valid_score(raw)
    reason_count_ok = len(codes) >= MIN_REASON_CODES
    status_reasons = [
        "MISSING_PREDICTION_ID",
        "UNAPPROVED_TAXONOMY",
        "UNCALIBRATED",
        "MISSING_BUSINESS_TEXT",
    ]
    if prediction["valid_until"] is None:
        status_reasons.append("MISSING_PRODUCER_EXPIRY")
    if not score_ok:
        status_reasons.append(INVALID_SCORE)
    if not reason_count_ok:
        status_reasons.append(FEWER_THAN_3)
    if reasons["status"] != "OK":
        status_reasons.append("INSUFFICIENT_EXPLANATION")
    status = INVALID_SCORE if not score_ok else SCHEMA_PARTIAL
    score = float(raw) if score_ok else None
    return {
        "customer_id": customer,
        "cutoff_at": cutoff,
        "prediction_type": PREDICTION_TYPE,
        "score": score,
        "band": score_to_band(score) if score_ok else None,
        "band_cutoffs_version": BAND_CUTOFFS_VERSION,
        "score_is_calibrated": False,
        "calibration_version": None,
        "calibration_tested_and_did_not_generalize": True,
        "calibration_note": CALIBRATION_NOTE,
        "reason_codes": entries,
        "reason_status": reasons["status"],
        "approved_taxonomy": False,
        "display_text": None,
        "model_version": prediction["model_version"],
        "feature_set_version": prediction["feature_version"],
        "label_version": prediction["label_version"],
        "prediction_date": prediction_date.isoformat(),
        "horizon_days": horizon,
        "outcome_window_end": (prediction_date + timedelta(days=horizon)).isoformat(),
        "valid_until": prediction["valid_until"],
        "proposed_valid_until": (
            prediction_date + timedelta(days=VALID_DAYS)
        ).isoformat(),
        "score_generated_at": generated_at,
        "contract_status": status,
        "contract_status_reasons": status_reasons,
        "producer_version": PRODUCER_VERSION,
        "reason_count_ok": reason_count_ok,
        "distinct_reason_concepts": concepts,
        "meets_three_distinct_concepts": concepts >= MIN_DISTINCT_CONCEPTS,
        "frd_distinct_reason_concept_unresolved": True,
        "identity_time_policy": IDENTITY_TIME_POLICY,
        "development_only": True,
        "serving_ready": False,
        "approved": False,
    }


def to_ai_scores_dict(record: dict, *, allow_development: bool = False) -> dict:
    """Legacy name: development inspection only, NOT an AIScores adapter.

    No combination of caller-supplied readiness flags authorizes serving.
    Structured explanations and lineage remain intact; AIScores fields are not emitted.
    """
    if allow_development is not True:
        raise ValueError("explicit allow_development=True required; no serving adapter")
    if not _valid_score(record.get("score")):
        raise ValueError("invalid score cannot be previewed")
    return {
        **record,
        "contract_status": SCHEMA_PARTIAL,
        "development_only": True,
        "serving_ready": False,
        "approved": False,
        "aiscores_compatible": False,
    }


def _load_manifest(path: Path, *, require_taxonomy_unapproved: bool = False) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if (
        manifest.get("development_only") is not True
        or manifest.get("serving_ready") is not False
    ):
        raise ValueError(
            f"{path.name}: development-only, non-serving manifest required"
        )
    if require_taxonomy_unapproved and manifest.get("approved_taxonomy") is not False:
        raise ValueError(f"{path.name}: approved_taxonomy must be false")
    return manifest


def _check_paths(pdir: Path, rdir: Path, out: Path) -> None:
    if out.exists():
        raise ValueError("Use a new output directory")
    parts = pdir.parts + rdir.parts + out.parts
    if any(part.lower() == "ground_truth" for part in parts):
        raise ValueError("ground_truth paths are not allowed")
    for other in (pdir, rdir):
        if out == other or out in other.parents or other in out.parents:
            raise ValueError("Keep input and output directories separate")


def _dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, allow_nan=False)


def run(predictions_dir: Path, reasons_dir: Path, output_dir: Path) -> dict:
    pdir = Path(predictions_dir).resolve()
    rdir = Path(reasons_dir).resolve()
    out = Path(output_dir).resolve()
    _check_paths(pdir, rdir, out)
    paths = {
        "prediction_manifest.json": pdir / "prediction_manifest.json",
        "predictions.json": pdir / "predictions.json",
        "reasons_manifest.json": rdir / "reasons_manifest.json",
        "reasons.json": rdir / "reasons.json",
    }
    before = {name: sha256(path) for name, path in paths.items()}
    pman = _load_manifest(paths["prediction_manifest.json"])
    rman = _load_manifest(
        paths["reasons_manifest.json"], require_taxonomy_unapproved=True
    )
    if (
        pman.get("output_sha256", {}).get("predictions.json")
        != before["predictions.json"]
    ):
        raise ValueError("predictions.json checksum mismatch against manifest")
    if rman.get("output_sha256", {}).get("reasons.json") != before["reasons.json"]:
        raise ValueError("reasons.json checksum mismatch against manifest")
    for name in ("predictions.json", "prediction_manifest.json"):
        if rman.get("input_sha256", {}).get(name) != before[name]:
            raise ValueError(f"{name}: reasons input checksum mismatch")
    for key in ("model_version", "feature_version", "label_version"):
        if pman.get(key) != rman.get(key):
            raise ValueError(f"{key} differs between prediction and reasons manifests")
    generated_at = pman.get("generated_at")
    if not isinstance(generated_at, str):
        raise ValueError("prediction manifest generated_at is required")
    _aware_timestamp(generated_at, "generated_at")
    predictions = json.loads(paths["predictions.json"].read_text(encoding="utf-8"))
    reasons = json.loads(paths["reasons.json"].read_text(encoding="utf-8"))
    if not isinstance(predictions, list) or not predictions:
        raise ValueError("predictions.json must hold a nonempty list")
    if not isinstance(reasons, list) or not all(isinstance(r, dict) for r in reasons):
        raise ValueError("reasons.json must hold a list of objects")
    if not all(isinstance(p, dict) for p in predictions):
        raise ValueError("predictions.json must hold a list of objects")
    for name, count, rows in (
        ("Prediction", pman.get("rows"), predictions),
        (
            "reasons",
            (
                rman.get("summary", {}).get("total")
                if "summary" in rman
                else rman.get("rows")
            ),
            reasons,
        ),
    ):
        if type(count) is not int or count != len(rows):
            raise ValueError(f"{name} row count mismatch against manifest")
    if any(
        p.get(field) != predictions[0].get(field)
        for p in predictions
        for field in ("cutoff_at", "horizon_days")
    ):
        raise ValueError("mixed cutoff_at or horizon_days inputs are not supported")
    by_key: dict[tuple[str, str], dict] = {}
    for item in reasons:
        key = (item["golden_customer_id"], item["cutoff_at"])
        if key in by_key:
            raise ValueError("Duplicate customer/cutoff in reasons")
        by_key[key] = item
    if len(by_key) != len(predictions):
        raise ValueError("Cannot join: prediction/reasons row sets differ")
    lines: list[str] = []
    records: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for prediction in predictions:
        key = (prediction["golden_customer_id"], prediction["cutoff_at"])
        if key in seen:
            raise ValueError("Duplicate customer/cutoff in predictions")
        seen.add(key)
        if key not in by_key:
            raise ValueError("Cannot join: prediction without reasons row")
        for field in ("model_version", "feature_version", "label_version"):
            if prediction[field] != pman[field] or by_key[key][field] != pman[field]:
                raise ValueError(f"{field} differs from manifest in a row")
        record = build_record(prediction, by_key[key], generated_at=generated_at)
        records.append(record)
        lines.append(_dumps(record))
    after = {name: sha256(path) for name, path in paths.items()}
    if after != before:
        raise ValueError("Input changed during contract production")
    out.mkdir(parents=True)
    (out / "records.jsonl").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    status_counts = {name: 0 for name in STATUSES}
    band_counts = {name: 0 for name in BANDS}
    for record in records:
        status_counts[record["contract_status"]] += 1
        if record["band"] is not None:
            band_counts[record["band"]] += 1
    manifest = {
        "producer_version": PRODUCER_VERSION,
        "prediction_type": PREDICTION_TYPE,
        "model_version": pman["model_version"],
        "feature_set_version": pman["feature_version"],
        "label_version": pman["label_version"],
        "prediction_date": records[0]["prediction_date"],
        "proposed_valid_days": VALID_DAYS,
        "horizon_days": records[0]["horizon_days"],
        "band_cutoffs_version": BAND_CUTOFFS_VERSION,
        "band_cutoffs": {
            "LOW": "<0.30",
            "MEDIUM": "0.30-<0.60",
            "HIGH": "0.60-<0.80",
            "VERY_HIGH": ">=0.80",
        },
        "calibration_version": None,
        "score_is_calibrated": False,
        "calibration_note": CALIBRATION_NOTE,
        "development_only": True,
        "serving_ready": False,
        "approved": False,
        "approved_taxonomy": False,
        "clv_fields_produced": False,
        "prediction_id_produced": False,
        "frd_distinct_reason_concept_unresolved": True,
        "rows": len(records),
        "counts_by_contract_status": status_counts,
        "counts_by_band": band_counts,
        "count_meeting_3_reason_codes": sum(r["reason_count_ok"] for r in records),
        "count_meeting_3_distinct_concepts": sum(
            r["reason_count_ok"] and r["meets_three_distinct_concepts"] for r in records
        ),
        "input_sha256": before,
        "input_sha256_after": after,
        "output_sha256": {"records.jsonl": sha256(out / "records.jsonl")},
        "limitations": list(LIMITATIONS),
    }
    (out / "contract_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions-dir", type=Path, required=True)
    parser.add_argument("--reasons-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.predictions_dir, args.reasons_dir, args.output_dir)
    print(
        _dumps(
            {
                "rows": result["rows"],
                "counts_by_contract_status": result["counts_by_contract_status"],
                "serving_ready": False,
            }
        )
    )


if __name__ == "__main__":
    main()
