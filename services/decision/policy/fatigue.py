"""
fatigue.py — Contact Frequency Cap Policy
==========================================
Modul ini menegakkan aturan batas frekuensi kontak pemasaran (Fatigue / Frequency Cap)
sebelum sebuah penawaran didistribusikan kepada pelanggan.

Aturan Bisnis (dari target_definitions.md §4.1):
- Batas maksimum: 2 kontak pemasaran per 14 hari (rolling window)
- Jika batas terlampaui: status FREQ_CAP_SUPPRESSED dikembalikan
- Pengecualian: COMPLAINT_RESOLUTION dan SERVICE_REMINDER tidak dihitung

Referensi: Requirement_Capstone.md Bab 3 (FRD §9.6 / TRD §10.1)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional


# ---------------------------------------------------------------------------
# Konstanta Bisnis
# ---------------------------------------------------------------------------

FREQ_CAP_MAX_CONTACTS: int = 2
"""Jumlah maksimum kontak pemasaran yang diizinkan dalam satu rolling window."""

FREQ_CAP_WINDOW_DAYS: int = 14
"""Panjang rolling window dalam hari."""

# Aksi yang dikecualikan dari perhitungan frekuensi (non-commercial)
EXCLUDED_ACTIONS: frozenset[str] = frozenset({
    "COMPLAINT_RESOLUTION",
    "SERVICE_REMINDER",
})


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class ContactRecord:
    """Representasi satu catatan kontak yang dikirimkan kepada pelanggan."""
    customer_id: str
    action_id: str
    channel: str
    sent_at: datetime
    is_commercial: bool = True


@dataclass
class FatigueCheckResult:
    """Hasil pemeriksaan fatigue untuk seorang pelanggan."""
    customer_id: str
    is_suppressed: bool
    status: str
    contact_count_in_window: int
    window_start: datetime
    window_end: datetime
    message: str
    contacts_in_window: List[ContactRecord] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Fungsi Utama
# ---------------------------------------------------------------------------

def check_frequency_cap(
    customer_id: str,
    contact_history: List[ContactRecord],
    evaluation_date: Optional[datetime] = None,
    max_contacts: int = FREQ_CAP_MAX_CONTACTS,
    window_days: int = FREQ_CAP_WINDOW_DAYS,
) -> FatigueCheckResult:
    """
    Memeriksa apakah pelanggan telah mencapai batas frekuensi kontak pemasaran
    dalam rentang waktu rolling window yang ditentukan.

    Args:
        customer_id: ID unik pelanggan yang diperiksa.
        contact_history: Daftar catatan kontak historis pelanggan tersebut.
        evaluation_date: Tanggal evaluasi (default: sekarang / datetime.utcnow()).
        max_contacts: Batas maksimum kontak dalam window (default: 2).
        window_days: Panjang rolling window dalam hari (default: 14).

    Returns:
        FatigueCheckResult berisi status suppression dan detail pemeriksaan.
        - Jika is_suppressed=True, status="FREQ_CAP_SUPPRESSED" -> sistem wajib NO_ACTION.
        - Jika is_suppressed=False, status="FREQ_CAP_OK" -> aksi dapat dilanjutkan.

    Contoh:
        >>> history = [
        ...     ContactRecord("C001", "RETENTION_OUTREACH", "email", datetime(2026, 10, 20)),
        ...     ContactRecord("C001", "CROSS_SELL", "push", datetime(2026, 10, 25)),
        ... ]
        >>> result = check_frequency_cap("C001", history, datetime(2026, 10, 28))
        >>> result.status
        'FREQ_CAP_SUPPRESSED'
    """
    if evaluation_date is None:
        evaluation_date = datetime.now(timezone.utc).replace(tzinfo=None)

    window_start = evaluation_date - timedelta(days=window_days)
    window_end = evaluation_date

    # Filter hanya kontak komersial yang relevan dalam window dan milik pelanggan ini
    contacts_in_window: List[ContactRecord] = [
        record
        for record in contact_history
        if (
            record.customer_id == customer_id
            and record.action_id not in EXCLUDED_ACTIONS
            and record.is_commercial
            and window_start <= record.sent_at <= window_end
        )
    ]

    contact_count = len(contacts_in_window)
    is_suppressed = contact_count >= max_contacts

    if is_suppressed:
        status = "FREQ_CAP_SUPPRESSED"
        message = (
            f"Pelanggan {customer_id} telah menerima {contact_count} kontak komersial "
            f"dalam {window_days} hari terakhir (batas: {max_contacts}). "
            f"Seluruh aksi komersial diblokir."
        )
    else:
        status = "FREQ_CAP_OK"
        message = (
            f"Pelanggan {customer_id} baru menerima {contact_count}/{max_contacts} "
            f"kontak komersial dalam {window_days} hari terakhir. Aksi dapat dilanjutkan."
        )

    return FatigueCheckResult(
        customer_id=customer_id,
        is_suppressed=is_suppressed,
        status=status,
        contact_count_in_window=contact_count,
        window_start=window_start,
        window_end=window_end,
        message=message,
        contacts_in_window=contacts_in_window,
    )


def remaining_quota(
    customer_id: str,
    contact_history: List[ContactRecord],
    evaluation_date: Optional[datetime] = None,
    max_contacts: int = FREQ_CAP_MAX_CONTACTS,
    window_days: int = FREQ_CAP_WINDOW_DAYS,
) -> int:
    """
    Menghitung sisa kuota kontak komersial yang tersedia untuk pelanggan
    dalam rolling window saat ini.

    Returns:
        int: Jumlah kontak yang masih diperbolehkan. 0 berarti sudah mencapai batas.
    """
    result = check_frequency_cap(
        customer_id, contact_history, evaluation_date, max_contacts, window_days
    )
    used = result.contact_count_in_window
    return max(0, max_contacts - used)
