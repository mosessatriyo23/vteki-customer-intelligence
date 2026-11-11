"""
touchpoint.py — Last-Touch Attribution (Minggu 11)
==================================================
Mengatribusikan setiap konversi (K-09) ke touchpoint (paparan kampanye) TERAKHIR yang terjadi
dalam jendela konversi (default 30 hari) SEBELUM atau SAAT konversi.

Aturan:
  - Touchpoint setelah konversi tidak pernah eligible.
  - Selisih konversi - touch harus 0 <= selisih <= conversion_window_days.
  - KONFLIK atribusi dicatat bila dalam jendela ada paparan dari >= 2 kampanye berbeda
    (paparan ganda). Touch terakhir tetap dipilih, tetapi konflik ditandai dan kandidat
    lain disimpan di `competing`.
  - Seri waktu persis sama: dipilih campaign_id terkecil (deterministik) dan `tie_on_timestamp`
    ditandai.

PENTING: last-touch adalah ATRIBUSI, bukan INKREMENTALITAS. Pelanggan yang membeli setelah
dipapar belum tentu membeli KARENA kampanye. Efek kausal hanya diukur oleh
`measurement/uplift.py` (Treatment vs Control). Karena itu `is_incremental` pada keluaran
K-09 selalu None di level individu.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from services.decision.measurement.uplift import (
    DEFAULT_ADJUSTMENT_WINDOW_DAYS,
    DEFAULT_CONVERSION_WINDOW_DAYS,
    DEFAULT_REVENUE_BASIS,
    Outcome,
)
from services.decision.simulator.channel_sim import SimulatedDelivery
from services.decision.timeutil import to_naive_utc

STATUS_ATTRIBUTED = "ATTRIBUTED"
STATUS_NO_TOUCHPOINT = "UNATTRIBUTED_NO_TOUCHPOINT"
STATUS_OUTSIDE_WINDOW = "UNATTRIBUTED_OUTSIDE_WINDOW"


@dataclass(frozen=True)
class Touchpoint:
    """Satu paparan kampanye kepada pelanggan."""

    customer_id: str
    campaign_id: str
    action_id: str
    channel: str
    touched_at: datetime
    decision_id: Optional[str] = None
    correlation_id: Optional[str] = None
    delivery_id: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "customer_id", str(self.customer_id).strip())
        object.__setattr__(self, "touched_at", to_naive_utc(self.touched_at))


def touchpoints_from_deliveries(
    deliveries: Iterable[SimulatedDelivery],
) -> List[Touchpoint]:
    """Mengubah rekaman simulator menjadi touchpoint (hanya yang tercatat sebagai paparan)."""
    return [
        Touchpoint(
            customer_id=d.customer_id,
            campaign_id=d.campaign_id,
            action_id=d.action_id,
            channel=d.channel,
            touched_at=d.attempted_at,
            correlation_id=d.correlation_id,
            delivery_id=d.delivery_id,
        )
        for d in deliveries
        if d.exposure_recorded
    ]


@dataclass(frozen=True)
class AttributionResult:
    outcome_id: str
    customer_id: str
    status: str
    conversion_window_days: int
    attributed: Optional[Touchpoint] = None
    days_to_convert: Optional[float] = None
    competing: Tuple[Touchpoint, ...] = ()
    campaigns_in_window: Tuple[str, ...] = ()
    conflict: bool = False
    tie_on_timestamp: bool = False

    @property
    def is_attributed(self) -> bool:
        return self.status == STATUS_ATTRIBUTED

    def to_k09_attribution(self) -> Dict[str, Any]:
        """Blok `attribution` sesuai K-09 (`is_incremental` selalu None di level individu)."""
        a = self.attributed
        return {
            "campaign_id": a.campaign_id if a else None,
            "decision_id": a.decision_id if a else None,
            "action_id": a.action_id if a else None,
            "attributed_channel": a.channel if a else None,
            "days_to_convert": self.days_to_convert,
            "is_incremental": None,
            "attribution_model": "LAST_TOUCH",
            "attribution_status": self.status,
            "attribution_conflict": self.conflict,
            "campaigns_in_window": list(self.campaigns_in_window),
        }


@dataclass(frozen=True)
class AttributionReport:
    results: Tuple[AttributionResult, ...]
    outcomes: Tuple[Outcome, ...] = field(default=(), repr=False)

    @property
    def n_outcomes(self) -> int:
        return len(self.results)

    @property
    def n_attributed(self) -> int:
        return sum(1 for r in self.results if r.is_attributed)

    @property
    def n_unattributed(self) -> int:
        return self.n_outcomes - self.n_attributed

    @property
    def conflicts(self) -> Tuple[AttributionResult, ...]:
        return tuple(r for r in self.results if r.conflict)

    def conversions_by_campaign(self) -> Dict[str, int]:
        counts: Dict[str, int] = defaultdict(int)
        for r in self.results:
            if r.attributed is not None:
                counts[r.attributed.campaign_id] += 1
        return dict(counts)

    def attributed_revenue_by_campaign(
        self,
        revenue_basis: str = DEFAULT_REVENUE_BASIS,
        adjustment_window_days: int = DEFAULT_ADJUSTMENT_WINDOW_DAYS,
    ) -> Dict[str, float]:
        by_id = {o.outcome_id: o for o in self.outcomes}
        totals: Dict[str, float] = defaultdict(float)
        for r in self.results:
            if r.attributed is not None and r.outcome_id in by_id:
                totals[r.attributed.campaign_id] += by_id[r.outcome_id].revenue(
                    revenue_basis, adjustment_window_days
                )
        return dict(totals)

    def summary(self) -> Dict[str, Any]:
        return {
            "model": "LAST_TOUCH",
            "n_outcomes": self.n_outcomes,
            "n_attributed": self.n_attributed,
            "n_unattributed": self.n_unattributed,
            "n_conflicts": len(self.conflicts),
            "conversions_by_campaign": self.conversions_by_campaign(),
            "note": "Atribusi last-touch BUKAN ukuran inkrementalitas; gunakan uplift.",
        }


def attribute_conversion(
    outcome: Outcome,
    touchpoints: Iterable[Touchpoint],
    conversion_window_days: int = DEFAULT_CONVERSION_WINDOW_DAYS,
) -> AttributionResult:
    """Atribusi last-touch untuk satu konversi."""
    if conversion_window_days < 1:
        raise ValueError("conversion_window_days harus >= 1.")
    mine = [t for t in touchpoints if t.customer_id == outcome.customer_id]
    before = [t for t in mine if t.touched_at <= outcome.occurred_at]
    if not before:
        return AttributionResult(
            outcome.outcome_id,
            outcome.customer_id,
            STATUS_NO_TOUCHPOINT,
            conversion_window_days,
        )
    in_window = [
        t
        for t in before
        if (outcome.occurred_at - t.touched_at).total_seconds()
        <= conversion_window_days * 86400
    ]
    if not in_window:
        return AttributionResult(
            outcome.outcome_id,
            outcome.customer_id,
            STATUS_OUTSIDE_WINDOW,
            conversion_window_days,
        )

    latest = max(t.touched_at for t in in_window)
    tied = sorted(
        (t for t in in_window if t.touched_at == latest),
        key=lambda t: (t.campaign_id, t.delivery_id or "", t.action_id),
    )
    winner = tied[0]
    campaigns = tuple(sorted({t.campaign_id for t in in_window}))
    competing = tuple(t for t in in_window if t is not winner)
    return AttributionResult(
        outcome_id=outcome.outcome_id,
        customer_id=outcome.customer_id,
        status=STATUS_ATTRIBUTED,
        conversion_window_days=conversion_window_days,
        attributed=winner,
        days_to_convert=(outcome.occurred_at - winner.touched_at).total_seconds()
        / 86400,
        competing=competing,
        campaigns_in_window=campaigns,
        conflict=len(campaigns) > 1,
        tie_on_timestamp=len({t.campaign_id for t in tied}) > 1,
    )


def attribute_conversions(
    outcomes: Iterable[Outcome],
    touchpoints: Iterable[Touchpoint],
    conversion_window_days: int = DEFAULT_CONVERSION_WINDOW_DAYS,
) -> AttributionReport:
    """Atribusi last-touch untuk banyak konversi (indeks per pelanggan)."""
    by_customer: Mapping[str, List[Touchpoint]] = defaultdict(list)
    for t in touchpoints:
        by_customer[t.customer_id].append(t)
    outs = tuple(outcomes)
    results = tuple(
        attribute_conversion(
            o, by_customer.get(o.customer_id, []), conversion_window_days
        )
        for o in outs
    )
    return AttributionReport(results=results, outcomes=outs)
