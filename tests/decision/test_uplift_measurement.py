"""
test_uplift_measurement.py — Verifikasi independen rumus Incremental Revenue (Fase 4, Minggu 12).

Berbeda dari `test_uplift.py` (contoh manual & edge case per fungsi), file ini menguji
rumus dari sisi lain:

  1. Differential testing: 300 skenario acak (seed tetap) dibandingkan dengan ORACLE
     brute-force yang ditulis ulang tanpa memakai kode di `uplift.py`.
  2. Properti matematis: linearitas, identitas per-kapita, aditivitas, dan kasus nol.
  3. Contoh hitung-tangan baru (angka berbeda dari test_uplift.py) termasuk refund.

Rumus (Panduan Minggu 10):
    IncrementalRevenue = Revenue_Treatment - Revenue_Control x (N_Treatment / N_Control)

Jalankan: python -m pytest tests/decision/test_uplift_measurement.py -v
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import List, Tuple

import pytest

from services.decision.campaign.holdout import HoldoutSplit
from services.decision.measurement.uplift import (
    BASIS_GROSS,
    BASIS_NET,
    BASIS_REFUND_ADJUSTED,
    Outcome,
    RefundEvent,
    build_window,
    compute_uplift,
    incremental_revenue,
)

START = datetime(2026, 11, 1)
END = datetime(2026, 11, 7)
CONVERSION_DAYS = 30
ADJUSTMENT_DAYS = 14
WINDOW = build_window(START, END, CONVERSION_DAYS, ADJUSTMENT_DAYS)
OBS_START = START
OBS_END = END + timedelta(days=CONVERSION_DAYS)
LATE = datetime(2027, 3, 1)  # jauh setelah finalisasi


def make_split(n_t: int, n_c: int) -> HoldoutSplit:
    return HoldoutSplit(
        "CMP-M",
        1,
        0.1,
        tuple(f"T{i}" for i in range(n_t)),
        tuple(f"C{i}" for i in range(n_c)),
    )


def purchase(oid: str, cid: str, value: float, when: datetime, **kw) -> Outcome:
    return Outcome(oid, cid, "PURCHASE", when, value, **kw)


# ---------------------------------------------------------------------------
# Oracle brute-force (tanpa memakai kode uplift.py kecuali dataclass input)
# ---------------------------------------------------------------------------


def oracle_revenue(o: Outcome, basis: str) -> float:
    if basis == BASIS_GROSS:
        return o.gross_revenue
    deadline = o.occurred_at + timedelta(days=ADJUSTMENT_DAYS)
    refund = sum(
        r.amount
        for r in o.refunds
        if r.refunded_at is None or r.refunded_at <= deadline
    )
    if basis == BASIS_REFUND_ADJUSTED:
        return max(0.0, o.gross_revenue - refund)
    return max(
        0.0,
        o.gross_revenue
        - o.discount_amount
        - o.voucher_amount
        - o.tax_amount
        - o.cancellation_deduction
        - refund,
    )


def oracle_group(
    ids: Tuple[str, ...], outcomes: List[Outcome], basis: str
) -> Tuple[int, float]:
    """Mengembalikan (pelanggan yang konversi, total revenue) untuk satu grup."""
    members = set(ids)
    seen = set()
    buyers = set()
    revenue = 0.0
    for o in outcomes:
        if o.customer_id not in members or o.outcome_id in seen:
            continue
        seen.add(o.outcome_id)
        if not (OBS_START <= o.occurred_at <= OBS_END):
            continue
        buyers.add(o.customer_id)
        revenue += oracle_revenue(o, basis)
    return len(buyers), revenue


def random_scenario(rng: random.Random) -> Tuple[HoldoutSplit, List[Outcome]]:
    n_t = rng.randint(20, 400)
    n_c = rng.randint(5, 80)
    split = make_split(n_t, n_c)
    everyone = list(split.treatment_ids) + list(split.control_ids)
    outcomes: List[Outcome] = []
    for i in range(rng.randint(0, 250)):
        cid = rng.choice(everyone)
        when = START - timedelta(days=5) + timedelta(hours=rng.randint(0, 24 * 45))
        gross = float(rng.randint(10, 500) * 1000)
        refunds: Tuple[RefundEvent, ...] = ()
        if rng.random() < 0.3:
            delay = timedelta(days=rng.choice([1, 7, 14, 20]))
            refunds = (
                RefundEvent(
                    amount=float(rng.randint(1, int(gross // 1000)) * 1000),
                    refunded_at=when + delay,
                ),
            )
        outcomes.append(
            purchase(
                f"O{i}",
                cid,
                gross,
                when,
                discount_amount=float(rng.randint(0, 5) * 1000),
                tax_amount=float(rng.randint(0, 3) * 1000),
                refunds=refunds,
            )
        )
        if rng.random() < 0.05:  # duplikat outcome_id harus dihitung sekali
            outcomes.append(outcomes[-1])
    return split, outcomes


# ---------------------------------------------------------------------------
# 1. Differential testing vs oracle
# ---------------------------------------------------------------------------


class TestAgainstOracle:
    @pytest.mark.parametrize("basis", [BASIS_GROSS, BASIS_REFUND_ADJUSTED, BASIS_NET])
    def test_300_random_scenarios_match_oracle(self, basis):
        rng = random.Random(20261116)
        for trial in range(300):
            split, outcomes = random_scenario(rng)
            res = compute_uplift(
                split, outcomes, WINDOW, revenue_basis=basis, as_of=LATE
            )

            buyers_t, rev_t = oracle_group(split.treatment_ids, outcomes, basis)
            buyers_c, rev_c = oracle_group(split.control_ids, outcomes, basis)
            scale = split.n_treatment / split.n_control

            ctx = f"trial={trial} basis={basis}"
            assert res.treatment.converting_customers == buyers_t, ctx
            assert res.control.converting_customers == buyers_c, ctx
            assert res.treatment.revenue == pytest.approx(rev_t), ctx
            assert res.control.revenue == pytest.approx(rev_c), ctx
            assert res.incremental_revenue == pytest.approx(rev_t - rev_c * scale), ctx
            assert res.incremental_conversions == pytest.approx(
                buyers_t - buyers_c * scale
            ), ctx
            assert res.cr_absolute_lift == pytest.approx(
                buyers_t / split.n_treatment - buyers_c / split.n_control
            ), ctx


# ---------------------------------------------------------------------------
# 2. Properti matematis
# ---------------------------------------------------------------------------


class TestMathematicalProperties:
    def _base(self) -> Tuple[HoldoutSplit, List[Outcome]]:
        split = make_split(400, 40)
        when = datetime(2026, 11, 10)
        outcomes = [purchase(f"OT{i}", f"T{i}", 100_000, when) for i in range(60)]
        outcomes += [purchase(f"OC{i}", f"C{i}", 100_000, when) for i in range(3)]
        return split, outcomes

    def test_per_capita_identity(self):
        """IncrementalRevenue == N_T x (RPC_T - RPC_C) dan idem untuk konversi."""
        split, outcomes = self._base()
        res = compute_uplift(split, outcomes, WINDOW, as_of=LATE)
        assert res.incremental_revenue == pytest.approx(
            split.n_treatment * res.revenue_per_customer_lift
        )
        assert res.incremental_conversions == pytest.approx(
            split.n_treatment * res.cr_absolute_lift
        )

    def test_linear_in_order_value(self):
        split, outcomes = self._base()
        base = compute_uplift(split, outcomes, WINDOW, as_of=LATE)
        tripled = [
            purchase(o.outcome_id, o.customer_id, o.gross_revenue * 3, o.occurred_at)
            for o in outcomes
        ]
        res = compute_uplift(split, tripled, WINDOW, as_of=LATE)
        assert res.incremental_revenue == pytest.approx(3 * base.incremental_revenue)
        assert res.incremental_conversions == pytest.approx(
            base.incremental_conversions
        )

    def test_one_more_control_buyer_lowers_incremental_by_value_times_scale(self):
        split, outcomes = self._base()
        base = compute_uplift(split, outcomes, WINDOW, as_of=LATE)
        extra = outcomes + [purchase("OC-X", "C10", 250_000, datetime(2026, 11, 12))]
        res = compute_uplift(split, extra, WINDOW, as_of=LATE)
        scale = split.n_treatment / split.n_control
        assert base.incremental_revenue - res.incremental_revenue == pytest.approx(
            250_000 * scale
        )

    def test_one_more_treatment_buyer_raises_incremental_by_exact_value(self):
        split, outcomes = self._base()
        base = compute_uplift(split, outcomes, WINDOW, as_of=LATE)
        extra = outcomes + [purchase("OT-X", "T300", 175_000, datetime(2026, 11, 12))]
        res = compute_uplift(split, extra, WINDOW, as_of=LATE)
        assert res.incremental_revenue - base.incremental_revenue == pytest.approx(
            175_000
        )

    def test_same_conversion_rate_means_zero_incremental(self):
        split = make_split(900, 100)
        when = datetime(2026, 11, 10)
        outcomes = [purchase(f"OT{i}", f"T{i}", 80_000, when) for i in range(90)]
        outcomes += [purchase(f"OC{i}", f"C{i}", 80_000, when) for i in range(10)]
        res = compute_uplift(split, outcomes, WINDOW, as_of=LATE)
        assert res.incremental_revenue == pytest.approx(0.0)
        assert res.incremental_conversions == pytest.approx(0.0)
        assert res.cr_absolute_lift == pytest.approx(0.0)
        assert res.treatment.revenue > 0  # observed tetap besar, incremental nol

    def test_incremental_is_independent_of_split_size_when_rates_equal(self):
        """Menggandakan kedua grup (rasio sama) tidak mengubah lift per kapita."""
        small = make_split(90, 10)
        large = make_split(900, 100)
        when = datetime(2026, 11, 10)

        def outcomes_for(n_t_buyers: int, n_c_buyers: int):
            rows = [
                purchase(f"OT{i}", f"T{i}", 100_000, when) for i in range(n_t_buyers)
            ]
            rows += [
                purchase(f"OC{i}", f"C{i}", 100_000, when) for i in range(n_c_buyers)
            ]
            return rows

        a = compute_uplift(small, outcomes_for(18, 1), WINDOW, as_of=LATE)
        b = compute_uplift(large, outcomes_for(180, 10), WINDOW, as_of=LATE)
        assert a.cr_absolute_lift == pytest.approx(b.cr_absolute_lift)
        assert a.revenue_per_customer_lift == pytest.approx(b.revenue_per_customer_lift)
        assert b.incremental_revenue == pytest.approx(10 * a.incremental_revenue)

    @pytest.mark.parametrize(
        "rev_t,rev_c,n_t,n_c,expected",
        [
            (9_000_000, 500_000, 900, 100, 4_500_000),
            (6_750_000, 300_000, 450, 50, 4_050_000),
            (0, 0, 10, 10, 0),
            (1_000_000, 1_000_000, 10, 10, 0),
            (1_000_000, 2_000_000, 10, 10, -1_000_000),
            (1_000_000, 100_000, 10, 5, 800_000),
        ],
    )
    def test_pure_formula_table(self, rev_t, rev_c, n_t, n_c, expected):
        assert incremental_revenue(rev_t, rev_c, n_t, n_c) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# 3. Contoh hitung-tangan (angka baru) termasuk refund 14 hari
# ---------------------------------------------------------------------------


class TestHandCalculatedExamples:
    def test_example_450_vs_50(self):
        """
        N_T=450, N_C=50 -> scale 9.
        Treatment: 45 pelanggan x Rp150.000 = Rp6.750.000.
        Control  :  2 pelanggan x Rp150.000 = Rp  300.000 -> 300.000 x 9 = 2.700.000.
        Incremental = 6.750.000 - 2.700.000 = Rp4.050.000.
        Incremental conversions = 45 - 2 x 9 = 27. CR_T=0.10, CR_C=0.04, lift=0.06.
        """
        split = make_split(450, 50)
        when = datetime(2026, 11, 9)
        outcomes = [purchase(f"OT{i}", f"T{i}", 150_000, when) for i in range(45)]
        outcomes += [purchase(f"OC{i}", f"C{i}", 150_000, when) for i in range(2)]
        res = compute_uplift(split, outcomes, WINDOW, as_of=LATE)
        assert res.scale_factor == pytest.approx(9.0)
        assert res.incremental_revenue == pytest.approx(4_050_000)
        assert res.incremental_conversions == pytest.approx(27)
        assert res.cr_absolute_lift == pytest.approx(0.06)

    def test_refund_adjustment_14_days_by_hand(self):
        """
        Treatment (N=100): 10 order Rp200.000.
          - order #0: refund Rp50.000 di hari ke-3  -> dihitung (<= 14 hari)
          - order #1: refund Rp80.000 di hari ke-20 -> DIABAIKAN (> 14 hari)
        Revenue treatment = 10 x 200.000 - 50.000 = 1.950.000.
        Control (N=100): 4 order Rp200.000 tanpa refund = 800.000 (scale 1).
        Incremental = 1.950.000 - 800.000 = 1.150.000.
        """
        split = make_split(100, 100)
        when = datetime(2026, 11, 10)
        outcomes: List[Outcome] = []
        for i in range(10):
            refunds: Tuple[RefundEvent, ...] = ()
            if i == 0:
                refunds = (RefundEvent(50_000, when + timedelta(days=3)),)
            if i == 1:
                refunds = (RefundEvent(80_000, when + timedelta(days=20)),)
            outcomes.append(purchase(f"OT{i}", f"T{i}", 200_000, when, refunds=refunds))
        outcomes += [purchase(f"OC{i}", f"C{i}", 200_000, when) for i in range(4)]

        adjusted = compute_uplift(
            split, outcomes, WINDOW, revenue_basis=BASIS_REFUND_ADJUSTED, as_of=LATE
        )
        gross = compute_uplift(
            split, outcomes, WINDOW, revenue_basis=BASIS_GROSS, as_of=LATE
        )
        assert adjusted.treatment.revenue == pytest.approx(1_950_000)
        assert adjusted.incremental_revenue == pytest.approx(1_150_000)
        assert gross.incremental_revenue == pytest.approx(2_000_000 - 800_000)

    def test_conversion_counted_once_per_customer_revenue_counted_per_order(self):
        split = make_split(10, 10)
        when = datetime(2026, 11, 10)
        outcomes = [
            purchase("A1", "T0", 100_000, when),
            purchase("A2", "T0", 50_000, when + timedelta(days=2)),
        ]
        res = compute_uplift(split, outcomes, WINDOW, as_of=LATE)
        assert res.treatment.converting_customers == 1
        assert res.treatment.orders == 2
        assert res.treatment.revenue == pytest.approx(150_000)
