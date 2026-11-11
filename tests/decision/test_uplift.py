"""
test_uplift.py — Test Incremental Revenue & Conversion Uplift (Minggu 10).

Contoh utama dihitung manual:
  N_T=900, N_C=100 -> scale 9.
  Treatment: 90 pelanggan konversi x Rp100.000 = Rp9.000.000.
  Control  :  5 pelanggan konversi x Rp100.000 = Rp  500.000.
  IncrementalRevenue = 9.000.000 - 500.000 x 9 = 4.500.000
  IncrementalConversions = 90 - 5 x 9 = 45
  CR_T=0.10, CR_C=0.05 -> lift absolut 0.05, relatif 1.0

Jalankan: python -m pytest tests/decision/test_uplift.py -v
"""

from datetime import datetime, timedelta

import pytest

from services.decision.campaign.holdout import HoldoutSplit
from services.decision.measurement.uplift import (
    BASIS_GROSS,
    BASIS_NET,
    BASIS_REFUND_ADJUSTED,
    STATUS_FINAL,
    STATUS_PROVISIONAL,
    Outcome,
    RefundEvent,
    build_window,
    compute_uplift,
    conversion_rate_lift,
    incremental_revenue,
    window_from_campaign,
)

START = datetime(2026, 11, 1)
END = datetime(2026, 11, 7)
WINDOW = build_window(START, END, 30, 14)  # observasi s.d. 7 Des; final 21 Des
LATE = datetime(2027, 1, 31)  # jauh setelah finalisasi
T_IDS = tuple(f"T{i}" for i in range(900))
C_IDS = tuple(f"C{i}" for i in range(100))
SPLIT = HoldoutSplit("CMP-1", 42, 0.1, T_IDS, C_IDS)


def out(oid, cid, revenue=100_000, when=datetime(2026, 11, 10), **kw):
    return Outcome(oid, cid, "PURCHASE", when, revenue, **kw)


def main_outcomes():
    rows = [out(f"OT{i}", f"T{i}") for i in range(90)]
    rows += [out(f"OC{i}", f"C{i}") for i in range(5)]
    return rows


class TestPureFormulas:
    def test_incremental_revenue_formula(self):
        assert incremental_revenue(9_000_000, 500_000, 900, 100) == 4_500_000

    def test_incremental_revenue_negative_when_control_better(self):
        assert incremental_revenue(100, 100, 100, 100) == 0
        assert incremental_revenue(50, 100, 100, 100) == -50

    @pytest.mark.parametrize("nt,nc", [(0, 1), (1, 0), (-1, 5)])
    def test_incremental_revenue_requires_positive_n(self, nt, nc):
        with pytest.raises(ValueError):
            incremental_revenue(1, 1, nt, nc)

    def test_conversion_rate_lift(self):
        r = conversion_rate_lift(90, 5, 900, 100)
        assert r["cr_treatment"] == pytest.approx(0.10)
        assert r["cr_control"] == pytest.approx(0.05)
        assert r["absolute_lift"] == pytest.approx(0.05)
        assert r["relative_lift"] == pytest.approx(1.0)

    def test_relative_lift_none_when_control_cr_zero(self):
        assert conversion_rate_lift(10, 0, 100, 100)["relative_lift"] is None


