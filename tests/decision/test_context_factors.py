"""
test_context_factors.py — Faktor konteks bisnis (alasan churn tambahan, bukan kontribusi model).

Yang dibuktikan:
  * MEMBERSHIP_EXPIRING mengikuti aturan RENEWAL_REMINDER yang sama (<= 15 hari, membership aktif);
  * UNRESOLVED_COMPLAINT hanya untuk tiket belum selesai milik pelanggan ini;
  * sumber None (belum tersambung) tidak menghasilkan faktor, [] (kosong) juga tidak;
  * NO_CROSS_CATEGORY tidak pernah muncul (tidak ada datanya);
  * faktor ikut rationale dan respons API, tetapi TIDAK mengubah aksi yang dipilih.

Jalankan: python -m pytest tests/decision/test_context_factors.py -v
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from services.decision.nba.context_factors import (
    MEMBERSHIP_EXPIRING,
    MEMBERSHIP_EXPIRING_WINDOW_DAYS,
    SOURCE_BUSINESS_RULE,
    UNRESOLVED_COMPLAINT,
    compute_context_factors,
)
from services.decision.nba.engine import EligibilityProfile, ProductSuitability
from services.decision.nba.serving import evaluate_customer
from services.decision.policy.suppression import ComplaintStatus, ComplaintTicket
from tests.decision.test_nba_serving import (
    CORR,
    NOW,
    REF,
    consent_doc,
    score_row,
)
from tests.decision.test_phase4_hardening import CID, _decide, _scores


def _elig(days: int, *, active: bool = True, customer: str = REF) -> EligibilityProfile:
    return EligibilityProfile(customer, 400, days, active, [], False, None)


def _ticket(status: ComplaintStatus, customer: str = REF) -> ComplaintTicket:
    return ComplaintTicket("T-1", customer, status, "SEVERE", NOW - timedelta(days=1))


def _codes(**kwargs) -> list[str]:
    return [f.code for f in compute_context_factors(customer_ref=REF, **kwargs)]


class TestMembershipExpiring:
    @pytest.mark.parametrize("days", [15, 10, 1, 0])
    def test_active_membership_within_window_is_flagged(self, days):
        assert _codes(eligibility=_elig(days), complaint_tickets=[]) == [
            MEMBERSHIP_EXPIRING
        ]

    @pytest.mark.parametrize("days", [16, 30, 365])
    def test_beyond_window_is_not_flagged(self, days):
        assert _codes(eligibility=_elig(days), complaint_tickets=[]) == []

    def test_inactive_membership_is_not_flagged(self):
        assert _codes(eligibility=_elig(5, active=False), complaint_tickets=[]) == []

    def test_other_customers_profile_is_ignored(self):
        assert (
            _codes(eligibility=_elig(5, customer="ORANG-LAIN"), complaint_tickets=[])
            == []
        )

    def test_window_matches_renewal_reminder_rule_in_engine(self):
        # Satu sumber kebenaran: faktor menyala tepat ketika RENEWAL_REMINDER eligible.
        # Segmen CHURNED dipakai karena aksi promosi lain diblokir di sana, sehingga
        # RENEWAL_REMINDER terpilih HANYA bila ia eligible (aksi lain tidak menutupinya).
        scores = _scores(
            lifecycle_stage="CHURNED",
            clv_tier="GOLD",
            churn_risk_band="MEDIUM",
            churn_score=0.4,
        )
        for days in (
            MEMBERSHIP_EXPIRING_WINDOW_DAYS,
            MEMBERSHIP_EXPIRING_WINDOW_DAYS + 1,
        ):
            profile = EligibilityProfile(CID, 400, days, True, [], False, None)
            renewal_eligible = (
                _decide(scores, eligibility=profile).selected_action_id
                == "RENEWAL_REMINDER"
            )
            flagged = bool(
                compute_context_factors(
                    customer_ref=CID, eligibility=profile, complaint_tickets=[]
                )
            )
            assert renewal_eligible == flagged, f"berbeda pada sisa {days} hari"


class TestUnresolvedComplaint:
    @pytest.mark.parametrize(
        "status",
        [
            ComplaintStatus.OPEN_SEVERE,
            ComplaintStatus.OPEN_MILD,
            ComplaintStatus.IN_PROGRESS,
        ],
    )
    def test_unresolved_statuses_are_flagged(self, status):
        assert _codes(eligibility=None, complaint_tickets=[_ticket(status)]) == [
            UNRESOLVED_COMPLAINT
        ]

    @pytest.mark.parametrize(
        "status", [ComplaintStatus.RESOLVED, ComplaintStatus.CLOSED]
    )
    def test_finished_tickets_are_not_flagged(self, status):
        assert _codes(eligibility=None, complaint_tickets=[_ticket(status)]) == []

    def test_other_customers_ticket_is_ignored(self):
        tickets = [_ticket(ComplaintStatus.OPEN_SEVERE, customer="ORANG-LAIN")]
        assert _codes(eligibility=None, complaint_tickets=tickets) == []


class TestSourcesAndOrder:
    def test_unconnected_sources_produce_nothing(self):
        assert _codes(eligibility=None, complaint_tickets=None) == []

    def test_connected_but_empty_sources_produce_nothing(self):
        assert _codes(eligibility=_elig(99), complaint_tickets=[]) == []

    def test_fixed_order_membership_then_complaint(self):
        codes = _codes(
            eligibility=_elig(3),
            complaint_tickets=[_ticket(ComplaintStatus.OPEN_MILD)],
        )
        assert codes == [MEMBERSHIP_EXPIRING, UNRESOLVED_COMPLAINT]

    def test_no_cross_category_is_never_produced(self):
        profile = EligibilityProfile(REF, 400, 3, True, ["GROCERY"], False, None)
        codes = _codes(
            eligibility=profile,
            complaint_tickets=[_ticket(ComplaintStatus.OPEN_SEVERE)],
        )
        assert "NO_CROSS_CATEGORY" not in codes

    def test_texts_are_neutral_and_source_is_business_rule(self):
        factors = compute_context_factors(
            customer_ref=REF,
            eligibility=_elig(3),
            complaint_tickets=[_ticket(ComplaintStatus.OPEN_SEVERE)],
        )
        for factor in factors:
            assert factor.source == SOURCE_BUSINESS_RULE
            assert "karena" not in factor.text.lower()
            assert REF not in factor.text


def _evaluate(*, elig, tickets, consent=True):
    return evaluate_customer(
        customer_ref=REF,
        correlation_id=CORR,
        score_row=score_row(),
        consent_doc=consent_doc() if consent else None,
        complaint_tickets=tickets,
        contact_history=[],
        eligibility=elig,
        product_suitability=ProductSuitability(),
        evaluation_date=NOW,
    )


class TestReachesRationaleAndApi:
    def test_api_and_rationale_expose_factors(self):
        out = _evaluate(elig=_elig(10), tickets=[_ticket(ComplaintStatus.OPEN_MILD)])
        resp = out.to_api_response(decision_id=1, status="proposed")
        assert [f["code"] for f in resp["context_factors"]] == [
            MEMBERSHIP_EXPIRING,
            UNRESOLVED_COMPLAINT,
        ]
        assert all(f["source"] == SOURCE_BUSINESS_RULE for f in resp["context_factors"])
        row = out.to_nba_decision_row(customer_db_id=1)
        assert row["rationale"]["context_factors"] == resp["context_factors"]

    def test_no_factors_when_nothing_applies(self):
        out = _evaluate(elig=_elig(99), tickets=[])
        assert out.to_api_response(decision_id=1, status="x")["context_factors"] == []

    def test_factor_is_computed_from_connected_source_even_if_another_is_not(self):
        out = _evaluate(
            elig=_elig(5), tickets=[], consent=False
        )  # consent belum tersambung
        resp = out.to_api_response(decision_id=None, status="accepted")
        assert resp["serving_ready"] is False
        assert [f["code"] for f in resp["context_factors"]] == [MEMBERSHIP_EXPIRING]

    def test_factors_do_not_change_the_selected_action(self):
        # Keputusan sama persis dengan dan tanpa tiket keluhan yang SUDAH selesai
        # (tiket selesai tidak memicu faktor maupun aturan keluhan).
        base = _evaluate(elig=_elig(99), tickets=[])
        with_closed = _evaluate(
            elig=_elig(99), tickets=[_ticket(ComplaintStatus.CLOSED)]
        )
        assert base.selected_action_id == with_closed.selected_action_id
        assert base.to_api_response(decision_id=1, status="x")["context_factors"] == []

    def test_factors_never_create_money_values(self):
        out = _evaluate(elig=_elig(3), tickets=[_ticket(ComplaintStatus.OPEN_SEVERE)])
        for factor in out.to_api_response(decision_id=1, status="x")["context_factors"]:
            assert "Rp" not in factor["text"]
