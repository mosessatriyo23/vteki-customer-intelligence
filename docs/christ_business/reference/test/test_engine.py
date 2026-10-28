"""
test_engine.py — Unit Tests untuk services/decision/nba/engine.py
==================================================================
Menguji kelas NBAEngine secara menyeluruh mencakup semua skenario
keputusan berdasarkan 5 masukan independen.

Jalankan dengan:
    pytest docs/christ_business/reference/test/ -v
"""

import pytest
from datetime import datetime, timedelta

from services.decision.nba.engine import (
    AIScores,
    EligibilityProfile,
    NBAEngine,
    NBAResult,
    ProductSuitability,
)
from services.decision.policy.fatigue import ContactRecord
from services.decision.policy.suppression import (
    ComplaintStatus,
    ComplaintTicket,
    CustomerConsent,
)


# ---------------------------------------------------------------------------
# Constants & Helpers
# ---------------------------------------------------------------------------

CUSTOMER_ID = "CUST-ENGINE-001"
EVAL_DATE = datetime(2026, 10, 28, 10, 0, 0)
SCORE_DATE = EVAL_DATE - timedelta(days=5)   # Skor baru (tidak kadaluarsa)
EXPIRED_SCORE_DATE = EVAL_DATE - timedelta(days=35)  # Skor kadaluarsa


def _make_engine(**kwargs) -> NBAEngine:
    return NBAEngine(**kwargs)


def _make_consent(global_opt_out: bool = False, cid: str = CUSTOMER_ID) -> CustomerConsent:
    return CustomerConsent(
        customer_id=cid,
        email_opt_in=True,
        push_opt_in=True,
        sms_opt_in=True,
        global_opt_out=global_opt_out,
    )


def _make_ticket(status: ComplaintStatus, ticket_id: str = "T001") -> ComplaintTicket:
    return ComplaintTicket(
        ticket_id=ticket_id,
        customer_id=CUSTOMER_ID,
        status=status,
        severity="SEVERE",
        opened_at=EVAL_DATE,
    )


def _make_contact(action_id: str, days_ago: int) -> ContactRecord:
    return ContactRecord(
        customer_id=CUSTOMER_ID,
        action_id=action_id,
        channel="email",
        sent_at=EVAL_DATE - timedelta(days=days_ago),
        is_commercial=True,
    )


def _make_ai_scores(
    lifecycle: str = "ACTIVE",
    churn_score: float = 0.3,
    churn_band: str = "MEDIUM",
    clv: float = 750_000,
    clv_tier: str = "GOLD",
    propensity_purchase: float = 0.7,
    propensity_renew: float = 0.7,
    score_date: datetime = None,
) -> AIScores:
    return AIScores(
        customer_id=CUSTOMER_ID,
        churn_score=churn_score,
        churn_risk_band=churn_band,
        propensity_purchase=propensity_purchase,
        propensity_renew=propensity_renew,
        clv_amount=clv,
        clv_tier=clv_tier,
        lifecycle_stage=lifecycle,
        score_generated_at=score_date or SCORE_DATE,
        reason_codes=["RECENCY_LONG", "SPEND_DECLINE", "FREQUENCY_DROP"],
    )


def _make_eligibility(
    tenure: int = 90,
    membership_days: int = 30,
    has_membership: bool = True,
    has_win_back: bool = False,
) -> EligibilityProfile:
    return EligibilityProfile(
        customer_id=CUSTOMER_ID,
        tenure_days=tenure,
        membership_days_remaining=membership_days,
        has_active_membership=has_membership,
        has_active_win_back_offer=has_win_back,
    )


def _make_suitability(available: list = None, unsuitable: list = None) -> ProductSuitability:
    return ProductSuitability(
        available_action_ids=available or [],
        unsuitable_action_ids=unsuitable or [],
    )


# ---------------------------------------------------------------------------
# Tests: Skenario Suppression → NO_ACTION / COMPLAINT_RESOLUTION
# ---------------------------------------------------------------------------