class TestMainExample:
    def setup_method(self):
        self.r = compute_uplift(SPLIT, main_outcomes(), WINDOW, as_of=LATE)

    def test_group_stats(self):
        assert self.r.treatment.n_customers == 900
        assert self.r.treatment.converting_customers == 90
        assert self.r.treatment.revenue == 9_000_000
        assert self.r.control.converting_customers == 5
        assert self.r.control.revenue == 500_000
        assert self.r.scale_factor == 9

    def test_incremental_values(self):
        assert self.r.incremental_revenue == pytest.approx(4_500_000)
        assert self.r.incremental_conversions == pytest.approx(45)
        assert self.r.cr_absolute_lift == pytest.approx(0.05)
        assert self.r.cr_relative_lift == pytest.approx(1.0)
        assert self.r.revenue_per_customer_lift == pytest.approx(5_000)

    def test_observed_differs_from_incremental(self):
        assert self.r.treatment.revenue != self.r.incremental_revenue
        assert self.r.treatment.converting_customers != self.r.incremental_conversions

    def test_statistics_match_manual_calculation(self):
        assert self.r.cr_z_score == pytest.approx(1.6177267, abs=1e-6)
        assert self.r.cr_p_value == pytest.approx(0.1057215, abs=1e-6)
        lo, hi = self.r.cr_ci95
        assert lo == pytest.approx(0.0030017, abs=1e-6)
        assert hi == pytest.approx(0.0969983, abs=1e-6)
        assert self.r.significant_at_5pct is False

    def test_final_status(self):
        assert self.r.status == STATUS_FINAL and self.r.is_final
        assert not any("PROVISIONAL" in w for w in self.r.warnings)

    def test_to_dict_separates_observed_and_incremental(self):
        d = self.r.to_dict()
        assert "observed_conversion" in d and "incremental_conversion" in d
        assert d["observed_conversion"]["treatment_revenue"] == 9_000_000
        assert d["incremental_conversion"]["incremental_revenue"] == pytest.approx(
            4_500_000
        )
        assert d["incremental_conversion"]["incremental_conversions"] == pytest.approx(
            45
        )
        assert "incremental" in d["reporting_note"]

    def test_measurement_rows_for_msr_table(self):
        rows = {r["metric_name"]: r for r in self.r.measurement_rows()}
        assert rows["conversion_rate"]["observed_value"] == pytest.approx(0.10)
        assert rows["conversion_rate"]["incremental_value"] == pytest.approx(0.05)
        assert rows["revenue"]["incremental_value"] == pytest.approx(4_500_000)
        assert rows["converting_customers"]["incremental_value"] == pytest.approx(45)
        for row in rows.values():
            assert set(row) == {"metric_name", "observed_value", "incremental_value"}


class TestEdgeCases:
    def test_no_effect_gives_zero_incremental(self):
        rows = [out(f"OT{i}", f"T{i}") for i in range(90)]
        rows += [out(f"OC{i}", f"C{i}") for i in range(10)]
        r = compute_uplift(SPLIT, rows, WINDOW, as_of=LATE)
        assert r.incremental_revenue == pytest.approx(0)
        assert r.incremental_conversions == pytest.approx(0)
        assert r.cr_absolute_lift == pytest.approx(0)

    def test_negative_incremental_when_control_converts_more(self):
        rows = [out(f"OT{i}", f"T{i}") for i in range(45)]
        rows += [out(f"OC{i}", f"C{i}") for i in range(10)]
        r = compute_uplift(SPLIT, rows, WINDOW, as_of=LATE)
        assert r.incremental_revenue < 0 and r.cr_absolute_lift < 0

    def test_no_conversions_anywhere(self):
        r = compute_uplift(SPLIT, [], WINDOW, as_of=LATE)
        assert r.incremental_revenue == 0 and r.cr_relative_lift is None
        assert r.cr_z_score is None and r.cr_ci95 is None
        assert any("Tidak ada konversi" in w for w in r.warnings)

    def test_multiple_orders_one_customer_counts_one_conversion(self):
        rows = [out("A", "T1"), out("B", "T1"), out("C", "C1")]
        r = compute_uplift(SPLIT, rows, WINDOW, as_of=LATE)
        assert r.treatment.converting_customers == 1 and r.treatment.orders == 2
        assert r.treatment.revenue == 200_000

    def test_empty_control_raises(self):
        split = HoldoutSplit("X", 1, 0.1, ("T1",), ())
        with pytest.raises(ValueError, match="control"):
            compute_uplift(split, [], WINDOW, as_of=LATE)

    def test_empty_treatment_raises(self):
        split = HoldoutSplit("X", 1, 0.1, (), ("C1",))
        with pytest.raises(ValueError):
            compute_uplift(split, [], WINDOW, as_of=LATE)

    def test_unknown_basis_raises(self):
        with pytest.raises(ValueError):
            compute_uplift(SPLIT, [], WINDOW, revenue_basis="WRONG", as_of=LATE)


