"""
ev_calculator.py — Kalkulator Expected Value (EV) NBA
=====================================================
Fungsi-fungsi MURNI (pure function): tanpa I/O, tanpa jaringan, deterministik.

Rumus (FRD §10.3 / TRD §10.2):

    EV = Propensity x ExpectedRevenueContribution x ActionWeight - IncentiveCost

Modul ini berisi:
- calculate_expected_value : rumus EV beserta validasi input
- get_propensity           : memilih skor propensity yang relevan untuk satu aksi
- estimate_expected_revenue: estimasi kontribusi pendapatan dari CLV (proxy)
- estimate_incentive_cost  : estimasi biaya insentif dari band insentif & CLV

Dipakai oleh `engine.py` (NBAEngine) dan diuji di `tests/decision/test_ev_calculator.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict

from services.decision.nba.catalogue import IncentiveBand

if TYPE_CHECKING:  # hanya untuk type hint; hindari import melingkar dengan engine.py
    from services.decision.nba.engine import AIScores


# ---------------------------------------------------------------------------
# Konstanta
# ---------------------------------------------------------------------------

EV_ROUNDING_DIGITS: int = 2
"""Pembulatan hasil EV (2 desimal = sen rupiah) agar hasil konsisten & dapat diaudit."""

SERVICE_REMINDER_PROPENSITY: float = 0.9
"""Service reminder hampir selalu relevan (konstanta bisnis dari engine awal)."""

COMPLAINT_RESOLUTION_PROPENSITY: float = 1.0
"""Selalu relevan jika ada keluhan."""

# Faktor kontribusi pendapatan terhadap CLV (proxy; sama dengan engine awal)
REVENUE_FACTOR_BY_ACTION: Dict[str, float] = {
    "RETENTION_OUTREACH": 0.5,  # retensi mencegah kehilangan 50% CLV
    "RELATIONSHIP_MANAGER_CONTACT": 0.6,
    "WIN_BACK_OFFER": 0.4,
    "CROSS_SELL": 0.3,
    "UPSELL": 0.35,
    "RENEWAL_REMINDER": 0.25,
    "LOYALTY_REWARD": 0.2,
    "EDUCATION": 0.15,
    "SERVICE_REMINDER": 0.1,
    "COMPLAINT_RESOLUTION": 0.0,  # non-revenue, tetapi protektif
}
DEFAULT_REVENUE_FACTOR: float = 0.1

# (persentase CLV, batas maksimum IDR) per band insentif
INCENTIVE_COST_RULES: Dict[IncentiveBand, tuple[float, float]] = {
    IncentiveBand.LOW: (0.05, 25_000.0),
    IncentiveBand.MEDIUM: (0.10, 75_000.0),
    IncentiveBand.HIGH: (0.15, 150_000.0),
    IncentiveBand.DISCOUNT_LIMITED: (0.08, 50_000.0),
    IncentiveBand.LOYALTY_POINTS: (0.05, 30_000.0),
}


# ---------------------------------------------------------------------------
# Rumus EV
# ---------------------------------------------------------------------------


def calculate_expected_value(
    propensity: float,
    expected_revenue: float,
    action_weight: float,
    incentive_cost: float = 0.0,
) -> float:
    """
    Menghitung Expected Value sebuah kandidat aksi.

        EV = propensity x expected_revenue x action_weight - incentive_cost

    Args:
        propensity: Kecenderungan pelanggan, wajib 0.0 - 1.0.
        expected_revenue: Estimasi kontribusi pendapatan (IDR), tidak boleh negatif.
        action_weight: Bobot strategis aksi, tidak boleh negatif.
        incentive_cost: Biaya insentif (IDR), tidak boleh negatif.

    Returns:
        EV (float) dibulatkan ke `EV_ROUNDING_DIGITS` desimal. Boleh negatif.

    Raises:
        ValueError: jika ada input di luar rentang yang valid.
    """
    if not 0.0 <= propensity <= 1.0:
        raise ValueError(
            f"propensity harus di antara 0.0 dan 1.0, diterima: {propensity}"
        )
    if expected_revenue < 0:
        raise ValueError(
            f"expected_revenue tidak boleh negatif, diterima: {expected_revenue}"
        )
    if action_weight < 0:
        raise ValueError(
            f"action_weight tidak boleh negatif, diterima: {action_weight}"
        )
    if incentive_cost < 0:
        raise ValueError(
            f"incentive_cost tidak boleh negatif, diterima: {incentive_cost}"
        )

    ev = (propensity * expected_revenue * action_weight) - incentive_cost
    return round(ev, EV_ROUNDING_DIGITS)


# ---------------------------------------------------------------------------
# Komponen masukan EV
# ---------------------------------------------------------------------------


def _clamp_probability(value: float) -> float:
    """Membatasi nilai ke rentang [0.0, 1.0] (kontrak K-07 mensyaratkan 0..1)."""
    return max(0.0, min(1.0, float(value)))


def get_propensity(
    action_id: str, ai_scores: "AIScores", scores_expired: bool
) -> float:
    """
    Memilih propensity yang relevan untuk sebuah aksi.

    - Skor kedaluwarsa -> 0.0 (konservatif; skor lama tidak boleh dipakai).
    - Hasil selalu dibatasi pada rentang 0.0 - 1.0.
    """
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
        "EDUCATION": 1.0 - ai_scores.churn_score,  # churn rendah = edukasi relevan
        "SERVICE_REMINDER": SERVICE_REMINDER_PROPENSITY,
        "COMPLAINT_RESOLUTION": COMPLAINT_RESOLUTION_PROPENSITY,
    }
    return _clamp_probability(
        propensity_map.get(action_id, ai_scores.propensity_purchase)
    )


def estimate_expected_revenue(clv_amount: float, action_id: str) -> float:
    """
    Estimasi kontribusi pendapatan sebuah aksi sebagai proporsi dari CLV.
    Nilai ini proxy; tidak pernah negatif.
    """
    factor = REVENUE_FACTOR_BY_ACTION.get(action_id, DEFAULT_REVENUE_FACTOR)
    return max(0.0, clv_amount * factor)


def estimate_incentive_cost(incentive_band: IncentiveBand, clv_amount: float) -> float:
    """
    Estimasi biaya insentif berdasarkan band insentif & CLV, dengan batas maksimum IDR.
    Band `NONE` -> 0.0.
    """
    rule = INCENTIVE_COST_RULES.get(incentive_band)
    if rule is None:
        return 0.0
    pct, cap = rule
    return max(0.0, min(clv_amount * pct, cap))
