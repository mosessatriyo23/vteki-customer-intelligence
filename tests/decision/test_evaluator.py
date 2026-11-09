"""
test_evaluator.py — Test evaluator 5 gerbang independen (Minggu 6).

Jalankan: python -m pytest tests/decision/test_evaluator.py -v
"""

from datetime import datetime, timedelta

import pytest

from services.decision.nba.engine import (
    AIScores,
    EligibilityProfile,
    ProductSuitability,
)
from services.decision.nba.evaluator import (
    ALL_GATES,
    GATE_BUSINESS_ELIGIBILITY,
    GATE_CONTACT_POLICY,
    GATE_CUSTOMER_CONSENT,
    GATE_ML_SCORE,
    GATE_PRODUCT_SUITABILITY,
    check_business_eligibility,
    check_product_suitability,
    evaluate_business_eligibility_gate,
    evaluate_complaint_block,
    evaluate_consent_gate,
    evaluate_contact_policy_gate,
    evaluate_five_gates,
    evaluate_ml_score_gate,
    evaluate_product_suitability_gate,
)
from services.decision.policy.fatigue import ContactRecord, check_frequency_cap
from services.decision.policy.suppression import (
    ComplaintStatus,
    ComplaintTicket,
    CustomerConsent,
    check_suppression,
)

CID = "CUST-EVAL-001"
NOW = datetime(2026, 11, 5, 10, 0, 0)


def _scores(**kw) -> AIScores:
    base = dict(
        customer_id=CID,
        churn_score=0.3,
        churn_risk_band="LOW",
        propensity_purchase=0.8,
        propensity_renew=0.6,
        clv_amount=2_000_000.0,
        clv_tier="GOLD",
        lifecycle_stage="ACTIVE",
        score_generated_at=NOW - timedelta(days=2),
    )
    base.update(kw)
    return AIScores(**base)


def _elig(**kw) -> EligibilityProfile:
    base = dict(
        customer_id=CID,
        tenure_days=200,
        membership_days_remaining=100,
        has_active_membership=True,
    )
    base.update(kw)
    return EligibilityProfile(**base)


def _supp(complaint=False, opt_out=False):
    tickets = (
        [ComplaintTicket("T1", CID, ComplaintStatus.OPEN_SEVERE, "SEVERE", NOW)]
        if complaint
        else []
    )
    return check_suppression(CID, CustomerConsent(CID, global_opt_out=opt_out), tickets)


def _fatigue(n: int):
    hist = [
        ContactRecord(CID, "CROSS_SELL", "email", NOW - timedelta(days=i + 1))
        for i in range(n)
    ]
    return check_frequency_cap(CID, hist, NOW)


class TestMlScoreGate:
    def test_fresh_passes(self):
        g = evaluate_ml_score_gate(scores_expired=False)
        assert g.passed and g.gate == GATE_ML_SCORE and g.k07_category == "VALIDITY"

    def test_expired_fails(self):
        g = evaluate_ml_score_gate(scores_expired=True)
        assert not g.passed and g.status == "SCORE_EXPIRED"

    def test_missing_fails(self):
        g = evaluate_ml_score_gate(scores_expired=True, scores_missing=True)
        assert not g.passed and g.details["scores_missing"] is True


class TestBusinessEligibilityGate:
    def test_cross_sell_active_passes(self):
        assert check_business_eligibility("CROSS_SELL", _scores(), _elig()) is None
        assert evaluate_business_eligibility_gate(
            "CROSS_SELL", _scores(), _elig()
        ).passed

    def test_cross_sell_new_lifecycle_fails(self):
        g = evaluate_business_eligibility_gate(
            "CROSS_SELL", _scores(lifecycle_stage="NEW"), _elig()
        )
        assert not g.passed and g.status == "NOT_ELIGIBLE" and g.reason

    def test_upsell_requires_tenure_60(self):
        assert check_business_eligibility("UPSELL", _scores(), _elig(tenure_days=59))
        assert (
            check_business_eligibility("UPSELL", _scores(), _elig(tenure_days=60))
            is None
        )

    def test_renewal_reminder_window_15_days(self):
        assert (
            check_business_eligibility(
                "RENEWAL_REMINDER", _scores(), _elig(membership_days_remaining=15)
            )
            is None
        )
        assert check_business_eligibility(
            "RENEWAL_REMINDER", _scores(), _elig(membership_days_remaining=16)
        )

    def test_relationship_manager_needs_platinum_and_high_churn(self):
        ok = _scores(clv_tier="PLATINUM", churn_risk_band="VERY_HIGH")
        assert (
            check_business_eligibility("RELATIONSHIP_MANAGER_CONTACT", ok, _elig())
            is None
        )
        no = _scores(clv_tier="GOLD", churn_risk_band="VERY_HIGH")
        assert check_business_eligibility("RELATIONSHIP_MANAGER_CONTACT", no, _elig())

    def test_win_back_blocked_when_offer_already_active(self):
        s = _scores(lifecycle_stage="DORMANT", clv_tier="GOLD", churn_risk_band="HIGH")
        assert check_business_eligibility("WIN_BACK_OFFER", s, _elig()) is None
        assert check_business_eligibility(
            "WIN_BACK_OFFER", s, _elig(has_active_win_back_offer=True)
        )

    def test_unknown_action_without_rule_is_eligible(self):
        assert (
            check_business_eligibility("ACTION_TANPA_ATURAN", _scores(), _elig())
            is None
        )


