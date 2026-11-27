"""
test_cross_segment_matrix.py — Bukti untuk jawaban P2 (rekonsiliasi Moses, 20 Nov 2026).

Pertanyaan P2: untuk segmen CHURNED / REACTIVATED / NEVER_TRANSACTED, apakah aksi lintas segmen
(RELATIONSHIP_MANAGER_CONTACT, RENEWAL_REMINDER, COMPLAINT_RESOLUTION) tetap boleh, atau
NO_ACTION/cool-off mengalahkannya?

Keputusan P2 (26 Nov 2026, sisi Christ): **Opsi A** (aksi lintas segmen tidak dibatasi lifecycle,
sesuai target_definitions.md v1.5 §3.1 baris "Lintas segmen" dan §3.2.A). Test ini mengunci
keputusan itu. Persetujuan mentor atas dokumen tetap PENDING (Gate A).
Bila mentor memilih "Opsi B" (NO_ACTION/cool-off menang untuk RM/renewal di REACTIVATED),
ubah evaluator.py, terbitkan versi baru target_definitions.md, lalu ubah test ini secara sadar.

Yang TIDAK boleh berubah pada opsi mana pun: global opt-out dan suppression mutlak.

Jalankan: python -m pytest tests/decision/test_cross_segment_matrix.py -v
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from services.decision.nba.engine import EligibilityProfile
from services.decision.policy.suppression import (
    ComplaintStatus,
    ComplaintTicket,
    CustomerConsent,
)
from tests.decision.test_phase4_hardening import CID, NOW, _decide, _scores

SEGMENTS = ["CHURNED", "REACTIVATED", "NEVER_TRANSACTED"]


def _elig(membership_days_remaining: int, active: bool) -> EligibilityProfile:
    return EligibilityProfile(
        CID, 400, membership_days_remaining, active, [], False, None
    )


def _severe_complaint() -> ComplaintTicket:
    return ComplaintTicket(
        "T-SEV", CID, ComplaintStatus.OPEN_SEVERE, "SEVERE", NOW - timedelta(days=1)
    )


@pytest.mark.parametrize("segment", SEGMENTS)
def test_rm_contact_is_not_limited_by_lifecycle(segment):
    scores = _scores(
        lifecycle_stage=segment,
        clv_tier="PLATINUM",
        churn_risk_band="HIGH",
        churn_score=0.7,
    )
    record = _decide(scores, eligibility=_elig(100, False))
    assert record.selected_action_id == "RELATIONSHIP_MANAGER_CONTACT"


@pytest.mark.parametrize("segment", SEGMENTS)
def test_renewal_reminder_is_not_limited_by_lifecycle(segment):
    scores = _scores(
        lifecycle_stage=segment,
        clv_tier="GOLD",
        churn_risk_band="MEDIUM",
        churn_score=0.4,
    )
    record = _decide(scores, eligibility=_elig(10, True))
    assert record.selected_action_id == "RENEWAL_REMINDER"


@pytest.mark.parametrize("segment", SEGMENTS)
def test_complaint_resolution_is_service_and_wins_in_every_segment(segment):
    scores = _scores(
        lifecycle_stage=segment,
        clv_tier="GOLD",
        churn_risk_band="MEDIUM",
        churn_score=0.4,
    )
    record = _decide(
        scores,
        eligibility=_elig(100, False),
        complaint_tickets=[_severe_complaint()],
    )
    assert record.selected_action_id == "COMPLAINT_RESOLUTION"


@pytest.mark.parametrize("segment", SEGMENTS)
def test_promotional_actions_are_still_blocked_for_these_segments(segment):
    # Tanpa pemicu lintas segmen (bukan PLATINUM berisiko, membership > 15 hari):
    # tidak ada aksi promosi yang lolos -> NO_ACTION.
    scores = _scores(
        lifecycle_stage=segment,
        clv_tier="GOLD",
        churn_risk_band="MEDIUM",
        churn_score=0.4,
    )
    record = _decide(scores, eligibility=_elig(100, False))
    assert record.selected_action_id == "NO_ACTION"


@pytest.mark.parametrize("segment", SEGMENTS)
def test_global_opt_out_beats_every_action_including_complaint_resolution(segment):
    scores = _scores(
        lifecycle_stage=segment,
        clv_tier="PLATINUM",
        churn_risk_band="HIGH",
        churn_score=0.7,
    )
    record = _decide(
        scores,
        eligibility=_elig(10, True),
        consent=CustomerConsent(CID, global_opt_out=True),
        complaint_tickets=[_severe_complaint()],
    )
    assert record.selected_action_id == "NO_ACTION"
    assert record.no_action_reason == "OPT_OUT_SUPPRESSED"
