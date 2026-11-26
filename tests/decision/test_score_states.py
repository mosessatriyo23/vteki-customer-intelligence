"""
test_score_states.py — Tiga keadaan skor untuk UI (to-do Project Manager 26 Nov 2026).

Sebelumnya UI menampilkan "SCORE_ROW_MISSING" untuk ketiga keadaan berikut:
  1. SCORE_MISSING               - tidak ada baris skor.
  2. SCORE_PRESENT_NOT_APPROVED  - ada, tetapi belum direview / belum disetujui / kontrak belum
                                   lengkap / field kosong / nilai tidak valid.
  3. SCORE_READY                 - lolos semua gerbang dan dipakai.

Yang dibuktikan di sini (sisi `services/decision`; loader di api/ milik James/Moses):
  * setiap alasan penolakan skor dipetakan ke tepat satu keadaan, tanpa angka karangan;
  * baris dengan `contract_status` non-serving dibedakan dari "baris tidak ada";
  * alasan tak dikenal = fail-closed ("ada tapi belum dipakai"), bukan "siap" / "belum ada";
  * `score_state` dan `score_unavailable_reason` ikut respons API dan kolom rationale;
  * skor siap TIDAK otomatis berarti keputusan siap bila sumber non-skor belum tersambung.

Jalankan: python -m pytest tests/decision/test_score_states.py -v
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from services.decision.nba.engine import ProductSuitability
from services.decision.nba.serving import (
    SCORE_CONTRACT_NOT_SERVING,
    SCORE_CUSTOMER_MISMATCH,
    SCORE_EXPIRED,
    SCORE_INCOMPLETE,
    SCORE_INVALID,
    SCORE_NO_ROW,
    SCORE_NOT_REVIEWED,
    SCORE_SELF_REVIEWED,
    SCORE_STATE_MISSING,
    SCORE_STATE_PRESENT_NOT_APPROVED,
    SCORE_STATE_READY,
    SCORE_USAGE_NOT_APPROVED,
    evaluate_customer,
    lookup_scores,
    score_state_for,
)
from tests.decision.test_nba_serving import (
    CORR,
    NOW,
    REF,
    consent_doc,
    eligibility,
    run,
    score_row,
)


class TestMappingFromReasonToState:
    def test_no_row_is_missing(self):
        assert score_state_for(SCORE_NO_ROW, usable=False) == SCORE_STATE_MISSING

    @pytest.mark.parametrize(
        "reason",
        [
            SCORE_NOT_REVIEWED,
            SCORE_SELF_REVIEWED,
            SCORE_USAGE_NOT_APPROVED,
            SCORE_CONTRACT_NOT_SERVING,
            SCORE_INCOMPLETE,
            SCORE_INVALID,
        ],
    )
    def test_existing_but_unusable_row_is_present_not_approved(self, reason):
        assert score_state_for(reason, usable=False) == SCORE_STATE_PRESENT_NOT_APPROVED

    def test_usable_is_ready(self):
        assert score_state_for(None, usable=True) == SCORE_STATE_READY

    @pytest.mark.parametrize("reason", [None, "", "SOMETHING_NEW"])
    def test_unknown_reason_fails_closed_to_present_not_approved(self, reason):
        state = score_state_for(reason, usable=False)
        assert state == SCORE_STATE_PRESENT_NOT_APPROVED
        assert state not in (SCORE_STATE_READY, SCORE_STATE_MISSING)


class TestLookupStates:
    def test_state_1_no_row(self):
        assert lookup_scores(None, customer_id=REF).state == SCORE_STATE_MISSING
        assert lookup_scores({}, customer_id=REF).state == SCORE_STATE_MISSING

    def test_state_2_pending_review_run(self):
        row = score_row(review_status="pending_review", reviewed_by=None)
        lookup = lookup_scores(row, customer_id=REF)
        assert lookup.unavailable_reason == SCORE_NOT_REVIEWED
        assert lookup.state == SCORE_STATE_PRESENT_NOT_APPROVED

    def test_state_2_rejected_run(self):
        lookup = lookup_scores(score_row(review_status="rejected"), customer_id=REF)
        assert lookup.state == SCORE_STATE_PRESENT_NOT_APPROVED

    def test_state_2_reviewed_but_usage_not_approved(self):
        lookup = lookup_scores(score_row(usage_approved=None), customer_id=REF)
        assert lookup.unavailable_reason == SCORE_USAGE_NOT_APPROVED
        assert lookup.state == SCORE_STATE_PRESENT_NOT_APPROVED

    def test_state_2_usage_revoked_after_being_approved(self):
        lookup = lookup_scores(score_row(usage_approved=False), customer_id=REF)
        assert lookup.state == SCORE_STATE_PRESENT_NOT_APPROVED

    @pytest.mark.parametrize("status", ["SCHEMA_PARTIAL", "INVALID_SCORE"])
    def test_state_2_contract_not_serving_is_not_confused_with_missing(self, status):
        # Inilah kasus yang dulu tampil "SCORE_ROW_MISSING": baris ada, kontrak belum lengkap.
        row = score_row(contract_status=status, churn_score=None)
        lookup = lookup_scores(row, customer_id=REF)
        assert lookup.unavailable_reason == SCORE_CONTRACT_NOT_SERVING
        assert lookup.state == SCORE_STATE_PRESENT_NOT_APPROVED
        assert lookup.ai_scores is None

    def test_contract_not_serving_wins_even_if_reviewed_and_approved(self):
        # Review/izin tidak bisa memperbaiki kontrak yang belum lengkap.
        row = score_row(contract_status="SCHEMA_PARTIAL", usage_approved=True)
        assert (
            lookup_scores(row, customer_id=REF).unavailable_reason
            == SCORE_CONTRACT_NOT_SERVING
        )

    def test_other_contract_status_values_do_not_block(self):
        row = score_row(contract_status="VALID")
        assert lookup_scores(row, customer_id=REF).state == SCORE_STATE_READY

    def test_incomplete_and_invalid_scores_are_present_not_approved(self):
        incomplete = lookup_scores(score_row(clv_amount=None), customer_id=REF)
        invalid = lookup_scores(score_row(churn_score=1.7), customer_id=REF)
        assert incomplete.state == SCORE_STATE_PRESENT_NOT_APPROVED
        assert invalid.state == SCORE_STATE_PRESENT_NOT_APPROVED

    def test_state_3_ready(self):
        lookup = lookup_scores(score_row(), customer_id=REF)
        assert lookup.usable
        assert lookup.state == SCORE_STATE_READY


class TestStateReachesApiAndRationale:
    def test_api_response_exposes_state_and_reason(self):
        out = run(row=score_row(usage_approved=None))
        resp = out.to_api_response(decision_id=1, status="proposed")
        assert resp["score_state"] == SCORE_STATE_PRESENT_NOT_APPROVED
        assert resp["score_unavailable_reason"] == SCORE_USAGE_NOT_APPROVED
        assert resp["expected_value"] is None  # tidak ada angka bila skor tidak dipakai

    @pytest.mark.parametrize("status", ["pending_review", "rejected"])
    def test_review_status_distinguishes_pending_from_rejected(self, status):
        # Kode alasannya sama (MODEL_RUN_NOT_REVIEWED); UI memakai status ini untuk teksnya.
        out = run(row=score_row(review_status=status, reviewed_by=None))
        resp = out.to_api_response(decision_id=1, status="proposed")
        assert resp["score_unavailable_reason"] == SCORE_NOT_REVIEWED
        assert resp["model_review_status"] == status

    def test_missing_row_has_no_review_status(self):
        resp = run(row={}).to_api_response(decision_id=None, status="accepted")
        assert resp["model_review_status"] is None

    def test_missing_row_state_in_api_and_rationale(self):
        out = run(row={})
        resp = out.to_api_response(decision_id=None, status="accepted")
        assert resp["score_state"] == SCORE_STATE_MISSING
        assert out.rationale_payload()["score_state"] == SCORE_STATE_MISSING

    def test_contract_not_serving_has_its_own_plain_sentence(self):
        out = run(row=score_row(contract_status="SCHEMA_PARTIAL"))
        assert "formatnya belum lengkap" in out.plain_rationale
        # bukan kalimat "belum ada" milik keadaan 1
        assert "Skor prediksi untuk pelanggan ini belum ada" not in out.plain_rationale

    def test_ready_state_and_serving_ready(self):
        out = run()
        resp = out.to_api_response(decision_id=1, status="proposed")
        assert resp["score_state"] == SCORE_STATE_READY
        assert resp["score_unavailable_reason"] is None
        assert resp["serving_ready"] is True

    def test_ready_score_does_not_mean_ready_decision_when_source_unconnected(self):
        out = evaluate_customer(
            customer_ref=REF,
            correlation_id=CORR,
            score_row=score_row(),
            consent_doc=None,  # belum tersambung
            complaint_tickets=[],
            contact_history=[],
            eligibility=eligibility(),
            product_suitability=ProductSuitability(),
            evaluation_date=NOW,
        )
        resp = out.to_api_response(decision_id=None, status="accepted")
        assert resp["score_state"] == SCORE_STATE_READY  # skornya sah
        assert resp["serving_ready"] is False  # tetapi keputusan belum siap
        assert resp["unavailable_sources"] == ["consent"]
        assert resp["expected_value"] is None

    def test_state_is_stored_in_decision_row_rationale(self):
        out = run(row=score_row(review_status="pending_review", reviewed_by=None))
        rationale = out.to_nba_decision_row(customer_db_id=1)["rationale"]
        assert rationale["score_state"] == SCORE_STATE_PRESENT_NOT_APPROVED
        assert rationale["score_unavailable_reason"] == SCORE_NOT_REVIEWED


class TestCustomerMismatch:
    """Skenario wajib "ID tidak cocok": skor milik pelanggan lain tidak boleh dipakai."""

    def test_score_of_another_customer_is_rejected(self):
        out = run(row=score_row(customer_id="ORANG-LAIN-999"))
        resp = out.to_api_response(decision_id=1, status="x")
        assert resp["score_unavailable_reason"] == SCORE_CUSTOMER_MISMATCH
        assert resp["score_state"] == SCORE_STATE_PRESENT_NOT_APPROVED
        assert resp["serving_ready"] is False
        assert resp["expected_value"] is None
        assert resp["selected_action"] == "NO_ACTION"

    @pytest.mark.parametrize("bad_id", [None, "", "gold-0001", " GOLD-0001"])
    def test_missing_or_non_identical_id_is_rejected_no_guessing(self, bad_id):
        lookup = lookup_scores(score_row(customer_id=bad_id), customer_id=REF)
        assert lookup.unavailable_reason == SCORE_CUSTOMER_MISMATCH
        assert lookup.ai_scores is None

    def test_message_does_not_leak_the_other_customers_id(self):
        out = run(row=score_row(customer_id="ORANG-LAIN-999"))
        assert "ORANG-LAIN-999" not in out.plain_rationale
        assert "ORANG-LAIN-999" not in str(out.rationale_payload()["technical_reason"])

    def test_matching_id_is_accepted(self):
        assert lookup_scores(score_row(), customer_id=REF).usable


class TestExpiredScoreIsNotReady:
    """Skor > 30 hari sejak cutoff: dulu tampil SCORE_READY + serving_ready (menyesatkan)."""

    @staticmethod
    def _row_aged(days: int):
        return score_row(score_generated_at=(NOW - timedelta(days=days)).isoformat())

    def test_exactly_30_days_is_still_ready(self):
        resp = run(row=self._row_aged(30)).to_api_response(decision_id=1, status="x")
        assert resp["score_state"] == SCORE_STATE_READY
        assert resp["serving_ready"] is True
        assert resp["expected_value"] is not None

    def test_31_days_is_present_not_approved_and_not_serving_ready(self):
        out = run(row=self._row_aged(31))
        resp = out.to_api_response(decision_id=1, status="x")
        assert resp["score_state"] == SCORE_STATE_PRESENT_NOT_APPROVED
        assert resp["score_unavailable_reason"] == SCORE_EXPIRED
        assert resp["serving_ready"] is False
        assert resp["degraded_input"] is True
        assert resp["expected_value"] is None
        assert resp["selected_action"] == "NO_ACTION"

    def test_expiry_is_flagged_even_when_other_sources_are_unconnected(self):
        out = evaluate_customer(
            customer_ref=REF,
            correlation_id=CORR,
            score_row=self._row_aged(40),
            consent_doc=None,
            complaint_tickets=[],
            contact_history=[],
            eligibility=eligibility(),
            product_suitability=ProductSuitability(),
            evaluation_date=NOW,
        )
        resp = out.to_api_response(decision_id=None, status="accepted")
        assert resp["score_unavailable_reason"] == SCORE_EXPIRED
        assert resp["score_state"] == SCORE_STATE_PRESENT_NOT_APPROVED

    def test_expired_reason_has_plain_sentence_without_numbers(self):
        out = run(row=self._row_aged(31))
        assert "kedaluwarsa" in out.plain_rationale
        assert "Rp" not in out.plain_rationale


def test_consent_helper_is_valid_for_ready_case():
    # Penjaga fixture: kasus READY memang memakai consent sah, bukan celah.
    assert consent_doc()["channels"]["email"]["opt_in"] is True
