"""
test_lifecycle_matrix.py — Matriks alokasi perlakuan per segmen (`target_definitions.md`
§3.1) harus sama dengan perilaku engine.

Tabel dibaca langsung dari dokumen, sehingga dokumen dan kode tidak bisa menyimpang diam-diam.

Jalankan: python -m pytest tests/decision/test_lifecycle_matrix.py -v
"""

import re
from datetime import datetime
from pathlib import Path

import pytest

from services.decision.nba.catalogue import ACTION_CATALOGUE
from services.decision.nba.engine import AIScores, EligibilityProfile
from services.decision.nba.evaluator import check_business_eligibility

DOC = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "christ_business"
    / "approved"
    / "target_definitions.md"
)
NOW = datetime(2026, 11, 5)

# Aksi yang dibatasi segmen lifecycle (aksi lintas segmen tidak termasuk matriks per-segmen)
SEGMENT_ACTIONS = {
    "SERVICE_REMINDER",
    "EDUCATION",
    "CROSS_SELL",
    "UPSELL",
    "LOYALTY_REWARD",
    "RETENTION_OUTREACH",
    "WIN_BACK_OFFER",
}
SEGMENTS = [
    "NEW",
    "ACTIVE",
    "LOYAL",
    "AT_RISK",
    "DORMANT",
    "CHURNED",
    "REACTIVATED",
    "OCCASIONAL",
    "NEVER_TRANSACTED",
]


def _doc_matrix():
    text = DOC.read_text(encoding="utf-8")
    section = text.split("### 3.1 Matriks Alokasi Perlakuan per Segmen")[1].split(
        "\n---\n"
    )[0]
    rows = {}
    for line in section.splitlines():
        m = re.match(r"\|\s*`([A-Z_]+)`\s*\|(.*?)\|", line)
        if m:
            cells = m.group(2)
            rows[m.group(1)] = {
                a for a in re.findall(r"`([A-Z_]+)`", cells) if a in ACTION_CATALOGUE
            }
    # v1.3 expresses REACTIVATED as an explicit reference, not an action list.
    if "| `REACTIVATED` | Perlakuan seperti `ACTIVE` |" in section:
        rows["REACTIVATED"] = rows["ACTIVE"].copy()
    return rows


def _engine_actions(segment):
    """Aksi segmen-spesifik yang eligible untuk segmen ini pada atribut yang paling mendukung."""
    found = set()
    for band in ("LOW", "HIGH"):  # EDUCATION butuh LOW, RETENTION butuh HIGH
        scores = AIScores(
            customer_id="C",
            churn_score=0.2 if band == "LOW" else 0.7,
            churn_risk_band=band,
            propensity_purchase=0.8,
            propensity_renew=0.8,
            clv_amount=2_000_000.0,
            clv_tier="GOLD",
            lifecycle_stage=segment,
            score_generated_at=NOW,
        )
        elig = EligibilityProfile(
            customer_id="C",
            tenure_days=300,
            membership_days_remaining=100,
            has_active_membership=False,
            days_until_replenishment=3,
        )
        for action_id in SEGMENT_ACTIONS:
            if check_business_eligibility(action_id, scores, elig) is None:
                found.add(action_id)
    return found


def test_doc_matrix_covers_nine_segments():
    assert set(_doc_matrix()) == set(SEGMENTS)


@pytest.mark.parametrize("segment", SEGMENTS)
def test_engine_matches_doc_matrix(segment):
    assert _engine_actions(segment) == _doc_matrix()[segment] & SEGMENT_ACTIONS


def test_churned_has_no_proactive_segment_action():
    """NO_ACTION is a fallback, never a proactive candidate."""
    assert _doc_matrix()["CHURNED"] == {"NO_ACTION"}
    assert _engine_actions("CHURNED") == set()


@pytest.mark.parametrize("segment", ["OCCASIONAL", "NEVER_TRANSACTED"])
def test_education_only_for_noncommercial_segments(segment):
    assert _doc_matrix()[segment] == {"EDUCATION"}
    assert _engine_actions(segment) == {"EDUCATION"}
    assert ACTION_CATALOGUE["EDUCATION"].is_commercial is False


def test_reactivated_treated_like_active():
    assert _engine_actions("REACTIVATED") == _engine_actions("ACTIVE")


@pytest.mark.parametrize("segment", ["CHURNED", "NEVER_TRANSACTED"])
def test_restricted_segments_block_all_other_proactive_candidates(segment):
    scores = AIScores(
        customer_id="C",
        churn_score=0.9,
        churn_risk_band="VERY_HIGH",
        propensity_purchase=0.8,
        propensity_renew=0.8,
        clv_amount=2_000_000.0,
        clv_tier="PLATINUM",
        lifecycle_stage=segment,
        score_generated_at=NOW,
    )
    eligibility = EligibilityProfile(
        customer_id="C",
        tenure_days=300,
        membership_days_remaining=1,
        has_active_membership=True,
        days_until_replenishment=3,
    )
    allowed = (
        {"NO_ACTION", "EDUCATION"} if segment == "NEVER_TRANSACTED" else {"NO_ACTION"}
    )
    for action_id in ACTION_CATALOGUE:
        if action_id not in allowed:
            assert (
                check_business_eligibility(action_id, scores, eligibility) is not None
            )
    assert check_business_eligibility("NO_ACTION", scores, eligibility) is None
