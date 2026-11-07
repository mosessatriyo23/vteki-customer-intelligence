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

Pembagian modul (Minggu 6-7):
    - nba/ev_calculator.py : rumus EV & estimasi komponen (fungsi murni)
    - nba/evaluator.py     : evaluasi 5 gerbang independen -> GateResult
    - nba/engine.py        : orkestrasi. `evaluate()` (asli) dan `decide()` (keluaran bentuk K-07)

Referensi: Requirement_Capstone.md Bab 3, 4, 5 (FRD §9.6, §10.1, §10.3 / TRD §10.1, §10.2)
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from services.decision.nba.catalogue import (
    ACTION_CATALOGUE,
    Action,
    get_action,
)
from services.decision.nba.ev_calculator import (
    calculate_expected_value,
    estimate_expected_revenue,
    estimate_incentive_cost,
    get_propensity,
)
from services.decision.nba.evaluator import (
    GATE_BUSINESS_ELIGIBILITY,
    GATE_PRODUCT_SUITABILITY,
    GateResult,
    check_business_eligibility,
    check_product_suitability,
    evaluate_complaint_block,
    evaluate_consent_gate,
    evaluate_contact_policy_gate,
    evaluate_ml_score_gate,
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
    is_opted_out,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Konstanta Engine
# ---------------------------------------------------------------------------

DEFAULT_MIN_EV_THRESHOLD: float = 0.0
"""EV minimum agar aksi dapat dipilih. Jika EV < threshold, pilih NO_ACTION."""

ENGINE_VERSION: str = "nba-engine-1.1.0"
"""Versi NBAEngine yang dicatat pada rekaman keputusan K-07 (`engine_version`)."""

NO_ACTION_REASON_OPT_OUT = "OPT_OUT_SUPPRESSED"
NO_ACTION_REASON_FREQ_CAP = "FREQ_CAP_SUPPRESSED"
NO_ACTION_REASON_ALL_BLOCKED = "ALL_CANDIDATES_BLOCKED"
"""Alasan NO_ACTION menurut Requirement_Capstone Bab 4 (baris NO_ACTION): Consent = Opt-Out,
Frequency Cap tercapai, atau ALL_CANDIDATES_BLOCKED."""

CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
"""Pola `correlation_id` sesuai kontrak K-07."""

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
    blocked_gate: Optional[str] = None
    """Gerbang yang memblokir kandidat (BUSINESS_ELIGIBILITY / PRODUCT_SUITABILITY)."""


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


@dataclass
class DecisionRecord:
    """
    Rekaman keputusan NBA bentuk kontrak K-07 (`contracts/K-07_decision_record.json`).

    Gunakan `to_dict()` untuk mendapatkan dict yang JSON-serializable dan sesuai skema.
    `result` menyimpan `NBAResult` mentah (tidak ikut diserialisasi).
    """

    decision_id: str
    customer_id: str
    selected_action_id: str
    expected_value: float
    candidates: List[Dict[str, Any]]
    checks: List[Dict[str, Any]]
    rationale_text: str
    correlation_id: str
    evaluation_timestamp: datetime
    engine_version: str
    channel_selected: Optional[str]
    degraded_input: bool
    scores_snapshot: Dict[str, Any]
    no_action_reason: Optional[str] = None
    """Diisi hanya untuk alasan yang disebut Requirement_Capstone Bab 4; selain itu None."""
    result: Optional[NBAResult] = None

    def to_dict(self) -> Dict[str, Any]:
        """Dict sesuai K-07 (+ `degraded_input`; K-07 mengizinkan properti tambahan)."""
        return {
            "decision_id": self.decision_id,
            "customer_id": self.customer_id,
            "selected_action_id": self.selected_action_id,
            "expected_value": self.expected_value,
            "candidates": self.candidates,
            "checks": self.checks,
            "rationale_text": self.rationale_text,
            "correlation_id": self.correlation_id,
            "evaluation_timestamp": self.evaluation_timestamp.isoformat(),
            "engine_version": self.engine_version,
            "channel_selected": self.channel_selected,
            "degraded_input": self.degraded_input,
            "no_action_reason": self.no_action_reason,
            "scores_snapshot": self.scores_snapshot,
        }


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
        *,
        ev_min_threshold: Optional[float] = None,
    ) -> None:
        """
        Inisialisasi NBAEngine.

        Args:
            min_ev_threshold: Nilai EV minimum agar aksi dapat dipilih.
            score_validity_days: Masa berlaku skor AI dalam hari.
            ev_min_threshold: Alias `min_ev_threshold` (nama di roadmap Minggu 7).
                Jika diisi, nilainya dipakai menggantikan `min_ev_threshold`.
        """
        if ev_min_threshold is not None:
            min_ev_threshold = ev_min_threshold
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
    # Public Method: decide (keluaran bentuk K-07)
    # ------------------------------------------------------------------

    def decide(
        self,
        customer_id: str,
        ai_scores: Optional[AIScores],
        consent: CustomerConsent,
        complaint_tickets: List[ComplaintTicket],
        contact_history: List[ContactRecord],
        eligibility: EligibilityProfile,
        product_suitability: ProductSuitability,
        evaluation_date: Optional[datetime] = None,
        correlation_id: Optional[str] = None,
        decision_id: Optional[str] = None,
    ) -> DecisionRecord:
        """
        Mengambil keputusan NBA dan mengembalikannya sebagai `DecisionRecord` (K-07).

        Perbedaan dengan `evaluate()`:
          - `ai_scores` boleh `None` (skor belum dihitung) -> default konservatif
            dan `degraded_input = True`.
          - Skor kedaluwarsa juga menandai `degraded_input = True`.
          - Keputusan aksi IDENTIK dengan `evaluate()`; `decide()` hanya menambahkan
            penanda `degraded_input`, alasan NO_ACTION, dan bentuk K-07.
          - Menyertakan `checks[]` (5 gerbang), `candidates[]` berperingkat,
            `rationale_text`, `correlation_id`, dan `decision_id`.

        Args:
            customer_id: ID pelanggan (harus sama dengan `ai_scores.customer_id` jika ada).
            correlation_id: Jika None dibuat otomatis; jika diisi harus cocok
                `^[A-Za-z0-9._:-]{1,128}$` (K-07), selain itu ValueError.
            decision_id: Jika None dibuat otomatis (`DEC-<uuid4 hex>`).

        Raises:
            ValueError: customer_id tidak konsisten atau correlation_id tidak valid.
        """
        if evaluation_date is None:
            evaluation_date = datetime.utcnow()

        if correlation_id is None:
            correlation_id = f"corr-{uuid.uuid4().hex}"
        elif not CORRELATION_ID_PATTERN.match(correlation_id):
            raise ValueError(
                "correlation_id tidak valid (pola K-07: ^[A-Za-z0-9._:-]{1,128}$): "
                f"{correlation_id!r}"
            )
        if decision_id is None:
            decision_id = f"DEC-{uuid.uuid4().hex}"

        scores_missing = ai_scores is None
        if ai_scores is None:
            scores = self._conservative_scores(customer_id, evaluation_date)
        else:
            if ai_scores.customer_id != customer_id:
                raise ValueError(
                    f"Mismatch customer_id: skor milik '{ai_scores.customer_id}' "
                    f"tetapi keputusan untuk '{customer_id}'"
                )
            scores = ai_scores

        result = self.evaluate(
            ai_scores=scores,
            consent=consent,
            complaint_tickets=complaint_tickets,
            contact_history=contact_history,
            eligibility=eligibility,
            product_suitability=product_suitability,
            evaluation_date=evaluation_date,
        )

        degraded = scores_missing or result.scores_expired
        rationale = result.decision_rationale

        selected = result.selected_action
        no_action_reason = self._no_action_reason(result)
        if no_action_reason == NO_ACTION_REASON_ALL_BLOCKED:
            rationale = (
                "NO_ACTION dipilih. ALL_CANDIDATES_BLOCKED: seluruh kandidat aksi "
                "diblokir oleh aturan kelayakan atau kesesuaian produk."
            )
        if degraded:
            rationale += (
                " [degraded_input=True: skor AI kedaluwarsa atau belum dihitung; "
                "nilai default dipakai.]"
            )

        return DecisionRecord(
            decision_id=decision_id,
            customer_id=customer_id,
            selected_action_id=selected.action_id,
            expected_value=result.expected_value,
            candidates=self._candidates_to_k07(result.candidates_evaluated),
            checks=self._checks_to_k07(result, scores_missing),
            rationale_text=rationale,
            correlation_id=correlation_id,
            evaluation_timestamp=evaluation_date,
            engine_version=ENGINE_VERSION,
            channel_selected=self._select_channel(selected, consent),
            degraded_input=degraded,
            no_action_reason=no_action_reason,
            scores_snapshot=self._scores_snapshot(scores),
            result=result,
        )

    # ------------------------------------------------------------------
    # Private Methods
    # ------------------------------------------------------------------

    def _is_score_expired(
        self, ai_scores: AIScores, evaluation_date: datetime
    ) -> bool:
        """Memeriksa apakah skor AI sudah melampaui masa berlaku (valid_until)."""
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

            # Masukan 5: ketersediaan & kesesuaian produk (evaluator.py)
            suitability_reason = check_product_suitability(
                action_id, product_suitability
            )
            if suitability_reason is not None:
                candidates.append(
                    self._blocked_candidate(
                        action, suitability_reason, GATE_PRODUCT_SUITABILITY
                    )
                )
                continue

            # Masukan 2: kelayakan bisnis (evaluator.py)
            eligibility_reason = check_business_eligibility(
                action_id, ai_scores, eligibility
            )
            if eligibility_reason is not None:
                candidates.append(
                    self._blocked_candidate(
                        action, eligibility_reason, GATE_BUSINESS_ELIGIBILITY
                    )
                )
                continue

            # Hitung Expected Value (ev_calculator.py)
            propensity = get_propensity(action_id, ai_scores, scores_expired)
            expected_revenue = estimate_expected_revenue(ai_scores.clv_amount, action_id)
            incentive_cost = estimate_incentive_cost(
                action.incentive_band, ai_scores.clv_amount
            )
            ev = calculate_expected_value(
                propensity=propensity,
                expected_revenue=expected_revenue,
                action_weight=action.action_weight,
                incentive_cost=incentive_cost,
            )

            candidates.append(
                ActionCandidate(
                    action=action,
                    propensity=propensity,
                    expected_revenue=expected_revenue,
                    incentive_cost=incentive_cost,
                    expected_value=ev,
                    is_eligible=True,
                )
            )

        return candidates

    @staticmethod
    def _blocked_candidate(action: Action, reason: str, gate: str) -> ActionCandidate:
        """Membangun kandidat yang diblokir oleh sebuah gerbang (EV = 0)."""
        return ActionCandidate(
            action=action,
            propensity=0.0,
            expected_revenue=0.0,
            incentive_cost=0.0,
            expected_value=0.0,
            blocked_reason=reason,
            is_eligible=False,
            blocked_gate=gate,
        )

    def _check_business_eligibility(
        self,
        action_id: str,
        ai_scores: AIScores,
        eligibility: EligibilityProfile,
    ) -> Optional[str]:
        """Delegasi ke `evaluator.check_business_eligibility` (kompatibilitas)."""
        return check_business_eligibility(action_id, ai_scores, eligibility)

    def _get_propensity(
        self, action_id: str, ai_scores: AIScores, scores_expired: bool
    ) -> float:
        """Delegasi ke `ev_calculator.get_propensity` (kompatibilitas)."""
        return get_propensity(action_id, ai_scores, scores_expired)

    def _estimate_expected_revenue(self, ai_scores: AIScores, action_id: str) -> float:
        """Delegasi ke `ev_calculator.estimate_expected_revenue` (kompatibilitas)."""
        return estimate_expected_revenue(ai_scores.clv_amount, action_id)

    def _estimate_incentive_cost(self, action: Action, ai_scores: AIScores) -> float:
        """Delegasi ke `ev_calculator.estimate_incentive_cost` (kompatibilitas)."""
        return estimate_incentive_cost(action.incentive_band, ai_scores.clv_amount)

    def _conservative_scores(
        self, customer_id: str, evaluation_date: datetime
    ) -> AIScores:
        """
        Skor default konservatif saat skor ML belum tersedia: semua propensity 0,
        CLV 0, lifecycle/band tidak dikenal, dan ditandai kedaluwarsa.
        """
        return AIScores(
            customer_id=customer_id,
            churn_score=0.0,
            churn_risk_band="UNKNOWN",
            propensity_purchase=0.0,
            propensity_renew=0.0,
            clv_amount=0.0,
            clv_tier="INSUFFICIENT_HISTORY",
            lifecycle_stage="UNKNOWN",
            score_generated_at=evaluation_date
            - timedelta(days=self.score_validity_days + 1),
            reason_codes=[],
        )

    @staticmethod
    def _scores_snapshot(scores: AIScores) -> Dict[str, Any]:
        """Snapshot skor untuk `scores_snapshot` K-07."""
        return {
            "churn_score": scores.churn_score,
            "churn_risk_band": scores.churn_risk_band,
            "propensity_purchase": scores.propensity_purchase,
            "propensity_renew": scores.propensity_renew,
            "clv_amount": scores.clv_amount,
            "clv_tier": scores.clv_tier,
            "lifecycle_stage": scores.lifecycle_stage,
            "reason_codes": list(scores.reason_codes),
        }

    @staticmethod
    def _select_channel(action: Action, consent: CustomerConsent) -> Optional[str]:
        """Kanal pertama dari aksi yang tidak diblokir opt-out; None untuk NO_ACTION."""
        if action.action_id == "NO_ACTION":
            return None
        for channel in action.allowed_channels:
            if not is_opted_out(consent, channel):
                return channel
        return None

    @staticmethod
    def _candidates_to_k07(candidates: List[ActionCandidate]) -> List[Dict[str, Any]]:
        """Kandidat -> daftar dict K-07; kandidat eligible diberi `rank` berdasarkan EV."""
        ranked = sorted(
            (c for c in candidates if c.is_eligible),
            key=lambda c: c.expected_value,
            reverse=True,
        )
        rank_by_id = {c.action.action_id: i + 1 for i, c in enumerate(ranked)}

        out: List[Dict[str, Any]] = []
        for c in candidates:
            item: Dict[str, Any] = {
                "action_id": c.action.action_id,
                "expected_value": c.expected_value,
                "propensity": c.propensity,
                "action_weight": c.action.action_weight,
                "incentive_cost": c.incentive_cost,
                "is_eligible": c.is_eligible,
                "rejection_reason": c.blocked_reason,
            }
            if c.is_eligible:
                item["rank"] = rank_by_id[c.action.action_id]
            out.append(item)
        return out

    @staticmethod
    def _gate_to_check(name: str, gate: GateResult) -> Dict[str, Any]:
        return {
            "check_name": name,
            "check_category": gate.k07_category,
            "passed": gate.passed,
            "status": gate.status,
            "reason": gate.reason,
            "details": dict(gate.details),
        }

    @staticmethod
    def _no_action_reason(result: NBAResult) -> Optional[str]:
        """
        Alasan NO_ACTION yang disebut Requirement_Capstone Bab 4:
        Opt-Out, Frequency Cap tercapai, atau ALL_CANDIDATES_BLOCKED.
        Untuk alasan lain (mis. EV < threshold) dokumen tidak memberi kode -> None.
        """
        if result.selected_action.action_id != "NO_ACTION":
            return None
        if result.suppression_result.reason_code == "OPT_OUT_SUPPRESSED":
            return NO_ACTION_REASON_OPT_OUT
        if result.fatigue_result.is_suppressed:
            return NO_ACTION_REASON_FREQ_CAP
        cands = result.candidates_evaluated
        if cands and not any(c.is_eligible for c in cands):
            return NO_ACTION_REASON_ALL_BLOCKED
        return None

    def _checks_to_k07(
        self, result: NBAResult, scores_missing: bool
    ) -> List[Dict[str, Any]]:
        """
        Menyusun `checks[]` K-07 sesuai pembagian 5 masukan Requirement_Capstone Bab 3:

        - ML_SCORE_CHECK       (masukan 1) selalu ada
        - ELIGIBILITY_CHECK    (masukan 2) komplain aktif -> gagal; selain itu agregat
                               kandidat (hanya ada bila kandidat sempat dievaluasi)
        - CONSENT_CHECK        (masukan 3) selalu ada
        - CONTACT_POLICY_CHECK (masukan 4) frequency cap, selalu ada
        - SUITABILITY_CHECK    (masukan 5) agregat kandidat (bila kandidat dievaluasi)
        """
        checks = [
            self._gate_to_check(
                "ML_SCORE_CHECK",
                evaluate_ml_score_gate(result.scores_expired, scores_missing),
            ),
            self._gate_to_check(
                "CONSENT_CHECK", evaluate_consent_gate(result.suppression_result)
            ),
            self._gate_to_check(
                "CONTACT_POLICY_CHECK",
                evaluate_contact_policy_gate(result.fatigue_result),
            ),
        ]

        cands = result.candidates_evaluated
        complaint_gate = evaluate_complaint_block(result.suppression_result)

        if not complaint_gate.passed:
            checks.append(self._gate_to_check("ELIGIBILITY_CHECK", complaint_gate))
        elif cands:
            total = len(cands)
            eligible = sum(1 for c in cands if c.is_eligible)
            eligibility_blocked = sum(
                1 for c in cands if c.blocked_gate == GATE_BUSINESS_ELIGIBILITY
            )
            checks.append(
                {
                    "check_name": "ELIGIBILITY_CHECK",
                    "check_category": "ELIGIBILITY",
                    "passed": eligible > 0,
                    "status": "PASSED" if eligible > 0 else "NOT_ELIGIBLE",
                    "reason": None
                    if eligible > 0
                    else "Tidak ada kandidat aksi yang lolos kelayakan bisnis.",
                    "details": {
                        "candidates_total": total,
                        "candidates_eligible": eligible,
                        "blocked_by_eligibility": eligibility_blocked,
                    },
                }
            )

        if cands:
            total = len(cands)
            suitability_blocked = sum(
                1 for c in cands if c.blocked_gate == GATE_PRODUCT_SUITABILITY
            )
            suitable = total - suitability_blocked
            checks.append(
                {
                    "check_name": "SUITABILITY_CHECK",
                    "check_category": "SUITABILITY",
                    "passed": suitable > 0,
                    "status": "PASSED" if suitable > 0 else "PRODUCT_UNSUITABLE",
                    "reason": None
                    if suitable > 0
                    else "Seluruh kandidat gagal ketersediaan/kesesuaian produk.",
                    "details": {
                        "candidates_total": total,
                        "blocked_by_suitability": suitability_blocked,
                    },
                }
            )
        return checks

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
