"""
test_nba_input_contract.py — Bukti untuk jawaban D5 (input minimum NBA).

TEAM_ALIGNMENT_MVP_2026-11-21 §5 D5 bertanya: band/tier, reason codes, dan input
minimum apa yang dibutuhkan NBA, dan apa yang terjadi bila kosong. Jawabannya ditulis
di docs/christ_business/integration/D5_NBA_INPUT_CONTRACT.md. Test ini mengunci setiap
klaim di dokumen itu terhadap engine ASLI, supaya dokumen tidak bisa menyimpang dari
kode tanpa test gagal.

Semua data di sini sintetis dan hanya untuk test.

Jalankan: python -m pytest tests/decision/test_nba_input_contract.py -v
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, List, Optional

import pytest

from services.decision.nba.engine import (
    AIScores,
    EligibilityProfile,
    NBAEngine,
    ProductSuitability,
)
from services.decision.policy.suppression import (
    ComplaintStatus,
    ComplaintTicket,
    CustomerConsent,
)

NOW = datetime(2026, 11, 20, 10, 0, 0)
REF = "X-1"


def consent() -> CustomerConsent:
    def ch() -> dict:
        return {"status": "OPT_IN", "opt_in": True, "effective_permission": "ALLOWED"}

    return CustomerConsent.from_k10(
        {
            "customer_id": REF,
            "global_consent": {"status": "OPT_IN", "is_global_opt_out": False},
            "channels": {"email": ch(), "push": ch()},
            "unknown_expired_policy": "BLOCKED",
            "identity_merge_policy": "MOST_RESTRICTIVE_WINS",
            "most_restrictive_wins": True,
        },
        now=NOW,
    )


def eligibility(**kw: Any) -> EligibilityProfile:
    base: dict = dict(
        customer_id=REF,
        tenure_days=400,
        membership_days_remaining=200,
        has_active_membership=True,
        purchased_categories=["GROCERY"],
        days_until_replenishment=None,
    )
    base.update(kw)
    return EligibilityProfile(**base)


def scores(**kw: Any) -> AIScores:
    base: dict = dict(
        customer_id=REF,
        churn_score=0.9,
        churn_risk_band="VERY_HIGH",
        propensity_purchase=0.7,
        propensity_renew=0.7,
        clv_amount=3_000_000.0,
        clv_tier="GOLD",
        lifecycle_stage="AT_RISK",
        score_generated_at=NOW - timedelta(days=1),
        reason_codes=[],
    )
    base.update(kw)
    return AIScores(**base)


def decide(
    ai: Optional[AIScores],
    elig: Optional[EligibilityProfile] = None,
    complaints: Optional[List[ComplaintTicket]] = None,
    at: datetime = NOW,
):
    return NBAEngine().decide(
        customer_id=REF,
        ai_scores=ai,
        consent=consent(),
        complaint_tickets=complaints or [],
        contact_history=[],
        eligibility=elig or eligibility(),
        product_suitability=ProductSuitability(),
        evaluation_date=at,
        correlation_id="corr-contract",
    )


# ---------------------------------------------------------------------------
# Reason codes: tidak dipakai logika keputusan
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "codes",
    [[], ["A"], ["PURCHASE_FREQUENCY_90D", "RETAINED_REVENUE_365D", "X"], ["Z"] * 10],
)
def test_reason_codes_never_change_the_decision(codes):
    baseline = decide(scores(reason_codes=[]))
    other = decide(scores(reason_codes=codes))
    assert (
        other.selected_action_id == baseline.selected_action_id == "RETENTION_OUTREACH"
    )
    assert other.expected_value == baseline.expected_value
    assert other.degraded_input is False


def test_reason_codes_are_only_recorded_in_the_snapshot_for_audit():
    record = decide(scores(reason_codes=["A", "B", "C"]))
    assert record.scores_snapshot["reason_codes"] == ["A", "B", "C"]


# ---------------------------------------------------------------------------
# Tanpa skor: hanya jalur keluhan (layanan) yang tetap jalan
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "elig",
    [
        eligibility(),
        eligibility(membership_days_remaining=10),  # kandidat RENEWAL_REMINDER
        eligibility(days_until_replenishment=3),  # kandidat SERVICE_REMINDER
    ],
)
def test_without_scores_no_promotion_is_ever_recommended(elig):
    record = decide(None, elig)
    assert record.selected_action_id == "NO_ACTION"
    assert record.degraded_input is True


def test_without_scores_an_open_severe_complaint_still_routes_to_resolution():
    ticket = ComplaintTicket(
        "T-1", REF, ComplaintStatus.OPEN_SEVERE, "SEVERE", NOW - timedelta(days=1)
    )
    record = decide(None, complaints=[ticket])
    assert record.selected_action_id == "COMPLAINT_RESOLUTION"


# ---------------------------------------------------------------------------
# Nilai nol = nilai prediksi, bukan "kosong"; CLV wajib untuk EV
# ---------------------------------------------------------------------------


def test_zero_clv_is_a_real_value_and_yields_no_promotion_not_degraded():
    record = decide(scores(clv_amount=0.0))
    assert record.selected_action_id == "NO_ACTION"
    assert record.no_action_reason == "BELOW_MIN_EV"
    assert record.degraded_input is False  # engine menganggap 0 sebagai skor sah


@pytest.mark.parametrize("lifecycle", ["NEW", "ACTIVE", "LOYAL", "AT_RISK", "DORMANT"])
@pytest.mark.parametrize("tier", ["SILVER", "GOLD", "PLATINUM"])
@pytest.mark.parametrize("band", ["LOW", "MEDIUM", "HIGH", "VERY_HIGH"])
def test_without_clv_no_score_combination_can_recommend_a_promotion(
    lifecycle, tier, band
):
    record = decide(
        scores(
            clv_amount=0.0,
            clv_tier=tier,
            lifecycle_stage=lifecycle,
            churn_risk_band=band,
            propensity_purchase=0.99,
            propensity_renew=0.99,
        ),
        eligibility(membership_days_remaining=10, days_until_replenishment=3),
    )
    assert record.selected_action_id == "NO_ACTION"


# ---------------------------------------------------------------------------
# Band dan tier ikut menentukan kelayakan
# ---------------------------------------------------------------------------


def test_band_that_disagrees_with_score_blocks_the_action():
    record = decide(scores(churn_score=0.9, churn_risk_band="LOW"))
    assert record.selected_action_id == "NO_ACTION"
    assert record.degraded_input is False  # engine tidak mendeteksi inkonsistensi


@pytest.mark.parametrize(
    "overrides",
    [
        {"clv_tier": "SILVER"},
        {"lifecycle_stage": "UNKNOWN"},
        {"lifecycle_stage": "ACTIVE"},
    ],
)
def test_retention_needs_gold_or_platinum_and_at_risk_or_dormant(overrides):
    assert decide(scores(**overrides)).selected_action_id != "RETENTION_OUTREACH"


# ---------------------------------------------------------------------------
# Masa berlaku skor: 30 hari, batas tepat masih sah
# ---------------------------------------------------------------------------


def test_score_exactly_30_days_old_is_still_valid_and_one_second_later_is_expired():
    generated = NOW - timedelta(days=30)
    ok = decide(scores(score_generated_at=generated))
    assert ok.degraded_input is False and ok.selected_action_id == "RETENTION_OUTREACH"

    late = decide(scores(score_generated_at=generated - timedelta(seconds=1)))
    assert late.degraded_input is True and late.selected_action_id == "NO_ACTION"


@pytest.mark.parametrize(
    "bad",
    [
        {"churn_score": 1.01},
        {"churn_score": -0.01},
        {"propensity_purchase": float("nan")},
        {"propensity_renew": 2},
        {"clv_amount": -1.0},
        {"clv_amount": float("inf")},
    ],
)
def test_out_of_range_values_make_the_whole_score_unusable(bad):
    record = decide(replace(scores(), **bad))
    assert record.degraded_input is True
    assert record.selected_action_id == "NO_ACTION"
