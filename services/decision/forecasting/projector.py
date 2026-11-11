"""
projector.py — Revenue Forecasting Baseline vs Campaign Scenario (Minggu 11)
============================================================================
Memproyeksikan pendapatan 1-3 bulan ke depan:

  Baseline_m = mean(riwayat bulanan terakhir `baseline_window_months`) x (1 + g)^m
  Incremental_m = lift_per_treated_customer x treated_customers x realization x decay^(m-1)
  Campaign_m = Baseline_m + Incremental_m

Sengaja SEDERHANA dan transparan (run-rate rata-rata, tanpa musiman). Setiap hasil membawa
daftar `assumptions` yang harus ditampilkan bersama angkanya agar manajemen tidak menganggap
proyeksi sebagai fakta.

Asumsi yang HARUS dikonfirmasi tim (tidak ditentukan di Requirement):
  - `effect_decay_per_month` default 1.0 (efek terukur bertahan konstan) — kemungkinan
    optimistis; kampanye promo biasanya meluruh. Uji dengan nilai < 1.
  - Lift terukur mencakup jendela konversi 30 hari, dianggap setara efek bulan ke-1.
  - Tidak ada musiman, tren hanya dari `baseline_monthly_growth_rate` (default 0).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from services.decision.measurement.uplift import (
    DEFAULT_REVENUE_BASIS,
    UpliftResult,
)

MIN_HORIZON_MONTHS = 1
MAX_HORIZON_MONTHS = 3
DEFAULT_BASELINE_WINDOW_MONTHS = 3


@dataclass(frozen=True)
class MonthlyProjection:
    month_index: int
    baseline_revenue: float
    campaign_revenue: float
    incremental_revenue: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "month_index": self.month_index,
            "baseline_revenue": self.baseline_revenue,
            "campaign_revenue": self.campaign_revenue,
            "incremental_revenue": self.incremental_revenue,
        }


@dataclass(frozen=True)
class ForecastResult:
    horizon_months: int
    months: Tuple[MonthlyProjection, ...]
    baseline_total: float
    campaign_total: float
    incremental_total: float
    incremental_pct_of_baseline: Optional[float]
    revenue_basis: str
    is_provisional: bool
    assumptions: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "horizon_months": self.horizon_months,
            "months": [m.to_dict() for m in self.months],
            "baseline_total": self.baseline_total,
            "campaign_total": self.campaign_total,
            "incremental_total": self.incremental_total,
            "incremental_pct_of_baseline": self.incremental_pct_of_baseline,
            "revenue_basis": self.revenue_basis,
            "is_provisional": self.is_provisional,
            "assumptions": list(self.assumptions),
        }


def _finite(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} harus berupa angka.")
    if not math.isfinite(value):
        raise ValueError(f"{name} harus terhingga.")
    return float(value)


def lift_per_treated_customer(uplift: UpliftResult) -> float:
    """Incremental revenue per pelanggan treatment dari hasil pengukuran."""
    return uplift.incremental_revenue / uplift.treatment.n_customers


def project_revenue(
    *,
    monthly_revenue_history: Sequence[float],
    horizon_months: int,
    treated_customers: int,
    incremental_revenue_per_treated_customer: float,
    baseline_window_months: int = DEFAULT_BASELINE_WINDOW_MONTHS,
    baseline_monthly_growth_rate: float = 0.0,
    effect_decay_per_month: float = 1.0,
    lift_realization: float = 1.0,
    is_provisional: bool = False,
    revenue_basis: str = DEFAULT_REVENUE_BASIS,
) -> ForecastResult:
    """
    Membandingkan forecast baseline vs skenario kampanye untuk 1-3 bulan.

    Args:
        monthly_revenue_history: pendapatan bulanan historis (terlama -> terbaru), >= 1 nilai.
        horizon_months: 1..3.
        treated_customers: jumlah pelanggan yang akan menerima kampanye.
        incremental_revenue_per_treated_customer: lift bulan ke-1 per pelanggan
            (boleh negatif bila kampanye merugikan).
        baseline_window_months: jumlah bulan terakhir yang dirata-rata.
        baseline_monthly_growth_rate: pertumbuhan baseline per bulan (> -1).
        effect_decay_per_month: faktor peluruhan efek (0..1).
        lift_realization: pengali skenario (0.5 = konservatif, 1.5 = optimistis).
        is_provisional: True bila lift berasal dari pengukuran PROVISIONAL.
    """
    if isinstance(horizon_months, bool) or not isinstance(horizon_months, int):
        raise ValueError("horizon_months harus integer.")
    if not MIN_HORIZON_MONTHS <= horizon_months <= MAX_HORIZON_MONTHS:
        raise ValueError(
            f"horizon_months harus {MIN_HORIZON_MONTHS}..{MAX_HORIZON_MONTHS}, "
            f"diterima {horizon_months}."
        )
    history = [_finite("monthly_revenue_history", v) for v in monthly_revenue_history]
    if not history:
        raise ValueError("monthly_revenue_history tidak boleh kosong.")
    if any(v < 0 for v in history):
        raise ValueError("monthly_revenue_history tidak boleh berisi nilai negatif.")
    if baseline_window_months < 1:
        raise ValueError("baseline_window_months harus >= 1.")
    if isinstance(treated_customers, bool) or treated_customers < 0:
        raise ValueError("treated_customers harus >= 0.")
    growth = _finite("baseline_monthly_growth_rate", baseline_monthly_growth_rate)
    if growth <= -1.0:
        raise ValueError("baseline_monthly_growth_rate harus > -1.")
    decay = _finite("effect_decay_per_month", effect_decay_per_month)
    if not 0.0 <= decay <= 1.0:
        raise ValueError("effect_decay_per_month harus di antara 0 dan 1.")
    realization = _finite("lift_realization", lift_realization)
    if realization < 0:
        raise ValueError("lift_realization harus >= 0.")
    per_customer = _finite(
        "incremental_revenue_per_treated_customer",
        incremental_revenue_per_treated_customer,
    )

    window = history[-baseline_window_months:]
    base_level = sum(window) / len(window)

    months: List[MonthlyProjection] = []
    for m in range(1, horizon_months + 1):
        baseline = base_level * (1.0 + growth) ** m
        incremental = per_customer * treated_customers * realization * decay ** (m - 1)
        months.append(
            MonthlyProjection(m, baseline, baseline + incremental, incremental)
        )

    baseline_total = sum(p.baseline_revenue for p in months)
    incremental_total = sum(p.incremental_revenue for p in months)
    assumptions = [
        f"Baseline = rata-rata {len(window)} bulan terakhir ({base_level:,.2f}); "
        f"tanpa musiman; pertumbuhan {growth:.2%}/bulan.",
        "Lift terukur (jendela konversi 30 hari) dianggap setara efek bulan ke-1.",
        f"Efek kampanye meluruh x{decay:g} per bulan; realisasi lift x{realization:g}.",
        f"Basis pendapatan: {revenue_basis}.",
        "Proyeksi adalah skenario, bukan fakta; bukan jaminan hasil.",
    ]
    if decay == 1.0 and horizon_months > 1:
        assumptions.append(
            "PERHATIAN: efek diasumsikan tidak meluruh; ini bisa terlalu optimistis."
        )
    if is_provisional:
        assumptions.append(
            "PROVISIONAL: lift berasal dari pengukuran yang belum final."
        )
    if per_customer < 0:
        assumptions.append("PERHATIAN: lift negatif; kampanye menurunkan pendapatan.")

    return ForecastResult(
        horizon_months=horizon_months,
        months=tuple(months),
        baseline_total=baseline_total,
        campaign_total=baseline_total + incremental_total,
        incremental_total=incremental_total,
        incremental_pct_of_baseline=(
            incremental_total / baseline_total if baseline_total > 0 else None
        ),
        revenue_basis=revenue_basis,
        is_provisional=is_provisional,
        assumptions=tuple(assumptions),
    )


def project_from_uplift(
    uplift: UpliftResult,
    *,
    monthly_revenue_history: Sequence[float],
    horizon_months: int,
    treated_customers: Optional[int] = None,
    **kwargs: Any,
) -> ForecastResult:
    """
    Proyeksi langsung dari hasil `compute_uplift`.

    `treated_customers` default = N treatment saat pengukuran; isi untuk memproyeksikan
    peluncuran ke audiens yang lebih besar.
    """
    return project_revenue(
        monthly_revenue_history=monthly_revenue_history,
        horizon_months=horizon_months,
        treated_customers=(
            uplift.treatment.n_customers
            if treated_customers is None
            else treated_customers
        ),
        incremental_revenue_per_treated_customer=lift_per_treated_customer(uplift),
        is_provisional=not uplift.is_final,
        revenue_basis=uplift.revenue_basis,
        **kwargs,
    )
