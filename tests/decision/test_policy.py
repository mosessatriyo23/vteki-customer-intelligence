"""
test_policy.py — Test Policy Engine (Minggu 5): field aditif `reason_code`,
batas frekuensi, dan penekanan komplain aktif.

Jalankan: python -m pytest tests/decision/test_policy.py -v
"""

from datetime import datetime, timedelta

import pytest

from services.decision.policy.fatigue import ContactRecord, check_frequency_cap
from services.decision.policy.suppression import (
    ComplaintStatus,
    ComplaintTicket,
    CustomerConsent,
    check_suppression,
)

CID = "CUST-POLICY-001"
NOW = datetime(2026, 11, 5, 10, 0, 0)


def _contact(days_ago: float, action: str = "CROSS_SELL", commercial: bool = True):
    return ContactRecord(
        customer_id=CID,
        action_id=action,
        channel="email",
        sent_at=NOW - timedelta(days=days_ago),
        is_commercial=commercial,
    )


def _ticket(status: ComplaintStatus, tid: str = "T1", cid: str = CID):
    return ComplaintTicket(
        ticket_id=tid, customer_id=cid, status=status, severity="SEVERE", opened_at=NOW
    )


# --------------------------- Fatigue ---------------------------------------


class TestFatigueReasonCode:
    def test_suppressed_has_reason_code(self):
        r = check_frequency_cap(CID, [_contact(1), _contact(3)], NOW)
        assert r.is_suppressed is True
        assert r.status == "FREQ_CAP_SUPPRESSED"
        assert r.reason_code == "FREQ_CAP_SUPPRESSED"

    def test_ok_has_empty_reason_code(self):
        r = check_frequency_cap(CID, [_contact(1)], NOW)
        assert r.is_suppressed is False
        assert r.status == "FREQ_CAP_OK"
        assert r.reason_code == ""

    def test_empty_history_ok(self):
        r = check_frequency_cap(CID, [], NOW)
        assert r.is_suppressed is False
        assert r.contact_count_in_window == 0

    def test_exactly_at_cap_is_suppressed(self):
        """Batas 2: kontak ke-2 sudah mencapai cap -> terblokir."""
        r = check_frequency_cap(CID, [_contact(2), _contact(5)], NOW)
        assert r.contact_count_in_window == 2
        assert r.is_suppressed is True

    def test_contact_on_window_boundary_is_counted(self):
        """Tepat 14 hari lalu masih dihitung (window_start <= sent_at)."""
        r = check_frequency_cap(CID, [_contact(14), _contact(1)], NOW)
        assert r.contact_count_in_window == 2

    def test_contact_outside_window_not_counted(self):
        r = check_frequency_cap(CID, [_contact(14.01), _contact(20)], NOW)
        assert r.contact_count_in_window == 0
        assert r.is_suppressed is False

    @pytest.mark.parametrize("excluded", ["COMPLAINT_RESOLUTION", "SERVICE_REMINDER"])
    def test_excluded_actions_not_counted(self, excluded):
        history = [_contact(1, excluded), _contact(2, excluded), _contact(3, excluded)]
        r = check_frequency_cap(CID, history, NOW)
        assert r.contact_count_in_window == 0
        assert r.is_suppressed is False

    def test_non_commercial_not_counted(self):
        r = check_frequency_cap(CID, [_contact(1, commercial=False)] * 3, NOW)
        assert r.contact_count_in_window == 0

    def test_other_customer_contacts_ignored(self):
        other = ContactRecord("OTHER", "CROSS_SELL", "email", NOW - timedelta(days=1))
        r = check_frequency_cap(CID, [other, other, other], NOW)
        assert r.contact_count_in_window == 0


# --------------------------- Suppression -----------------------------------


class TestSuppressionReasonCode:
    def test_open_severe_complaint_reason_code(self):
        r = check_suppression(
            CID, CustomerConsent(CID), [_ticket(ComplaintStatus.OPEN_SEVERE)]
        )
        assert r.is_suppressed is True
        assert r.status == "COMPLAINT_SUPPRESSED"  # status lama tidak berubah
        assert r.reason_code == "EXCL_OPEN_SEVERE_COMPLAINT"
        assert r.allowed_actions == ["COMPLAINT_RESOLUTION"]

    def test_opt_out_reason_code(self):
        r = check_suppression(CID, CustomerConsent(CID, global_opt_out=True), [])
        assert r.is_suppressed is True
        assert r.status == "OPT_OUT_SUPPRESSED"
        assert r.reason_code == "OPT_OUT_SUPPRESSED"
        assert r.allowed_actions == []

    def test_clear_has_empty_reason_code(self):
        r = check_suppression(CID, CustomerConsent(CID), [])
        assert r.is_suppressed is False
        assert r.reason_code == ""

    @pytest.mark.parametrize(
        "status",
        [
            ComplaintStatus.RESOLVED,
            ComplaintStatus.CLOSED,
            ComplaintStatus.IN_PROGRESS,
            ComplaintStatus.OPEN_MILD,
        ],
    )
    def test_non_severe_or_resolved_complaint_does_not_block(self, status):
        r = check_suppression(CID, CustomerConsent(CID), [_ticket(status)])
        assert r.is_suppressed is False

    def test_opt_out_has_priority_over_complaint(self):
        """Opt-out mutlak: tidak boleh menyisakan COMPLAINT_RESOLUTION."""
        r = check_suppression(
            CID,
            CustomerConsent(CID, global_opt_out=True),
            [_ticket(ComplaintStatus.OPEN_SEVERE)],
        )
        assert r.reason_code == "OPT_OUT_SUPPRESSED"
        assert r.allowed_actions == []

    def test_other_customer_ticket_ignored(self):
        r = check_suppression(
            CID,
            CustomerConsent(CID),
            [_ticket(ComplaintStatus.OPEN_SEVERE, cid="OTHER")],
        )
        assert r.is_suppressed is False

    def test_consent_customer_mismatch_raises(self):
        with pytest.raises(ValueError):
            check_suppression(CID, CustomerConsent("OTHER"), [])
