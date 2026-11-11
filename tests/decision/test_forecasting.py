"""
test_forecasting.py — Test Revenue Forecasting Baseline vs Campaign (Minggu 11).

Jalankan: python -m pytest tests/decision/test_forecasting.py -v
"""

from datetime import datetime

import pytest

from services.decision.campaign.holdout import HoldoutSplit
from services.decision.forecasting.projector import (
    lift_per_treated_customer,
    project_from_uplift,
    project_revenue,
)
from services.decision.measurement.uplift import (
    Outcome,
    build_window,
    compute_uplift,
)

BASE = dict(
    monthly_revenue_history=[1_000_000, 1_000_000, 1_000_000],
    treated_customers=100,
    incremental_revenue_per_treated_customer=100,
)


class TestBaselineAndCampaign:
    def test_constant_effect_three_months(self):
        f = project_revenue(horizon_months=3, **BASE)
        assert [m.baseline_revenue for m in f.months] == [1_000_000] * 3
        assert [m.incremental_revenue for m in f.months] == [10_000] * 3
        assert [m.campaign_revenue for m in f.months] == [1_010_000] * 3
        assert f.baseline_total == 3_000_000 and f.campaign_total == 3_030_000
        assert f.incremental_total == 30_000
        assert f.incremental_pct_of_baseline == pytest.approx(0.01)

    def test_decay(self):
        f = project_revenue(horizon_months=3, effect_decay_per_month=0.5, **BASE)
        assert [m.incremental_revenue for m in f.months] == [10_000, 5_000, 2_500]
        assert f.incremental_total == 17_500

    def test_realization_scales_lift(self):
        low = project_revenue(horizon_months=1, lift_realization=0.5, **BASE)
        high = project_revenue(horizon_months=1, lift_realization=1.5, **BASE)
        assert low.incremental_total == 5_000 and high.incremental_total == 15_000

    def test_growth_compounds_baseline(self):
        f = project_revenue(
            monthly_revenue_history=[100],
            horizon_months=3,
            treated_customers=0,
            incremental_revenue_per_treated_customer=0,
            baseline_monthly_growth_rate=0.1,
        )
        assert [m.baseline_revenue for m in f.months] == pytest.approx(
            [110, 121, 133.1]
        )

    def test_baseline_uses_last_n_months(self):
        f = project_revenue(
            monthly_revenue_history=[1, 1, 1, 100, 200, 300],
            horizon_months=1,
            treated_customers=0,
            incremental_revenue_per_treated_customer=0,
        )
        assert f.months[0].baseline_revenue == 200

    def test_short_history_uses_all(self):
        f = project_revenue(
            monthly_revenue_history=[50, 150],
            horizon_months=1,
            treated_customers=0,
            incremental_revenue_per_treated_customer=0,
        )
        assert f.months[0].baseline_revenue == 100

    @pytest.mark.parametrize("h", [1, 2, 3])
    def test_horizon_lengths(self, h):
        f = project_revenue(horizon_months=h, **BASE)
        assert len(f.months) == h and f.horizon_months == h
        assert [m.month_index for m in f.months] == list(range(1, h + 1))

    def test_negative_lift_is_allowed_and_flagged(self):
        f = project_revenue(
            horizon_months=1,
            monthly_revenue_history=[1_000],
            treated_customers=10,
            incremental_revenue_per_treated_customer=-5,
        )
        assert f.incremental_total == -50 and f.campaign_total < f.baseline_total
        assert any("negatif" in a for a in f.assumptions)

    def test_zero_baseline_gives_no_percentage(self):
        f = project_revenue(
            monthly_revenue_history=[0],
            horizon_months=1,
            treated_customers=1,
            incremental_revenue_per_treated_customer=10,
        )
        assert f.incremental_pct_of_baseline is None


