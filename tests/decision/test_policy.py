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
    is_opted_out,
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


# --------------------------- K-10: unknown / expired = BLOCKED ----------------------


def _k10(channels, global_consent=None, **extra):
    return {
        "customer_id": CID,
        "global_consent": global_consent
        or {"status": "OPT_IN", "is_global_opt_out": False},
        "channels": channels,
        "unknown_expired_policy": "BLOCKED",
        "identity_merge_policy": "MOST_RESTRICTIVE_WINS",
        "most_restrictive_wins": True,
        **extra,
    }


def _ch(status="OPT_IN", permission="ALLOWED", **extra):
    return {
        "status": status,
        "opt_in": status == "OPT_IN",
        "effective_permission": permission,
        **extra,
    }


class TestConsentFromK10:
    def test_opt_in_channel_allowed(self):
        c = CustomerConsent.from_k10(_k10({"email": _ch()}), now=NOW)
        assert c.email_opt_in is True
        assert is_opted_out(c, "email") is False

    def test_channel_missing_from_document_is_blocked(self):
        c = CustomerConsent.from_k10(_k10({"email": _ch()}), now=NOW)
        for channel in ("push", "sms", "whatsapp", "phone"):
            assert is_opted_out(c, channel) is True, channel

    @pytest.mark.parametrize("status", ["UNKNOWN", "EXPIRED", "OPT_OUT", "BLOCKED"])
    def test_non_opt_in_status_is_blocked(self, status):
        c = CustomerConsent.from_k10(_k10({"email": _ch(status, "BLOCKED")}), now=NOW)
        assert is_opted_out(c, "email") is True

    def test_effective_permission_blocked_overrides_opt_in_status(self):
        c = CustomerConsent.from_k10(_k10({"email": _ch("OPT_IN", "BLOCKED")}), now=NOW)
        assert is_opted_out(c, "email") is True

    def test_valid_until_in_the_past_is_expired_and_blocked(self):
        past = (NOW - timedelta(days=1)).isoformat()
        c = CustomerConsent.from_k10(_k10({"email": _ch(valid_until=past)}), now=NOW)
        assert is_opted_out(c, "email") is True

    def test_valid_until_in_the_future_is_allowed(self):
        future = (NOW + timedelta(days=30)).isoformat() + "Z"
        c = CustomerConsent.from_k10(_k10({"email": _ch(valid_until=future)}), now=NOW)
        assert is_opted_out(c, "email") is False

    def test_global_opt_out_flag(self):
        doc = _k10({"email": _ch()}, {"status": "OPT_OUT", "is_global_opt_out": True})
        c = CustomerConsent.from_k10(doc, now=NOW)
        assert c.global_opt_out is True
        assert check_suppression(CID, c, []).reason_code == "OPT_OUT_SUPPRESSED"

    @pytest.mark.parametrize("status", ["UNKNOWN", "EXPIRED", "BLOCKED"])
    def test_global_unknown_expired_blocks_every_channel(self, status):
        doc = _k10(
            {"email": _ch(), "push": _ch()},
            {"status": status, "is_global_opt_out": False},
        )
        c = CustomerConsent.from_k10(doc, now=NOW)
        assert is_opted_out(c, "email") and is_opted_out(c, "push")

    def test_integer_customer_id_is_accepted(self):
        doc = _k10({"email": _ch()})
        doc["customer_id"] = 123
        assert CustomerConsent.from_k10(doc, now=NOW).customer_id == "123"

    def test_internal_channels_are_not_subject_to_marketing_consent(self):
        c = CustomerConsent.from_k10(_k10({}), now=NOW)
        assert (
            is_opted_out(c, "task_rm") is False and is_opted_out(c, "branch") is False
        )

    def test_phone_channel_supported(self):
        assert is_opted_out(CustomerConsent(CID, phone_opt_in=False), "phone") is True
        assert is_opted_out(CustomerConsent(CID), "phone") is False
