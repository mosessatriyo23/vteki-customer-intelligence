"""
test_nba_serving.py — Revisi mentor: NBA tersambung ke aplikasi (Fase 4 lanjutan).

Yang dibuktikan:
  1. Skor model hanya dipakai bila run sudah `reviewed` oleh ORANG LAIN (fail-closed).
  2. Data kosong ditulis kosong: tidak ada angka karangan di alasan / kolom rationale.
  3. Alasan keputusan memakai kalimat Indonesia yang mudah dipahami.
  4. Hasil siap-simpan untuk `dec.nba_decisions`, `gov.decision_traces`, audit event.
  5. Kode di `services/decision/` tetap fungsi murni (tidak mengimpor api/db/web).

Jalankan: python -m pytest tests/decision/test_nba_serving.py -v
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import jsonschema
import pytest

from services.decision.nba.engine import EligibilityProfile, ProductSuitability
from services.decision.nba.serving import (
    SCORE_INCOMPLETE,
    SCORE_INVALID,
    SCORE_NO_ROW,
    SCORE_NOT_REVIEWED,
    SCORE_SELF_REVIEWED,
    SOURCE_UNAVAILABLE,
    DecisionOutput,
    evaluate_customer,
    lookup_scores,
)
from services.decision.policy.fatigue import ContactRecord
from services.decision.policy.suppression import ComplaintStatus, ComplaintTicket

ROOT = Path(__file__).resolve().parents[2]
K07 = json.loads((ROOT / "contracts" / "K-07_decision_record.json").read_text("utf-8"))

NOW = datetime(2026, 11, 20, 10, 0, 0)
REF = "GOLD-0001"
CORR = "corr-serving-test-0001"


def consent_doc(email: bool = True, push: bool = True, global_opt_out: bool = False):
    def ch(on: bool) -> Dict[str, Any]:
        status = "OPT_IN" if on else "OPT_OUT"
        return {
            "status": status,
            "opt_in": on,
            "effective_permission": "ALLOWED" if on else "BLOCKED",
        }

    return {
        "customer_id": REF,
        "global_consent": {
            "status": "OPT_OUT" if global_opt_out else "OPT_IN",
            "is_global_opt_out": global_opt_out,
        },
        "channels": {"email": ch(email), "push": ch(push)},
        "unknown_expired_policy": "BLOCKED",
        "identity_merge_policy": "MOST_RESTRICTIVE_WINS",
        "most_restrictive_wins": True,
    }


def score_row(**overrides: Any) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "customer_id": REF,
        "churn_score": 0.92,
        "churn_risk_band": "VERY_HIGH",
        "propensity_purchase": 0.6,
        "propensity_renew": 0.5,
        "clv_amount": 3_000_000.0,
        "clv_tier": "GOLD",
        "lifecycle_stage": "AT_RISK",
        "score_generated_at": (NOW - timedelta(days=1)).isoformat(),
        "reason_codes": [
            "PURCHASE_FREQUENCY_90D",
            "RETAINED_REVENUE_365D",
            "X_UNKNOWN",
        ],
        "model_version": "churn-dev-1.0",
        "review_status": "reviewed",
        "reviewed_by": 7,
        "submitted_by": 3,
    }
    row.update(overrides)
    return row


def eligibility() -> EligibilityProfile:
    return EligibilityProfile(
        customer_id=REF,
        tenure_days=400,
        membership_days_remaining=20,
        has_active_membership=True,
        purchased_categories=["GROCERY"],
        days_until_replenishment=3,
    )


def run(
    *,
    row: Optional[Dict[str, Any]] = None,
    consent: Optional[Dict[str, Any]] = None,
    complaints: Optional[List[ComplaintTicket]] = None,
    contacts: Optional[List[ContactRecord]] = None,
    elig: Optional[EligibilityProfile] = None,
    suitability: Optional[ProductSuitability] = None,
) -> DecisionOutput:
    return evaluate_customer(
        customer_ref=REF,
        correlation_id=CORR,
        score_row=score_row() if row is None else row,
        consent_doc=consent_doc() if consent is None else consent,
        complaint_tickets=[] if complaints is None else complaints,
        contact_history=[] if contacts is None else contacts,
        eligibility=eligibility() if elig is None else elig,
        product_suitability=(
            ProductSuitability() if suitability is None else suitability
        ),
        evaluation_date=NOW,
    )


# ---------------------------------------------------------------------------
# 1. Skor: hanya yang sudah dicek orang lain
# ---------------------------------------------------------------------------


class TestScoreLookup:
    def test_reviewed_by_other_person_is_used(self):
        lookup = lookup_scores(score_row(), customer_id=REF)
        assert lookup.usable and lookup.model_version == "churn-dev-1.0"
        assert lookup.ai_scores.churn_score == 0.92

    def test_missing_row_is_unavailable_not_defaulted(self):
        lookup = lookup_scores(None, customer_id=REF)
        assert not lookup.usable and lookup.unavailable_reason == SCORE_NO_ROW

    @pytest.mark.parametrize("status", ["pending_review", "rejected", None])
    def test_unreviewed_run_is_rejected(self, status):
        lookup = lookup_scores(score_row(review_status=status), customer_id=REF)
        assert lookup.unavailable_reason == SCORE_NOT_REVIEWED

    def test_review_by_same_person_who_submitted_is_rejected(self):
        lookup = lookup_scores(
            score_row(reviewed_by=3, submitted_by=3), customer_id=REF
        )
        assert lookup.unavailable_reason == SCORE_SELF_REVIEWED

    def test_review_without_reviewer_is_rejected(self):
        lookup = lookup_scores(score_row(reviewed_by=None), customer_id=REF)
        assert lookup.unavailable_reason == SCORE_SELF_REVIEWED

    def test_incomplete_score_lists_missing_fields_and_invents_nothing(self):
        lookup = lookup_scores(
            score_row(clv_amount=None, propensity_renew=None), customer_id=REF
        )
        assert lookup.unavailable_reason == SCORE_INCOMPLETE
        assert set(lookup.missing_fields) == {"clv_amount", "propensity_renew"}
        assert lookup.ai_scores is None

    @pytest.mark.parametrize(
        "bad",
        [
            {"churn_score": 1.5},
            {"churn_score": float("nan")},
            {"clv_amount": -1},
            {"churn_score": True},
            {"score_generated_at": "bukan-tanggal"},
            {"clv_amount": 10**400},
        ],
    )
    def test_invalid_values_are_rejected(self, bad):
        lookup = lookup_scores(score_row(**bad), customer_id=REF)
        assert lookup.unavailable_reason == SCORE_INVALID


# ---------------------------------------------------------------------------
# 2. Data kosong ditulis kosong (tanpa angka karangan)
# ---------------------------------------------------------------------------


class TestEmptyDataStaysEmpty:
    def test_no_score_row_means_degraded_with_no_numbers_in_rationale(self):
        output = run(row={})
        payload = output.rationale_payload()
        assert output.degraded_input is True
        assert payload["expected_value"] is None
        assert payload["serving_ready"] is False
        assert payload["score_unavailable_reason"] == SCORE_NO_ROW
        assert "belum ada" in output.plain_rationale
        assert not re.search(r"\d", output.plain_rationale)
        assert output.is_no_action

    def test_unreviewed_model_never_drives_a_recommendation(self):
        output = run(row=score_row(review_status="pending_review"))
        assert output.is_no_action
        assert output.rationale_payload()["model_review_status"] == "pending_review"
        assert output.rationale_payload()["expected_value"] is None

    @pytest.mark.parametrize(
        "missing",
        [
            "consent",
            "complaint_history",
            "contact_history",
            "eligibility",
            "product_suitability",
        ],
    )
    def test_unconnected_source_yields_honest_no_decision(self, missing):
        kwargs: Dict[str, Any] = dict(
            customer_ref=REF,
            correlation_id=CORR,
            score_row=score_row(),
            consent_doc=consent_doc(),
            complaint_tickets=[],
            contact_history=[],
            eligibility=eligibility(),
            product_suitability=ProductSuitability(),
            evaluation_date=NOW,
        )
        key = {
            "consent": "consent_doc",
            "complaint_history": "complaint_tickets",
            "contact_history": "contact_history",
            "eligibility": "eligibility",
            "product_suitability": "product_suitability",
        }[missing]
        kwargs[key] = None
        output = evaluate_customer(**kwargs)
        assert output.record is None and output.is_no_action
        assert output.unavailable_sources == (missing,)
        payload = output.rationale_payload()
        assert payload["no_action_reason"] == SOURCE_UNAVAILABLE
        assert payload["expected_value"] is None
        assert payload["serving_ready"] is False
        assert payload["input_availability"][missing] == "unavailable"
        assert "belum tersambung" in output.plain_rationale
        assert not re.search(r"\d", output.plain_rationale)

    def test_empty_but_connected_sources_are_allowed(self):
        output = run(complaints=[], contacts=[])
        assert output.record is not None
        assert output.unavailable_sources == ()


# ---------------------------------------------------------------------------
# 3. Kalimat yang mudah dipahami
# ---------------------------------------------------------------------------


class TestPlainLanguage:
    def test_recommendation_is_written_in_plain_indonesian(self):
        output = run()
        assert output.record is not None and not output.is_no_action
        text = output.plain_rationale
        assert text.startswith("Disarankan:")
        assert "Rp" in text and "bukan jaminan" in text
        assert "risiko" in text.lower()
        # kode teknis tidak bocor ke kalimat untuk staf bisnis
        for technical in (
            "ALL_CANDIDATES_BLOCKED",
            "EV=",
            "degraded_input",
            "OPT_OUT_SUPPRESSED",
        ):
            assert technical not in text

    def test_known_reason_codes_are_translated_unknown_are_not_guessed(self):
        text = run().plain_rationale
        assert "seberapa sering belanja dalam 90 hari terakhir" in text
        assert "X_UNKNOWN" in text  # kode asing ditampilkan apa adanya, tidak ditebak

    def test_opt_out_explains_that_high_score_is_not_permission(self):
        output = run(consent=consent_doc(global_opt_out=True))
        assert output.is_no_action
        assert output.record.no_action_reason == "OPT_OUT_SUPPRESSED"
        assert "menolak dihubungi" in output.plain_rationale
        assert "tidak cukup" in output.plain_rationale

    def test_frequency_cap_is_explained(self):
        contacts = [
            ContactRecord(REF, "CROSS_SELL", "email", NOW - timedelta(days=d))
            for d in (1, 6)
        ]
        output = run(contacts=contacts)
        assert output.record.no_action_reason == "FREQ_CAP_SUPPRESSED"
        assert "14 hari" in output.plain_rationale

    def test_open_severe_complaint_prefers_resolution_over_promotion(self):
        ticket = ComplaintTicket(
            ticket_id="T-1",
            customer_id=REF,
            status=ComplaintStatus.OPEN_SEVERE,
            severity="SEVERE",
            opened_at=NOW - timedelta(days=1),
        )
        output = run(complaints=[ticket])
        assert output.selected_action_id == "COMPLAINT_RESOLUTION"
        assert "keluhan berat" in output.plain_rationale

    def test_rupiah_uses_indonesian_thousand_separator(self):
        assert re.search(r"Rp \d{1,3}(\.\d{3})+", run().plain_rationale)

    @pytest.mark.parametrize(
        "row, expected",
        [
            ({}, "belum ada"),
            (score_row(review_status="pending_review"), "belum diperiksa orang lain"),
            (score_row(reviewed_by=3), "orang yang sama"),
            (score_row(clv_amount=None), "belum lengkap"),
            (score_row(churn_score=2), "tidak valid"),
        ],
    )
    def test_reason_for_unusable_score_is_specific_and_leads_with_the_score(
        self, row, expected
    ):
        text = run(row=row).plain_rationale
        assert expected in text
        assert "Belum ada rekomendasi pesan" in text
        assert "kelayakan" not in text  # penyebab sebenarnya skor, bukan kelayakan

    def test_technical_rationale_for_audit_is_kept_unchanged(self):
        output = run(consent=consent_doc(global_opt_out=True))
        assert output.record.rationale_text  # K-07 tetap terisi
        payload = output.rationale_payload()
        assert payload["technical_reason"] == output.record.rationale_text
        assert payload["reason"] == output.plain_rationale


# ---------------------------------------------------------------------------
# 4. Baris siap-simpan untuk api/
# ---------------------------------------------------------------------------


class TestPersistableRows:
    def test_recommendation_row_matches_nba_decisions_columns(self):
        output = run()
        row = output.to_nba_decision_row(customer_db_id=42)
        assert set(row) == {
            "customer_id",
            "correlation_id",
            "recommended_action",
            "rationale",
            "status",
        }
        assert row["customer_id"] == 42 and row["correlation_id"] == CORR
        assert row["status"] == "proposed"
        rationale = row["rationale"]
        assert rationale["serving_ready"] is True
        assert rationale["model_version"] == "churn-dev-1.0"
        assert rationale["model_reviewed_by"] == 7
        assert rationale["expected_value"] is not None
        json.dumps(rationale, allow_nan=False)  # JSON valid, tanpa NaN/inf

    def test_no_action_is_stored_as_accepted(self):
        row = run(consent=consent_doc(global_opt_out=True)).to_nba_decision_row(
            customer_db_id=1
        )
        assert row["recommended_action"] == "NO_ACTION" and row["status"] == "accepted"

    def test_k07_record_still_validates_against_contract(self):
        record = run().record
        jsonschema.Draft7Validator(K07).validate(record.to_dict())

    def test_trace_row_and_audit_details(self):
        output = run()
        trace = output.to_trace_row(customer_code="CUST-1")
        assert trace["trigger_event"] == "nba.engine_evaluated"
        assert trace["decision_output"] == output.selected_action_id
        assert trace["step_logs"][0]["correlation_id"] == CORR
        details = output.to_audit_details(decision_id=9)
        assert (
            details["decision_id"] == 9 and details["model_version"] == "churn-dev-1.0"
        )

    def test_api_response_shape_for_ui(self):
        response = run().to_api_response(decision_id=5, status="proposed")
        assert {"id", "status", "selected_action", "reason", "serving_ready"} <= set(
            response
        )
        assert response["unavailable_sources"] == []

    def test_unconnected_source_trace_has_no_fake_k07_record(self):
        output = evaluate_customer(
            customer_ref=REF,
            correlation_id=CORR,
            score_row=None,
            consent_doc=None,
            complaint_tickets=None,
            contact_history=None,
            eligibility=None,
            product_suitability=None,
            evaluation_date=NOW,
        )
        step = output.to_trace_row(customer_code="CUST-1")["step_logs"][0]
        assert step["no_action_reason"] == SOURCE_UNAVAILABLE
        assert "candidates" not in step and "expected_value" not in step


# ---------------------------------------------------------------------------
# 5. Arsitektur: services/ = fungsi murni
# ---------------------------------------------------------------------------


def test_services_decision_never_imports_api_worker_or_database_layers():
    banned = re.compile(
        r"^\s*(?:from|import)\s+(api|worker|web|sqlalchemy|fastapi|psycopg|requests|httpx)\b",
        re.MULTILINE,
    )
    offenders = [
        str(path.relative_to(ROOT))
        for path in (ROOT / "services" / "decision").rglob("*.py")
        if banned.search(path.read_text("utf-8"))
    ]
    assert offenders == []
