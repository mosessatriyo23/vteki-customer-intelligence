"""
context_factors.py — Faktor konteks bisnis yang menyertai keputusan NBA.

Ini BUKAN kontribusi model. Faktor konteks adalah fakta yang dihitung dengan aturan bisnis
deterministik dari data yang SUDAH menjadi masukan engine (profil kelayakan dan tiket keluhan),
sehingga tidak ada angka, ambang, atau data baru yang dikarang di sini.

Dua faktor aktif (lihat docs/christ_business/approved/reason_taxonomy.md §3):
  * MEMBERSHIP_EXPIRING  - membership aktif dan sisa masa berlaku <= jendela RENEWAL_REMINDER
                           (15 hari, aturan yang sama dengan evaluator.py).
  * UNRESOLVED_COMPLAINT - ada tiket keluhan pelanggan ini yang belum selesai
                           (OPEN_SEVERE, OPEN_MILD, atau IN_PROGRESS).

`NO_CROSS_CATEGORY` SENGAJA tidak ada: data kepemilikan kategori belum tersedia
(target_definitions.md §3.2.C), jadi faktor itu tidak boleh dikeluarkan.

Aturan keras:
  * Sumber `None` (belum tersambung) tidak menghasilkan faktor apa pun; tidak ada tebakan.
  * Data milik pelanggan lain diabaikan.
  * Urutan keluaran tetap: MEMBERSHIP_EXPIRING, lalu UNRESOLVED_COMPLAINT.
  * Teks netral: tidak menyiratkan sebab dan tidak menyebut data pribadi.
  * Fungsi ini TIDAK memengaruhi pemilihan aksi; ia hanya menjelaskan.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

from services.decision.nba.engine import EligibilityProfile
from services.decision.policy.suppression import ComplaintStatus, ComplaintTicket

MEMBERSHIP_EXPIRING = "MEMBERSHIP_EXPIRING"
UNRESOLVED_COMPLAINT = "UNRESOLVED_COMPLAINT"

SOURCE_BUSINESS_RULE = "BUSINESS_RULE"

MEMBERSHIP_EXPIRING_WINDOW_DAYS = 15
"""Sama dengan jendela RENEWAL_REMINDER di evaluator.py; dijaga test agar tidak berbeda."""

UNRESOLVED_COMPLAINT_STATUSES = frozenset(
    {
        ComplaintStatus.OPEN_SEVERE,
        ComplaintStatus.OPEN_MILD,
        ComplaintStatus.IN_PROGRESS,
    }
)

_TEXTS = {
    MEMBERSHIP_EXPIRING: (
        f"Masa keanggotaan akan berakhir dalam {MEMBERSHIP_EXPIRING_WINDOW_DAYS} hari "
        "atau kurang."
    ),
    UNRESOLVED_COMPLAINT: "Ada keluhan pelanggan yang belum selesai ditangani.",
}


@dataclass(frozen=True)
class ContextFactor:
    """Satu faktor konteks: kode taxonomy, kalimat Indonesia, dan sumbernya."""

    code: str
    text: str
    source: str = SOURCE_BUSINESS_RULE

    def as_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "text": self.text, "source": self.source}


def compute_context_factors(
    *,
    customer_ref: str,
    eligibility: Optional[EligibilityProfile],
    complaint_tickets: Optional[Sequence[ComplaintTicket]],
) -> Tuple[ContextFactor, ...]:
    """
    Menghitung faktor konteks yang berlaku untuk satu pelanggan.

    `None` = sumber belum tersambung -> faktor dari sumber itu tidak dihitung.
    `[]`   = sumber tersambung dan memang kosong -> tidak ada faktor dari sumber itu.
    """
    factors: list[ContextFactor] = []

    if (
        eligibility is not None
        and eligibility.customer_id == customer_ref
        and eligibility.has_active_membership
        and eligibility.membership_days_remaining <= MEMBERSHIP_EXPIRING_WINDOW_DAYS
    ):
        factors.append(ContextFactor(MEMBERSHIP_EXPIRING, _TEXTS[MEMBERSHIP_EXPIRING]))

    if complaint_tickets is not None and any(
        ticket.customer_id == customer_ref
        and ticket.status in UNRESOLVED_COMPLAINT_STATUSES
        for ticket in complaint_tickets
    ):
        factors.append(
            ContextFactor(UNRESOLVED_COMPLAINT, _TEXTS[UNRESOLVED_COMPLAINT])
        )

    return tuple(factors)
