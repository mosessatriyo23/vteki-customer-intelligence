"""
test_suppression.py — Unit Tests untuk services/decision/policy/suppression.py
================================================================================
Menguji fungsi check_suppression, has_open_severe_complaint, dan is_opted_out.

Jalankan dengan:
    pytest docs/christ_business/reference/test/ -v
"""

import pytest
from datetime import datetime

from services.decision.policy.suppression import (
    ComplaintStatus,
    ComplaintTicket,
    CustomerConsent,
    SuppressionReason,
    check_suppression,
    has_open_severe_complaint,
    is_opted_out,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CUSTOMER_ID = "CUST-001"
NOW = datetime(2026, 10, 28, 10, 0, 0)


def _make_consent(
    customer_id: str = CUSTOMER_ID,
    global_opt_out: bool = False,
    email_opt_in: bool = True,
    push_opt_in: bool = True,
) -> CustomerConsent:
    return CustomerConsent(
        customer_id=customer_id,
        email_opt_in=email_opt_in,
        push_opt_in=push_opt_in,
        global_opt_out=global_opt_out,
    )


def _make_ticket(
    status: ComplaintStatus,
    ticket_id: str = "T001",
    customer_id: str = CUSTOMER_ID,
) -> ComplaintTicket:
    return ComplaintTicket(
        ticket_id=ticket_id,
        customer_id=customer_id,
        status=status,
        severity="SEVERE",
        opened_at=NOW,
    )


# ---------------------------------------------------------------------------
# Tests: check_suppression — Skenario CLEAR
# ---------------------------------------------------------------------------

class TestCheckSuppressionClear:

    def test_no_suppression_when_clear(self):
        """Pelanggan aktif tanpa keluhan dan opt-in harus lolos tanpa suppression."""
        consent = _make_consent()
        result = check_suppression(CUSTOMER_ID, consent, [])
        assert result.is_suppressed is False
        assert result.status == "SUPPRESSION_CLEAR"
        assert result.suppression_reason == SuppressionReason.NONE
        assert "ALL" in result.allowed_actions

    def test_resolved_complaint_does_not_suppress(self):
        """Keluhan yang sudah RESOLVED tidak memicu suppression."""
        consent = _make_consent()
        tickets = [_make_ticket(ComplaintStatus.RESOLVED)]
        result = check_suppression(CUSTOMER_ID, consent, tickets)
        assert result.is_suppressed is False
        assert result.status == "SUPPRESSION_CLEAR"

    def test_mild_complaint_does_not_suppress(self):
        """Keluhan OPEN_MILD tidak memicu suppression (hanya SEVERE yang memblokir)."""
        consent = _make_consent()
        tickets = [_make_ticket(ComplaintStatus.OPEN_MILD)]
        result = check_suppression(CUSTOMER_ID, consent, tickets)
        assert result.is_suppressed is False

    def test_in_progress_complaint_does_not_suppress(self):
        """Keluhan IN_PROGRESS tidak memicu suppression."""
        consent = _make_consent()
        tickets = [_make_ticket(ComplaintStatus.IN_PROGRESS)]
        result = check_suppression(CUSTOMER_ID, consent, tickets)
        assert result.is_suppressed is False


# ---------------------------------------------------------------------------
# Tests: check_suppression — Skenario OPT_OUT
# ---------------------------------------------------------------------------

class TestCheckSuppressionOptOut:

    def test_global_opt_out_suppresses(self):
        """Global Opt-Out harus memicu suppression mutlak."""
        consent = _make_consent(global_opt_out=True)
        result = check_suppression(CUSTOMER_ID, consent, [])
        assert result.is_suppressed is True
        assert result.status == "OPT_OUT_SUPPRESSED"
        assert result.suppression_reason == SuppressionReason.OPT_OUT
        assert result.is_global_opt_out is True

    def test_opt_out_allows_no_actions(self):
        """Saat Opt-Out, tidak ada aksi apapun yang diizinkan (list kosong)."""
        consent = _make_consent(global_opt_out=True)
        result = check_suppression(CUSTOMER_ID, consent, [])
        assert result.allowed_actions == []

    def test_opt_out_overrides_everything(self):
        """Opt-Out harus di-prioritaskan meskipun ada keluhan OPEN_SEVERE."""
        consent = _make_consent(global_opt_out=True)
        tickets = [_make_ticket(ComplaintStatus.OPEN_SEVERE)]
        result = check_suppression(CUSTOMER_ID, consent, tickets)
        # OPT_OUT adalah prioritas tertinggi
        assert result.status == "OPT_OUT_SUPPRESSED"
        assert result.allowed_actions == []

    def test_opt_out_message_is_descriptive(self):
        """Pesan hasil pemeriksaan harus mengandung informasi yang jelas."""
        consent = _make_consent(global_opt_out=True)
        result = check_suppression(CUSTOMER_ID, consent, [])
        assert CUSTOMER_ID in result.message
        assert "Opt-Out" in result.message


# ---------------------------------------------------------------------------
# Tests: check_suppression — Skenario OPEN_SEVERE_COMPLAINT
# ---------------------------------------------------------------------------

class TestCheckSuppressionComplaint:

    def test_open_severe_complaint_suppresses(self):
        """OPEN_SEVERE_COMPLAINT harus memicu COMPLAINT_SUPPRESSED."""
        consent = _make_consent()
        tickets = [_make_ticket(ComplaintStatus.OPEN_SEVERE)]
        result = check_suppression(CUSTOMER_ID, consent, tickets)
        assert result.is_suppressed is True
        assert result.status == "COMPLAINT_SUPPRESSED"
        assert result.suppression_reason == SuppressionReason.COMPLAINT

    def test_complaint_suppression_allows_only_complaint_resolution(self):
        """Saat COMPLAINT_SUPPRESSED, hanya COMPLAINT_RESOLUTION yang diizinkan."""
        consent = _make_consent()
        tickets = [_make_ticket(ComplaintStatus.OPEN_SEVERE)]
        result = check_suppression(CUSTOMER_ID, consent, tickets)
        assert result.allowed_actions == ["COMPLAINT_RESOLUTION"]

    def test_multiple_severe_complaints_all_listed(self):
        """Semua tiket OPEN_SEVERE harus tercantum dalam active_complaints."""
        consent = _make_consent()
        tickets = [
            _make_ticket(ComplaintStatus.OPEN_SEVERE, "T001"),
            _make_ticket(ComplaintStatus.OPEN_SEVERE, "T002"),
            _make_ticket(ComplaintStatus.RESOLVED, "T003"),
        ]
        result = check_suppression(CUSTOMER_ID, consent, tickets)
        assert result.is_suppressed is True
        assert len(result.active_complaints) == 2
        ticket_ids = [t.ticket_id for t in result.active_complaints]
        assert "T001" in ticket_ids
        assert "T002" in ticket_ids

    def test_complaint_of_other_customer_does_not_suppress(self):
        """Tiket keluhan milik pelanggan lain tidak mempengaruhi pelanggan ini."""
        consent = _make_consent()
        other_ticket = _make_ticket(
            ComplaintStatus.OPEN_SEVERE, customer_id="OTHER-CUST"
        )
        result = check_suppression(CUSTOMER_ID, consent, [other_ticket])
        assert result.is_suppressed is False

    def test_complaint_message_contains_ticket_id(self):
        """Pesan suppression harus menyebut ticket ID."""
        consent = _make_consent()
        tickets = [_make_ticket(ComplaintStatus.OPEN_SEVERE, "T999")]
        result = check_suppression(CUSTOMER_ID, consent, tickets)
        assert "T999" in result.message


# ---------------------------------------------------------------------------
# Tests: check_suppression — Validasi Customer ID Mismatch
# ---------------------------------------------------------------------------

class TestCheckSuppressionValidation:

    def test_raises_when_consent_customer_id_mismatch(self):
        """Harus raise ValueError jika customer_id consent tidak cocok."""
        consent = _make_consent(customer_id="WRONG-CUST")
        with pytest.raises(ValueError, match="Mismatch customer_id"):
            check_suppression(CUSTOMER_ID, consent, [])


# ---------------------------------------------------------------------------
# Tests: has_open_severe_complaint
# ---------------------------------------------------------------------------

class TestHasOpenSevereComplaint:

    def test_returns_true_when_open_severe_exists(self):
        tickets = [_make_ticket(ComplaintStatus.OPEN_SEVERE)]
        assert has_open_severe_complaint(CUSTOMER_ID, tickets) is True

    def test_returns_false_when_no_tickets(self):
        assert has_open_severe_complaint(CUSTOMER_ID, []) is False

    def test_returns_false_when_only_resolved(self):
        tickets = [_make_ticket(ComplaintStatus.RESOLVED)]
        assert has_open_severe_complaint(CUSTOMER_ID, tickets) is False

    def test_returns_false_for_other_customer_ticket(self):
        other_ticket = _make_ticket(ComplaintStatus.OPEN_SEVERE, customer_id="OTHER")
        assert has_open_severe_complaint(CUSTOMER_ID, [other_ticket]) is False

    def test_returns_true_among_mixed_statuses(self):
        tickets = [
            _make_ticket(ComplaintStatus.RESOLVED, "T001"),
            _make_ticket(ComplaintStatus.OPEN_SEVERE, "T002"),
            _make_ticket(ComplaintStatus.IN_PROGRESS, "T003"),
        ]
        assert has_open_severe_complaint(CUSTOMER_ID, tickets) is True


# ---------------------------------------------------------------------------
# Tests: is_opted_out
# ---------------------------------------------------------------------------

class TestIsOptedOut:

    def test_global_opt_out_returns_true(self):
        consent = _make_consent(global_opt_out=True)
        assert is_opted_out(consent) is True

    def test_no_opt_out_returns_false(self):
        consent = _make_consent(global_opt_out=False)
        assert is_opted_out(consent) is False

    def test_email_opted_out(self):
        consent = _make_consent(email_opt_in=False)
        assert is_opted_out(consent, channel="email") is True

    def test_push_opted_in(self):
        consent = _make_consent(push_opt_in=True)
        assert is_opted_out(consent, channel="push") is False

    def test_global_opt_out_overrides_channel(self):
        """Global opt-out harus mengalahkan cek kanal spesifik."""
        consent = CustomerConsent(
            customer_id=CUSTOMER_ID,
            email_opt_in=True,
            push_opt_in=True,
            global_opt_out=True,
        )
        assert is_opted_out(consent, channel="email") is True
        assert is_opted_out(consent, channel="push") is True

    def test_unknown_channel_returns_false_without_global_opt_out(self):
        """Kanal tidak dikenal dan tanpa global opt-out mengembalikan False."""
        consent = _make_consent()
        assert is_opted_out(consent, channel="fax") is False
