"""
uplift.py — Incremental Revenue & Conversion Uplift Measurement (Minggu 10)
===========================================================================
Menghitung dampak MURNI kampanye dengan membandingkan Treatment vs Holdout Control.

Rumus (Panduan Minggu 10):
    IncrementalRevenue = Revenue_Treatment - (Revenue_Control x (N_Treatment / N_Control))
    IncrementalConversions = Conv_Treatment - (Conv_Control x (N_Treatment / N_Control))
    ConversionRateLift (absolut) = CR_Treatment - CR_Control

Pelaporan dipisah tegas:
    - OBSERVED    : apa adanya yang terjadi di grup treatment (termasuk pembelian yang
                    akan terjadi tanpa kampanye).
    - INCREMENTAL : selisih terhadap control = efek kampanye. Hanya ini yang boleh
                    diklaim sebagai hasil kampanye.

Keputusan desain (lihat reference/fase2.md; butuh konfirmasi tim/dosen):
  A1. Jendela observasi = [exposure_window.start, exposure_window.end + conversion_window_days]
      dan SAMA untuk treatment & control (control tidak punya waktu paparan).
  A2. Intent-to-treat: N_Treatment = seluruh pelanggan yang DITUGASKAN ke treatment,
      bukan hanya yang pesannya terkirim.
  A3. Konversi dihitung per pelanggan (>= 1 outcome valid di jendela), pendapatan per outcome.
  A4. Basis pendapatan default REFUND_ADJUSTED = gross - refund yang terjadi dalam
      adjustment_window_days (14 hari) sejak transaksi. Refund di luar jendela diabaikan
      (K-09: NET_FINALIZED setelah 14 hari). Basis GROSS dan NET tersedia.
  A5. Hasil berstatus PROVISIONAL sampai `as_of` melewati
      exposure_end + conversion_window + adjustment_window.

Modul 100% offline, deterministik, hanya memakai pustaka standar.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import (
    Any,
    Collection,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Tuple,
)

from services.decision.campaign.holdout import HoldoutSplit
from services.decision.timeutil import to_naive_utc, utc_now

# ---------------------------------------------------------------------------
# Konstanta
# ---------------------------------------------------------------------------

CONVERSION_TYPES = frozenset({"BOOKING", "PURCHASE", "MEMBERSHIP_RENEWAL", "UPGRADE"})
DEFAULT_CONVERSION_WINDOW_DAYS = 30
DEFAULT_ADJUSTMENT_WINDOW_DAYS = 14

BASIS_GROSS = "GROSS"
BASIS_REFUND_ADJUSTED = "REFUND_ADJUSTED"
BASIS_NET = "NET"
REVENUE_BASES = (BASIS_GROSS, BASIS_REFUND_ADJUSTED, BASIS_NET)
DEFAULT_REVENUE_BASIS = BASIS_REFUND_ADJUSTED

STATUS_FINAL = "FINAL"
STATUS_PROVISIONAL = "PROVISIONAL"

Z_95 = 1.959963984540054

REPORTING_NOTE = (
    "Hanya blok 'incremental' yang menunjukkan efek kampanye. Blok 'observed' mencakup "
    "pembelian yang akan terjadi tanpa kampanye dan tidak boleh disajikan sebagai dampak."
)


def _check_amount(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} harus berupa angka.")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} harus >= 0 dan terhingga, diterima {value}.")
    return number


# ---------------------------------------------------------------------------
# Input: Outcome & Refund
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RefundEvent:
    """Satu pengembalian dana. `refunded_at=None` = waktu tidak diketahui (dianggap di jendela)."""

    amount: float
    refunded_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", _check_amount("refund.amount", self.amount))
        if self.refunded_at is not None:
            object.__setattr__(self, "refunded_at", to_naive_utc(self.refunded_at))


@dataclass(frozen=True)
class Outcome:
    """Satu konversi bentuk K-09 (`contracts/K-09_outcome_definition.json`)."""

    outcome_id: str
    customer_id: str
    conversion_type: str
    occurred_at: datetime
    gross_revenue: float
    discount_amount: float = 0.0
    voucher_amount: float = 0.0
    tax_amount: float = 0.0
    cancellation_deduction: float = 0.0
    refunds: Tuple[RefundEvent, ...] = ()
    correlation_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not str(self.outcome_id).strip():
            raise ValueError("outcome_id tidak boleh kosong.")
        if not str(self.customer_id).strip():
            raise ValueError("customer_id tidak boleh kosong.")
        object.__setattr__(self, "customer_id", str(self.customer_id).strip())
        if self.conversion_type not in CONVERSION_TYPES:
            raise ValueError(
                f"conversion_type '{self.conversion_type}' tidak valid; "
                f"harus salah satu dari {sorted(CONVERSION_TYPES)}."
            )
        occurred = to_naive_utc(self.occurred_at)
        object.__setattr__(self, "occurred_at", occurred)
        for name in (
            "gross_revenue",
            "discount_amount",
            "voucher_amount",
            "tax_amount",
            "cancellation_deduction",
        ):
            object.__setattr__(self, name, _check_amount(name, getattr(self, name)))
        for refund in self.refunds:
            if refund.refunded_at is not None and refund.refunded_at < occurred:
                raise ValueError("refunded_at tidak boleh lebih awal dari occurred_at.")

    @classmethod
    def from_k09(cls, record: Mapping[str, Any]) -> "Outcome":
        """
        Membuat Outcome dari dict K-09.

        K-09 tidak mewajibkan `occurred_at` dan tidak memuat waktu refund; keduanya diperlukan
        untuk jendela pengukuran, sehingga:
          - `occurred_at` WAJIB (ValueError bila tidak ada).
          - Ekstensi opsional `refund_events: [{amount, refunded_at}]` dipakai bila ada.
          - Jika tidak, `deductions.refund_amount` dicatat sebagai satu refund tanpa waktu
            (dianggap terjadi dalam adjustment window).
        """
        for key in ("outcome_id", "customer_id", "conversion_type", "gross_revenue"):
            if record.get(key) is None:
                raise ValueError(f"Field K-09 '{key}' wajib ada.")
        if record.get("occurred_at") is None:
            raise ValueError("occurred_at wajib ada untuk pengukuran jendela konversi.")
        deductions = record.get("deductions") or {}
        refunds: List[RefundEvent] = []
        events = record.get("refund_events")
        if events:
            refunds = [RefundEvent(e["amount"], e.get("refunded_at")) for e in events]
        elif float(deductions.get("refund_amount", 0.0) or 0.0) > 0:
            refunds = [RefundEvent(float(deductions["refund_amount"]), None)]
        return cls(
            outcome_id=str(record["outcome_id"]),
            customer_id=str(record["customer_id"]),
            conversion_type=record["conversion_type"],
            occurred_at=record["occurred_at"],
            gross_revenue=record["gross_revenue"],
            discount_amount=deductions.get("discount_amount", 0.0) or 0.0,
            voucher_amount=deductions.get("voucher_amount", 0.0) or 0.0,
            tax_amount=deductions.get("tax_amount", 0.0) or 0.0,
            cancellation_deduction=deductions.get("cancellation_deduction", 0.0) or 0.0,
            refunds=tuple(refunds),
            correlation_id=record.get("correlation_id"),
        )

    def refund_in_window(
        self, adjustment_window_days: int = DEFAULT_ADJUSTMENT_WINDOW_DAYS
    ) -> float:
        """Total refund yang terjadi dalam adjustment window sejak transaksi."""
        deadline = self.occurred_at + timedelta(days=adjustment_window_days)
        return sum(
            r.amount
            for r in self.refunds
            if r.refunded_at is None or r.refunded_at <= deadline
        )

    def revenue(
        self,
        basis: str = DEFAULT_REVENUE_BASIS,
        adjustment_window_days: int = DEFAULT_ADJUSTMENT_WINDOW_DAYS,
    ) -> float:
        """Pendapatan outcome menurut basis (tidak pernah negatif)."""
        if basis == BASIS_GROSS:
            return self.gross_revenue
        refund = self.refund_in_window(adjustment_window_days)
        if basis == BASIS_REFUND_ADJUSTED:
            return max(0.0, self.gross_revenue - refund)
        if basis == BASIS_NET:
            return max(
                0.0,
                self.gross_revenue
                - self.discount_amount
                - self.voucher_amount
                - self.tax_amount
                - self.cancellation_deduction
                - refund,
            )
        raise ValueError(f"Basis pendapatan tidak dikenal: {basis}")


# ---------------------------------------------------------------------------
# Jendela pengukuran
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MeasurementWindow:
    """Jendela observasi konversi + penyesuaian (asumsi A1)."""

    observation_start: datetime
    observation_end: datetime
    conversion_window_days: int
    adjustment_window_days: int

    @property
    def finalization_date(self) -> datetime:
        return self.observation_end + timedelta(days=self.adjustment_window_days)

    def contains(self, moment: datetime) -> bool:
        return self.observation_start <= moment <= self.observation_end


def build_window(
    exposure_start: Any,
    exposure_end: Any,
    conversion_window_days: int = DEFAULT_CONVERSION_WINDOW_DAYS,
    adjustment_window_days: int = DEFAULT_ADJUSTMENT_WINDOW_DAYS,
) -> MeasurementWindow:
    start = to_naive_utc(exposure_start)
    end = to_naive_utc(exposure_end)
    if end < start:
        raise ValueError("exposure_end tidak boleh lebih awal dari exposure_start.")
    if conversion_window_days < 1:
        raise ValueError("conversion_window_days harus >= 1.")
    if adjustment_window_days < 0:
        raise ValueError("adjustment_window_days harus >= 0.")
    return MeasurementWindow(
        observation_start=start,
        observation_end=end + timedelta(days=conversion_window_days),
        conversion_window_days=conversion_window_days,
        adjustment_window_days=adjustment_window_days,
    )


def window_from_campaign(campaign: Mapping[str, Any]) -> MeasurementWindow:
    """Membangun jendela dari metadata K-08."""
    exposure = campaign.get("exposure_window") or {}
    return build_window(
        exposure.get("start_time"),
        exposure.get("end_time"),
        campaign.get("conversion_window_days", DEFAULT_CONVERSION_WINDOW_DAYS),
        campaign.get("adjustment_window_days", DEFAULT_ADJUSTMENT_WINDOW_DAYS),
    )


# ---------------------------------------------------------------------------
# Rumus murni
# ---------------------------------------------------------------------------


def incremental_revenue(
    revenue_treatment: float,
    revenue_control: float,
    n_treatment: int,
    n_control: int,
) -> float:
    """IncrementalRevenue = Rev_T - Rev_C x (N_T / N_C)."""
    if n_treatment <= 0 or n_control <= 0:
        raise ValueError("n_treatment dan n_control harus > 0.")
    return revenue_treatment - revenue_control * (n_treatment / n_control)


def conversion_rate_lift(
    conversions_treatment: int,
    conversions_control: int,
    n_treatment: int,
    n_control: int,
) -> Dict[str, Optional[float]]:
    """Lift konversi absolut & relatif (relatif None bila CR control = 0)."""
    if n_treatment <= 0 or n_control <= 0:
        raise ValueError("n_treatment dan n_control harus > 0.")
    cr_t = conversions_treatment / n_treatment
    cr_c = conversions_control / n_control
    absolute = cr_t - cr_c
    return {
        "cr_treatment": cr_t,
        "cr_control": cr_c,
        "absolute_lift": absolute,
        "relative_lift": (absolute / cr_c) if cr_c > 0 else None,
    }


def _two_proportion_stats(
    x_t: int, n_t: int, x_c: int, n_c: int
) -> Tuple[Optional[float], Optional[float], Optional[Tuple[float, float]]]:
    """(z, p_value dua sisi, CI 95% selisih proporsi). None bila tidak terdefinisi."""
    p_t, p_c = x_t / n_t, x_c / n_c
    diff = p_t - p_c
    pooled = (x_t + x_c) / (n_t + n_c)
    se_pool = math.sqrt(pooled * (1 - pooled) * (1 / n_t + 1 / n_c))
    z = diff / se_pool if se_pool > 0 else None
    p_value = math.erfc(abs(z) / math.sqrt(2)) if z is not None else None
    se = math.sqrt(p_t * (1 - p_t) / n_t + p_c * (1 - p_c) / n_c)
    ci = (diff - Z_95 * se, diff + Z_95 * se) if se > 0 else None
    return z, p_value, ci


# ---------------------------------------------------------------------------
# Hasil
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GroupStats:
    group: str
    n_customers: int
    converting_customers: int
    orders: int
    revenue: float

    @property
    def conversion_rate(self) -> float:
        return self.converting_customers / self.n_customers

    @property
    def revenue_per_customer(self) -> float:
        return self.revenue / self.n_customers

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group": self.group,
            "n_customers": self.n_customers,
            "converting_customers": self.converting_customers,
            "orders": self.orders,
            "revenue": self.revenue,
            "conversion_rate": self.conversion_rate,
            "revenue_per_customer": self.revenue_per_customer,
        }


@dataclass(frozen=True)
class UpliftResult:
    campaign_id: str
    revenue_basis: str
    status: str
    as_of: datetime
    window: MeasurementWindow
    treatment: GroupStats
    control: GroupStats
    scale_factor: float
    incremental_revenue: float
    incremental_conversions: float
    cr_absolute_lift: float
    cr_relative_lift: Optional[float]
    revenue_per_customer_lift: float
    cr_z_score: Optional[float]
    cr_p_value: Optional[float]
    cr_ci95: Optional[Tuple[float, float]]
    ignored_outcomes: int = 0
    outside_window_outcomes: int = 0
    duplicate_outcomes: int = 0
    pending_adjustment_outcomes: int = 0
    exposed_treatment_count: Optional[int] = None
    control_exposed_count: int = 0
    warnings: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_final(self) -> bool:
        return self.status == STATUS_FINAL

    @property
    def significant_at_5pct(self) -> Optional[bool]:
        return None if self.cr_p_value is None else self.cr_p_value < 0.05

    def to_dict(self) -> Dict[str, Any]:
        """Laporan terstruktur; blok observed dan incremental DIPISAH tegas."""
        return {
            "campaign_id": self.campaign_id,
            "revenue_basis": self.revenue_basis,
            "status": self.status,
            "as_of": self.as_of.isoformat(),
            "window": {
                "observation_start": self.window.observation_start.isoformat(),
                "observation_end": self.window.observation_end.isoformat(),
                "conversion_window_days": self.window.conversion_window_days,
                "adjustment_window_days": self.window.adjustment_window_days,
                "finalization_date": self.window.finalization_date.isoformat(),
            },
            "observed_conversion": {
                "treatment": self.treatment.to_dict(),
                "control": self.control.to_dict(),
                "treatment_conversion_rate": self.treatment.conversion_rate,
                "treatment_revenue": self.treatment.revenue,
            },
            "incremental_conversion": {
                "scale_factor_n_treatment_over_n_control": self.scale_factor,
                "incremental_conversions": self.incremental_conversions,
                "conversion_rate_lift_absolute": self.cr_absolute_lift,
                "conversion_rate_lift_relative": self.cr_relative_lift,
                "incremental_revenue": self.incremental_revenue,
                "revenue_per_customer_lift": self.revenue_per_customer_lift,
                "z_score": self.cr_z_score,
                "p_value_two_sided": self.cr_p_value,
                "conversion_rate_lift_ci95": (
                    list(self.cr_ci95) if self.cr_ci95 is not None else None
                ),
                "significant_at_5pct": self.significant_at_5pct,
            },
            "data_quality": {
                "ignored_outcomes_not_in_audience": self.ignored_outcomes,
                "outside_window_outcomes": self.outside_window_outcomes,
                "duplicate_outcomes": self.duplicate_outcomes,
                "pending_adjustment_outcomes": self.pending_adjustment_outcomes,
                "exposed_treatment_count": self.exposed_treatment_count,
                "control_exposed_count": self.control_exposed_count,
            },
            "warnings": list(self.warnings),
            "reporting_note": REPORTING_NOTE,
        }

    def measurement_rows(self) -> List[Dict[str, Any]]:
        """
        Baris siap-simpan ke `msr.campaign_measurements` (milik James):
        {metric_name, observed_value, incremental_value}. `campaign_id` (integer di DB)
        dipetakan oleh pemanggil.
        """
        return [
            {
                "metric_name": "conversion_rate",
                "observed_value": self.treatment.conversion_rate,
                "incremental_value": self.cr_absolute_lift,
            },
            {
                "metric_name": "converting_customers",
                "observed_value": float(self.treatment.converting_customers),
                "incremental_value": self.incremental_conversions,
            },
            {
                "metric_name": "revenue",
                "observed_value": self.treatment.revenue,
                "incremental_value": self.incremental_revenue,
            },
        ]


# ---------------------------------------------------------------------------
# Fungsi utama
# ---------------------------------------------------------------------------


def compute_uplift(
    split: HoldoutSplit,
    outcomes: Iterable[Outcome],
    window: MeasurementWindow,
    *,
    revenue_basis: str = DEFAULT_REVENUE_BASIS,
    as_of: Optional[datetime] = None,
    exposed_customer_ids: Optional[Collection[str]] = None,
) -> UpliftResult:
    """
    Menghitung Conversion Rate Lift dan Incremental Revenue.

    Args:
        split: pembagian treatment/control kampanye.
        outcomes: konversi (K-09). Outcome pelanggan di luar audiens, di luar jendela, atau
            ber-`outcome_id` ganda diabaikan dan dihitung di `data_quality`.
        window: jendela observasi (`build_window` / `window_from_campaign`).
        revenue_basis: GROSS / REFUND_ADJUSTED (default) / NET.
        as_of: waktu pengukuran (default: sekarang). Menentukan FINAL vs PROVISIONAL.
        exposed_customer_ids: opsional, ID yang benar-benar terpapar (dari simulator) untuk
            mendeteksi kontaminasi control.

    Raises:
        ValueError: grup treatment atau control kosong, atau basis tidak dikenal.
    """
    if revenue_basis not in REVENUE_BASES:
        raise ValueError(f"revenue_basis harus salah satu dari {REVENUE_BASES}.")
    if split.n_treatment == 0 or split.n_control == 0:
        raise ValueError(
            "Grup treatment dan control keduanya harus berisi pelanggan; "
            "Incremental Revenue tidak dapat dihitung."
        )
    moment = to_naive_utc(as_of) if as_of is not None else utc_now()
    adj = window.adjustment_window_days

    seen_ids: set[str] = set()
    customers: Dict[str, set[str]] = {"TREATMENT": set(), "CONTROL": set()}
    orders = {"TREATMENT": 0, "CONTROL": 0}
    revenue = {"TREATMENT": 0.0, "CONTROL": 0.0}
    ignored = outside = duplicates = pending = 0

    for outcome in outcomes:
        group = split.group_of(outcome.customer_id)
        if group is None:
            ignored += 1
            continue
        if outcome.outcome_id in seen_ids:
            duplicates += 1
            continue
        seen_ids.add(outcome.outcome_id)
        if not window.contains(outcome.occurred_at):
            outside += 1
            continue
        customers[group].add(outcome.customer_id)
        orders[group] += 1
        revenue[group] += outcome.revenue(revenue_basis, adj)
        if moment < outcome.occurred_at + timedelta(days=adj):
            pending += 1

    treatment = GroupStats(
        "TREATMENT",
        split.n_treatment,
        len(customers["TREATMENT"]),
        orders["TREATMENT"],
        revenue["TREATMENT"],
    )
    control = GroupStats(
        "CONTROL",
        split.n_control,
        len(customers["CONTROL"]),
        orders["CONTROL"],
        revenue["CONTROL"],
    )

    scale = split.n_treatment / split.n_control
    inc_rev = incremental_revenue(
        treatment.revenue, control.revenue, split.n_treatment, split.n_control
    )
    inc_conv = treatment.converting_customers - control.converting_customers * scale
    lift = conversion_rate_lift(
        treatment.converting_customers,
        control.converting_customers,
        split.n_treatment,
        split.n_control,
    )
    z, p_value, ci = _two_proportion_stats(
        treatment.converting_customers,
        split.n_treatment,
        control.converting_customers,
        split.n_control,
    )

    status = STATUS_FINAL if moment >= window.finalization_date else STATUS_PROVISIONAL
    warnings: List[str] = []
    if status == STATUS_PROVISIONAL:
        warnings.append(
            "PROVISIONAL: jendela konversi/penyesuaian refund belum selesai; "
            f"angka final baru tersedia setelah {window.finalization_date.isoformat()}."
        )

    exposed_count: Optional[int] = None
    control_exposed = 0
    if exposed_customer_ids is not None:
        exposed = {str(c).strip() for c in exposed_customer_ids}
        exposed_count = sum(1 for c in exposed if split.is_treatment(c))
        control_exposed = sum(1 for c in exposed if split.is_control(c))
        if control_exposed:
            warnings.append(
                f"KONTAMINASI: {control_exposed} anggota control tercatat terpapar; "
                "hasil uplift tidak valid."
            )
    if treatment.converting_customers + control.converting_customers == 0:
        warnings.append("Tidak ada konversi di kedua grup pada jendela ini.")

    return UpliftResult(
        campaign_id=split.campaign_id,
        revenue_basis=revenue_basis,
        status=status,
        as_of=moment,
        window=window,
        treatment=treatment,
        control=control,
        scale_factor=scale,
        incremental_revenue=inc_rev,
        incremental_conversions=inc_conv,
        cr_absolute_lift=float(lift["absolute_lift"] or 0.0),
        cr_relative_lift=lift["relative_lift"],
        revenue_per_customer_lift=treatment.revenue_per_customer
        - control.revenue_per_customer,
        cr_z_score=z,
        cr_p_value=p_value,
        cr_ci95=ci,
        ignored_outcomes=ignored,
        outside_window_outcomes=outside,
        duplicate_outcomes=duplicates,
        pending_adjustment_outcomes=pending,
        exposed_treatment_count=exposed_count,
        control_exposed_count=control_exposed,
        warnings=tuple(warnings),
    )