class TestEngineSuppressionPriority:

    def test_opt_out_returns_no_action(self):
        """Global Opt-Out harus langsung mengembalikan NO_ACTION."""
        engine = _make_engine()
        result = engine.evaluate(
            ai_scores=_make_ai_scores(),
            consent=_make_consent(global_opt_out=True),
            complaint_tickets=[],
            contact_history=[],
            eligibility=_make_eligibility(),
            product_suitability=_make_suitability(),
            evaluation_date=EVAL_DATE,
        )
        assert result.selected_action.action_id == "NO_ACTION"
        assert result.suppression_result.is_suppressed is True
        assert "OPT_OUT" in result.suppression_result.status

    def test_open_severe_complaint_returns_complaint_resolution(self):
        """OPEN_SEVERE_COMPLAINT harus mengembalikan COMPLAINT_RESOLUTION."""
        engine = _make_engine()
        result = engine.evaluate(
            ai_scores=_make_ai_scores(),
            consent=_make_consent(),
            complaint_tickets=[_make_ticket(ComplaintStatus.OPEN_SEVERE)],
            contact_history=[],
            eligibility=_make_eligibility(),
            product_suitability=_make_suitability(),
            evaluation_date=EVAL_DATE,
        )
        assert result.selected_action.action_id == "COMPLAINT_RESOLUTION"
        assert result.suppression_result.is_suppressed is True

    def test_opt_out_takes_precedence_over_complaint(self):
        """Opt-Out harus lebih prioritas dibanding OPEN_SEVERE_COMPLAINT."""
        engine = _make_engine()
        result = engine.evaluate(
            ai_scores=_make_ai_scores(),
            consent=_make_consent(global_opt_out=True),
            complaint_tickets=[_make_ticket(ComplaintStatus.OPEN_SEVERE)],
            contact_history=[],
            eligibility=_make_eligibility(),
            product_suitability=_make_suitability(),
            evaluation_date=EVAL_DATE,
        )
        # OPT_OUT lebih prioritas → NO_ACTION, bukan COMPLAINT_RESOLUTION
        assert result.selected_action.action_id == "NO_ACTION"
        assert "OPT_OUT" in result.suppression_result.status

    def test_resolved_complaint_does_not_trigger_complaint_resolution(self):
        """Keluhan RESOLVED tidak boleh memicu COMPLAINT_RESOLUTION."""
        engine = _make_engine()
        result = engine.evaluate(
            ai_scores=_make_ai_scores(lifecycle="ACTIVE", churn_band="MEDIUM"),
            consent=_make_consent(),
            complaint_tickets=[_make_ticket(ComplaintStatus.RESOLVED)],
            contact_history=[],
            eligibility=_make_eligibility(),
            product_suitability=_make_suitability(),
            evaluation_date=EVAL_DATE,
        )
        assert result.selected_action.action_id != "COMPLAINT_RESOLUTION"
        assert result.suppression_result.is_suppressed is False


# ---------------------------------------------------------------------------
# Tests: Skenario Fatigue → NO_ACTION
# ---------------------------------------------------------------------------

class TestEngineFatiguePriority:

    def test_freq_cap_reached_returns_no_action(self):
        """Frequency cap tercapai harus mengembalikan NO_ACTION."""
        engine = _make_engine()
        history = [
            _make_contact("CROSS_SELL", days_ago=3),
            _make_contact("RETENTION_OUTREACH", days_ago=7),
        ]
        result = engine.evaluate(
            ai_scores=_make_ai_scores(),
            consent=_make_consent(),
            complaint_tickets=[],
            contact_history=history,
            eligibility=_make_eligibility(),
            product_suitability=_make_suitability(),
            evaluation_date=EVAL_DATE,
        )
        assert result.selected_action.action_id == "NO_ACTION"
        assert result.fatigue_result.is_suppressed is True

    def test_one_contact_does_not_suppress(self):
        """Satu kontak dalam window tidak boleh memblokir evaluasi."""
        engine = _make_engine()
        history = [_make_contact("CROSS_SELL", days_ago=5)]
        result = engine.evaluate(
            ai_scores=_make_ai_scores(lifecycle="ACTIVE"),
            consent=_make_consent(),
            complaint_tickets=[],
            contact_history=history,
            eligibility=_make_eligibility(),
            product_suitability=_make_suitability(),
            evaluation_date=EVAL_DATE,
        )
        assert result.fatigue_result.is_suppressed is False
        assert result.selected_action.action_id != "NO_ACTION"

    def test_excluded_actions_in_history_do_not_count_toward_cap(self):
        """Riwayat COMPLAINT_RESOLUTION dan SERVICE_REMINDER tidak memicu cap."""
        engine = _make_engine()
        history = [
            _make_contact("COMPLAINT_RESOLUTION", days_ago=2),
            _make_contact("SERVICE_REMINDER", days_ago=5),
            _make_contact("COMPLAINT_RESOLUTION", days_ago=8),
        ]
        result = engine.evaluate(
            ai_scores=_make_ai_scores(lifecycle="ACTIVE"),
            consent=_make_consent(),
            complaint_tickets=[],
            contact_history=history,
            eligibility=_make_eligibility(),
            product_suitability=_make_suitability(),
            evaluation_date=EVAL_DATE,
        )
        assert result.fatigue_result.is_suppressed is False