class TestWindowAndDataQuality:
    def test_window_computation(self):
        assert WINDOW.observation_start == START
        assert WINDOW.observation_end == END + timedelta(days=30)
        assert WINDOW.finalization_date == END + timedelta(days=44)

    def test_boundaries_inclusive_and_outside_excluded(self):
        rows = [
            out("in1", "T1", when=START),
            out("in2", "T2", when=WINDOW.observation_end),
            out("before", "T3", when=START - timedelta(seconds=1)),
            out("after", "T4", when=WINDOW.observation_end + timedelta(seconds=1)),
        ]
        r = compute_uplift(SPLIT, rows, WINDOW, as_of=LATE)
        assert r.treatment.converting_customers == 2
        assert r.outside_window_outcomes == 2

    def test_outcomes_outside_audience_ignored(self):
        r = compute_uplift(SPLIT, [out("X", "STRANGER")], WINDOW, as_of=LATE)
        assert r.ignored_outcomes == 1 and r.treatment.revenue == 0

    def test_duplicate_outcome_id_counted_once(self):
        r = compute_uplift(SPLIT, [out("D", "T1"), out("D", "T1")], WINDOW, as_of=LATE)
        assert r.treatment.orders == 1 and r.duplicate_outcomes == 1

    def test_window_from_campaign_k08(self):
        w = window_from_campaign(
            {
                "exposure_window": {
                    "start_time": "2026-11-01T00:00:00Z",
                    "end_time": "2026-11-07T00:00:00Z",
                },
                "conversion_window_days": 30,
                "adjustment_window_days": 14,
            }
        )
        assert w == WINDOW

    def test_window_defaults_when_days_absent(self):
        w = window_from_campaign(
            {"exposure_window": {"start_time": START, "end_time": END}}
        )
        assert w.conversion_window_days == 30 and w.adjustment_window_days == 14

    def test_window_from_campaign_requires_exposure(self):
        with pytest.raises(Exception):
            window_from_campaign({})

    def test_invalid_windows(self):
        with pytest.raises(ValueError):
            build_window(END, START)
        with pytest.raises(ValueError):
            build_window(START, END, 0)
        with pytest.raises(ValueError):
            build_window(START, END, 30, -1)


class TestRefundAdjustment:
    def test_refund_inside_14_days_is_subtracted(self):
        o = out(
            "R",
            "T1",
            refunds=(RefundEvent(40_000, datetime(2026, 11, 20)),),
        )
        assert o.revenue(BASIS_GROSS) == 100_000
        assert o.revenue(BASIS_REFUND_ADJUSTED) == 60_000

    def test_refund_after_14_days_is_ignored(self):
        o = out("R", "T1", refunds=(RefundEvent(40_000, datetime(2026, 11, 25)),))
        assert o.revenue(BASIS_REFUND_ADJUSTED) == 100_000

    def test_refund_exactly_on_day_14_counts(self):
        o = out("R", "T1", refunds=(RefundEvent(10_000, datetime(2026, 11, 24)),))
        assert o.revenue(BASIS_REFUND_ADJUSTED) == 90_000

    def test_refund_without_timestamp_counts(self):
        o = out("R", "T1", refunds=(RefundEvent(10_000),))
        assert o.revenue(BASIS_REFUND_ADJUSTED) == 90_000

    def test_refund_larger_than_gross_never_negative(self):
        o = out("R", "T1", refunds=(RefundEvent(500_000),))
        assert o.revenue(BASIS_REFUND_ADJUSTED) == 0

    def test_net_basis_subtracts_all_deductions(self):
        o = out(
            "N",
            "T1",
            discount_amount=5_000,
            voucher_amount=5_000,
            tax_amount=11_000,
            cancellation_deduction=1_000,
            refunds=(RefundEvent(8_000),),
        )
        assert o.revenue(BASIS_NET) == 70_000
        assert o.revenue(BASIS_REFUND_ADJUSTED) == 92_000

    def test_basis_flows_into_uplift(self):
        rows = [
            out("A", "T1", refunds=(RefundEvent(50_000, datetime(2026, 11, 12)),)),
            out("B", "C1"),
        ]
        gross = compute_uplift(
            SPLIT, rows, WINDOW, revenue_basis=BASIS_GROSS, as_of=LATE
        )
        adj = compute_uplift(SPLIT, rows, WINDOW, as_of=LATE)
        assert gross.treatment.revenue == 100_000
        assert adj.treatment.revenue == 50_000
        assert adj.revenue_basis == BASIS_REFUND_ADJUSTED

    def test_refund_before_purchase_rejected(self):
        with pytest.raises(ValueError):
            out("R", "T1", refunds=(RefundEvent(1, datetime(2026, 11, 9)),))


