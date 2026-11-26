"""
test_phase4_hardening.py — Hardening Fase 4 (Minggu 12): regresi temuan + celah coverage.

Isi:
  A. DEF-01 Safety Scanner: normalisasi Unicode NFKC (fullwidth "１００％" tidak boleh lolos).
  B. DEF-02 Zona waktu: policy/fatigue & NBAEngine menerima datetime naif DAN beraksesoris
     zona waktu (mis. timestamptz PostgreSQL) tanpa TypeError.
  C. DEF-03 Skor AI tidak valid (di luar 0-1 / NaN / inf / CLV negatif) -> default konservatif,
     `degraded_input=True`, NO_ACTION; rekaman K-07 tetap JSON valid (tanpa NaN/Infinity).
  D. Anti-penghindaran Safety Scanner (dahulu 3 xfail "risiko sisa"): homoglyph Kiril,
     huruf berjarak, dan diskon ditulis dengan kata kini TERDETEKSI. Penanda xfail dihapus
     secara sadar (strict XPASS memaksa langkah ini) + test false-positive agar teks wajar
     tidak ikut terblokir.
  E. Penutup celah coverage pada modul Fase 2-3.

Jalankan: python -m pytest tests/decision/test_phase4_hardening.py -v
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import jsonschema
import pytest

import services.decision.nudge.generator as generator_module
from services.decision.forecasting.projector import project_revenue
from services.decision.measurement.uplift import (
    Outcome,
    conversion_rate_lift,
)
from services.decision.nba.catalogue import (
    ACTION_CATALOGUE,
    ActionCategory,
    get_actions_by_category,
    list_all_action_ids,
    require_action,
)
from services.decision.nba.engine import (
    AIScores,
    EligibilityProfile,
    NBAEngine,
    ProductSuitability,
    scores_are_valid,
)
from services.decision.nba.ev_calculator import (
    estimate_expected_revenue,
    estimate_incentive_cost,
    get_propensity,
)
from services.decision.nba.evaluator import (
    check_business_eligibility,
    check_channel_availability,
)
from services.decision.nudge.generator import (
    STATUS_BLOCKED_BY_GUARDRAIL,
    STATUS_GENERATED_DRAFT,
    _clean_fact,
    generate_nudge,
    required_facts,
)
from services.decision.nudge.safety import _to_percent, scan_message
from services.decision.policy.fatigue import (
    ContactRecord,
    check_frequency_cap,
    remaining_quota,
)
from services.decision.policy.suppression import (
    ComplaintStatus,
    ComplaintTicket,
    CustomerConsent,
    has_open_severe_complaint,
    is_opted_out,
)
from services.decision.simulator.channel_sim import (
    ChannelSimulator,
    SimulatedDelivery,
    UnregisteredCampaignError,
)
from services.decision.timeutil import utc_now

K07_SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[2] / "contracts" / "K-07_decision_record.json"
    ).read_text(encoding="utf-8")
)
CID = "CUST-HARD-001"
NOW = datetime(2026, 11, 16, 10, 0, 0)


def _scores(**kw) -> AIScores:
    base = dict(
        customer_id=CID,
        churn_score=0.7,
        churn_risk_band="HIGH",
        propensity_purchase=0.6,
        propensity_renew=0.5,
        clv_amount=3_000_000.0,
        clv_tier="GOLD",
        lifecycle_stage="AT_RISK",
        score_generated_at=NOW - timedelta(days=1),
        reason_codes=["R1", "R2", "R3"],
    )
    base.update(kw)
    return AIScores(**base)


def _elig() -> EligibilityProfile:
    return EligibilityProfile(
        customer_id=CID,
        tenure_days=400,
        membership_days_remaining=20,
        has_active_membership=True,
        purchased_categories=["GROCERY"],
        days_until_replenishment=3,
    )


def _decide(scores, engine=None, **over):
    kw = dict(
        customer_id=CID,
        ai_scores=scores,
        consent=CustomerConsent(CID),
        complaint_tickets=[],
        contact_history=[],
        eligibility=_elig(),
        product_suitability=ProductSuitability(),
        evaluation_date=NOW,
        correlation_id="corr-hard-1",
        decision_id="DEC-HARD-1",
    )
    kw.update(over)
    return (engine or NBAEngine()).decide(**kw)


# ---------------------------------------------------------------------------
# A. DEF-01 — Safety Scanner: normalisasi Unicode
# ---------------------------------------------------------------------------


class TestDef01UnicodeNormalisation:
    @pytest.mark.parametrize(
        "text",
        [
            "Dijamin １００％ aman",  # angka + persen fullwidth
            "１００％ dijamin untuk Anda",
            "ＤＩＪＡＭＩＮ 100% hari ini",  # huruf fullwidth
            "Jaminan １００ ％ untuk Anda",
        ],
    )
    def test_fullwidth_guarantee_is_blocked(self, text):
        result = scan_message(text, max_discount_percent=30)
        assert not result.is_safe
        assert "ABSOLUTE_GUARANTEE" in result.rule_ids

    @pytest.mark.parametrize(
        "text", ["Diskon ４５％ hari ini", "Hemat ９０％ semua produk"]
    )
    def test_fullwidth_discount_above_cap_is_blocked(self, text):
        result = scan_message(text, max_discount_percent=30)
        assert not result.is_safe
        assert "DISCOUNT_ABOVE_CAP" in result.rule_ids

    def test_fullwidth_discount_within_cap_is_allowed(self):
        assert scan_message("Diskon ２０％ hari ini", max_discount_percent=30).is_safe

    def test_ascii_behaviour_unchanged(self):
        assert scan_message("Halo Budi, selamat datang kembali.").is_safe
        assert not scan_message("Dijamin 100% aman").is_safe

    def test_attack_through_fact_package_is_blocked_end_to_end(self):
        draft = generate_nudge(
            "C1",
            "RETENTION_OUTREACH",
            "email",
            {
                "first_name": "Budi Diskon ９０％",
                "preferred_branch": "Yogyakarta",
                "offer_validity": "30-11-2026",
            },
        )
        assert draft.status == STATUS_BLOCKED_BY_GUARDRAIL
        assert not draft.is_releasable

    def test_to_percent_returns_none_for_non_numeric(self):
        assert _to_percent("abc") is None
        assert _to_percent("12,5") == pytest.approx(12.5)


# ---------------------------------------------------------------------------
# B. DEF-02 — Zona waktu
# ---------------------------------------------------------------------------


class TestDef02Timezones:
    def test_fatigue_accepts_aware_contacts_with_naive_evaluation(self):
        history = [
            ContactRecord(
                CID,
                "CROSS_SELL",
                "email",
                datetime(2026, 11, 15, 10, tzinfo=timezone.utc),
            ),
            ContactRecord(
                CID, "UPSELL", "push", datetime(2026, 11, 14, 10, tzinfo=timezone.utc)
            ),
        ]
        result = check_frequency_cap(CID, history, NOW)
        assert result.is_suppressed
        assert result.contact_count_in_window == 2

    def test_fatigue_accepts_aware_evaluation_with_naive_contacts(self):
        history = [ContactRecord(CID, "CROSS_SELL", "email", NOW - timedelta(days=1))]
        aware_now = NOW.replace(tzinfo=timezone.utc)
        result = check_frequency_cap(CID, history, aware_now)
        assert result.contact_count_in_window == 1
        assert result.window_end == NOW  # dinormalisasi ke naive-UTC

    def test_fatigue_offset_is_converted_not_just_stripped(self):
        """10:00 WIB (+07:00) = 03:00 UTC; tepat 14 hari sebelum 03:00 UTC masih dihitung."""
        wib = timezone(timedelta(hours=7))
        eval_utc = datetime(2026, 11, 19, 3, 0, 0)
        on_boundary = ContactRecord(
            CID, "X", "email", datetime(2026, 11, 5, 10, 0, tzinfo=wib)
        )
        just_outside = ContactRecord(
            CID, "X", "email", datetime(2026, 11, 5, 9, 59, tzinfo=wib)
        )
        assert (
            check_frequency_cap(CID, [on_boundary], eval_utc).contact_count_in_window
            == 1
        )
        assert (
            check_frequency_cap(CID, [just_outside], eval_utc).contact_count_in_window
            == 0
        )

    def test_fatigue_default_evaluation_date_is_now(self):
        history = [
            ContactRecord(CID, "X", "email", utc_now() - timedelta(days=1)),
            ContactRecord(CID, "Y", "push", utc_now() - timedelta(days=2)),
        ]
        assert check_frequency_cap(CID, history).is_suppressed

    @pytest.mark.parametrize("n_contacts,expected", [(0, 2), (1, 1), (2, 0), (5, 0)])
    def test_remaining_quota(self, n_contacts, expected):
        history = [
            ContactRecord(CID, "X", "email", NOW - timedelta(days=i + 1))
            for i in range(n_contacts)
        ]
        assert remaining_quota(CID, history, NOW) == expected

    def test_engine_accepts_aware_evaluation_and_score_timestamps(self):
        naive = _decide(_scores())
        aware = _decide(
            _scores(
                score_generated_at=(NOW - timedelta(days=1)).replace(
                    tzinfo=timezone.utc
                )
            ),
            evaluation_date=NOW.replace(tzinfo=timezone.utc),
        )
        assert aware.selected_action_id == naive.selected_action_id
        assert aware.expected_value == pytest.approx(naive.expected_value)
        assert aware.evaluation_timestamp == NOW
        assert aware.degraded_input is False
        jsonschema.Draft7Validator(K07_SCHEMA).validate(aware.to_dict())

    def test_engine_aware_score_expiry_is_still_detected(self):
        old = _scores(
            score_generated_at=(NOW - timedelta(days=45)).replace(tzinfo=timezone.utc)
        )
        record = _decide(old, evaluation_date=NOW.replace(tzinfo=timezone.utc))
        assert record.degraded_input is True
        assert record.selected_action_id == "NO_ACTION"

    def test_engine_default_evaluation_date_paths(self):
        fresh = _scores(score_generated_at=utc_now() - timedelta(days=1))
        engine = NBAEngine()
        record = engine.decide(
            customer_id=CID,
            ai_scores=fresh,
            consent=CustomerConsent(CID),
            complaint_tickets=[],
            contact_history=[],
            eligibility=_elig(),
            product_suitability=ProductSuitability(),
        )
        assert record.selected_action_id == "RETENTION_OUTREACH"
        assert abs((record.evaluation_timestamp - utc_now()).total_seconds()) < 60
        result = engine.evaluate(
            fresh,
            CustomerConsent(CID),
            [],
            [],
            _elig(),
            ProductSuitability(),
        )
        assert result.selected_action.action_id == "RETENTION_OUTREACH"


# ---------------------------------------------------------------------------
# C. DEF-03 — Skor AI tidak valid
# ---------------------------------------------------------------------------

INVALID_SCORE_CASES = [
    ("churn_above_1", dict(churn_score=1.5)),
    ("churn_negative", dict(churn_score=-0.1)),
    ("churn_nan", dict(churn_score=math.nan)),
    ("churn_inf", dict(churn_score=math.inf)),
    ("propensity_purchase_above_1", dict(propensity_purchase=1.8)),
    ("propensity_purchase_negative", dict(propensity_purchase=-0.5)),
    ("propensity_renew_nan", dict(propensity_renew=math.nan)),
    ("clv_nan", dict(clv_amount=math.nan)),
    ("clv_inf", dict(clv_amount=math.inf)),
    ("clv_negative", dict(clv_amount=-5_000_000.0)),
    ("churn_bool", dict(churn_score=True)),
]


class TestDef03InvalidScores:
    @pytest.mark.parametrize("label,override", INVALID_SCORE_CASES)
    def test_invalid_scores_fall_back_to_conservative_no_action(self, label, override):
        record = _decide(_scores(**override))
        assert record.selected_action_id == "NO_ACTION", label
        assert record.expected_value == 0.0
        assert record.degraded_input is True
        assert "tidak valid" in record.rationale_text

    @pytest.mark.parametrize("label,override", INVALID_SCORE_CASES)
    def test_k07_record_stays_strict_json(self, label, override):
        record = _decide(_scores(**override)).to_dict()
        jsonschema.Draft7Validator(K07_SCHEMA).validate(record)
        json.dumps(record, allow_nan=False)  # tidak boleh ada NaN / Infinity

    def test_evaluate_direct_path_is_also_protected(self):
        result = NBAEngine().evaluate(
            _scores(churn_score=1.5),
            CustomerConsent(CID),
            [],
            [],
            _elig(),
            ProductSuitability(),
            NOW,
        )
        assert result.selected_action.action_id == "NO_ACTION"
        assert result.scores_expired is True

    def test_inflated_probability_can_no_longer_inflate_ev(self):
        valid = _decide(_scores(churn_score=1.0))
        inflated = _decide(_scores(churn_score=50.0))
        assert valid.selected_action_id == "RETENTION_OUTREACH"
        assert inflated.expected_value == 0.0  # bukan 50x lebih besar

    @pytest.mark.parametrize(
        "override",
        [
            dict(churn_score=0.0),
            dict(churn_score=1.0),
            dict(propensity_purchase=0.0, propensity_renew=1.0),
            dict(clv_amount=0.0),
            dict(churn_score=1),  # int sah
        ],
    )
    def test_boundary_values_are_valid(self, override):
        assert scores_are_valid(_scores(**override)) is True

    def test_valid_scores_do_not_trigger_degraded(self):
        record = _decide(_scores())
        assert record.degraded_input is False
        assert "tidak valid" not in record.rationale_text


# ---------------------------------------------------------------------------
# D. RISIKO SISA — terdokumentasi (xfail strict)
# ---------------------------------------------------------------------------


class TestEvasionTechniquesAreDetected:
    def test_cyrillic_homoglyph_is_detected(self):
        assert not scan_message("p\u0430sti berhasil").is_safe  # 'а' Kiril

    def test_letter_spacing_is_detected(self):
        assert not scan_message("p a s t i berhasil").is_safe

    def test_letter_spacing_with_dots_is_detected(self):
        assert not scan_message("m.e.d.i.s").is_safe

    def test_discount_written_in_words_is_detected(self):
        assert not scan_message(
            "Diskon sembilan puluh persen", max_discount_percent=30
        ).is_safe

    @pytest.mark.parametrize(
        "text",
        [
            "Diskon tiga puluh lima persen",
            "Potongan seratus persen",
            "Diskon empat puluh persen",
        ],
    )
    def test_discount_words_above_cap_blocked_and_escalated(self, text):
        result = scan_message(text, max_discount_percent=30)
        assert not result.is_safe
        assert result.requires_escalation

    @pytest.mark.parametrize(
        "text",
        [
            "Diskon tiga puluh persen",  # tepat sama dengan pagu -> boleh
            "Diskon dua puluh persen untuk Anda",
            "Paket A B C tersedia",
            "Pilih opsi a, b, atau c",
            "Halo Budi, poin Anda 120 siap dipakai",
        ],
    )
    def test_normal_text_is_not_blocked(self, text):
        assert scan_message(text, max_discount_percent=30).is_safe


# ---------------------------------------------------------------------------
# E. Penutup celah coverage
# ---------------------------------------------------------------------------


class TestCoverageGaps:
    def test_below_min_ev_reason(self):
        record = _decide(_scores(), engine=NBAEngine(min_ev_threshold=1e12))
        assert record.selected_action_id == "NO_ACTION"
        assert record.no_action_reason == "BELOW_MIN_EV"

    def test_engine_compat_wrappers_delegate_to_pure_functions(self):
        engine = NBAEngine()
        scores = _scores()
        elig = _elig()
        action = require_action("RETENTION_OUTREACH")
        assert engine._check_business_eligibility(
            "RETENTION_OUTREACH", scores, elig
        ) == check_business_eligibility("RETENTION_OUTREACH", scores, elig)
        assert engine._get_propensity(
            "RETENTION_OUTREACH", scores, False
        ) == get_propensity("RETENTION_OUTREACH", scores, False)
        assert engine._estimate_expected_revenue(
            scores, "RETENTION_OUTREACH"
        ) == estimate_expected_revenue(scores.clv_amount, "RETENTION_OUTREACH")
        assert engine._estimate_incentive_cost(action, scores) == (
            estimate_incentive_cost(action.incentive_band, scores.clv_amount)
        )

    def test_select_channel_none_when_all_marketing_channels_opted_out(self):
        consent = CustomerConsent(CID, email_opt_in=False, push_opt_in=False)
        assert NBAEngine._select_channel(require_action("CROSS_SELL"), consent) is None

    def test_check_channel_availability_no_channels_is_ok(self):
        assert check_channel_availability([], CustomerConsent(CID)) is None
        blocked = CustomerConsent(CID, global_opt_out=True)
        assert check_channel_availability(["email"], blocked) is not None

    def test_suppression_helpers(self):
        severe = ComplaintTicket(
            "T1", CID, ComplaintStatus.OPEN_SEVERE, "SEVERE", NOW - timedelta(days=1)
        )
        other = ComplaintTicket(
            "T2",
            "OTHER",
            ComplaintStatus.OPEN_SEVERE,
            "SEVERE",
            NOW - timedelta(days=1),
        )
        closed = ComplaintTicket(
            "T3", CID, ComplaintStatus.CLOSED, "SEVERE", NOW - timedelta(days=9)
        )
        assert has_open_severe_complaint(CID, [severe]) is True
        assert has_open_severe_complaint(CID, [other, closed]) is False
        assert is_opted_out(CustomerConsent(CID, global_opt_out=True), "email") is True
        assert is_opted_out(CustomerConsent(CID, email_opt_in=False), "email") is True
        assert is_opted_out(CustomerConsent(CID), "task_rm") is False

    def test_catalogue_helpers(self):
        ids = list_all_action_ids()
        assert ids == list(ACTION_CATALOGUE)
        assert "NO_ACTION" in ids and len(ids) == 11
        retention = get_actions_by_category(ActionCategory.RETENTION)
        assert [a.action_id for a in retention] == ["RETENTION_OUTREACH"]

    def test_generator_clean_fact_and_required_facts(self):
        assert required_facts("NO_ACTION") == []
        assert _clean_fact(date(2026, 11, 30)) == "30-11-2026"
        assert _clean_fact(datetime(2026, 11, 30, 8, 0)) == "30-11-2026"
        assert _clean_fact(12.0) == "12"
        assert _clean_fact("a{b}\nc") == "a b c"

    def test_generator_accepts_date_and_float_facts(self):
        draft = generate_nudge(
            "C1",
            "LOYALTY_REWARD",
            "email",
            {"first_name": "Sari", "points_balance": 1250.0},
        )
        assert draft.status == STATUS_GENERATED_DRAFT
        assert "1250 poin" in draft.body

    def test_template_with_non_whitelisted_variable_is_rejected(self, monkeypatch):
        monkeypatch.setitem(
            generator_module.TEMPLATES, "CROSS_SELL", "Halo {first_name} {secret_field}"
        )
        with pytest.raises(ValueError, match="whitelist"):
            generator_module._validate_templates()

    def test_uplift_input_validation(self):
        with pytest.raises(ValueError):
            Outcome(" ", "C1", "PURCHASE", NOW, 1.0)
        with pytest.raises(ValueError):
            Outcome("O1", "  ", "PURCHASE", NOW, 1.0)
        outcome = Outcome("O1", "C1", "PURCHASE", NOW, 1.0)
        with pytest.raises(ValueError):
            outcome.revenue("BASIS_TIDAK_ADA")
        with pytest.raises(ValueError):
            conversion_rate_lift(1, 1, 0, 10)
        with pytest.raises(ValueError):
            conversion_rate_lift(1, 1, 10, 0)

    def test_forecast_rejects_non_numeric_inputs(self):
        with pytest.raises(ValueError):
            project_revenue(
                monthly_revenue_history=[1_000_000],
                horizon_months=1,
                treated_customers=10,
                incremental_revenue_per_treated_customer="banyak",  # type: ignore[arg-type]
            )
        with pytest.raises(ValueError):
            project_revenue(
                monthly_revenue_history=[1_000_000],
                horizon_months=1,
                treated_customers=10,
                incremental_revenue_per_treated_customer=math.nan,
            )

    def test_simulator_exposures_property_lists_only_exposed_attempts(self):
        from services.decision.campaign.holdout import split_from_campaign
        from services.decision.nudge.generator import approve_draft

        campaign = {
            "campaign_id": "CMP-HARD",
            "control_holdout_ratio": 0.2,
            "random_seed": 7,
        }
        audience = [f"C{i:03d}" for i in range(100)]
        split = split_from_campaign(campaign, audience)
        sim = ChannelSimulator(clock=lambda: NOW)
        sim.register_campaign(split)
        facts = {
            "first_name": "Budi",
            "preferred_branch": "Yogyakarta",
            "offer_validity": "30-11-2026",
        }
        for cid in audience:
            draft = approve_draft(
                generate_nudge(cid, "RETENTION_OUTREACH", "email", facts), "approver-1"
            )
            sim.send(draft, campaign_id="CMP-HARD")
        assert len(sim.attempts) == 100
        assert len(sim.exposures) == split.n_treatment
        assert all(e.exposure_recorded for e in sim.exposures)


class TestControlIsolationDetector:
    """
    Menutup mutan M15 (verify_control_isolation selalu True) yang lolos dari suite lama:
    detektor kontaminasi harus benar-benar MELAPORKAN kontaminasi bila ia terjadi.
    """

    def _contaminated_sim(self):
        from services.decision.campaign.holdout import split_from_campaign

        campaign = {
            "campaign_id": "CMP-CONTAM",
            "control_holdout_ratio": 0.2,
            "random_seed": 11,
        }
        split = split_from_campaign(campaign, [f"C{i:03d}" for i in range(50)])
        sim = ChannelSimulator(clock=lambda: NOW)
        sim.register_campaign(split)
        control_id = split.control_ids[0]
        # Simulasi bug hulu: ada catatan paparan untuk anggota control (tidak lewat send()).
        sim._attempts.append(
            SimulatedDelivery(
                delivery_id="SIM-FAKE-1",
                campaign_id="CMP-CONTAM",
                customer_id=control_id,
                action_id="RETENTION_OUTREACH",
                channel="email",
                status="SIMULATED_SENT",
                group="CONTROL",
                attempted_at=NOW,
                correlation_id="corr-contam",
                exposure_recorded=True,
            )
        )
        return sim, split, control_id

    def test_detector_reports_contamination(self):
        sim, _, control_id = self._contaminated_sim()
        assert sim.control_exposure_count("CMP-CONTAM") == 1
        assert sim.verify_control_isolation("CMP-CONTAM") is False
        assert sim.has_exposure(control_id) is True

    def test_measurement_flags_contaminated_control(self):
        from services.decision.measurement.uplift import (
            build_window,
            compute_uplift,
        )

        sim, split, _ = self._contaminated_sim()
        result = compute_uplift(
            split,
            [],
            build_window(datetime(2026, 11, 1), datetime(2026, 11, 7), 30, 14),
            as_of=datetime(2027, 3, 1),
            exposed_customer_ids=sim.exposed_customer_ids("CMP-CONTAM"),
        )
        assert result.control_exposed_count == 1
        assert result.warnings  # kontaminasi harus muncul sebagai peringatan

    def test_unregistered_campaign_is_an_error_not_a_pass(self):
        sim = ChannelSimulator()
        with pytest.raises(UnregisteredCampaignError):
            sim.verify_control_isolation("CMP-TIDAK-ADA")
