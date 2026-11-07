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


@pytest.mark.parametrize(
    "segment", ["CHURNED", "REACTIVATED", "OCCASIONAL", "NEVER_TRANSACTED"]
)
def test_undecided_segments_have_no_segment_specific_action(segment):
    """Segmen 'Belum ditetapkan' di dokumen: tidak ada aksi proaktif segmen-spesifik."""
    assert _doc_matrix()[segment] == set()
    assert _engine_actions(segment) == set()