class TestProvisionalStatus:
    def test_provisional_before_finalization(self):
        r = compute_uplift(
            SPLIT,
            main_outcomes(),
            WINDOW,
            as_of=WINDOW.finalization_date - timedelta(seconds=1),
        )
        assert r.status == STATUS_PROVISIONAL and not r.is_final
        assert any("PROVISIONAL" in w for w in r.warnings)

    def test_final_at_finalization_date(self):
        r = compute_uplift(
            SPLIT, main_outcomes(), WINDOW, as_of=WINDOW.finalization_date
        )
        assert r.status == STATUS_FINAL

    def test_pending_adjustment_counted(self):
        rows = [out("P", "T1", when=datetime(2026, 11, 10))]
        r = compute_uplift(SPLIT, rows, WINDOW, as_of=datetime(2026, 11, 15))
        assert r.pending_adjustment_outcomes == 1
        r2 = compute_uplift(SPLIT, rows, WINDOW, as_of=datetime(2026, 11, 24))
        assert r2.pending_adjustment_outcomes == 0

    def test_default_as_of_is_now_so_future_campaign_is_provisional(self):
        far = datetime.now() + timedelta(days=365)
        w = build_window(far, far + timedelta(days=1))
        assert compute_uplift(SPLIT, [], w).status == STATUS_PROVISIONAL


class TestContamination:
    def test_clean_exposure_reports_counts(self):
        r = compute_uplift(
            SPLIT, main_outcomes(), WINDOW, as_of=LATE, exposed_customer_ids=T_IDS[:800]
        )
        assert r.exposed_treatment_count == 800 and r.control_exposed_count == 0
        assert not any("KONTAMINASI" in w for w in r.warnings)

    def test_control_exposure_flagged(self):
        r = compute_uplift(
            SPLIT,
            main_outcomes(),
            WINDOW,
            as_of=LATE,
            exposed_customer_ids=list(T_IDS[:10]) + ["C1", "C2"],
        )
        assert r.control_exposed_count == 2
        assert any("KONTAMINASI" in w for w in r.warnings)

    def test_exposure_not_provided_leaves_none(self):
        r = compute_uplift(SPLIT, main_outcomes(), WINDOW, as_of=LATE)
        assert r.exposed_treatment_count is None


class TestOutcomeModel:
    K09 = {
        "outcome_id": "OUT-1",
        "customer_id": "T5",
        "conversion_type": "PURCHASE",
        "gross_revenue": 200_000,
        "occurred_at": "2026-11-10T08:00:00Z",
        "deductions": {"discount_amount": 10_000, "refund_amount": 20_000},
        "correlation_id": "corr-1",
    }

    def test_from_k09(self):
        o = Outcome.from_k09(self.K09)
        assert o.gross_revenue == 200_000 and o.discount_amount == 10_000
        assert o.occurred_at == datetime(2026, 11, 10, 8)
        assert o.refunds == (RefundEvent(20_000, None),)
        assert o.revenue(BASIS_REFUND_ADJUSTED) == 180_000

    def test_from_k09_refund_events_extension(self):
        rec = dict(
            self.K09,
            refund_events=[{"amount": 20_000, "refunded_at": "2026-12-30T00:00:00Z"}],
        )
        assert Outcome.from_k09(rec).revenue(BASIS_REFUND_ADJUSTED) == 200_000

    def test_from_k09_requires_occurred_at(self):
        rec = {k: v for k, v in self.K09.items() if k != "occurred_at"}
        with pytest.raises(ValueError, match="occurred_at"):
            Outcome.from_k09(rec)

    @pytest.mark.parametrize("missing", ["outcome_id", "customer_id", "gross_revenue"])
    def test_from_k09_required_fields(self, missing):
        rec = {k: v for k, v in self.K09.items() if k != missing}
        with pytest.raises(ValueError):
            Outcome.from_k09(rec)

    def test_invalid_conversion_type(self):
        with pytest.raises(ValueError):
            Outcome("X", "T1", "SIGNUP", START, 1)

    @pytest.mark.parametrize("bad", [-1, float("nan"), float("inf"), True, "10"])
    def test_invalid_gross_revenue(self, bad):
        with pytest.raises(ValueError):
            Outcome("X", "T1", "PURCHASE", START, bad)

    def test_timezone_aware_occurred_at_normalized(self):
        o = Outcome.from_k09(dict(self.K09, occurred_at="2026-11-10T15:00:00+07:00"))
        assert o.occurred_at == datetime(2026, 11, 10, 8)
