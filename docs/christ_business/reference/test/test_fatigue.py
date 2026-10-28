"""
test_fatigue.py — Unit Tests untuk services/decision/policy/fatigue.py
========================================================================
Menguji fungsi check_frequency_cap dan remaining_quota.

Jalankan dengan:
    pytest docs/christ_business/reference/test/ -v
"""

import pytest
from datetime import datetime, timedelta

from services.decision.policy.fatigue import (
    ContactRecord,
    FatigueCheckResult,
    FREQ_CAP_MAX_CONTACTS,
    FREQ_CAP_WINDOW_DAYS,
    EXCLUDED_ACTIONS,
    check_frequency_cap,
    remaining_quota,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CUSTOMER_ID = "CUST-001"
EVAL_DATE = datetime(2026, 10, 28, 10, 0, 0)


def _make_contact(action_id: str, days_ago: int, customer_id: str = CUSTOMER_ID) -> ContactRecord:
    """Helper: membuat ContactRecord N hari sebelum EVAL_DATE."""
    return ContactRecord(
        customer_id=customer_id,
        action_id=action_id,
        channel="email",
        sent_at=EVAL_DATE - timedelta(days=days_ago),
        is_commercial=True,
    )


# ---------------------------------------------------------------------------
# Tests: check_frequency_cap
# ---------------------------------------------------------------------------

class TestCheckFrequencyCap:

    def test_no_history_returns_ok(self):
        """Pelanggan tanpa riwayat kontak harus lolos."""
        result = check_frequency_cap(CUSTOMER_ID, [], EVAL_DATE)
        assert result.is_suppressed is False
        assert result.status == "FREQ_CAP_OK"
        assert result.contact_count_in_window == 0

    def test_one_contact_in_window_returns_ok(self):
        """1 kontak dalam window (batas 2) harus lolos."""
        history = [_make_contact("CROSS_SELL", days_ago=5)]
        result = check_frequency_cap(CUSTOMER_ID, history, EVAL_DATE)
        assert result.is_suppressed is False
        assert result.status == "FREQ_CAP_OK"
        assert result.contact_count_in_window == 1

    def test_exactly_at_cap_returns_suppressed(self):
        """Tepat 2 kontak dalam window harus disuppress."""
        history = [
            _make_contact("CROSS_SELL", days_ago=3),
            _make_contact("RETENTION_OUTREACH", days_ago=7),
        ]
        result = check_frequency_cap(CUSTOMER_ID, history, EVAL_DATE)
        assert result.is_suppressed is True
        assert result.status == "FREQ_CAP_SUPPRESSED"
        assert result.contact_count_in_window == 2

    def test_over_cap_returns_suppressed(self):
        """Lebih dari 2 kontak dalam window harus disuppress."""
        history = [
            _make_contact("CROSS_SELL", days_ago=2),
            _make_contact("UPSELL", days_ago=5),
            _make_contact("WIN_BACK_OFFER", days_ago=10),
        ]
        result = check_frequency_cap(CUSTOMER_ID, history, EVAL_DATE)
        assert result.is_suppressed is True
        assert result.contact_count_in_window == 3

    def test_contact_outside_window_not_counted(self):
        """Kontak di luar 14 hari tidak dihitung."""
        history = [
            _make_contact("CROSS_SELL", days_ago=15),  # Tepat di luar window
            _make_contact("UPSELL", days_ago=20),      # Jauh di luar window
        ]
        result = check_frequency_cap(CUSTOMER_ID, history, EVAL_DATE)
        assert result.is_suppressed is False
        assert result.contact_count_in_window == 0

    def test_excluded_actions_not_counted(self):
        """COMPLAINT_RESOLUTION dan SERVICE_REMINDER dikecualikan dari hitungan."""
        history = [
            _make_contact("COMPLAINT_RESOLUTION", days_ago=1),
            _make_contact("SERVICE_REMINDER", days_ago=3),
            _make_contact("COMPLAINT_RESOLUTION", days_ago=5),
        ]
        result = check_frequency_cap(CUSTOMER_ID, history, EVAL_DATE)
        assert result.is_suppressed is False
        assert result.contact_count_in_window == 0

    def test_excluded_actions_do_not_trigger_cap(self):
        """Mix excluded + 1 commercial tidak memicu cap."""
        history = [
            _make_contact("COMPLAINT_RESOLUTION", days_ago=1),
            _make_contact("SERVICE_REMINDER", days_ago=2),
            _make_contact("CROSS_SELL", days_ago=3),  # Hanya 1 commercial
        ]
        result = check_frequency_cap(CUSTOMER_ID, history, EVAL_DATE)
        assert result.is_suppressed is False
        assert result.contact_count_in_window == 1

    def test_excluded_actions_combined_with_cap_breached(self):
        """2 commercial + excluded actions tetap menyebabkan suppression."""
        history = [
            _make_contact("SERVICE_REMINDER", days_ago=1),
            _make_contact("CROSS_SELL", days_ago=3),
            _make_contact("RETENTION_OUTREACH", days_ago=7),
        ]
        result = check_frequency_cap(CUSTOMER_ID, history, EVAL_DATE)
        assert result.is_suppressed is True
        assert result.contact_count_in_window == 2

    def test_only_counts_contacts_for_target_customer(self):
        """Kontak milik pelanggan lain tidak dihitung."""
        history = [
            ContactRecord("OTHER-CUST", "CROSS_SELL", "email", EVAL_DATE - timedelta(days=2), True),
            ContactRecord("OTHER-CUST", "UPSELL", "push", EVAL_DATE - timedelta(days=5), True),
            _make_contact("CROSS_SELL", days_ago=3),  # Hanya 1 milik CUST-001
        ]
        result = check_frequency_cap(CUSTOMER_ID, history, EVAL_DATE)
        assert result.is_suppressed is False
        assert result.contact_count_in_window == 1

    def test_boundary_contact_at_window_start_is_included(self):
        """Kontak tepat pada batas awal window (14 hari lalu) harus dihitung."""
        history = [
            _make_contact("CROSS_SELL", days_ago=14),   # Tepat di batas window
            _make_contact("UPSELL", days_ago=7),
        ]
        result = check_frequency_cap(CUSTOMER_ID, history, EVAL_DATE)
        assert result.contact_count_in_window == 2
        assert result.is_suppressed is True

    def test_result_contains_contacts_in_window(self):
        """Result harus berisi daftar kontak yang ada dalam window."""
        contact = _make_contact("CROSS_SELL", days_ago=5)
        result = check_frequency_cap(CUSTOMER_ID, [contact], EVAL_DATE)
        assert len(result.contacts_in_window) == 1
        assert result.contacts_in_window[0].action_id == "CROSS_SELL"

    def test_default_eval_date_uses_now(self):
        """Jika evaluation_date tidak diberikan, gunakan datetime.utcnow()."""
        result = check_frequency_cap(CUSTOMER_ID, [])
        assert result.is_suppressed is False
        assert isinstance(result.window_start, datetime)

    def test_custom_max_contacts(self):
        """Parameter max_contacts bisa dikustomisasi."""
        history = [
            _make_contact("CROSS_SELL", days_ago=3),
            _make_contact("UPSELL", days_ago=5),
            _make_contact("RETENTION_OUTREACH", days_ago=7),
        ]
        # Dengan batas 4 (lebih dari 3 kontak), tidak suppressed
        result = check_frequency_cap(CUSTOMER_ID, history, EVAL_DATE, max_contacts=4)
        assert result.is_suppressed is False

        # Dengan batas 3 (tepat sama dengan jumlah kontak), suppressed (>= logika)
        result_at_cap = check_frequency_cap(CUSTOMER_ID, history, EVAL_DATE, max_contacts=3)
        assert result_at_cap.is_suppressed is True

        # Dengan batas 2 (default), tetap suppressed
        result_default = check_frequency_cap(CUSTOMER_ID, history, EVAL_DATE, max_contacts=2)
        assert result_default.is_suppressed is True

    def test_non_commercial_records_not_counted(self):
        """ContactRecord dengan is_commercial=False tidak dihitung."""
        history = [
            ContactRecord(CUSTOMER_ID, "EDUCATION", "email",
                          EVAL_DATE - timedelta(days=3), is_commercial=False),
            ContactRecord(CUSTOMER_ID, "EDUCATION", "push",
                          EVAL_DATE - timedelta(days=6), is_commercial=False),
        ]
        result = check_frequency_cap(CUSTOMER_ID, history, EVAL_DATE)
        assert result.contact_count_in_window == 0
        assert result.is_suppressed is False


# ---------------------------------------------------------------------------
# Tests: remaining_quota
# ---------------------------------------------------------------------------

class TestRemainingQuota:

    def test_full_quota_when_no_history(self):
        assert remaining_quota(CUSTOMER_ID, [], EVAL_DATE) == FREQ_CAP_MAX_CONTACTS

    def test_reduced_quota_after_one_contact(self):
        history = [_make_contact("CROSS_SELL", days_ago=3)]
        assert remaining_quota(CUSTOMER_ID, history, EVAL_DATE) == 1

    def test_zero_quota_when_cap_reached(self):
        history = [
            _make_contact("CROSS_SELL", days_ago=3),
            _make_contact("UPSELL", days_ago=7),
        ]
        assert remaining_quota(CUSTOMER_ID, history, EVAL_DATE) == 0

    def test_zero_quota_cannot_go_negative(self):
        """Sisa kuota tidak boleh negatif meskipun cap sudah terlampaui."""
        history = [
            _make_contact("CROSS_SELL", days_ago=2),
            _make_contact("UPSELL", days_ago=4),
            _make_contact("WIN_BACK_OFFER", days_ago=6),
        ]
        assert remaining_quota(CUSTOMER_ID, history, EVAL_DATE) == 0


# ---------------------------------------------------------------------------
# Tests: Verifikasi Konstanta
# ---------------------------------------------------------------------------

class TestConstants:

    def test_freq_cap_default_values(self):
        assert FREQ_CAP_MAX_CONTACTS == 2
        assert FREQ_CAP_WINDOW_DAYS == 14

    def test_excluded_actions_set(self):
        assert "COMPLAINT_RESOLUTION" in EXCLUDED_ACTIONS
        assert "SERVICE_REMINDER" in EXCLUDED_ACTIONS
        assert "CROSS_SELL" not in EXCLUDED_ACTIONS
        assert "RETENTION_OUTREACH" not in EXCLUDED_ACTIONS