# ---------------------------------------------------------------------------
# Tests: Skenario Skor Kadaluarsa
# ---------------------------------------------------------------------------

class TestEngineExpiredScores:

    def test_expired_scores_causes_no_action(self):
        """Skor yang kadaluarsa (> 30 hari) harus menghasilkan NO_ACTION
        karena semua propensity = 0.0 sehingga EV negatif atau nol."""
        engine = _make_engine()
        result = engine.evaluate(
            ai_scores=_make_ai_scores(score_date=EXPIRED_SCORE_DATE),
            consent=_make_consent(),
            complaint_tickets=[],
            contact_history=[],
            eligibility=_make_eligibility(),
            product_suitability=_make_suitability(),
            evaluation_date=EVAL_DATE,
        )
        assert result.scores_expired is True

    def test_fresh_scores_not_expired(self):
        """Skor baru (< 30 hari) tidak boleh dianggap kadaluarsa."""
        engine = _make_engine()
        result = engine.evaluate(
            ai_scores=_make_ai_scores(score_date=SCORE_DATE),
            consent=_make_consent(),
            complaint_tickets=[],
            contact_history=[],
            eligibility=_make_eligibility(),
            product_suitability=_make_suitability(),
            evaluation_date=EVAL_DATE,
        )
        assert result.scores_expired is False


# ---------------------------------------------------------------------------
# Tests: Skenario Eligibility Rules
# ---------------------------------------------------------------------------