class TestAssumptionsAndFlags:
    def test_assumptions_always_present(self):
        f = project_revenue(horizon_months=2, **BASE)
        text = " ".join(f.assumptions)
        assert "Baseline" in text and "bukan fakta" in text
        assert "REFUND_ADJUSTED" in text

    def test_no_decay_warning_only_for_multi_month(self):
        multi = project_revenue(horizon_months=3, **BASE)
        single = project_revenue(horizon_months=1, **BASE)
        assert any("tidak meluruh" in a for a in multi.assumptions)
        assert not any("tidak meluruh" in a for a in single.assumptions)

    def test_provisional_flag(self):
        f = project_revenue(horizon_months=1, is_provisional=True, **BASE)
        assert f.is_provisional and any("PROVISIONAL" in a for a in f.assumptions)

    def test_to_dict(self):
        d = project_revenue(horizon_months=2, **BASE).to_dict()
        assert len(d["months"]) == 2 and d["baseline_total"] == 2_000_000
        assert d["assumptions"] and d["revenue_basis"] == "REFUND_ADJUSTED"


class TestValidation:
    @pytest.mark.parametrize("h", [0, 4, -1, 1.5, True, "2", None])
    def test_horizon_must_be_1_to_3(self, h):
        with pytest.raises(ValueError):
            project_revenue(horizon_months=h, **BASE)

    @pytest.mark.parametrize(
        "kw",
        [
            {"monthly_revenue_history": []},
            {"monthly_revenue_history": [100, -1]},
            {"monthly_revenue_history": [float("nan")]},
            {"treated_customers": -1},
            {"baseline_window_months": 0},
            {"baseline_monthly_growth_rate": -1.0},
            {"effect_decay_per_month": 1.5},
            {"effect_decay_per_month": -0.1},
            {"lift_realization": -1},
            {"incremental_revenue_per_treated_customer": float("inf")},
        ],
    )
    def test_invalid_inputs(self, kw):
        with pytest.raises(ValueError):
            project_revenue(horizon_months=1, **{**BASE, **kw})


class TestFromUplift:
    def setup_method(self):
        t = tuple(f"T{i}" for i in range(900))
        c = tuple(f"C{i}" for i in range(100))
        split = HoldoutSplit("CMP-1", 1, 0.1, t, c)
        window = build_window(datetime(2026, 11, 1), datetime(2026, 11, 7))
        when = datetime(2026, 11, 10)
        rows = [
            Outcome(f"OT{i}", f"T{i}", "PURCHASE", when, 100_000) for i in range(90)
        ]
        rows += [
            Outcome(f"OC{i}", f"C{i}", "PURCHASE", when, 100_000) for i in range(5)
        ]
        self.final = compute_uplift(split, rows, window, as_of=datetime(2027, 3, 1))
        self.prov = compute_uplift(split, rows, window, as_of=datetime(2026, 11, 15))

    def test_lift_per_customer(self):
        assert lift_per_treated_customer(self.final) == pytest.approx(5_000)

    def test_projection_matches_measured_incremental_month_one(self):
        f = project_from_uplift(
            self.final, monthly_revenue_history=[2_000_000], horizon_months=1
        )
        assert f.months[0].incremental_revenue == pytest.approx(4_500_000)
        assert not f.is_provisional

    def test_scale_to_larger_audience(self):
        f = project_from_uplift(
            self.final,
            monthly_revenue_history=[2_000_000],
            horizon_months=1,
            treated_customers=1_800,
        )
        assert f.months[0].incremental_revenue == pytest.approx(9_000_000)

    def test_provisional_uplift_propagates(self):
        f = project_from_uplift(
            self.prov, monthly_revenue_history=[2_000_000], horizon_months=2
        )
        assert f.is_provisional

    def test_kwargs_forwarded(self):
        f = project_from_uplift(
            self.final,
            monthly_revenue_history=[2_000_000],
            horizon_months=2,
            effect_decay_per_month=0.5,
        )
        assert f.months[1].incremental_revenue == pytest.approx(2_250_000)
