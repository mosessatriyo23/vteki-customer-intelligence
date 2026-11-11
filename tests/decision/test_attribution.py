"""
test_attribution.py — Test Last-Touch Attribution (Minggu 11).

Jalankan: python -m pytest tests/decision/test_attribution.py -v
"""

from datetime import datetime, timedelta

import pytest

from services.decision.attribution.touchpoint import (
    STATUS_ATTRIBUTED,
    STATUS_NO_TOUCHPOINT,
    STATUS_OUTSIDE_WINDOW,
    Touchpoint,
    attribute_conversion,
    attribute_conversions,
    touchpoints_from_deliveries,
)
from services.decision.measurement.uplift import Outcome, RefundEvent
from services.decision.simulator.channel_sim import SimulatedDelivery

BUY = datetime(2026, 11, 20, 12, 0)


def touch(days_before, campaign="CMP-A", cid="C1", action="UPSELL", **kw):
    return Touchpoint(
        cid, campaign, action, "email", BUY - timedelta(days=days_before), **kw
    )


def outcome(cid="C1", revenue=100_000, **kw):
    return Outcome("OUT-1", cid, "PURCHASE", BUY, revenue, **kw)


class TestSingleConversion:
    def test_last_touch_is_selected(self):
        r = attribute_conversion(
            outcome(), [touch(10, "OLD"), touch(2, "NEW"), touch(5, "MID")]
        )
        assert r.status == STATUS_ATTRIBUTED
        assert r.attributed.campaign_id == "NEW"
        assert r.days_to_convert == pytest.approx(2.0)

    def test_days_to_convert_fractional(self):
        t = Touchpoint("C1", "A", "UPSELL", "email", BUY - timedelta(hours=36))
        assert attribute_conversion(outcome(), [t]).days_to_convert == pytest.approx(
            1.5
        )

    def test_touch_after_conversion_ignored(self):
        r = attribute_conversion(outcome(), [touch(-1, "FUTURE")])
        assert r.status == STATUS_NO_TOUCHPOINT and r.attributed is None

    def test_future_touch_does_not_override_valid_earlier_touch(self):
        r = attribute_conversion(outcome(), [touch(3, "PAST"), touch(-2, "FUTURE")])
        assert r.attributed.campaign_id == "PAST"

    def test_touch_at_same_instant_allowed(self):
        r = attribute_conversion(outcome(), [touch(0, "NOW")])
        assert r.is_attributed and r.days_to_convert == 0

    def test_exactly_30_days_included(self):
        assert attribute_conversion(outcome(), [touch(30)]).is_attributed

    def test_just_over_30_days_excluded(self):
        t = Touchpoint(
            "C1", "A", "UPSELL", "email", BUY - timedelta(days=30, seconds=1)
        )
        r = attribute_conversion(outcome(), [t])
        assert r.status == STATUS_OUTSIDE_WINDOW and r.attributed is None

    def test_custom_window(self):
        assert (
            attribute_conversion(outcome(), [touch(10)], 7).status
            == STATUS_OUTSIDE_WINDOW
        )
        assert attribute_conversion(outcome(), [touch(10)], 14).is_attributed

    def test_no_touchpoints(self):
        assert attribute_conversion(outcome(), []).status == STATUS_NO_TOUCHPOINT

    def test_other_customers_touches_ignored(self):
        r = attribute_conversion(outcome(), [touch(1, cid="SOMEONE_ELSE")])
        assert r.status == STATUS_NO_TOUCHPOINT

    def test_invalid_window(self):
        with pytest.raises(ValueError):
            attribute_conversion(outcome(), [], 0)


class TestConflicts:
    def test_dual_campaign_exposure_flags_conflict(self):
        r = attribute_conversion(outcome(), [touch(8, "A"), touch(2, "B")])
        assert r.conflict is True
        assert r.attributed.campaign_id == "B"
        assert r.campaigns_in_window == ("A", "B")
        assert [t.campaign_id for t in r.competing] == ["A"]

    def test_same_campaign_repeat_touch_is_not_conflict(self):
        r = attribute_conversion(outcome(), [touch(8, "A"), touch(2, "A")])
        assert r.conflict is False and len(r.competing) == 1

    def test_old_touch_outside_window_does_not_create_conflict(self):
        r = attribute_conversion(outcome(), [touch(40, "OLD"), touch(2, "NEW")])
        assert r.conflict is False and r.campaigns_in_window == ("NEW",)

    def test_timestamp_tie_is_deterministic_and_flagged(self):
        a = attribute_conversion(outcome(), [touch(2, "B"), touch(2, "A")])
        b = attribute_conversion(outcome(), [touch(2, "A"), touch(2, "B")])
        assert a.attributed.campaign_id == b.attributed.campaign_id == "A"
        assert a.tie_on_timestamp and a.conflict

    def test_no_tie_flag_for_same_campaign_same_time(self):
        r = attribute_conversion(outcome(), [touch(2, "A"), touch(2, "A")])
        assert r.tie_on_timestamp is False