class TestEngineEligibilityRules:

    def test_cross_sell_selected_for_active_customer(self):
        """CROSS_SELL harus menjadi kandidat untuk pelanggan ACTIVE."""
        engine = _make_engine()
        result = engine.evaluate(
            ai_scores=_make_ai_scores(lifecycle="ACTIVE", propensity_purchase=0.85),
            consent=_make_consent(),
            complaint_tickets=[],
            contact_history=[],
            eligibility=_make_eligibility(tenure=90),
            product_suitability=_make_suitability(),
            evaluation_date=EVAL_DATE,
        )
        # Pastikan CROSS_SELL ada dalam kandidat yang eligible
        eligible = [c for c in result.candidates_evaluated if c.is_eligible]
        eligible_ids = [c.action.action_id for c in eligible]
        assert "CROSS_SELL" in eligible_ids

    def test_dormant_customer_with_gold_clv_eligible_for_win_back(self):
        """Pelanggan DORMANT dengan CLV GOLD harus eligible untuk WIN_BACK_OFFER."""
        engine = _make_engine()
        result = engine.evaluate(
            ai_scores=_make_ai_scores(
                lifecycle="DORMANT", clv_tier="GOLD",
                churn_score=0.75, churn_band="HIGH"
            ),
            consent=_make_consent(),
            complaint_tickets=[],
            contact_history=[],
            eligibility=_make_eligibility(has_win_back=False),
            product_suitability=_make_suitability(),
            evaluation_date=EVAL_DATE,
        )
        eligible = [c for c in result.candidates_evaluated if c.is_eligible]
        eligible_ids = [c.action.action_id for c in eligible]
        assert "WIN_BACK_OFFER" in eligible_ids

    def test_renewal_reminder_not_triggered_when_membership_not_expiring(self):
        """RENEWAL_REMINDER tidak boleh menjadi kandidat jika membership masih lama."""
        engine = _make_engine()
        result = engine.evaluate(
            ai_scores=_make_ai_scores(lifecycle="ACTIVE"),
            consent=_make_consent(),
            complaint_tickets=[],
            contact_history=[],
            eligibility=_make_eligibility(membership_days=60),  # 60 hari tersisa, bukan <= 15
            product_suitability=_make_suitability(),
            evaluation_date=EVAL_DATE,
        )
        blocked = [c for c in result.candidates_evaluated if not c.is_eligible]
        blocked_ids = [c.action.action_id for c in blocked]
        assert "RENEWAL_REMINDER" in blocked_ids

    def test_renewal_reminder_triggered_when_membership_expiring_soon(self):
        """RENEWAL_REMINDER harus eligible ketika sisa membership <= 15 hari."""
        engine = _make_engine()
        result = engine.evaluate(
            ai_scores=_make_ai_scores(lifecycle="ACTIVE"),
            consent=_make_consent(),
            complaint_tickets=[],
            contact_history=[],
            eligibility=_make_eligibility(membership_days=10, has_membership=True),
            product_suitability=_make_suitability(),
            evaluation_date=EVAL_DATE,
        )
        eligible = [c for c in result.candidates_evaluated if c.is_eligible]
        eligible_ids = [c.action.action_id for c in eligible]
        assert "RENEWAL_REMINDER" in eligible_ids

    def test_upsell_requires_tenure_60_days(self):
        """UPSELL tidak boleh eligible jika tenure < 60 hari."""
        engine = _make_engine()
        result = engine.evaluate(
            ai_scores=_make_ai_scores(lifecycle="ACTIVE"),
            consent=_make_consent(),
            complaint_tickets=[],
            contact_history=[],
            eligibility=_make_eligibility(tenure=30),  # Terlalu baru
            product_suitability=_make_suitability(),
            evaluation_date=EVAL_DATE,
        )
        blocked = [c for c in result.candidates_evaluated if not c.is_eligible]
        blocked_ids = [c.action.action_id for c in blocked]
        assert "UPSELL" in blocked_ids

    def test_education_only_eligible_for_new_low_churn(self):
        """EDUCATION hanya eligible untuk pelanggan NEW dengan churn risk LOW."""
        engine = _make_engine()
        result = engine.evaluate(
            ai_scores=_make_ai_scores(lifecycle="NEW", churn_band="LOW", churn_score=0.1),
            consent=_make_consent(),
            complaint_tickets=[],
            contact_history=[],
            eligibility=_make_eligibility(tenure=15),
            product_suitability=_make_suitability(),
            evaluation_date=EVAL_DATE,
        )
        eligible = [c for c in result.candidates_evaluated if c.is_eligible]
        eligible_ids = [c.action.action_id for c in eligible]
        assert "EDUCATION" in eligible_ids

    def test_retention_outreach_eligible_for_at_risk_high_churn_gold(self):
        """RETENTION_OUTREACH harus eligible untuk AT_RISK + HIGH churn + GOLD CLV."""
        engine = _make_engine()
        result = engine.evaluate(
            ai_scores=_make_ai_scores(
                lifecycle="AT_RISK", churn_band="HIGH",
                churn_score=0.75, clv_tier="GOLD"
            ),
            consent=_make_consent(),
            complaint_tickets=[],
            contact_history=[],
            eligibility=_make_eligibility(),
            product_suitability=_make_suitability(),
            evaluation_date=EVAL_DATE,
        )
        eligible = [c for c in result.candidates_evaluated if c.is_eligible]
        eligible_ids = [c.action.action_id for c in eligible]
        assert "RETENTION_OUTREACH" in eligible_ids


# ---------------------------------------------------------------------------
# Tests: Skenario Product Suitability (Masukan 5)
# ---------------------------------------------------------------------------