class TestServiceReminderRule:
    """Keputusan tim: ACTIVE/LOYAL + jadwal habis pakai <= 7 hari; data kosong = tidak eligible."""

    @pytest.mark.parametrize("days", [-3, 0, 1, 7])
    def test_within_window_is_eligible(self, days):
        e = _elig(days_until_replenishment=days)
        assert check_business_eligibility("SERVICE_REMINDER", _scores(), e) is None

    @pytest.mark.parametrize("days", [8, 30, 365])
    def test_beyond_window_is_not_eligible(self, days):
        e = _elig(days_until_replenishment=days)
        assert check_business_eligibility("SERVICE_REMINDER", _scores(), e)

    def test_missing_schedule_data_is_not_eligible_fail_closed(self):
        assert check_business_eligibility("SERVICE_REMINDER", _scores(), _elig())

    @pytest.mark.parametrize("lifecycle", ["ACTIVE", "LOYAL"])
    def test_active_and_loyal_allowed(self, lifecycle):
        s = _scores(lifecycle_stage=lifecycle)
        e = _elig(days_until_replenishment=3)
        assert check_business_eligibility("SERVICE_REMINDER", s, e) is None

    @pytest.mark.parametrize(
        "lifecycle",
        [
            "CHURNED",
            "DORMANT",
            "AT_RISK",
            "NEW",
            "REACTIVATED",
            "OCCASIONAL",
            "NEVER_TRANSACTED",
        ],
    )
    def test_other_lifecycles_excluded(self, lifecycle):
        s = _scores(lifecycle_stage=lifecycle)
        e = _elig(days_until_replenishment=3)
        assert check_business_eligibility("SERVICE_REMINDER", s, e)

    def test_window_constant_is_seven_days(self):
        from services.decision.nba.evaluator import SERVICE_REMINDER_WINDOW_DAYS

        assert SERVICE_REMINDER_WINDOW_DAYS == 7


class TestConsentGate:
    def test_clear_passes(self):
        assert evaluate_consent_gate(_supp()).passed

    def test_opt_out_fails(self):
        g = evaluate_consent_gate(_supp(opt_out=True))
        assert not g.passed and g.status == "OPT_OUT_SUPPRESSED"
        assert g.k07_category == "SUPPRESSION"

    def test_complaint_does_not_fail_consent_gate(self):
        assert evaluate_consent_gate(_supp(complaint=True)).passed


class TestContactPolicyGate:
    """Gerbang 4 = HANYA frequency cap (Requirement_Capstone Bab 3 baris 4)."""

    def test_clear_passes(self):
        assert evaluate_contact_policy_gate(_fatigue(1)).passed

    def test_frequency_cap_fails(self):
        g = evaluate_contact_policy_gate(_fatigue(2))
        assert not g.passed and g.status == "FREQ_CAP_SUPPRESSED"
        assert g.details["reason_code"] == "FREQ_CAP_SUPPRESSED"
        assert g.k07_category == "FATIGUE"

    def test_frequency_below_cap_passes_with_count(self):
        g = evaluate_contact_policy_gate(_fatigue(0))
        assert g.passed and g.details["contact_count_in_window"] == 0