class TestK09Output:
    def test_attributed_block(self):
        r = attribute_conversion(
            outcome(),
            [touch(3, "CMP-A", action="WIN_BACK_OFFER", decision_id="DEC-9")],
        )
        d = r.to_k09_attribution()
        assert d["campaign_id"] == "CMP-A" and d["decision_id"] == "DEC-9"
        assert d["action_id"] == "WIN_BACK_OFFER" and d["attributed_channel"] == "email"
        assert d["days_to_convert"] == pytest.approx(3.0)
        assert d["is_incremental"] is None
        assert d["attribution_model"] == "LAST_TOUCH"

    def test_unattributed_block(self):
        d = attribute_conversion(outcome(), []).to_k09_attribution()
        assert d["campaign_id"] is None and d["days_to_convert"] is None
        assert d["attribution_status"] == STATUS_NO_TOUCHPOINT


class TestReport:
    def setup_method(self):
        self.outs = [
            Outcome("O1", "C1", "PURCHASE", BUY, 100_000),
            Outcome(
                "O2", "C2", "PURCHASE", BUY, 200_000, refunds=(RefundEvent(50_000),)
            ),
            Outcome("O3", "C3", "PURCHASE", BUY, 300_000),
            Outcome("O4", "C4", "PURCHASE", BUY, 400_000),
        ]
        self.touches = [
            touch(3, "A", cid="C1"),
            touch(5, "A", cid="C2"),
            touch(1, "B", cid="C2"),
            touch(2, "B", cid="C3"),
            touch(45, "A", cid="C4"),
        ]
        self.rep = attribute_conversions(self.outs, self.touches)

    def test_counts(self):
        assert self.rep.n_outcomes == 4
        assert self.rep.n_attributed == 3 and self.rep.n_unattributed == 1

    def test_conflicts_listed(self):
        assert len(self.rep.conflicts) == 1
        assert self.rep.conflicts[0].customer_id == "C2"
        assert self.rep.conflicts[0].campaigns_in_window == ("A", "B")

    def test_conversions_by_campaign(self):
        assert self.rep.conversions_by_campaign() == {"A": 1, "B": 2}

    def test_revenue_by_campaign_uses_refund_adjusted_by_default(self):
        assert self.rep.attributed_revenue_by_campaign() == {
            "A": 100_000,
            "B": 150_000 + 300_000,
        }
        assert self.rep.attributed_revenue_by_campaign("GROSS")["B"] == 500_000

    def test_summary_warns_not_incrementality(self):
        s = self.rep.summary()
        assert s["n_conflicts"] == 1 and s["model"] == "LAST_TOUCH"
        assert "BUKAN" in s["note"]

    def test_empty_inputs(self):
        rep = attribute_conversions([], [])
        assert rep.n_outcomes == 0 and rep.summary()["n_attributed"] == 0


class TestFromDeliveries:
    def _delivery(self, status, exposure, cid="C1"):
        return SimulatedDelivery(
            delivery_id="SIM-1",
            campaign_id="CMP-A",
            customer_id=cid,
            action_id="UPSELL",
            channel="email",
            status=status,
            group="TREATMENT",
            attempted_at=BUY - timedelta(days=2),
            correlation_id="c-1",
            exposure_recorded=exposure,
        )

    def test_only_exposures_become_touchpoints(self):
        tps = touchpoints_from_deliveries(
            [
                self._delivery("SIMULATED_SENT", True),
                self._delivery("SKIPPED_CONTROL_HOLDOUT", False, "C2"),
            ]
        )
        assert len(tps) == 1 and tps[0].customer_id == "C1"
        assert tps[0].delivery_id == "SIM-1" and tps[0].correlation_id == "c-1"

    def test_pipeline_attribution(self):
        tps = touchpoints_from_deliveries([self._delivery("SIMULATED_SENT", True)])
        r = attribute_conversion(outcome(), tps)
        assert r.is_attributed and r.days_to_convert == pytest.approx(2.0)