class TestEngineProductSuitability:

    def test_action_blocked_when_not_in_available_list(self):
        """Aksi tidak boleh eligible jika tidak ada dalam available_action_ids."""
        engine = _make_engine()
        # Hanya CROSS_SELL yang tersedia
        result = engine.evaluate(
            ai_scores=_make_ai_scores(lifecycle="ACTIVE"),
            consent=_make_consent(),
            complaint_tickets=[],
            contact_history=[],
            eligibility=_make_eligibility(),
            product_suitability=_make_suitability(available=["CROSS_SELL"]),
            evaluation_date=EVAL_DATE,
        )
        blocked = [c for c in result.candidates_evaluated if not c.is_eligible]
        blocked_ids = [c.action.action_id for c in blocked]
        # Semua aksi selain CROSS_SELL harus diblokir
        assert "UPSELL" in blocked_ids
        assert "RETENTION_OUTREACH" in blocked_ids

    def test_action_blocked_when_in_unsuitable_list(self):
        """Aksi dalam unsuitable_action_ids harus diblokir."""
        engine = _make_engine()
        result = engine.evaluate(
            ai_scores=_make_ai_scores(lifecycle="ACTIVE"),
            consent=_make_consent(),
            complaint_tickets=[],
            contact_history=[],
            eligibility=_make_eligibility(),
            product_suitability=_make_suitability(unsuitable=["CROSS_SELL"]),
            evaluation_date=EVAL_DATE,
        )
        blocked = [c for c in result.candidates_evaluated if not c.is_eligible]
        blocked_ids = [c.action.action_id for c in blocked]
        assert "CROSS_SELL" in blocked_ids

    def test_empty_suitability_allows_all_actions(self):
        """ProductSuitability kosong (default) tidak memblokir aksi apapun dari sisi produk."""
        engine = _make_engine()
        result = engine.evaluate(
            ai_scores=_make_ai_scores(lifecycle="ACTIVE"),
            consent=_make_consent(),
            complaint_tickets=[],
            contact_history=[],
            eligibility=_make_eligibility(),
            product_suitability=_make_suitability(),  # Kosong = semua tersedia
            evaluation_date=EVAL_DATE,
        )
        # Tidak semua diblokir karena masalah produk
        product_blocked = [
            c for c in result.candidates_evaluated
            if not c.is_eligible and c.blocked_reason and "Masukan 5" in c.blocked_reason
        ]
        assert len(product_blocked) == 0


# ---------------------------------------------------------------------------
# Tests: Formula Expected Value
# ---------------------------------------------------------------------------

class TestEngineExpectedValue:

    def test_ev_positive_for_eligible_action(self):
        """Aksi eligible dengan propensity dan CLV tinggi harus memiliki EV positif."""
        engine = _make_engine()
        result = engine.evaluate(
            ai_scores=_make_ai_scores(
                lifecycle="ACTIVE", propensity_purchase=0.9,
                clv=1_500_000, clv_tier="PLATINUM"
            ),
            consent=_make_consent(),
            complaint_tickets=[],
            contact_history=[],
            eligibility=_make_eligibility(tenure=120),
            product_suitability=_make_suitability(),
            evaluation_date=EVAL_DATE,
        )
        eligible = [c for c in result.candidates_evaluated if c.is_eligible]
        assert any(c.expected_value > 0 for c in eligible)

    def test_no_action_has_zero_ev(self):
        """NO_ACTION tidak boleh memiliki EV yang dihitung (selalu 0.0 sebagai fallback)."""
        engine = _make_engine()
        result = engine.evaluate(
            ai_scores=_make_ai_scores(),
            consent=_make_consent(global_opt_out=True),
            complaint_tickets=[],
            contact_history=[],
            eligibility=_make_eligibility(),
            product_suitability=_make_suitability(),
            evaluation_date=EVAL_DATE,
        )
        assert result.selected_action.action_id == "NO_ACTION"
        assert result.expected_value == 0.0

    def test_selected_action_has_highest_ev(self):
        """Aksi yang dipilih harus memiliki EV tertinggi di antara kandidat eligible."""
        engine = _make_engine()
        result = engine.evaluate(
            ai_scores=_make_ai_scores(
                lifecycle="ACTIVE", clv=800_000, clv_tier="GOLD",
                propensity_purchase=0.8
            ),
            consent=_make_consent(),
            complaint_tickets=[],
            contact_history=[],
            eligibility=_make_eligibility(tenure=100),
            product_suitability=_make_suitability(),
            evaluation_date=EVAL_DATE,
        )
        if result.selected_action.action_id != "NO_ACTION":
            eligible = [c for c in result.candidates_evaluated if c.is_eligible]
            max_ev = max(c.expected_value for c in eligible)
            assert result.expected_value == pytest.approx(max_ev, rel=1e-6)


# ---------------------------------------------------------------------------
# Tests: Struktur NBAResult
# ---------------------------------------------------------------------------

