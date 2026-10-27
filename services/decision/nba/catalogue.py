"""
catalogue.py — NBA Action Catalogue
=====================================
Mendefinisikan 11 aksi standar sistem Next-Best-Action beserta syarat pemicunya.

Setiap aksi memiliki:
- ID unik (action_id)
- Kategori bisnis
- Syarat pemicu & kelayakan (eligibility)
- Kanal yang diizinkan
- Band insentif
- Bobot aksi (action_weight) untuk formula Expected Value

Referensi: Requirement_Capstone.md Bab 4 (FRD §10.1 / TRD §10.1)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ActionCategory(str, Enum):
    """Kategori bisnis untuk setiap aksi NBA."""
    PROTECTION = "Proteksi / System"
    SERVICE = "Layanan"
    RETENTION_SPECIAL = "Retensi Khusus"
    RETENTION = "Retensi"
    GROWTH = "Pertumbuhan"
    MEMBERSHIP = "Retensi / Keanggotaan"
    REMINDER = "Layanan / Pengingat"
    EDUCATION = "Edukasi Pelanggan"
    APPRECIATION = "Apresiasi"
    REACTIVATION = "Reaktivasi"


class IncentiveBand(str, Enum):
    """Band insentif / biaya yang diasosiasikan dengan aksi."""
    NONE = "Tanpa Insentif"
    LOW = "Band Rendah"
    MEDIUM = "Band Sedang"
    HIGH = "Band Tinggi"
    LOYALTY_POINTS = "Hadiah / Poin Loyalitas"
    DISCOUNT_LIMITED = "Diskon Berbatas Waktu"


# ---------------------------------------------------------------------------
# Data Class
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Action:
    """
    Definisi satu aksi dalam katalog NBA.

    Attributes:
        action_id: ID unik aksi (contoh: "NO_ACTION").
        name: Nama deskriptif aksi.
        category: Kategori bisnis aksi.
        description: Penjelasan singkat tujuan aksi.
        trigger_conditions: Daftar kondisi pemicu dalam bahasa bisnis.
        allowed_channels: Kanal komunikasi yang diizinkan.
        incentive_band: Band insentif yang terkait.
        action_weight: Bobot prioritas strategis untuk formula EV (0.0 - 2.0).
        is_commercial: Apakah aksi ini bersifat komersial (dihitung dalam fatigue cap).
        blocks_all_commercial: Jika True, aksi ini menghentikan semua penawaran komersial.
    """
    action_id: str
    name: str
    category: ActionCategory
    description: str
    trigger_conditions: List[str]
    allowed_channels: List[str]
    incentive_band: IncentiveBand
    action_weight: float
    is_commercial: bool = True
    blocks_all_commercial: bool = False


# ---------------------------------------------------------------------------
# Katalog Aksi — 11 Aksi Standar Sistem
# ---------------------------------------------------------------------------

ACTION_CATALOGUE: Dict[str, Action] = {

    # 1. NO_ACTION — Aksi Protektif Default
    "NO_ACTION": Action(
        action_id="NO_ACTION",
        name="No Action",
        category=ActionCategory.PROTECTION,
        description=(
            "Aksi default sistem ketika tidak ada aksi komersial yang aman atau layak "
            "untuk dikirimkan. Dipilih otomatis saat salah satu pemeriksaan protektif gagal "
            "atau Expected Value semua kandidat bernilai negatif."
        ),
        trigger_conditions=[
            "Consent = Opt-Out (global atau kanal spesifik)",
            "Frequency Cap tercapai (FREQ_CAP_SUPPRESSED)",
            "Semua kandidat aksi diblokir (ALL_CANDIDATES_BLOCKED)",
            "Expected Value semua kandidat < min_ev_threshold",
            "Skor AI kadaluarsa (valid_until terlewati)",
        ],
        allowed_channels=[],
        incentive_band=IncentiveBand.NONE,
        action_weight=0.0,
        is_commercial=False,
        blocks_all_commercial=False,
    ),

    # 2. COMPLAINT_RESOLUTION — Prioritas Layanan Tertinggi
    "COMPLAINT_RESOLUTION": Action(
        action_id="COMPLAINT_RESOLUTION",
        name="Complaint Resolution",
        category=ActionCategory.SERVICE,
        description=(
            "Penugasan tim Relationship Manager atau cabang untuk menyelesaikan "
            "keluhan aktif pelanggan. Menghentikan SELURUH pesan promosi komersial "
            "hingga keluhan tuntas diselesaikan."
        ),
        trigger_conditions=[
            "Pelanggan memiliki tiket keluhan status OPEN_SEVERE_COMPLAINT",
            "Prioritas #1 — mengesampingkan semua aksi komersial lainnya",
        ],
        allowed_channels=["task_rm", "branch"],
        incentive_band=IncentiveBand.NONE,
        action_weight=2.0,  # Bobot tertinggi sebagai prioritas layanan
        is_commercial=False,  # Bukan aksi komersial, tidak dihitung dalam fatigue cap
        blocks_all_commercial=True,
    ),

    # 3. RELATIONSHIP_MANAGER_CONTACT — Retensi Pelanggan Premium
    "RELATIONSHIP_MANAGER_CONTACT": Action(
        action_id="RELATIONSHIP_MANAGER_CONTACT",
        name="Relationship Manager Contact",
        category=ActionCategory.RETENTION_SPECIAL,
        description=(
            "Kontak langsung oleh Relationship Manager cabang untuk pelanggan "
            "bernilai sangat tinggi yang berisiko churn atau memiliki keluhan aktif."
        ),
        trigger_conditions=[
            "CLV Tier = PLATINUM (CLV >= Rp 1.000.000)",
            "Churn Risk = HIGH atau VERY_HIGH",
            "Lifecycle = AT_RISK atau DORMANT",
            "Consent = Opt-In pada kanal yang relevan",
        ],
        allowed_channels=["task_rm", "branch", "phone"],
        incentive_band=IncentiveBand.MEDIUM,
        action_weight=1.8,
        is_commercial=True,
    ),

    # 4. RETENTION_OUTREACH — Upaya Retensi Standar
    "RETENTION_OUTREACH": Action(
        action_id="RETENTION_OUTREACH",
        name="Retention Outreach",
        category=ActionCategory.RETENTION,
        description=(
            "Komunikasi retensi yang ditargetkan untuk pelanggan berisiko churn "
            "dengan nilai tinggi, berupa penawaran diskon berbatas waktu atau penawaran khusus."
        ),
        trigger_conditions=[
            "Churn Risk = HIGH",
            "CLV Tier = GOLD atau PLATINUM",
            "Lifecycle = AT_RISK atau DORMANT",
            "Consent = Opt-In",
            "Frequency Cap belum tercapai",
        ],
        allowed_channels=["email", "push"],
        incentive_band=IncentiveBand.DISCOUNT_LIMITED,
        action_weight=1.6,
        is_commercial=True,
    ),

    # 5. CROSS_SELL — Penawaran Lintas Kategori
    "CROSS_SELL": Action(
        action_id="CROSS_SELL",
        name="Cross-Category Introduction",
        category=ActionCategory.GROWTH,
        description=(
            "Memperkenalkan produk atau layanan dari kategori bersebelahan "
            "kepada pelanggan aktif/loyal yang belum pernah mencobanya."
        ),
        trigger_conditions=[
            "Lifecycle = ACTIVE atau LOYAL",
            "Propensity Purchase tinggi (>= 0.6)",
            "Pelanggan belum memiliki produk di kategori yang ditawarkan",
            "Consent = Opt-In",
            "Frequency Cap belum tercapai",
        ],
        allowed_channels=["email", "push"],
        incentive_band=IncentiveBand.LOW,
        action_weight=1.2,
        is_commercial=True,
    ),

    # 6. UPSELL — Upgrade Keanggotaan / Paket Premium
    "UPSELL": Action(
        action_id="UPSELL",
        name="Membership Upgrade / Upsell",
        category=ActionCategory.GROWTH,
        description=(
            "Penawaran upgrade membership atau paket premium kepada pelanggan "
            "aktif/loyal yang memiliki kecenderungan tinggi untuk upgrade."
        ),
        trigger_conditions=[
            "Lifecycle = ACTIVE atau LOYAL",
            "Tenure >= 60 hari",
            "Propensity Renew/Upgrade tinggi (>= 0.6)",
            "Consent = Opt-In",
            "Frequency Cap belum tercapai",
        ],
        allowed_channels=["email", "push"],
        incentive_band=IncentiveBand.MEDIUM,
        action_weight=1.4,
        is_commercial=True,
    ),

    # 7. RENEWAL_REMINDER — Pengingat Perpanjangan Membership
    "RENEWAL_REMINDER": Action(
        action_id="RENEWAL_REMINDER",
        name="Renewal Reminder",
        category=ActionCategory.MEMBERSHIP,
        description=(
            "Pengingat perpanjangan membership yang akan segera kadaluarsa, "
            "dikirimkan dalam jendela 15 hari sebelum kadaluarsa."
        ),
        trigger_conditions=[
            "Sisa masa keanggotaan <= 15 hari",
            "Membership belum diperpanjang",
            "Propensity Renew tinggi",
            "Consent = Opt-In",
        ],
        allowed_channels=["email", "push"],
        incentive_band=IncentiveBand.NONE,
        action_weight=1.5,
        is_commercial=True,
    ),

    # 8. SERVICE_REMINDER — Pengingat Jadwal Layanan
    "SERVICE_REMINDER": Action(
        action_id="SERVICE_REMINDER",
        name="Service Reminder",
        category=ActionCategory.REMINDER,
        description=(
            "Pengingat jadwal kunjungan rutin atau habisnya produk pakai "
            "tanpa unsur promosi komersial."
        ),
        trigger_conditions=[
            "Jadwal kunjungan / produk habis pakai mendekati (berdasarkan pola historis)",
            "Tidak ada keluhan aktif",
            "Consent = Opt-In pada kanal yang relevan",
        ],
        allowed_channels=["push", "email"],
        incentive_band=IncentiveBand.NONE,
        action_weight=1.0,
        is_commercial=False,  # Non-komersial, dikecualikan dari fatigue cap
    ),

    # 9. EDUCATION — Edukasi Pelanggan Baru
    "EDUCATION": Action(
        action_id="EDUCATION",
        name="Product & Service Education",
        category=ActionCategory.EDUCATION,
        description=(
            "Konten edukasi pemakaian produk/layanan yang ditargetkan untuk "
            "pelanggan baru atau pelanggan dengan risiko churn rendah."
        ),
        trigger_conditions=[
            "Lifecycle = NEW",
            "Churn Risk = LOW",
            "Consent = Opt-In",
            "Frequency Cap belum tercapai",
        ],
        allowed_channels=["email", "push"],
        incentive_band=IncentiveBand.NONE,
        action_weight=0.8,
        is_commercial=True,
    ),

    # 10. LOYALTY_REWARD — Apresiasi Pelanggan Setia
    "LOYALTY_REWARD": Action(
        action_id="LOYALTY_REWARD",
        name="Loyalty Reward",
        category=ActionCategory.APPRECIATION,
        description=(
            "Program apresiasi berupa hadiah atau poin loyalitas untuk "
            "pelanggan setia bernilai tinggi."
        ),
        trigger_conditions=[
            "Lifecycle = LOYAL",
            "CLV Tier = GOLD atau PLATINUM",
            "Frequency Cap belum tercapai",
            "Consent = Opt-In",
        ],
        allowed_channels=["email", "push"],
        incentive_band=IncentiveBand.LOYALTY_POINTS,
        action_weight=1.3,
        is_commercial=True,
    ),

    # 11. WIN_BACK_OFFER — Penawaran Reaktivasi
    "WIN_BACK_OFFER": Action(
        action_id="WIN_BACK_OFFER",
        name="Win-Back Offer",
        category=ActionCategory.REACTIVATION,
        description=(
            "Penawaran khusus reaktivasi dengan voucher atau diskon signifikan "
            "untuk menarik kembali pelanggan yang sudah lama tidak aktif."
        ),
        trigger_conditions=[
            "Lifecycle = DORMANT (91-180 hari pasif)",
            "CLV historis = GOLD atau PLATINUM",
            "Belum ada tawaran win-back aktif dalam 30 hari terakhir",
            "Consent = Opt-In",
            "Frequency Cap belum tercapai",
        ],
        allowed_channels=["email", "push"],
        incentive_band=IncentiveBand.MEDIUM,
        action_weight=1.5,
        is_commercial=True,
    ),
}


# ---------------------------------------------------------------------------
# Fungsi Utilitas Katalog
# ---------------------------------------------------------------------------

def get_action(action_id: str) -> Optional[Action]:
    """
    Mengambil definisi aksi dari katalog berdasarkan action_id.

    Args:
        action_id: ID aksi yang dicari.

    Returns:
        Action jika ditemukan, None jika tidak ada.
    """
    return ACTION_CATALOGUE.get(action_id)


def get_actions_by_category(category: ActionCategory) -> List[Action]:
    """
    Mengambil daftar semua aksi dalam kategori tertentu.

    Args:
        category: Kategori aksi yang dicari.

    Returns:
        List of Action yang termasuk dalam kategori tersebut.
    """
    return [
        action
        for action in ACTION_CATALOGUE.values()
        if action.category == category
    ]


def list_all_action_ids() -> List[str]:
    """Mengembalikan daftar semua action_id yang terdaftar dalam katalog."""
    return list(ACTION_CATALOGUE.keys())
