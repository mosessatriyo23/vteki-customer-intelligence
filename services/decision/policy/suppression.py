"""
suppression.py — Absolute Suppression Policy
=============================================
Modul ini mendeteksi dan menegakkan aturan suppression mutlak terhadap pelanggan
yang memiliki tiket keluhan aktif berstatus OPEN_SEVERE_COMPLAINT atau
yang telah menyatakan Opt-Out dari komunikasi pemasaran.

Aturan Bisnis (dari target_definitions.md §4.2):
- OPEN_SEVERE_COMPLAINT: Memblokir SELURUH penawaran komersial seketika.
  Hanya aksi COMPLAINT_RESOLUTION yang diizinkan.
- OPT_OUT: Memblokir SELURUH komunikasi. NO_ACTION mutlak, tanpa pengecualian.

Field aditif `reason_code` (Minggu 5) pada hasil pemeriksaan:
- OPT_OUT_SUPPRESSED      -> opt-out global
- EXCL_OPEN_SEVERE_COMPLAINT -> tiket keluhan OPEN_SEVERE_COMPLAINT aktif
- ""                      -> tidak ada suppression
Field `status` lama TIDAK berubah (kompatibel dengan test yang sudah ada).

Suppression bersifat MUTLAK — tidak ada skor AI, CLV, atau urgensi bisnis
yang dapat meng-override kondisi suppression ini.

Referensi: Requirement_Capstone.md Bab 2 & 3 (FRD §9.6 / TRD §10.1)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Mapping, Optional

# ---------------------------------------------------------------------------
# Enums & Konstanta
# ---------------------------------------------------------------------------


class SuppressionReason(str, Enum):
    """Jenis alasan suppression yang dapat diterapkan."""

    NONE = "NONE"
    OPT_OUT = "OPT_OUT_SUPPRESSED"
    COMPLAINT = "COMPLAINT_SUPPRESSED"
    FREQ_CAP = "FREQ_CAP_SUPPRESSED"  # Referensi dari fatigue.py


class ComplaintStatus(str, Enum):
    """Status tiket keluhan pelanggan."""

    OPEN_SEVERE = "OPEN_SEVERE_COMPLAINT"
    OPEN_MILD = "OPEN_MILD_COMPLAINT"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


# Satu-satunya aksi yang diizinkan saat COMPLAINT_SUPPRESSED aktif
COMPLAINT_ALLOWED_ACTION = "COMPLAINT_RESOLUTION"

# Kode alasan penekanan sesuai roadmap Minggu 5 (aditif terhadap `status`)
REASON_CODE_OPT_OUT = "OPT_OUT_SUPPRESSED"
REASON_CODE_OPEN_SEVERE_COMPLAINT = "EXCL_OPEN_SEVERE_COMPLAINT"


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------


@dataclass
class ComplaintTicket:
    """Representasi tiket keluhan pelanggan."""

    ticket_id: str
    customer_id: str
    status: ComplaintStatus
    severity: str  # "SEVERE", "MILD", "LOW"
    opened_at: datetime
    resolved_at: Optional[datetime] = None
    description: str = ""


@dataclass
class CustomerConsent:
    """
    Status consent/persetujuan komunikasi pelanggan.

    PENTING (kontrak K-10, Panduan Minggu 3): status consent yang UNKNOWN / EXPIRED /
    tidak tercantum = BLOCKED. Nilai default `True` pada dataclass ini hanya kemudahan
    saat membangun objek secara langsung (mis. di test). Untuk data nyata berformat K-10
    WAJIB memakai `CustomerConsent.from_k10(...)` yang menerapkan aturan tersebut.
    """

    customer_id: str
    email_opt_in: bool = True
    push_opt_in: bool = True
    sms_opt_in: bool = True
    whatsapp_opt_in: bool = True
    global_opt_out: bool = False  # Jika True, semua kanal diblokir
    updated_at: Optional[datetime] = None
    phone_opt_in: bool = True

    @classmethod
    def from_k10(
        cls, doc: Mapping[str, Any], now: Optional[datetime] = None
    ) -> "CustomerConsent":
        """
        Membangun CustomerConsent dari dokumen kontrak K-10 (`contracts/K-10_consent_contract.json`).

        Aturan (K-10 / Panduan Minggu 3):
        - Sebuah kanal DIIZINKAN hanya jika `status == OPT_IN`, `effective_permission == ALLOWED`,
          dan `valid_until` (jika ada) belum terlewati. Selain itu (OPT_OUT, UNKNOWN, EXPIRED,
          BLOCKED, `valid_until` terlewati, atau kanal tidak tercantum) = BLOCKED.
        - Global `OPT_OUT` atau `is_global_opt_out = true` -> `global_opt_out = True`.
        - Global `UNKNOWN` / `EXPIRED` / `BLOCKED` -> seluruh kanal diblokir.

        Args:
            doc: dokumen K-10 (dict hasil parse JSON).
            now: waktu acuan pengecekan `valid_until` (default: sekarang, UTC).
        """
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        global_consent = doc.get("global_consent") or {}
        global_status = global_consent.get("status")
        global_opt_out = bool(global_consent.get("is_global_opt_out")) or (
            global_status == "OPT_OUT"
        )
        global_blocked = global_status in ("UNKNOWN", "EXPIRED", "BLOCKED")

        channels = doc.get("channels") or {}

        def allowed(channel: str) -> bool:
            if global_blocked:
                return False
            detail = channels.get(channel)
            if not isinstance(detail, Mapping):
                return False  # kanal tidak tercantum = unknown = blocked
            if detail.get("status") != "OPT_IN":
                return False
            if detail.get("effective_permission") != "ALLOWED":
                return False
            valid_until = detail.get("valid_until")
            if valid_until:
                expiry = datetime.fromisoformat(str(valid_until).replace("Z", "+00:00"))
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                if expiry <= now:
                    return False  # masa berlaku terlewati = EXPIRED = blocked
            return True

        updated_raw = doc.get("last_updated_at") or global_consent.get("updated_at")
        updated_at = (
            datetime.fromisoformat(str(updated_raw).replace("Z", "+00:00"))
            if updated_raw
            else None
        )

        return cls(
            customer_id=str(doc["customer_id"]),
            email_opt_in=allowed("email"),
            push_opt_in=allowed("push"),
            sms_opt_in=allowed("sms"),
            whatsapp_opt_in=allowed("whatsapp"),
            phone_opt_in=allowed("phone"),
            global_opt_out=global_opt_out,
            updated_at=updated_at,
        )


@dataclass
class SuppressionCheckResult:
    """Hasil pemeriksaan suppression untuk seorang pelanggan."""

    customer_id: str
    is_suppressed: bool
    suppression_reason: SuppressionReason
    status: str
    allowed_actions: List[str]
    message: str
    active_complaints: List[ComplaintTicket] = field(default_factory=list)
    is_global_opt_out: bool = False
    reason_code: str = ""
    """Kode alasan penekanan (aditif). Kosong jika tidak ada suppression."""


# ---------------------------------------------------------------------------
# Fungsi Utama
# ---------------------------------------------------------------------------


def check_suppression(
    customer_id: str,
    consent: CustomerConsent,
    complaint_tickets: List[ComplaintTicket],
) -> SuppressionCheckResult:
    """
    Memeriksa apakah pelanggan memiliki kondisi suppression mutlak yang
    memblokir pengiriman penawaran komersial.

    Pemeriksaan dilakukan secara berurutan (prioritas tertinggi ke terendah):
      1. Opt-Out Global: Memblokir SEMUA komunikasi. NO_ACTION mutlak.
      2. OPEN_SEVERE_COMPLAINT: Memblokir semua KOMERSIAL. Hanya COMPLAINT_RESOLUTION diizinkan.

    Args:
        customer_id: ID unik pelanggan.
        consent: Objek status consent/opt-in pelanggan.
        complaint_tickets: Daftar semua tiket keluhan pelanggan.

    Returns:
        SuppressionCheckResult berisi status suppression dan aksi yang diizinkan.

    Contoh:
        >>> consent = CustomerConsent("C001", global_opt_out=False)
        >>> tickets = [
        ...     ComplaintTicket("T001", "C001", ComplaintStatus.OPEN_SEVERE, "SEVERE", datetime.now())
        ... ]
        >>> result = check_suppression("C001", consent, tickets)
        >>> result.status
        'COMPLAINT_SUPPRESSED'
        >>> result.allowed_actions
        ['COMPLAINT_RESOLUTION']
    """
    # Validasi bahwa consent dan tickets adalah untuk pelanggan yang sama
    if consent.customer_id != customer_id:
        raise ValueError(
            f"Mismatch customer_id: consent milik '{consent.customer_id}' "
            f"tapi pemeriksaan untuk '{customer_id}'"
        )

    # --- Pemeriksaan 1: Global Opt-Out ---
    # Prioritas tertinggi. Jika Opt-Out, tidak ada aksi apapun yang boleh dikirim.
    if consent.global_opt_out:
        return SuppressionCheckResult(
            customer_id=customer_id,
            is_suppressed=True,
            suppression_reason=SuppressionReason.OPT_OUT,
            status=SuppressionReason.OPT_OUT.value,
            allowed_actions=[],  # Tidak ada aksi yang diizinkan
            message=(
                f"Pelanggan {customer_id} berstatus Global Opt-Out. "
                f"Seluruh komunikasi diblokir secara mutlak. Tidak ada pengecualian."
            ),
            is_global_opt_out=True,
            reason_code=REASON_CODE_OPT_OUT,
        )

    # --- Pemeriksaan 2: OPEN_SEVERE_COMPLAINT ---
    # Cari tiket keluhan aktif dengan status OPEN_SEVERE_COMPLAINT
    active_severe_complaints = [
        ticket
        for ticket in complaint_tickets
        if (
            ticket.customer_id == customer_id
            and ticket.status == ComplaintStatus.OPEN_SEVERE
        )
    ]

    if active_severe_complaints:
        return SuppressionCheckResult(
            customer_id=customer_id,
            is_suppressed=True,
            suppression_reason=SuppressionReason.COMPLAINT,
            status=SuppressionReason.COMPLAINT.value,
            allowed_actions=[COMPLAINT_ALLOWED_ACTION],  # Hanya ini yang diizinkan
            message=(
                f"Pelanggan {customer_id} memiliki {len(active_severe_complaints)} "
                f"tiket keluhan OPEN_SEVERE_COMPLAINT aktif "
                f"(ID: {[t.ticket_id for t in active_severe_complaints]}). "
                f"Seluruh penawaran komersial diblokir. "
                f"Hanya aksi '{COMPLAINT_ALLOWED_ACTION}' yang diizinkan."
            ),
            active_complaints=active_severe_complaints,
            reason_code=REASON_CODE_OPEN_SEVERE_COMPLAINT,
        )

    # --- Tidak Ada Suppression ---
    return SuppressionCheckResult(
        customer_id=customer_id,
        is_suppressed=False,
        suppression_reason=SuppressionReason.NONE,
        status="SUPPRESSION_CLEAR",
        allowed_actions=[
            "ALL"
        ],  # Semua aksi berpotensi diizinkan (tergantung policy lain)
        message=(
            f"Pelanggan {customer_id} tidak memiliki kondisi suppression aktif. "
            f"Lanjutkan evaluasi fatigue dan eligibility."
        ),
    )


def has_open_severe_complaint(
    customer_id: str,
    complaint_tickets: List[ComplaintTicket],
) -> bool:
    """
    Utilitas cepat untuk mengecek apakah pelanggan memiliki keluhan OPEN_SEVERE_COMPLAINT.

    Returns:
        bool: True jika ada keluhan OPEN_SEVERE aktif, False jika tidak.
    """
    return any(
        ticket.customer_id == customer_id
        and ticket.status == ComplaintStatus.OPEN_SEVERE
        for ticket in complaint_tickets
    )


def is_opted_out(consent: CustomerConsent, channel: Optional[str] = None) -> bool:
    """
    Mengecek status Opt-Out pelanggan untuk kanal tertentu atau secara global.

    Args:
        consent: Objek CustomerConsent pelanggan.
        channel: Nama kanal spesifik ('email', 'push', 'sms', 'whatsapp', 'phone').
                 Kanal internal ('task_rm', 'branch') tidak diatur consent pemasaran.
                 Jika None, memeriksa global_opt_out.

    Returns:
        bool: True jika pelanggan opt-out dari kanal tersebut.
    """
    if consent.global_opt_out:
        return True

    channel_map = {
        "email": not consent.email_opt_in,
        "push": not consent.push_opt_in,
        "sms": not consent.sms_opt_in,
        "whatsapp": not consent.whatsapp_opt_in,
        "phone": not consent.phone_opt_in,
    }

    if channel and channel.lower() in channel_map:
        return channel_map[channel.lower()]

    return False
