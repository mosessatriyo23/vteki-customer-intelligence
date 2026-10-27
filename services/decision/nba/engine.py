"""
engine.py — Next-Best-Action (NBA) Engine
==========================================
Kelas utama NBAEngine yang mengorkestrasi evaluasi 5 masukan independen
dan menghitung Expected Value (EV) untuk memilih aksi terbaik berikutnya.

Formula Expected Value (FRD §10.3 / TRD §10.2):
    EV = Propensity * Expected_Revenue_Contribution * Action_Weight - Incentive_Cost_Estimate

Prinsip Utama (Requirement_Capstone.md Bab 3):
    'Skor tinggi bukan izin!'
    Sistem WAJIB mengevaluasi 5 masukan independen. Jika salah satu
    pemeriksaan protektif gagal ATAU EV negatif, mesin WAJIB memilih NO_ACTION.

5 Masukan Independen:
    1. Predictive AI Scores (Churn, Propensity)
    2. Business Eligibility Rules
    3. Customer Consent & Permission
    4. Contact Policy / Frequency Cap (Fatigue)
    5. Product Suitability & Availability

Referensi: Requirement_Capstone.md Bab 3, 4, 5 (FRD §9.6, §10.1, §10.3 / TRD §10.1, §10.2)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from services.decision.nba.catalogue import (
    ACTION_CATALOGUE,
    Action,
    get_action,
)
from services.decision.policy.fatigue import (
    ContactRecord,
    FatigueCheckResult,
    check_frequency_cap,
)
from services.decision.policy.suppression import (
    ComplaintTicket,
    CustomerConsent,
    SuppressionCheckResult,
    check_suppression,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Konstanta Engine
# ---------------------------------------------------------------------------

DEFAULT_MIN_EV_THRESHOLD: float = 0.0
"""EV minimum agar aksi dapat dipilih. Jika EV < threshold, pilih NO_ACTION."""

DEFAULT_SCORE_VALIDITY_DAYS: int = 30
"""Masa berlaku skor AI dalam hari. Skor kadaluarsa diabaikan (dianggap 0.0)."""


# ---------------------------------------------------------------------------
# Data Classes — Input
# ---------------------------------------------------------------------------

@dataclass
class AIScores:
    """
    Masukan 1: Skor prediktif AI untuk pelanggan.

    Attributes:
        customer_id: ID pelanggan.
        churn_score: Probabilitas churn (0.0 - 1.0).
        churn_risk_band: LOW / MEDIUM / HIGH / VERY_HIGH.
        propensity_purchase: Kecenderungan membeli (0.0 - 1.0).
        propensity_renew: Kecenderungan memperpanjang membership (0.0 - 1.0).
        clv_amount: Nilai CLV dalam IDR.
        clv_tier: PLATINUM / GOLD / SILVER / INSUFFICIENT_HISTORY.
        lifecycle_stage: Tahap lifecycle saat ini.
        score_generated_at: Waktu skor diterbitkan (untuk cek valid_until).
        reason_codes: Minimal 3 reason codes churn.
    """
    customer_id: str
    churn_score: float
    churn_risk_band: str
    propensity_purchase: float
    propensity_renew: float
    clv_amount: float
    clv_tier: str
    lifecycle_stage: str
    score_generated_at: datetime
    reason_codes: List[str] = field(default_factory=list)


@dataclass
class EligibilityProfile:
    """
    Masukan 2: Profil kelayakan bisnis pelanggan.

    Attributes:
        customer_id: ID pelanggan.
        tenure_days: Jumlah hari sejak pelanggan pertama kali bergabung.
        membership_days_remaining: Sisa hari masa keanggotaan aktif.
        has_active_membership: Apakah pelanggan memiliki membership aktif.
        purchased_categories: Kategori produk yang sudah pernah dibeli.
        has_active_win_back_offer: Apakah sudah ada penawaran win-back aktif.
    """
    customer_id: str
    tenure_days: int
    membership_days_remaining: int
    has_active_membership: bool
    purchased_categories: List[str] = field(default_factory=list)
    has_active_win_back_offer: bool = False


@dataclass
class ProductSuitability:
    """
    Masukan 5: Ketersediaan dan kesesuaian produk.

    Attributes:
        available_action_ids: Daftar action_id yang produk/layanannya tersedia.
        unsuitable_action_ids: Daftar action_id yang tidak sesuai untuk pelanggan ini.
    """
    available_action_ids: List[str] = field(default_factory=list)
    unsuitable_action_ids: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Data Classes — Output
# ---------------------------------------------------------------------------

@dataclass
class ActionCandidate:
    """Sebuah aksi kandidat dengan Expected Value yang telah dihitung."""
    action: Action
    propensity: float
    expected_revenue: float
    incentive_cost: float
    expected_value: float
    blocked_reason: Optional[str] = None
    is_eligible: bool = True


@dataclass
class NBAResult:
    """
    Hasil akhir evaluasi NBA Engine untuk seorang pelanggan.

    Attributes:
        customer_id: ID pelanggan.
        selected_action: Aksi terbaik yang dipilih.
        expected_value: EV dari aksi yang dipilih (0.0 untuk NO_ACTION).
        evaluation_timestamp: Waktu evaluasi dilakukan.
        suppression_result: Detail hasil pemeriksaan suppression.
        fatigue_result: Detail hasil pemeriksaan fatigue.
        scores_expired: Apakah skor AI sudah kadaluarsa.
        candidates_evaluated: Semua kandidat yang dievaluasi beserta EV-nya.
        decision_rationale: Penjelasan singkat keputusan dalam bahasa bisnis.
    """
    customer_id: str
    selected_action: Action
    expected_value: float
    evaluation_timestamp: datetime
    suppression_result: SuppressionCheckResult
    fatigue_result: FatigueCheckResult
    scores_expired: bool
    candidates_evaluated: List[ActionCandidate] = field(default_factory=list)
    decision_rationale: str = ""


# ---------------------------------------------------------------------------
# Kelas Utama: NBAEngine
# ---------------------------------------------------------------------------

class NBAEngine:
    """
    Next-Best-Action Engine — Mengevaluasi 5 masukan independen dan
    menghitung Expected Value untuk memilih aksi terbaik.

    Prinsip:
      - Pemeriksaan protektif (Suppression, Fatigue, Consent) WAJIB lulus semua.
      - Jika salah satu pemeriksaan protektif gagal → NO_ACTION.
      - Jika EV semua kandidat < min_ev_threshold → NO_ACTION.
      - Aksi dengan EV tertinggi dipilih sebagai rekomendasi.

    Usage:
        engine = NBAEngine()
        result = engine.evaluate(
            ai_scores=ai_scores,
            consent=consent,
            complaint_tickets=tickets,
            contact_history=history,
            eligibility=eligibility,
            product_suitability=suitability,
        )
        print(result.selected_action.action_id)
    """

    def __init__(
        self,
        min_ev_threshold: float = DEFAULT_MIN_EV_THRESHOLD,
        score_validity_days: int = DEFAULT_SCORE_VALIDITY_DAYS,
    ) -> None:
        """
        Inisialisasi NBAEngine.

        Args:
            min_ev_threshold: Nilai EV minimum agar aksi dapat dipilih.
            score_validity_days: Masa berlaku skor AI dalam hari.
        """
        self.min_ev_threshold = min_ev_threshold
        self.score_validity_days = score_validity_days
        self._no_action = get_action("NO_ACTION")

    # ------------------------------------------------------------------
    # Public Method: evaluate
    # ------------------------------------------------------------------

    def evaluate(
        self,
        ai_scores: AIScores,
        consent: CustomerConsent,
        complaint_tickets: List[ComplaintTicket],
        contact_history: List[ContactRecord],
        eligibility: EligibilityProfile,
        product_suitability: ProductSuitability,
        evaluation_date: Optional[datetime] = None,
    ) -> NBAResult:
        """
        Mengevaluasi seluruh 5 masukan independen dan mengembalikan aksi terbaik.

        Args:
            ai_scores: Skor prediktif AI (Masukan 1).
            consent: Status consent & Opt-In/Out pelanggan (Masukan 3).
            complaint_tickets: Daftar tiket keluhan (Masukan 2 & Suppression).
            contact_history: Riwayat kontak (Masukan 4 — Fatigue Check).
            eligibility: Profil kelayakan bisnis (Masukan 2).
            product_suitability: Ketersediaan & kesesuaian produk (Masukan 5).
            evaluation_date: Tanggal evaluasi (default: sekarang).

        Returns:
            NBAResult berisi aksi terpilih, EV, dan detail semua pemeriksaan.
        """
        if evaluation_date is None:
            evaluation_date = datetime.utcnow()

        customer_id = ai_scores.customer_id
        logger.info(f"[NBAEngine] Memulai evaluasi untuk pelanggan: {customer_id}")

        # ---------------------------------------------------------------
        # LANGKAH 1: Cek Validitas Skor AI
        # ---------------------------------------------------------------
        scores_expired = self._is_score_expired(ai_scores, evaluation_date)
        if scores_expired:
            logger.warning(
                f"[NBAEngine] Skor AI pelanggan {customer_id} kadaluarsa. "
                f"Skor di-reset ke default (0.0)."
            )

        # ---------------------------------------------------------------
        # LANGKAH 2: Pemeriksaan Suppression Mutlak
        # (Consent Opt-Out + OPEN_SEVERE_COMPLAINT)
        # ---------------------------------------------------------------
        suppression_result = check_suppression(
            customer_id=customer_id,
            consent=consent,
            complaint_tickets=complaint_tickets,
        )

        if suppression_result.is_suppressed:
            # Kasus khusus: COMPLAINT_SUPPRESSED → izinkan COMPLAINT_RESOLUTION
            if (
                suppression_result.status == "COMPLAINT_SUPPRESSED"
                and "COMPLAINT_RESOLUTION" in suppression_result.allowed_actions
            ):
                logger.info(
                    f"[NBAEngine] {customer_id} memiliki OPEN_SEVERE_COMPLAINT. "
                    f"Memilih COMPLAINT_RESOLUTION."
                )
                fatigue_result = check_frequency_cap(customer_id, contact_history, evaluation_date)
                return self._build_result(
                    customer_id=customer_id,
                    selected_action=get_action("COMPLAINT_RESOLUTION"),
                    expected_value=0.0,
                    evaluation_timestamp=evaluation_date,
                    suppression_result=suppression_result,
                    fatigue_result=fatigue_result,
                    scores_expired=scores_expired,
                    candidates=[],
                    rationale="COMPLAINT_RESOLUTION dipilih karena ada tiket OPEN_SEVERE_COMPLAINT aktif.",
                )
            else:
                # OPT_OUT — NO_ACTION mutlak
                logger.info(
                    f"[NBAEngine] {customer_id} berstatus OPT_OUT. Memilih NO_ACTION."
                )
                fatigue_result = check_frequency_cap(customer_id, contact_history, evaluation_date)
                return self._build_result(
                    customer_id=customer_id,
                    selected_action=self._no_action,
                    expected_value=0.0,
                    evaluation_timestamp=evaluation_date,
                    suppression_result=suppression_result,
                    fatigue_result=fatigue_result,
                    scores_expired=scores_expired,
                    candidates=[],
                    rationale=f"NO_ACTION dipilih. Alasan suppression: {suppression_result.status}",
                )

        # ---------------------------------------------------------------
        # LANGKAH 3: Pemeriksaan Fatigue / Frequency Cap (Masukan 4)
        # ---------------------------------------------------------------
        fatigue_result = check_frequency_cap(
            customer_id=customer_id,
            contact_history=contact_history,
            evaluation_date=evaluation_date,
        )

        if fatigue_result.is_suppressed:
            logger.info(
                f"[NBAEngine] {customer_id} mencapai batas frekuensi. Memilih NO_ACTION."
            )
            return self._build_result(
                customer_id=customer_id,
                selected_action=self._no_action,
                expected_value=0.0,
                evaluation_timestamp=evaluation_date,
                suppression_result=suppression_result,
                fatigue_result=fatigue_result,
                scores_expired=scores_expired,
                candidates=[],
                rationale="NO_ACTION dipilih. Batas frekuensi kontak tercapai (FREQ_CAP_SUPPRESSED).",
            )

        # ---------------------------------------------------------------
        # LANGKAH 4: Evaluasi Kandidat Aksi dengan Expected Value
        # ---------------------------------------------------------------
        candidates = self._evaluate_candidates(
            ai_scores=ai_scores,
            eligibility=eligibility,
            product_suitability=product_suitability,
            scores_expired=scores_expired,
        )

        # Filter kandidat yang lolos pemeriksaan (is_eligible=True)
        eligible_candidates = [c for c in candidates if c.is_eligible]

        # Pilih kandidat dengan EV tertinggi yang memenuhi threshold
        best_candidate = self._select_best_candidate(eligible_candidates)

        if best_candidate is None or best_candidate.expected_value < self.min_ev_threshold:
            logger.info(
                f"[NBAEngine] Tidak ada kandidat dengan EV >= {self.min_ev_threshold}. "
                f"Memilih NO_ACTION."
            )
            return self._build_result(
                customer_id=customer_id,
                selected_action=self._no_action,
                expected_value=0.0,
                evaluation_timestamp=evaluation_date,
                suppression_result=suppression_result,
                fatigue_result=fatigue_result,
                scores_expired=scores_expired,
                candidates=candidates,
                rationale=(
                    "NO_ACTION dipilih. Tidak ada aksi kandidat dengan EV positif "
                    f"yang melampaui threshold {self.min_ev_threshold}."
                ),
            )

        logger.info(
            f"[NBAEngine] Aksi terpilih untuk {customer_id}: "
            f"{best_candidate.action.action_id} (EV={best_candidate.expected_value:.2f})"
        )
        return self._build_result(
            customer_id=customer_id,
            selected_action=best_candidate.action,
            expected_value=best_candidate.expected_value,
            evaluation_timestamp=evaluation_date,
            suppression_result=suppression_result,
            fatigue_result=fatigue_result,
            scores_expired=scores_expired,
            candidates=candidates,
            rationale=(
                f"Aksi '{best_candidate.action.action_id}' dipilih dengan "
                f"EV={best_candidate.expected_value:.2f} (tertinggi di antara kandidat)."
            ),
        )

    # ------------------------------------------------------------------
    # Private Methods
    # ------------------------------------------------------------------

    def _is_score_expired(
        self, ai_scores: AIScores, evaluation_date: datetime
    ) -> bool:
        """Memeriksa apakah skor AI sudah melampaui masa berlaku (valid_until)."""
        from datetime import timedelta
        valid_until = ai_scores.score_generated_at + timedelta(days=self.score_validity_days)
        return evaluation_date > valid_until

    def _evaluate_candidates(
        self,
        ai_scores: AIScores,
        eligibility: EligibilityProfile,
        product_suitability: ProductSuitability,
        scores_expired: bool,
    ) -> List[ActionCandidate]:
        """
        Mengevaluasi semua aksi dalam katalog sebagai kandidat potensial.
        Menghitung EV dan memeriksa kelayakan untuk setiap aksi.
        Mengabaikan NO_ACTION (selalu dipilih sebagai fallback oleh engine).
        """
        candidates: List[ActionCandidate] = []

        for action_id, action in ACTION_CATALOGUE.items():
            if action_id == "NO_ACTION":
                continue  # NO_ACTION adalah fallback, bukan kandidat

            # Masukan 5: Cek ketersediaan produk
            if (
                product_suitability.available_action_ids
                and action_id not in product_suitability.available_action_ids
            ):
                candidates.append(ActionCandidate(
                    action=action,
                    propensity=0.0,
                    expected_revenue=0.0,
                    incentive_cost=0.0,
                    expected_value=0.0,
                    blocked_reason="Produk/layanan tidak tersedia (Masukan 5)",
                    is_eligible=False,
                ))
                continue

            if action_id in product_suitability.unsuitable_action_ids:
                candidates.append(ActionCandidate(
                    action=action,
                    propensity=0.0,
                    expected_revenue=0.0,
                    incentive_cost=0.0,
                    expected_value=0.0,
                    blocked_reason="Produk tidak sesuai untuk pelanggan ini (Masukan 5)",
                    is_eligible=False,
                ))
                continue

            # Masukan 2: Cek kelayakan bisnis (eligibility rules)
            eligibility_check = self._check_business_eligibility(
                action_id, ai_scores, eligibility
            )
            if eligibility_check is not None:
                candidates.append(ActionCandidate(
                    action=action,
                    propensity=0.0,
                    expected_revenue=0.0,
                    incentive_cost=0.0,
                    expected_value=0.0,
                    blocked_reason=eligibility_check,
                    is_eligible=False,
                ))
                continue

            # Hitung Expected Value
            propensity = self._get_propensity(action_id, ai_scores, scores_expired)
            expected_revenue = self._estimate_expected_revenue(ai_scores, action_id)
            incentive_cost = self._estimate_incentive_cost(action, ai_scores)

            # Formula EV: Propensity * Expected_Revenue * Action_Weight - Incentive_Cost
            ev = (propensity * expected_revenue * action.action_weight) - incentive_cost

            candidates.append(ActionCandidate(
                action=action,
                propensity=propensity,
                expected_revenue=expected_revenue,
                incentive_cost=incentive_cost,
                expected_value=ev,
                is_eligible=True,
            ))

        return candidates

    def _check_business_eligibility(
        self,
        action_id: str,
        ai_scores: AIScores,
        eligibility: EligibilityProfile,
    ) -> Optional[str]:
        """
        Memeriksa kelayakan bisnis untuk aksi tertentu (Masukan 2).
        Mengembalikan None jika eligible, atau string alasan jika tidak eligible.
        """
        lifecycle = ai_scores.lifecycle_stage
        clv_tier = ai_scores.clv_tier
        churn_band = ai_scores.churn_risk_band

        eligibility_rules: Dict[str, callable] = {
            "RELATIONSHIP_MANAGER_CONTACT": lambda: (
                None if (
                    clv_tier == "PLATINUM"
                    and churn_band in ("HIGH", "VERY_HIGH")
                ) else "CLV bukan PLATINUM atau Churn Risk tidak HIGH/VERY_HIGH"
            ),
            "RETENTION_OUTREACH": lambda: (
                None if (
                    churn_band in ("HIGH", "VERY_HIGH")
                    and clv_tier in ("GOLD", "PLATINUM")
                    and lifecycle in ("AT_RISK", "DORMANT")
                ) else "Tidak memenuhi syarat RETENTION_OUTREACH (churn/CLV/lifecycle)"
            ),
            "CROSS_SELL": lambda: (
                None if lifecycle in ("ACTIVE", "LOYAL")
                else "Lifecycle bukan ACTIVE/LOYAL untuk CROSS_SELL"
            ),
            "UPSELL": lambda: (
                None if (lifecycle in ("ACTIVE", "LOYAL") and eligibility.tenure_days >= 60)
                else "Lifecycle atau tenure tidak memenuhi syarat UPSELL"
            ),
            "RENEWAL_REMINDER": lambda: (
                None if (
                    eligibility.has_active_membership
                    and eligibility.membership_days_remaining <= 15
                ) else "Membership tidak akan kadaluarsa dalam 15 hari"
            ),
            "LOYALTY_REWARD": lambda: (
                None if (lifecycle == "LOYAL" and clv_tier in ("GOLD", "PLATINUM"))
                else "Lifecycle bukan LOYAL atau CLV tidak memenuhi syarat"
            ),
            "WIN_BACK_OFFER": lambda: (
                None if (
                    lifecycle == "DORMANT"
                    and clv_tier in ("GOLD", "PLATINUM")
                    and not eligibility.has_active_win_back_offer
                ) else "Tidak memenuhi syarat WIN_BACK_OFFER"
            ),
            "EDUCATION": lambda: (
                None if (lifecycle == "NEW" and churn_band == "LOW")
                else "Lifecycle bukan NEW atau Churn Risk bukan LOW untuk EDUCATION"
            ),
        }

        rule = eligibility_rules.get(action_id)
        if rule:
            return rule()
        return None  # Tidak ada aturan khusus → eligible

    def _get_propensity(
        self, action_id: str, ai_scores: AIScores, scores_expired: bool
    ) -> float:
        """Mengambil propensity yang relevan untuk aksi. Jika skor kadaluarsa, return 0.0."""
        if scores_expired:
            return 0.0

        propensity_map: Dict[str, float] = {
            "RETENTION_OUTREACH": ai_scores.churn_score,
            "RELATIONSHIP_MANAGER_CONTACT": ai_scores.churn_score,
            "WIN_BACK_OFFER": ai_scores.churn_score,
            "RENEWAL_REMINDER": ai_scores.propensity_renew,
            "UPSELL": ai_scores.propensity_renew,
            "CROSS_SELL": ai_scores.propensity_purchase,
            "LOYALTY_REWARD": ai_scores.propensity_purchase,
            "EDUCATION": 1.0 - ai_scores.churn_score,  # Rendah churn = tinggi edukasi
            "SERVICE_REMINDER": 0.9,  # Service reminder hampir selalu relevan
            "COMPLAINT_RESOLUTION": 1.0,  # Selalu relevan jika ada keluhan
        }
        return propensity_map.get(action_id, ai_scores.propensity_purchase)

    def _estimate_expected_revenue(self, ai_scores: AIScores, action_id: str) -> float:
        """
        Estimasi kontribusi pendapatan dari aksi berdasarkan CLV pelanggan.
        Nilai ini adalah proxy; implementasi lengkap akan menggunakan data produk nyata.
        """
        clv = ai_scores.clv_amount
        revenue_factor_map: Dict[str, float] = {
            "RETENTION_OUTREACH": clv * 0.5,        # Retensi mencegah kehilangan 50% CLV
            "RELATIONSHIP_MANAGER_CONTACT": clv * 0.6,
            "WIN_BACK_OFFER": clv * 0.4,
            "CROSS_SELL": clv * 0.3,
            "UPSELL": clv * 0.35,
            "RENEWAL_REMINDER": clv * 0.25,
            "LOYALTY_REWARD": clv * 0.2,
            "EDUCATION": clv * 0.15,
            "SERVICE_REMINDER": clv * 0.1,
            "COMPLAINT_RESOLUTION": 0.0,            # Non-revenue, tapi protektif
        }
        return revenue_factor_map.get(action_id, clv * 0.1)

    def _estimate_incentive_cost(self, action: Action, ai_scores: AIScores) -> float:
        """
        Estimasi biaya insentif berdasarkan incentive_band aksi dan CLV pelanggan.
        """
        from services.decision.nba.catalogue import IncentiveBand
        clv = ai_scores.clv_amount

        cost_map: Dict[str, float] = {
            IncentiveBand.NONE.value: 0.0,
            IncentiveBand.LOW.value: min(clv * 0.05, 25_000),
            IncentiveBand.MEDIUM.value: min(clv * 0.10, 75_000),
            IncentiveBand.HIGH.value: min(clv * 0.15, 150_000),
            IncentiveBand.DISCOUNT_LIMITED.value: min(clv * 0.08, 50_000),
            IncentiveBand.LOYALTY_POINTS.value: min(clv * 0.05, 30_000),
        }
        return cost_map.get(action.incentive_band.value, 0.0)

    def _select_best_candidate(
        self, eligible_candidates: List[ActionCandidate]
    ) -> Optional[ActionCandidate]:
        """Memilih kandidat aksi dengan Expected Value tertinggi."""
        if not eligible_candidates:
            return None
        return max(eligible_candidates, key=lambda c: c.expected_value)

    @staticmethod
    def _build_result(
        customer_id: str,
        selected_action: Action,
        expected_value: float,
        evaluation_timestamp: datetime,
        suppression_result: SuppressionCheckResult,
        fatigue_result: FatigueCheckResult,
        scores_expired: bool,
        candidates: List[ActionCandidate],
        rationale: str,
    ) -> NBAResult:
        """Membangun objek NBAResult dari komponen-komponen hasil evaluasi."""
        return NBAResult(
            customer_id=customer_id,
            selected_action=selected_action,
            expected_value=expected_value,
            evaluation_timestamp=evaluation_timestamp,
            suppression_result=suppression_result,
            fatigue_result=fatigue_result,
            scores_expired=scores_expired,
            candidates_evaluated=candidates,
            decision_rationale=rationale,
        )
