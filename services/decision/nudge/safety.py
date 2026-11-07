"""
safety.py — Safety Scanner (Forbidden Claims Detector)
======================================================
Memindai teks draf pesan dengan blacklist regex dan memblokir klaim terlarang:

    1. MEDICAL_CLAIM       - klaim medis / kesehatan (menyembuhkan, mengobati, dll.)
    2. ABSOLUTE_GUARANTEE  - jaminan mutlak ("100% dijamin", "pasti berhasil", "tanpa risiko")
    3. DISCOUNT_ABOVE_CAP  - diskon/potongan melebihi pagu `MAX_DISCOUNT_PERCENT`
    4. UNRESOLVED_PLACEHOLDER - sisa placeholder `{...}` yang belum terisi

Draf yang melanggar mendapat status `MESSAGE_BLOCKED_BY_GUARDRAIL`.

Modul ini 100% offline (tanpa jaringan / LLM) dan deterministik.

CATATAN PENTING — PAGU DISKON BELUM DITETAPKAN:
Panduan_Kerja_Christ (Minggu 8) menyebut "diskon melebihi pagu", tetapi nilai pagu TIDAK
tertulis di Requirement_Capstone.md, target_definitions.md, maupun kontrak K-06...K-11
(Requirement hanya menyebut "Diskon Berbatas Waktu" / "Band Rendah" tanpa angka).
Karena itu `MAX_DISCOUNT_PERCENT = None` (tidak ada angka karangan) dan scanner bersifat
FAIL-CLOSED: selama pagu belum ditetapkan, SETIAP klaim diskon berbentuk persentase
diblokir. Setelah pagu resmi diputuskan, isi `MAX_DISCOUNT_PERCENT` atau berikan
`max_discount_percent` saat memanggil `scan_message()`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Pattern, Tuple

# ---------------------------------------------------------------------------
# Konstanta
# ---------------------------------------------------------------------------

STATUS_SAFE = "SAFE"
STATUS_BLOCKED = "MESSAGE_BLOCKED_BY_GUARDRAIL"

MAX_DISCOUNT_PERCENT: Optional[float] = None
"""Pagu diskon maksimum (%). None = belum ditetapkan -> semua diskon persentase diblokir."""

RULE_MEDICAL = "MEDICAL_CLAIM"
RULE_GUARANTEE = "ABSOLUTE_GUARANTEE"
RULE_DISCOUNT = "DISCOUNT_ABOVE_CAP"
RULE_PLACEHOLDER = "UNRESOLVED_PLACEHOLDER"

_FLAGS = re.IGNORECASE

# (rule_id, regex, deskripsi). Teks dinormalisasi (huruf kecil, spasi tunggal) sebelum dicocokkan.
_BLACKLIST: List[Tuple[str, Pattern[str], str]] = [
    (
        RULE_MEDICAL,
        re.compile(
            r"\b(menyembuhkan|sembuh\s+total|mengobati|pengobatan|obat\s+(?:mujarab|ajaib)|"
            r"terapi\s+penyembuhan|mencegah\s+(?:penyakit|kanker|diabetes|covid)|"
            r"bebas\s+penyakit|terbukti\s+secara\s+klinis|diagnosis|"
            r"cure[sd]?|heals?|treats?\s+(?:disease|illness))\b",
            _FLAGS,
        ),
        "Klaim medis/kesehatan dilarang pada pesan promosi.",
    ),
    (
        RULE_GUARANTEE,
        re.compile(
            r"(100\s*%\s*(?:dijamin|pasti|aman|berhasil|efektif|garansi|terjamin)|"
            r"(?:dijamin|garansi|jaminan)\s*100\s*%|"
            r"seratus\s+persen\s+(?:dijamin|pasti|aman|berhasil)|"
            r"pasti\s+(?:berhasil|sembuh|untung|menang)|"
            r"dijamin\s+(?:berhasil|untung|sembuh)|"
            r"tanpa\s+risiko|bebas\s+risiko|zero\s+risk|guaranteed|risk[- ]free)",
            _FLAGS,
        ),
        "Jaminan mutlak (mis. 100% dijamin / pasti berhasil / tanpa risiko) dilarang.",
    ),
    (
        RULE_PLACEHOLDER,
        re.compile(r"\{[^{}]*\}|\{\{|\}\}"),
        "Terdapat placeholder yang belum terisi.",
    ),
]

# Diskon: "diskon 40%", "potongan 50 %", "hemat 60%", "40% off", "diskon hingga 70 persen"
_DISCOUNT_PATTERNS: List[Pattern[str]] = [
    re.compile(
        r"(?:diskon|potongan|hemat|discount|cashback)\D{0,20}?(\d{1,3}(?:[.,]\d+)?)\s*(?:%|persen)",
        _FLAGS,
    ),
    re.compile(
        r"(\d{1,3}(?:[.,]\d+)?)\s*(?:%|persen)\s*(?:diskon|potongan|off|discount|cashback)",
        _FLAGS,
    ),
]


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SafetyViolation:
    """Satu pelanggaran yang ditemukan pada teks."""

    rule_id: str
    matched_text: str
    description: str


@dataclass
class SafetyScanResult:
    """Hasil pemindaian satu teks."""

    is_safe: bool
    status: str
    violations: List[SafetyViolation] = field(default_factory=list)

    @property
    def rule_ids(self) -> List[str]:
        """Daftar rule_id unik (urutan kemunculan) yang dilanggar."""
        seen: List[str] = []
        for v in self.violations:
            if v.rule_id not in seen:
                seen.append(v.rule_id)
        return seen


# ---------------------------------------------------------------------------
# Fungsi utama
# ---------------------------------------------------------------------------


_INVISIBLE_CHARS = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u00ad]")


def _normalize(text: str) -> str:
    """
    Huruf kecil + spasi tunggal + buang karakter tak terlihat (zero-width, soft hyphen)
    agar pencocokan tidak mudah dihindari.
    """
    text = _INVISIBLE_CHARS.sub("", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _to_percent(raw: str) -> Optional[float]:
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def scan_message(
    text: str, max_discount_percent: Optional[float] = None
) -> SafetyScanResult:
    """
    Memindai `text`.

    Args:
        text: Teks draf pesan.
        max_discount_percent: Pagu diskon (%). Jika None dipakai `MAX_DISCOUNT_PERCENT`;
            jika itu juga None (belum ditetapkan) maka SETIAP diskon persentase diblokir.
            Diskon di ATAS pagu diblokir; tepat sama dengan pagu diizinkan.

    Returns:
        SafetyScanResult. `is_safe=False` dan `status=MESSAGE_BLOCKED_BY_GUARDRAIL`
        jika ada pelanggaran.

    Raises:
        TypeError: jika `text` bukan str.
    """
    if not isinstance(text, str):
        raise TypeError("text harus berupa str")

    normalized = _normalize(text)
    violations: List[SafetyViolation] = []
    cap = (
        max_discount_percent
        if max_discount_percent is not None
        else MAX_DISCOUNT_PERCENT
    )

    for rule_id, pattern, description in _BLACKLIST:
        for match in pattern.finditer(normalized):
            violations.append(SafetyViolation(rule_id, match.group(0), description))

    for pattern in _DISCOUNT_PATTERNS:
        for match in pattern.finditer(normalized):
            pct = _to_percent(match.group(1))
            if pct is None:
                continue
            if cap is None:
                violations.append(
                    SafetyViolation(
                        RULE_DISCOUNT,
                        match.group(0),
                        "Pagu diskon belum ditetapkan; klaim diskon persentase diblokir.",
                    )
                )
            elif pct > cap:
                violations.append(
                    SafetyViolation(
                        RULE_DISCOUNT,
                        match.group(0),
                        f"Diskon {pct:g}% melebihi pagu {cap:g}%.",
                    )
                )

    if violations:
        return SafetyScanResult(False, STATUS_BLOCKED, violations)
    return SafetyScanResult(True, STATUS_SAFE, [])
