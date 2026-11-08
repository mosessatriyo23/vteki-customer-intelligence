"""
test_nba_engine.py — Test NBAEngine.decide() (Minggu 7): keluaran bentuk K-07,
degraded input, fallback NO_ACTION, dan "skor tinggi bukan izin".

Jalankan: python -m pytest tests/decision/test_nba_engine.py -v
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from services.decision.nba.catalogue import ACTION_CATALOGUE
from services.decision.nba.engine import (
    ENGINE_VERSION,
    AIScores,
    DecisionRecord,
    EligibilityProfile,
    NBAEngine,
    ProductSuitability,
)
from services.decision.policy.fatigue import ContactRecord
from services.decision.policy.suppression import (
    ComplaintStatus,
    ComplaintTicket,
    CustomerConsent,
)

ACTION_CHANNELS = {k: v.allowed_channels for k, v in ACTION_CATALOGUE.items()}
CID = "CUST-NBA-001"
NOW = datetime(2026, 11, 5, 10, 0, 0)
K07_PATH = (
    Path(__file__).resolve().parents[2] / "contracts" / "K-07_decision_record.json"
)


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
        reason_codes=["R1", "R2", "R3"],
    )
    base.update(kw)
    return AIScores(**base)


def _elig() -> EligibilityProfile:
    return EligibilityProfile(
        customer_id=CID,
        tenure_days=200,
        membership_days_remaining=100,
        has_active_membership=True,
    )


def _decide(engine=None, **over):
    kw = dict(
        customer_id=CID,
        ai_scores=_scores(),
        consent=CustomerConsent(CID),
        complaint_tickets=[],
        contact_history=[],
        eligibility=_elig(),
        product_suitability=ProductSuitability(),
        evaluation_date=NOW,
        correlation_id="corr-test-1",
        decision_id="DEC-TEST-1",
    )
    kw.update(over)
    return (engine or NBAEngine()).decide(**kw)


def _ticket(status=ComplaintStatus.OPEN_SEVERE):
    return ComplaintTicket("T1", CID, status, "SEVERE", NOW)


def _contacts(n):
    return [
        ContactRecord(CID, "CROSS_SELL", "email", NOW - timedelta(days=i + 1))
        for i in range(n)
    ]


# --------------------------- Jalur normal -----------------------------------


class TestDecideNormal:
    def test_returns_decision_record_with_action(self):
        rec = _decide()
        assert isinstance(rec, DecisionRecord)
        assert rec.selected_action_id != "NO_ACTION"
        assert rec.expected_value > 0
        assert rec.degraded_input is False
        assert rec.rationale_text
        assert rec.engine_version == ENGINE_VERSION

    def test_ids_are_injectable_and_deterministic(self):
        a = _decide().to_dict()
        b = _decide().to_dict()
        assert a == b
        assert a["decision_id"] == "DEC-TEST-1"
        assert a["correlation_id"] == "corr-test-1"

    def test_auto_generated_ids_valid_and_unique(self):
        r1 = _decide(correlation_id=None, decision_id=None)
        r2 = _decide(correlation_id=None, decision_id=None)
        assert r1.decision_id != r2.decision_id
        assert r1.correlation_id != r2.correlation_id
        assert re.match(r"^[A-Za-z0-9._:-]{1,128}$", r1.correlation_id)

    def test_candidates_ranked_by_ev_best_is_selected(self):
        rec = _decide()
        eligible = [c for c in rec.candidates if c["is_eligible"]]
        assert eligible
        top = min(eligible, key=lambda c: c["rank"])
        assert top["action_id"] == rec.selected_action_id
        assert top["expected_value"] == max(c["expected_value"] for c in eligible)
        assert sorted(c["rank"] for c in eligible) == list(range(1, len(eligible) + 1))

    def test_ineligible_candidates_have_reason_and_no_rank(self):
        rec = _decide()
        blocked = [c for c in rec.candidates if not c["is_eligible"]]
        assert blocked
        assert all(c["rejection_reason"] and "rank" not in c for c in blocked)

    def test_checks_contain_five_gates_with_k07_fields(self):
        rec = _decide()
        names = [c["check_name"] for c in rec.checks]
        assert names == [
            "ML_SCORE_CHECK",
            "CONSENT_CHECK",
            "CONTACT_POLICY_CHECK",
            "ELIGIBILITY_CHECK",
            "SUITABILITY_CHECK",
        ]
        assert all(c["passed"] for c in rec.checks)

    def test_channel_selected_respects_opt_in(self):
        rec = _decide(consent=CustomerConsent(CID, email_opt_in=False))
        assert rec.selected_action_id != "NO_ACTION"
        assert rec.channel_selected == "push"  # email opt-out -> kanal berikutnya

    def test_channel_none_when_every_channel_opted_out(self):
        consent = CustomerConsent(CID, email_opt_in=False, push_opt_in=False)
        assert _decide(consent=consent).channel_selected is None

    def test_scores_snapshot_filled(self):
        snap = _decide().scores_snapshot
        assert snap["clv_tier"] == "GOLD" and snap["reason_codes"] == ["R1", "R2", "R3"]


# --------------------------- Skor tinggi bukan izin ---------------------------


class TestChannelConsent:
    """Masukan 3 per kanal (Requirement Bab 3, K-10): aksi tanpa kanal yang diizinkan tidak dipilih."""

    ALL_BLOCKED = dict(
        email_opt_in=False,
        push_opt_in=False,
        sms_opt_in=False,
        whatsapp_opt_in=False,
        phone_opt_in=False,
    )

    def test_all_marketing_channels_blocked_leaves_only_internal_task_actions(self):
        rec = _decide(consent=CustomerConsent(CID, **self.ALL_BLOCKED))
        chosen = rec.selected_action_id
        # aksi yang masih mungkin hanya yang kanalnya internal (task_rm / branch) atau NO_ACTION
        assert chosen == "NO_ACTION" or all(
            c in ("task_rm", "branch") for c in ACTION_CHANNELS[chosen]
        )
        assert rec.channel_selected in (None, "task_rm", "branch")

    def test_candidates_blocked_by_channel_consent_have_reason(self):
        rec = _decide(consent=CustomerConsent(CID, **self.ALL_BLOCKED))
        blocked = [
            c for c in rec.candidates if "kanal" in (c["rejection_reason"] or "")
        ]
        assert blocked and all(c["is_eligible"] is False for c in blocked)

    def test_all_candidates_blocked_by_consent_gives_no_action_with_reason(self):
        rec = _decide(
            ai_scores=_scores(lifecycle_stage="ACTIVE"),
            consent=CustomerConsent(CID, **self.ALL_BLOCKED),
            product_suitability=ProductSuitability(
                available_action_ids=["CROSS_SELL", "UPSELL"]
            ),
        )
        assert rec.selected_action_id == "NO_ACTION"
        assert rec.channel_selected is None
        assert rec.no_action_reason == "ALL_CANDIDATES_BLOCKED"
        consent = next(c for c in rec.checks if c["check_name"] == "CONSENT_CHECK")
        assert consent["passed"] is False
        assert consent["status"] == "CHANNEL_CONSENT_BLOCKED"
        assert consent["details"]["candidates_blocked_by_channel_consent"] >= 1

    def test_one_open_channel_keeps_action_available(self):
        rec = _decide(consent=CustomerConsent(CID, email_opt_in=False))
        assert rec.selected_action_id != "NO_ACTION"
        assert rec.channel_selected == "push"

    def test_selected_action_always_has_a_usable_channel(self):
        for kwargs in (
            {},
            {"email_opt_in": False},
            {"push_opt_in": False},
            self.ALL_BLOCKED,
        ):
            rec = _decide(consent=CustomerConsent(CID, **kwargs))
            if rec.selected_action_id != "NO_ACTION":
                assert rec.channel_selected is not None, kwargs

    def test_decision_from_k10_document_unknown_channel_is_blocked(self):
        doc = {
            "customer_id": CID,
            "global_consent": {"status": "OPT_IN", "is_global_opt_out": False},
            "channels": {
                "email": {
                    "status": "UNKNOWN",
                    "opt_in": False,
                    "effective_permission": "BLOCKED",
                },
                "push": {
                    "status": "OPT_IN",
                    "opt_in": True,
                    "effective_permission": "ALLOWED",
                },
            },
            "unknown_expired_policy": "BLOCKED",
            "most_restrictive_wins": True,
        }
        rec = _decide(consent=CustomerConsent.from_k10(doc, now=NOW))
        assert rec.selected_action_id != "NO_ACTION"
        assert rec.channel_selected == "push"


class TestHighScoreIsNotPermission:
    def _high(self):
        return _scores(
            churn_score=0.95,
            churn_risk_band="VERY_HIGH",
            clv_tier="PLATINUM",
            lifecycle_stage="AT_RISK",
            propensity_purchase=0.99,
            clv_amount=9_000_000.0,
        )

    def test_opt_out_forces_no_action(self):
        rec = _decide(
            ai_scores=self._high(), consent=CustomerConsent(CID, global_opt_out=True)
        )
        assert rec.selected_action_id == "NO_ACTION"
        assert rec.expected_value == 0.0
        assert rec.channel_selected is None
        consent = next(c for c in rec.checks if c["check_name"] == "CONSENT_CHECK")
        assert consent["passed"] is False and consent["status"] == "OPT_OUT_SUPPRESSED"

    def test_open_severe_complaint_only_complaint_resolution(self):
        rec = _decide(ai_scores=self._high(), complaint_tickets=[_ticket()])
        assert rec.selected_action_id == "COMPLAINT_RESOLUTION"
        # Bab 3 baris 2: keluhan aktif = masukan 2 (Business Eligibility)
        elig = next(c for c in rec.checks if c["check_name"] == "ELIGIBILITY_CHECK")
        assert elig["passed"] is False
        assert elig["status"] == "COMPLAINT_SUPPRESSED"
        assert elig["details"]["reason_code"] == "EXCL_OPEN_SEVERE_COMPLAINT"
        # frequency cap (masukan 4) tidak ikut gagal hanya karena ada komplain
        policy = next(
            c for c in rec.checks if c["check_name"] == "CONTACT_POLICY_CHECK"
        )
        assert policy["passed"] is True

    def test_frequency_cap_forces_no_action(self):
        rec = _decide(ai_scores=self._high(), contact_history=_contacts(2))
        assert rec.selected_action_id == "NO_ACTION"
        policy = next(
            c for c in rec.checks if c["check_name"] == "CONTACT_POLICY_CHECK"
        )
        assert policy["status"] == "FREQ_CAP_SUPPRESSED"

    def test_resolved_complaint_does_not_block(self):
        rec = _decide(complaint_tickets=[_ticket(ComplaintStatus.RESOLVED)])
        assert rec.selected_action_id not in ("NO_ACTION", "COMPLAINT_RESOLUTION")


# --------------------------- Fallback NO_ACTION -------------------------------


class TestNoActionFallback:
    def test_threshold_above_all_ev_gives_no_action(self):
        rec = _decide(engine=NBAEngine(ev_min_threshold=1e12))
        assert rec.selected_action_id == "NO_ACTION"
        assert "NO_ACTION" in rec.rationale_text

    def test_ev_min_threshold_alias_equals_min_ev_threshold(self):
        assert NBAEngine(ev_min_threshold=5.0).min_ev_threshold == 5.0
        assert NBAEngine(min_ev_threshold=7.0).min_ev_threshold == 7.0

    def test_all_products_unavailable_gives_no_action(self):
        rec = _decide(
            product_suitability=ProductSuitability(available_action_ids=["NOPE"])
        )
        assert rec.selected_action_id == "NO_ACTION"
        suit = next(c for c in rec.checks if c["check_name"] == "SUITABILITY_CHECK")
        assert suit["passed"] is False

    def test_no_eligible_candidate_at_all_gives_no_action(self):
        rec = _decide(
            ai_scores=_scores(lifecycle_stage="CHURNED", clv_tier="SILVER"),
            product_suitability=ProductSuitability(
                unsuitable_action_ids=["SERVICE_REMINDER"]
            ),
        )
        assert [c for c in rec.candidates if c["is_eligible"]] == []
        assert rec.selected_action_id == "NO_ACTION"
        assert rec.no_action_reason == "ALL_CANDIDATES_BLOCKED"
        assert "ALL_CANDIDATES_BLOCKED" in rec.rationale_text
        elig = next(c for c in rec.checks if c["check_name"] == "ELIGIBILITY_CHECK")
        assert elig["passed"] is False


# --------------------------- Degraded input -----------------------------------


class TestDegradedInput:
    """
    Requirement_Capstone Bab 3 baris 1: skor kedaluwarsa -> default. Panduan Minggu 7:
    tandai `degraded_input = True`. Keputusan aksi sama dengan evaluate() (tidak ada
    aturan tambahan di decide()).
    """

    def test_expired_scores_set_degraded_flag(self):
        rec = _decide(ai_scores=_scores(score_generated_at=NOW - timedelta(days=45)))
        assert rec.degraded_input is True
        assert "degraded_input=True" in rec.rationale_text
        ml = next(c for c in rec.checks if c["check_name"] == "ML_SCORE_CHECK")
        assert ml["passed"] is False

    def test_expired_scores_use_zero_propensity_for_every_candidate(self):
        rec = _decide(ai_scores=_scores(score_generated_at=NOW - timedelta(days=45)))
        assert all(c["propensity"] == 0.0 for c in rec.candidates)

    def test_decide_equals_evaluate_for_degraded_input(self):
        """decide() tidak boleh memutuskan lain daripada evaluate()."""
        scores = _scores(score_generated_at=NOW - timedelta(days=45))
        eng = NBAEngine()
        legacy = eng.evaluate(
            scores, CustomerConsent(CID), [], [], _elig(), ProductSuitability(), NOW
        )
        rec = _decide(engine=eng, ai_scores=scores)
        assert rec.selected_action_id == legacy.selected_action.action_id
        assert rec.expected_value == legacy.expected_value

    def test_missing_scores_use_defaults_and_flag(self):
        rec = _decide(ai_scores=None)
        assert rec.degraded_input is True
        assert rec.scores_snapshot["clv_amount"] == 0.0
        assert rec.scores_snapshot["churn_score"] == 0.0
        assert all(c["propensity"] == 0.0 for c in rec.candidates)
        ml = next(c for c in rec.checks if c["check_name"] == "ML_SCORE_CHECK")
        assert ml["passed"] is False and ml["details"]["scores_missing"] is True

    def test_missing_scores_still_honour_complaint_resolution(self):
        rec = _decide(ai_scores=None, complaint_tickets=[_ticket()])
        assert rec.selected_action_id == "COMPLAINT_RESOLUTION"
        assert rec.degraded_input is True

    def test_missing_scores_with_opt_out_is_no_action(self):
        rec = _decide(ai_scores=None, consent=CustomerConsent(CID, global_opt_out=True))
        assert rec.selected_action_id == "NO_ACTION"
        assert rec.no_action_reason == "OPT_OUT_SUPPRESSED"

    def test_fresh_scores_not_degraded(self):
        assert _decide().degraded_input is False


class TestNoActionReason:
    """Bab 4 baris NO_ACTION: Opt-Out, Frequency Cap tercapai, ALL_CANDIDATES_BLOCKED."""

    def test_opt_out(self):
        rec = _decide(consent=CustomerConsent(CID, global_opt_out=True))
        assert rec.no_action_reason == "OPT_OUT_SUPPRESSED"

    def test_frequency_cap(self):
        rec = _decide(contact_history=_contacts(2))
        assert rec.selected_action_id == "NO_ACTION"
        assert rec.no_action_reason == "FREQ_CAP_SUPPRESSED"

    def test_all_candidates_blocked_by_suitability(self):
        rec = _decide(
            product_suitability=ProductSuitability(available_action_ids=["NOPE"])
        )
        assert rec.no_action_reason == "ALL_CANDIDATES_BLOCKED"

    def test_ev_below_threshold_has_no_documented_code(self):
        """Dokumen tidak memberi kode untuk EV < threshold -> tidak dikarang."""
        rec = _decide(engine=NBAEngine(ev_min_threshold=1e12))
        assert rec.selected_action_id == "NO_ACTION"
        assert rec.no_action_reason is None

    def test_not_set_when_action_selected(self):
        assert _decide().no_action_reason is None

    def test_present_in_to_dict(self):
        assert "no_action_reason" in _decide().to_dict()


# --------------------------- Validasi input -----------------------------------


class TestValidation:
    @pytest.mark.parametrize("bad", ["", "has space", "a/b", "x" * 129, "ünicode"])
    def test_invalid_correlation_id_raises(self, bad):
        with pytest.raises(ValueError):
            _decide(correlation_id=bad)

    def test_scores_customer_mismatch_raises(self):
        with pytest.raises(ValueError):
            _decide(ai_scores=_scores(customer_id="OTHER"))

    def test_evaluate_legacy_method_still_available(self):
        eng = NBAEngine()
        res = eng.evaluate(
            _scores(), CustomerConsent(CID), [], [], _elig(), ProductSuitability(), NOW
        )
        assert res.selected_action.action_id


# --------------------------- Kontrak K-07 -------------------------------------


class TestK07Contract:
    CASES = {
        "normal": {},
        "opt_out": dict(consent=CustomerConsent(CID, global_opt_out=True)),
        "complaint": dict(complaint_tickets=[_ticket()]),
        "fatigue": dict(contact_history=_contacts(2)),
        "missing_scores": dict(ai_scores=None),
        "expired": dict(ai_scores=_scores(score_generated_at=NOW - timedelta(days=60))),
    }

    @pytest.mark.parametrize("case", list(CASES))
    def test_to_dict_is_json_serialisable(self, case):
        json.dumps(_decide(**self.CASES[case]).to_dict())

    @pytest.mark.parametrize("case", list(CASES))
    def test_to_dict_has_all_required_k07_fields(self, case):
        schema = json.loads(K07_PATH.read_text(encoding="utf-8"))
        d = _decide(**self.CASES[case]).to_dict()
        for field in schema["required"]:
            assert field in d, field

    @pytest.mark.parametrize("case", list(CASES))
    def test_to_dict_validates_against_k07_schema(self, case):
        jsonschema = pytest.importorskip("jsonschema")
        schema = json.loads(K07_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(_decide(**self.CASES[case]).to_dict(), schema)
