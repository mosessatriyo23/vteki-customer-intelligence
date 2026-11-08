"""
evaluator.py — Evaluator 5 Masukan Independen NBA
=================================================
Setiap "gerbang" (gate) dievaluasi TERPISAH dan mengembalikan `GateResult`
(lolos/gagal + alasan), sehingga mudah diaudit dan dimasukkan ke `checks[]` K-07.

5 Masukan Independen (Requirement_Capstone.md Bab 3):
    1. ML_SCORE             - Skor Prediksi ML (default jika skor kedaluwarsa)
    2. BUSINESS_ELIGIBILITY - Kelayakan bisnis: tenure/lifecycle/CLV DAN status keluhan aktif
                              (OPEN_SEVERE_COMPLAINT memblokir promosi) — Bab 3 baris 2
    3. CUSTOMER_CONSENT     - Opt-In/Opt-Out. Opt-Out = TRUE -> NO_ACTION
    4. CONTACT_POLICY       - Batas frekuensi kontak (FREQ_CAP_SUPPRESSED) — Bab 3 baris 4
    5. PRODUCT_SUITABILITY  - Ketersediaan & kesesuaian produk (tanpa klaim medis)

Prinsip: "Skor tinggi bukan izin" — gerbang 2-5 tidak pernah dilonggarkan oleh skor AI.
Fungsi di sini murni (tanpa I/O).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from services.decision.policy.fatigue import FatigueCheckResult
from services.decision.policy.suppression import (
    CustomerConsent,
    SuppressionCheckResult,
    SuppressionReason,
    is_opted_out,
)

if TYPE_CHECKING:  # hindari import melingkar dengan engine.py
    from services.decision.nba.engine import (
        AIScores,
        EligibilityProfile,
        ProductSuitability,
    )


# ---------------------------------------------------------------------------
# Konstanta
# ---------------------------------------------------------------------------

GATE_ML_SCORE = "ML_SCORE"
GATE_BUSINESS_ELIGIBILITY = "BUSINESS_ELIGIBILITY"
GATE_CUSTOMER_CONSENT = "CUSTOMER_CONSENT"
GATE_CONTACT_POLICY = "CONTACT_POLICY"
GATE_PRODUCT_SUITABILITY = "PRODUCT_SUITABILITY"

ALL_GATES = (
    GATE_ML_SCORE,
    GATE_BUSINESS_ELIGIBILITY,
    GATE_CUSTOMER_CONSENT,
    GATE_CONTACT_POLICY,
    GATE_PRODUCT_SUITABILITY,
)

# Pemetaan gerbang -> check_category pada kontrak K-07
GATE_TO_K07_CATEGORY: Dict[str, str] = {
    GATE_ML_SCORE: "VALIDITY",
    GATE_BUSINESS_ELIGIBILITY: "ELIGIBILITY",
    GATE_CUSTOMER_CONSENT: "SUPPRESSION",
    GATE_CONTACT_POLICY: "FATIGUE",
    GATE_PRODUCT_SUITABILITY: "SUITABILITY",
}

STATUS_PASSED = "PASSED"
STATUS_SCORE_EXPIRED = "SCORE_EXPIRED"
STATUS_NOT_ELIGIBLE = "NOT_ELIGIBLE"
STATUS_PRODUCT_UNAVAILABLE = "PRODUCT_UNAVAILABLE"
STATUS_PRODUCT_UNSUITABLE = "PRODUCT_UNSUITABLE"


# ---------------------------------------------------------------------------
# Data class hasil
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateResult:
    """Hasil evaluasi satu gerbang."""

    gate: str
    passed: bool
    status: str
    reason: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def k07_category(self) -> str:
        """check_category sesuai kontrak K-07."""
        return GATE_TO_K07_CATEGORY[self.gate]


# ---------------------------------------------------------------------------
# Gerbang 2 & 5: aturan per-aksi (mengembalikan None jika lolos, atau alasan)
# ---------------------------------------------------------------------------


def check_business_eligibility(
    action_id: str,
    ai_scores: "AIScores",
    eligibility: "EligibilityProfile",
) -> Optional[str]:
    """
    Memeriksa kelayakan bisnis (Masukan 2) untuk satu aksi.

    Returns:
        None jika eligible, atau string alasan jika tidak eligible.
    """
    lifecycle = ai_scores.lifecycle_stage
    clv_tier = ai_scores.clv_tier
    churn_band = ai_scores.churn_risk_band

    rules: Dict[str, Callable[[], Optional[str]]] = {
        "RELATIONSHIP_MANAGER_CONTACT": lambda: (
            None
            if (clv_tier == "PLATINUM" and churn_band in ("HIGH", "VERY_HIGH"))
            else "CLV bukan PLATINUM atau Churn Risk tidak HIGH/VERY_HIGH"
        ),
        "RETENTION_OUTREACH": lambda: (
            None
            if (
                churn_band in ("HIGH", "VERY_HIGH")
                and clv_tier in ("GOLD", "PLATINUM")
                and lifecycle in ("AT_RISK", "DORMANT")
            )
            else "Tidak memenuhi syarat RETENTION_OUTREACH (churn/CLV/lifecycle)"
        ),
        "CROSS_SELL": lambda: (
            None
            if lifecycle in ("ACTIVE", "LOYAL")
            else "Lifecycle bukan ACTIVE/LOYAL untuk CROSS_SELL"
        ),
        "UPSELL": lambda: (
            None
            if (lifecycle in ("ACTIVE", "LOYAL") and eligibility.tenure_days >= 60)
            else "Lifecycle atau tenure tidak memenuhi syarat UPSELL"
        ),
        "RENEWAL_REMINDER": lambda: (
            None
            if (
                eligibility.has_active_membership
                and eligibility.membership_days_remaining <= 15
            )
            else "Membership tidak akan kadaluarsa dalam 15 hari"
        ),
        "LOYALTY_REWARD": lambda: (
            None
            if (lifecycle == "LOYAL" and clv_tier in ("GOLD", "PLATINUM"))
            else "Lifecycle bukan LOYAL atau CLV tidak memenuhi syarat"
        ),
        "WIN_BACK_OFFER": lambda: (
            None
            if (
                lifecycle == "DORMANT"
                and clv_tier in ("GOLD", "PLATINUM")
                and not eligibility.has_active_win_back_offer
            )
            else "Tidak memenuhi syarat WIN_BACK_OFFER"
        ),
        # COMPLAINT_RESOLUTION hanya dipilih lewat jalur suppression (tiket
        # OPEN_SEVERE_COMPLAINT aktif), BUKAN sebagai kandidat EV biasa.
        "COMPLAINT_RESOLUTION": lambda: (
            "COMPLAINT_RESOLUTION hanya untuk pelanggan dengan keluhan "
            "OPEN_SEVERE_COMPLAINT aktif (dipilih lewat jalur suppression)"
        ),
        "EDUCATION": lambda: (
            None
            if (lifecycle == "NEW" and churn_band == "LOW")
            else "Lifecycle bukan NEW atau Churn Risk bukan LOW untuk EDUCATION"
        ),
    }

    rule = rules.get(action_id)
    return rule() if rule else None  # tanpa aturan khusus -> eligible


def check_product_suitability(
    action_id: str, product_suitability: "ProductSuitability"
) -> Optional[str]:
    """
    Memeriksa ketersediaan & kesesuaian produk (Masukan 5) untuk satu aksi.

    Returns:
        None jika lolos, atau string alasan jika gagal.
    """
    if (
        product_suitability.available_action_ids
        and action_id not in product_suitability.available_action_ids
    ):
        return "Produk/layanan tidak tersedia (Masukan 5)"
    if action_id in product_suitability.unsuitable_action_ids:
        return "Produk tidak sesuai untuk pelanggan ini (Masukan 5)"
    return None


def check_channel_availability(
    allowed_channels: List[str], consent: CustomerConsent
) -> Optional[str]:
    """
    Masukan 3 per kanal (Requirement Bab 3: "mengizinkan kontak pada kanal ini?"; K-10).

    Aksi tidak dapat dieksekusi bila SELURUH kanalnya diblokir consent. Kanal internal
    (`task_rm`, `branch`) tidak diatur consent pemasaran sehingga tidak pernah terblokir.

    Returns:
        None jika minimal satu kanal tersedia (atau aksi tanpa kanal), selain itu alasan.
    """
    if not allowed_channels:
        return None
    if any(not is_opted_out(consent, c) for c in allowed_channels):
        return None
    return "Seluruh kanal aksi diblokir consent pelanggan (Masukan 3)"


# ---------------------------------------------------------------------------
# Evaluasi gerbang -> GateResult
# ---------------------------------------------------------------------------


def evaluate_ml_score_gate(
    scores_expired: bool, scores_missing: bool = False
) -> GateResult:
    """Gerbang 1: skor ML harus ada dan belum kedaluwarsa."""
    if scores_missing:
        return GateResult(
            gate=GATE_ML_SCORE,
            passed=False,
            status=STATUS_SCORE_EXPIRED,
            reason="Skor AI belum dihitung; default konservatif dipakai.",
            details={"scores_missing": True},
        )
    if scores_expired:
        return GateResult(
            gate=GATE_ML_SCORE,
            passed=False,
            status=STATUS_SCORE_EXPIRED,
            reason="Skor AI melampaui masa berlaku; propensity dianggap 0.0.",
            details={"scores_expired": True},
        )
    return GateResult(gate=GATE_ML_SCORE, passed=True, status=STATUS_PASSED)


def evaluate_complaint_block(suppression_result: SuppressionCheckResult) -> GateResult:
    """
    Bagian gerbang 2 yang bersifat per-pelanggan: keluhan OPEN_SEVERE_COMPLAINT aktif
    memblokir seluruh promosi (Requirement_Capstone Bab 3 baris 2).
    """
    if suppression_result.suppression_reason == SuppressionReason.COMPLAINT:
        return GateResult(
            gate=GATE_BUSINESS_ELIGIBILITY,
            passed=False,
            status=suppression_result.status,
            reason=suppression_result.message,
            details={"reason_code": suppression_result.reason_code},
        )
    return GateResult(gate=GATE_BUSINESS_ELIGIBILITY, passed=True, status=STATUS_PASSED)


def evaluate_business_eligibility_gate(
    action_id: str,
    ai_scores: "AIScores",
    eligibility: "EligibilityProfile",
    suppression_result: Optional[SuppressionCheckResult] = None,
) -> GateResult:
    """
    Gerbang 2: kelayakan bisnis untuk `action_id`.

    Jika `suppression_result` diberikan dan ada keluhan OPEN_SEVERE_COMPLAINT aktif:
      - aksi selain COMPLAINT_RESOLUTION -> gagal (promosi diblokir)
      - COMPLAINT_RESOLUTION             -> lolos (aksi ini memang dipicu keluhan aktif)
    """
    complaint_active = (
        suppression_result is not None
        and suppression_result.suppression_reason == SuppressionReason.COMPLAINT
    )
    if complaint_active:
        if action_id == "COMPLAINT_RESOLUTION":
            return GateResult(
                gate=GATE_BUSINESS_ELIGIBILITY,
                passed=True,
                status=STATUS_PASSED,
                details={"action_id": action_id},
            )
        blocked = evaluate_complaint_block(suppression_result)  # type: ignore[arg-type]
        return GateResult(
            gate=blocked.gate,
            passed=False,
            status=blocked.status,
            reason=blocked.reason,
            details={**blocked.details, "action_id": action_id},
        )

    reason = check_business_eligibility(action_id, ai_scores, eligibility)
    if reason is None:
        return GateResult(
            gate=GATE_BUSINESS_ELIGIBILITY,
            passed=True,
            status=STATUS_PASSED,
            details={"action_id": action_id},
        )
    return GateResult(
        gate=GATE_BUSINESS_ELIGIBILITY,
        passed=False,
        status=STATUS_NOT_ELIGIBLE,
        reason=reason,
        details={"action_id": action_id},
    )


def evaluate_consent_gate(suppression_result: SuppressionCheckResult) -> GateResult:
    """Gerbang 3: consent. Gagal hanya jika pelanggan opt-out global."""
    if suppression_result.suppression_reason == SuppressionReason.OPT_OUT:
        return GateResult(
            gate=GATE_CUSTOMER_CONSENT,
            passed=False,
            status=suppression_result.status,
            reason=suppression_result.message,
            details={"reason_code": suppression_result.reason_code},
        )
    return GateResult(gate=GATE_CUSTOMER_CONSENT, passed=True, status=STATUS_PASSED)


def evaluate_contact_policy_gate(fatigue_result: FatigueCheckResult) -> GateResult:
    """
    Gerbang 4: kebijakan kontak / frequency cap (Requirement_Capstone Bab 3 baris 4).
    Gagal dengan status `FREQ_CAP_SUPPRESSED` jika batas kontak tercapai.
    Keluhan aktif -> gerbang 2; opt-out -> gerbang 3.
    """
    if fatigue_result.is_suppressed:
        return GateResult(
            gate=GATE_CONTACT_POLICY,
            passed=False,
            status=fatigue_result.status,
            reason=fatigue_result.message,
            details={
                "reason_code": fatigue_result.reason_code,
                "contact_count_in_window": fatigue_result.contact_count_in_window,
            },
        )
    return GateResult(
        gate=GATE_CONTACT_POLICY,
        passed=True,
        status=STATUS_PASSED,
        details={"contact_count_in_window": fatigue_result.contact_count_in_window},
    )


def evaluate_product_suitability_gate(
    action_id: str, product_suitability: "ProductSuitability"
) -> GateResult:
    """Gerbang 5: ketersediaan & kesesuaian produk untuk `action_id`."""
    reason = check_product_suitability(action_id, product_suitability)
    if reason is None:
        return GateResult(
            gate=GATE_PRODUCT_SUITABILITY,
            passed=True,
            status=STATUS_PASSED,
            details={"action_id": action_id},
        )
    status = (
        STATUS_PRODUCT_UNAVAILABLE
        if "tidak tersedia" in reason
        else STATUS_PRODUCT_UNSUITABLE
    )
    return GateResult(
        gate=GATE_PRODUCT_SUITABILITY,
        passed=False,
        status=status,
        reason=reason,
        details={"action_id": action_id},
    )


def evaluate_five_gates(
    action_id: str,
    ai_scores: "AIScores",
    eligibility: "EligibilityProfile",
    product_suitability: "ProductSuitability",
    suppression_result: SuppressionCheckResult,
    fatigue_result: FatigueCheckResult,
    scores_expired: bool,
    scores_missing: bool = False,
) -> List[GateResult]:
    """
    Mengevaluasi KELIMA gerbang untuk satu aksi, masing-masing independen
    (satu gagal tidak menghentikan evaluasi yang lain), urutan sesuai `ALL_GATES`.
    """
    return [
        evaluate_ml_score_gate(scores_expired, scores_missing),
        evaluate_business_eligibility_gate(
            action_id, ai_scores, eligibility, suppression_result
        ),
        evaluate_consent_gate(suppression_result),
        evaluate_contact_policy_gate(fatigue_result),
        evaluate_product_suitability_gate(action_id, product_suitability),
    ]
