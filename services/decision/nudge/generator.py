"""
generator.py — Personalized Nudge Generator
===========================================
Membuat DRAF pesan personal dari Fact Package resmi memakai substitusi variabel
WHITELIST. Tidak ada teks yang "dikarang": fakta yang hilang menghasilkan penolakan,
bukan tebakan.

Aturan:
- Variabel yang boleh: `first_name`, `preferred_branch`, `points_balance`, `offer_validity`.
- Setiap draf berstatus `GENERATED_DRAFT` dan WAJIB persetujuan manusia sebelum dirilis
  (`requires_human_approval=True`, `is_releasable=False` sampai `approve_draft()`).
- Draf yang melanggar Safety Scanner -> `MESSAGE_BLOCKED_BY_GUARDRAIL` dan tidak dapat
  disetujui.
- 100% offline: tanpa jaringan, tanpa LLM.

Dipanggil dari luar (mis. James di `api/`):
    from services.decision.nudge.generator import generate_nudge
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any, Dict, FrozenSet, List, Mapping, Optional

from services.decision.nba.catalogue import get_action
from services.decision.nudge import safety
from services.decision.nudge.safety import (
    ESCALATION_CODE,
    STATUS_BLOCKED,
    SafetyViolation,
    scan_message,
)

# ---------------------------------------------------------------------------
# Konstanta
# ---------------------------------------------------------------------------

ALLOWED_VARIABLES: FrozenSet[str] = frozenset(
    {"first_name", "preferred_branch", "points_balance", "offer_validity"}
)

STATUS_GENERATED_DRAFT = "GENERATED_DRAFT"
STATUS_BLOCKED_BY_GUARDRAIL = STATUS_BLOCKED  # "MESSAGE_BLOCKED_BY_GUARDRAIL"
STATUS_MISSING_FACTS = "DRAFT_REJECTED_MISSING_FACTS"
STATUS_NO_TEMPLATE = "NO_TEMPLATE_FOR_ACTION"
STATUS_CHANNEL_NOT_ALLOWED = "CHANNEL_NOT_ALLOWED"

MAX_FACT_LENGTH = 60
_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")

# Template per aksi. Hanya memakai variabel whitelist. Aksi RM/Complaint/NO_ACTION
# tidak memiliki template teks (bukan pesan promosi otomatis).
TEMPLATES: Dict[str, str] = {
    "RETENTION_OUTREACH": (
        "Halo {first_name}, kami rindu melihat Anda di cabang {preferred_branch}. "
        "Ada penawaran khusus untuk Anda yang berlaku sampai {offer_validity}."
    ),
    "CROSS_SELL": (
        "Halo {first_name}, ada produk baru yang mungkin cocok untuk Anda "
        "di cabang {preferred_branch}. Kunjungi kami kapan saja."
    ),
    "UPSELL": (
        "Halo {first_name}, tingkatkan keanggotaan Anda dan nikmati manfaat tambahan. "
        "Penawaran berlaku sampai {offer_validity}."
    ),
    "RENEWAL_REMINDER": (
        "Halo {first_name}, keanggotaan Anda akan segera berakhir. "
        "Perpanjang sekarang di cabang {preferred_branch}."
    ),
    "SERVICE_REMINDER": (
        "Halo {first_name}, ini pengingat jadwal layanan Anda di cabang {preferred_branch}."
    ),
    "EDUCATION": (
        "Halo {first_name}, kenali layanan dan produk kami lebih dekat "
        "di cabang {preferred_branch}."
    ),
    "LOYALTY_REWARD": (
        "Halo {first_name}, terima kasih atas kesetiaan Anda. "
        "Saldo poin Anda saat ini {points_balance} poin."
    ),
    "WIN_BACK_OFFER": (
        "Halo {first_name}, kami ingin menyambut Anda kembali di cabang {preferred_branch}. "
        "Penawaran spesial berlaku sampai {offer_validity}."
    ),
}


def _validate_templates() -> None:
    """Pastikan semua template hanya memakai variabel whitelist (dicek saat import)."""
    for action_id, template in TEMPLATES.items():
        used = set(_PLACEHOLDER_RE.findall(template))
        illegal = used - ALLOWED_VARIABLES
        if illegal:
            raise ValueError(
                f"Template {action_id} memakai variabel di luar whitelist: {sorted(illegal)}"
            )


_validate_templates()


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NudgeDraft:
    """Draf pesan hasil generator."""

    customer_id: str
    action_id: str
    channel: str
    status: str
    body: str = ""
    requires_human_approval: bool = True
    approved_by: Optional[str] = None
    variables_used: Dict[str, str] = field(default_factory=dict)
    missing_facts: List[str] = field(default_factory=list)
    violations: List[SafetyViolation] = field(default_factory=list)
    reason: str = ""
    escalation: Optional[str] = None
    """`INCENTIVE_ESCALATED` jika diblokir karena pagu diskon: wajib dieskalasi ke Business Approver."""

    @property
    def is_releasable(self) -> bool:
        """True hanya jika draf aman DAN sudah disetujui manusia."""
        return self.status == STATUS_GENERATED_DRAFT and self.approved_by is not None


# ---------------------------------------------------------------------------
# Fungsi utama
# ---------------------------------------------------------------------------


def required_facts(action_id: str) -> List[str]:
    """Fakta (variabel) yang wajib ada pada Fact Package untuk `action_id`."""
    template = TEMPLATES.get(action_id)
    if template is None:
        return []
    found: List[str] = []
    for name in _PLACEHOLDER_RE.findall(template):
        if name not in found:
            found.append(name)
    return found


def _clean_fact(value: Any) -> str:
    """Mengubah nilai fakta menjadi teks aman: tanpa kurung kurawal/karakter kontrol."""
    if isinstance(value, (datetime, date)):
        text = value.strftime("%d-%m-%Y")
    elif isinstance(value, float) and value.is_integer():
        text = str(int(value))
    else:
        text = str(value)
    text = re.sub(r"[\x00-\x1f\x7f{}]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_FACT_LENGTH]


def _effective_discount_cap(
    action: object, override: Optional[float]
) -> Optional[float]:
    """
    Batas diskon yang berlaku untuk sebuah aksi.

    - `override` (parameter pemanggil) dipakai apa adanya bila diberikan.
    - Selain itu: pagu global `safety.MAX_DISCOUNT_PERCENT`; jika None -> None (fail-closed).
    - Bila band insentif aksi punya batas sendiri (`BAND_MAX_DISCOUNT_PERCENT`), dipakai nilai
      yang LEBIH KECIL antara pagu global dan batas band.
    """
    if override is not None:
        return override
    global_cap = safety.MAX_DISCOUNT_PERCENT
    if global_cap is None:
        return None
    band_cap = safety.BAND_MAX_DISCOUNT_PERCENT.get(
        getattr(getattr(action, "incentive_band", None), "name", "")
    )
    return global_cap if band_cap is None else min(global_cap, band_cap)


def generate_nudge(
    customer_id: str,
    action_id: str,
    channel: str,
    fact_package: Mapping[str, Any],
    max_discount_percent: Optional[float] = None,
) -> NudgeDraft:
    """
    Membuat draf pesan untuk satu pelanggan.

    Urutan pemeriksaan:
      1. Aksi harus punya template        -> `NO_TEMPLATE_FOR_ACTION`
      2. Kanal harus diizinkan aksi       -> `CHANNEL_NOT_ALLOWED`
      3. Semua fakta wajib harus ada      -> `DRAFT_REJECTED_MISSING_FACTS`
      4. Safety Scanner pada teks akhir   -> `MESSAGE_BLOCKED_BY_GUARDRAIL`
      5. Lolos semua                      -> `GENERATED_DRAFT` (butuh persetujuan manusia)

    Fakta di luar whitelist pada `fact_package` DIABAIKAN (tidak pernah disisipkan).
    """
    channel_l = channel.lower()
    template = TEMPLATES.get(action_id)
    if template is None:
        return NudgeDraft(
            customer_id=customer_id,
            action_id=action_id,
            channel=channel_l,
            status=STATUS_NO_TEMPLATE,
            reason=f"Aksi '{action_id}' tidak memiliki template pesan otomatis.",
        )

    action = get_action(action_id)
    if action is None or channel_l not in [c.lower() for c in action.allowed_channels]:
        return NudgeDraft(
            customer_id=customer_id,
            action_id=action_id,
            channel=channel_l,
            status=STATUS_CHANNEL_NOT_ALLOWED,
            reason=f"Kanal '{channel_l}' tidak diizinkan untuk aksi '{action_id}'.",
        )

    needed = required_facts(action_id)
    values: Dict[str, str] = {}
    missing: List[str] = []
    for name in needed:
        raw = fact_package.get(name)
        cleaned = "" if raw is None else _clean_fact(raw)
        if cleaned == "":
            missing.append(name)
        else:
            values[name] = cleaned

    if missing:
        return NudgeDraft(
            customer_id=customer_id,
            action_id=action_id,
            channel=channel_l,
            status=STATUS_MISSING_FACTS,
            missing_facts=missing,
            reason=f"Fakta wajib belum lengkap: {missing}. Pesan tidak dibuat.",
        )

    # Substitusi aman: hanya variabel whitelist, tanpa str.format (tanpa akses atribut).
    body = _PLACEHOLDER_RE.sub(lambda m: values[m.group(1)], template)

    scan = scan_message(
        body,
        max_discount_percent=_effective_discount_cap(action, max_discount_percent),
    )
    if not scan.is_safe:
        return NudgeDraft(
            customer_id=customer_id,
            action_id=action_id,
            channel=channel_l,
            status=STATUS_BLOCKED_BY_GUARDRAIL,
            body=body,
            variables_used=values,
            violations=list(scan.violations),
            reason="Draf diblokir Safety Scanner: " + ", ".join(scan.rule_ids),
            escalation=ESCALATION_CODE if scan.requires_escalation else None,
        )

    return NudgeDraft(
        customer_id=customer_id,
        action_id=action_id,
        channel=channel_l,
        status=STATUS_GENERATED_DRAFT,
        body=body,
        variables_used=values,
        reason="Draf dibuat. Menunggu persetujuan manusia sebelum dirilis.",
    )


def approve_draft(draft: NudgeDraft, approver_id: str) -> NudgeDraft:
    """
    Mencatat persetujuan manusia pada draf. Hanya draf `GENERATED_DRAFT` yang bisa disetujui.

    Raises:
        ValueError: `approver_id` kosong, atau draf bukan `GENERATED_DRAFT`
            (mis. diblokir guardrail / fakta kurang).
    """
    if not approver_id or not approver_id.strip():
        raise ValueError("approver_id wajib diisi (persetujuan harus oleh manusia).")
    if draft.status != STATUS_GENERATED_DRAFT:
        raise ValueError(
            f"Draf berstatus '{draft.status}' tidak dapat disetujui; "
            f"hanya '{STATUS_GENERATED_DRAFT}'."
        )
    return replace(draft, approved_by=approver_id.strip())