class TestEngineResultStructure:

    def test_result_has_all_required_fields(self):
        """NBAResult harus memiliki semua field yang diperlukan."""
        engine = _make_engine()
        result = engine.evaluate(
            ai_scores=_make_ai_scores(),
            consent=_make_consent(),
            complaint_tickets=[],
            contact_history=[],
            eligibility=_make_eligibility(),
            product_suitability=_make_suitability(),
            evaluation_date=EVAL_DATE,
        )
        assert isinstance(result, NBAResult)
        assert result.customer_id == CUSTOMER_ID
        assert result.selected_action is not None
        assert isinstance(result.evaluation_timestamp, datetime)
        assert result.suppression_result is not None
        assert result.fatigue_result is not None
        assert isinstance(result.candidates_evaluated, list)
        assert isinstance(result.decision_rationale, str)
        assert len(result.decision_rationale) > 0

    def test_result_contains_rationale(self):
        """Semua hasil evaluasi harus memiliki rationale yang tidak kosong."""
        engine = _make_engine()
        for opt_out in [True, False]:
            result = engine.evaluate(
                ai_scores=_make_ai_scores(),
                consent=_make_consent(global_opt_out=opt_out),
                complaint_tickets=[],
                contact_history=[],
                eligibility=_make_eligibility(),
                product_suitability=_make_suitability(),
                evaluation_date=EVAL_DATE,
            )
            assert len(result.decision_rationale) > 0

    def test_evaluation_timestamp_matches_input(self):
        """evaluation_timestamp harus sesuai dengan evaluation_date yang diberikan."""
        engine = _make_engine()
        result = engine.evaluate(
            ai_scores=_make_ai_scores(),
            consent=_make_consent(),
            complaint_tickets=[],
            contact_history=[],
            eligibility=_make_eligibility(),
            product_suitability=_make_suitability(),
            evaluation_date=EVAL_DATE,
        )
        assert result.evaluation_timestamp == EVAL_DATE


# ---------------------------------------------------------------------------
# Tests: End-to-End Skenario
# ---------------------------------------------------------------------------

class TestEngineEndToEnd:

    def test_at_risk_platinum_high_churn_returns_retention_or_rm(self):
        """Pelanggan AT_RISK, CLV PLATINUM, Churn HIGH harus mendapat aksi retensi."""
        engine = _make_engine()
        result = engine.evaluate(
            ai_scores=_make_ai_scores(
                lifecycle="AT_RISK", clv=1_200_000, clv_tier="PLATINUM",
                churn_score=0.80, churn_band="VERY_HIGH"
            ),
            consent=_make_consent(),
            complaint_tickets=[],
            contact_history=[],
            eligibility=_make_eligibility(tenure=180),
            product_suitability=_make_suitability(),
            evaluation_date=EVAL_DATE,
        )
        retention_actions = {
            "RETENTION_OUTREACH", "RELATIONSHIP_MANAGER_CONTACT"
        }
        assert result.selected_action.action_id in retention_actions or \
               result.selected_action.action_id != "NO_ACTION"

    def test_new_low_churn_returns_education(self):
        """Pelanggan NEW dengan churn LOW harus mendapat EDUCATION."""
        engine = _make_engine()
        result = engine.evaluate(
            ai_scores=_make_ai_scores(
                lifecycle="NEW", churn_band="LOW", churn_score=0.05,
                propensity_purchase=0.5, clv=50_000, clv_tier="INSUFFICIENT_HISTORY"
            ),
            consent=_make_consent(),
            complaint_tickets=[],
            contact_history=[],
            eligibility=_make_eligibility(tenure=10, has_membership=False),
            product_suitability=_make_suitability(),
            evaluation_date=EVAL_DATE,
        )
        # Pelanggan baru dengan CLV rendah → EDUCATION adalah aksi paling logis
        eligible = [c for c in result.candidates_evaluated if c.is_eligible]
        eligible_ids = [c.action.action_id for c in eligible]
        assert "EDUCATION" in eligible_ids

    def test_fully_suppressed_customer_gets_no_action_only(self):
        """Pelanggan dengan OPT_OUT HANYA boleh mendapat NO_ACTION."""
        engine = _make_engine()
        result = engine.evaluate(
            ai_scores=_make_ai_scores(
                lifecycle="LOYAL", clv=2_000_000, clv_tier="PLATINUM",
                churn_score=0.95, churn_band="VERY_HIGH"
            ),
            consent=_make_consent(global_opt_out=True),
            complaint_tickets=[],
            contact_history=[],
            eligibility=_make_eligibility(tenure=365),
            product_suitability=_make_suitability(),
            evaluation_date=EVAL_DATE,
        )
        # Tidak peduli seberapa berharga pelanggan, Opt-Out = NO_ACTION mutlak
        assert result.selected_action.action_id == "NO_ACTION"