class TestComplaintBelongsToBusinessEligibility:
    """Keluhan OPEN_SEVERE_COMPLAINT = gerbang 2 (Bab 3 baris 2), bukan gerbang 4."""

    def test_complaint_block_fails_gate_2(self):
        g = evaluate_complaint_block(_supp(complaint=True))
        assert g.gate == GATE_BUSINESS_ELIGIBILITY and not g.passed
        assert g.status == "COMPLAINT_SUPPRESSED"
        assert g.details["reason_code"] == "EXCL_OPEN_SEVERE_COMPLAINT"

    def test_no_complaint_passes(self):
        assert evaluate_complaint_block(_supp()).passed

    def test_opt_out_is_not_a_complaint_block(self):
        assert evaluate_complaint_block(_supp(opt_out=True)).passed

    def test_promo_action_blocked_when_complaint_active(self):
        g = evaluate_business_eligibility_gate(
            "CROSS_SELL", _scores(), _elig(), _supp(complaint=True)
        )
        assert not g.passed and g.status == "COMPLAINT_SUPPRESSED"
        assert g.details["action_id"] == "CROSS_SELL"

    def test_complaint_resolution_passes_when_complaint_active(self):
        g = evaluate_business_eligibility_gate(
            "COMPLAINT_RESOLUTION", _scores(), _elig(), _supp(complaint=True)
        )
        assert g.passed

    def test_complaint_resolution_fails_without_complaint(self):
        g = evaluate_business_eligibility_gate(
            "COMPLAINT_RESOLUTION", _scores(), _elig(), _supp()
        )
        assert not g.passed

    def test_gate_without_suppression_result_still_works(self):
        assert evaluate_business_eligibility_gate(
            "CROSS_SELL", _scores(), _elig()
        ).passed


class TestProductSuitabilityGate:
    def test_empty_lists_pass(self):
        assert evaluate_product_suitability_gate(
            "CROSS_SELL", ProductSuitability()
        ).passed

    def test_not_in_available_list(self):
        ps = ProductSuitability(available_action_ids=["UPSELL"])
        g = evaluate_product_suitability_gate("CROSS_SELL", ps)
        assert not g.passed and g.status == "PRODUCT_UNAVAILABLE"

    def test_in_unsuitable_list(self):
        ps = ProductSuitability(unsuitable_action_ids=["CROSS_SELL"])
        g = evaluate_product_suitability_gate("CROSS_SELL", ps)
        assert not g.passed and g.status == "PRODUCT_UNSUITABLE"
        assert check_product_suitability("UPSELL", ps) is None


class TestFiveGates:
    def test_all_pass_returns_five_in_order(self):
        gates = evaluate_five_gates(
            "CROSS_SELL",
            _scores(),
            _elig(),
            ProductSuitability(),
            _supp(),
            _fatigue(0),
            scores_expired=False,
        )
        assert [g.gate for g in gates] == list(ALL_GATES)
        assert all(g.passed for g in gates)

    def test_gates_are_independent(self):
        """Satu gerbang gagal tidak menghentikan evaluasi gerbang lain."""
        gates = evaluate_five_gates(
            "CROSS_SELL",
            _scores(lifecycle_stage="NEW"),
            _elig(),
            ProductSuitability(unsuitable_action_ids=["CROSS_SELL"]),
            _supp(opt_out=True),
            _fatigue(2),
            scores_expired=True,
        )
        by = {g.gate: g for g in gates}
        assert len(gates) == 5
        assert not by[GATE_ML_SCORE].passed
        assert not by[GATE_BUSINESS_ELIGIBILITY].passed
        assert not by[GATE_CUSTOMER_CONSENT].passed
        assert not by[GATE_CONTACT_POLICY].passed
        assert not by[GATE_PRODUCT_SUITABILITY].passed

    @pytest.mark.parametrize("gate", ALL_GATES)
    def test_every_gate_has_k07_category(self, gate):
        gates = evaluate_five_gates(
            "CROSS_SELL",
            _scores(),
            _elig(),
            ProductSuitability(),
            _supp(),
            _fatigue(0),
            scores_expired=False,
        )
        assert {g.gate: g for g in gates}[gate].k07_category in {
            "VALIDITY",
            "ELIGIBILITY",
            "SUPPRESSION",
            "FATIGUE",
            "SUITABILITY",
        }


class TestComplaintResolutionNotNormalCandidate:
    def test_not_eligible_as_regular_candidate(self):
        """COMPLAINT_RESOLUTION hanya lewat jalur komplain aktif, bukan kandidat EV."""
        assert check_business_eligibility("COMPLAINT_RESOLUTION", _scores(), _elig())
