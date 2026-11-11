"""
test_phase3_integration.py — Integrasi Fase 3 (Minggu 9-11).

Rantai: Holdout split -> Channel Simulator -> Atribusi -> Uplift -> Forecast.

Jalankan: python -m pytest tests/decision/test_phase3_integration.py -v
"""

from datetime import datetime, timedelta

import pytest

from services.decision.attribution.touchpoint import (
    attribute_conversions,
    touchpoints_from_deliveries,
)
from services.decision.campaign.holdout import split_from_campaign
from services.decision.forecasting.projector import project_from_uplift
from services.decision.measurement.uplift import (
    Outcome,
    compute_uplift,
    incremental_revenue,
    window_from_campaign,
)
from services.decision.nudge.generator import approve_draft, generate_nudge
from services.decision.simulator.channel_sim import ChannelSimulator

FACTS = {"first_name": "Budi", "preferred_branch": "Yogyakarta", "points_balance": 10}
CAMPAIGN = {
    "campaign_id": "CMP-INT-1",
    "control_holdout_ratio": 0.10,
    "random_seed": 20261101,
    "conversion_window_days": 30,
    "adjustment_window_days": 14,
    "exposure_window": {
        "start_time": "2026-11-01T00:00:00Z",
        "end_time": "2026-11-07T00:00:00Z",
    },
}
SENT_AT = datetime(2026, 11, 2, 9, 0)
AUDIENCE = [f"CUST{i:05d}" for i in range(3000)]


@pytest.fixture(scope="module")
def pipeline():
    split = split_from_campaign(CAMPAIGN, AUDIENCE)
    sim = ChannelSimulator()
    sim.register_campaign(split)
    drafts = [
        approve_draft(generate_nudge(c, "LOYALTY_REWARD", "email", FACTS), "christ")
        for c in AUDIENCE
    ]
    for d in drafts:
        sim.send(d, campaign_id="CMP-INT-1", sent_at=SENT_AT)

    # Perilaku sintetis: 20% treatment dan 10% control berbelanja 3 hari setelah hari kirim.
    outcomes = []
    for idx, cid in enumerate(split.treatment_ids):
        if idx % 5 == 0:
            outcomes.append(
                Outcome(
                    f"OT-{cid}", cid, "PURCHASE", SENT_AT + timedelta(days=3), 100_000
                )
            )
    for idx, cid in enumerate(split.control_ids):
        if idx % 10 == 0:
            outcomes.append(
                Outcome(
                    f"OC-{cid}", cid, "PURCHASE", SENT_AT + timedelta(days=3), 100_000
                )
            )
    return split, sim, outcomes


class TestEndToEnd:
    def test_control_group_has_zero_exposure(self, pipeline):
        split, sim, _ = pipeline
        assert split.n_control > 0
        assert sim.verify_control_isolation("CMP-INT-1")
        assert sim.exposure_count(campaign_id="CMP-INT-1") == split.n_treatment
        assert all(sim.has_exposure(c) is False for c in split.control_ids)

    def test_all_records_are_simulated(self, pipeline):
        _, sim, _ = pipeline
        assert all(a.is_simulated and not a.external_delivery for a in sim.attempts)

    def test_attribution_only_reaches_treatment(self, pipeline):
        split, sim, outcomes = pipeline
        tps = touchpoints_from_deliveries(sim.attempts)
        rep = attribute_conversions(outcomes, tps)
        treatment_buyers = sum(1 for o in outcomes if split.is_treatment(o.customer_id))
        assert rep.n_attributed == treatment_buyers
        assert all(
            split.is_treatment(r.customer_id) for r in rep.results if r.is_attributed
        )
        assert rep.conversions_by_campaign() == {"CMP-INT-1": treatment_buyers}
        assert rep.conflicts == ()

    def test_uplift_matches_independent_formula(self, pipeline):
        split, sim, outcomes = pipeline
        window = window_from_campaign(CAMPAIGN)
        res = compute_uplift(
            split,
            outcomes,
            window,
            as_of=datetime(2027, 2, 1),
            exposed_customer_ids=sim.exposed_customer_ids("CMP-INT-1"),
        )
        t_rev = 100_000 * sum(1 for o in outcomes if split.is_treatment(o.customer_id))
        c_rev = 100_000 * sum(1 for o in outcomes if split.is_control(o.customer_id))
        assert res.is_final and res.control_exposed_count == 0
        assert res.exposed_treatment_count == split.n_treatment
        assert res.incremental_revenue == pytest.approx(
            incremental_revenue(t_rev, c_rev, split.n_treatment, split.n_control)
        )
        assert res.incremental_revenue > 0 and res.cr_absolute_lift > 0
        assert res.treatment.revenue == t_rev

    def test_forecast_consumes_uplift(self, pipeline):
        split, _, outcomes = pipeline
        res = compute_uplift(
            split, outcomes, window_from_campaign(CAMPAIGN), as_of=datetime(2027, 2, 1)
        )
        f = project_from_uplift(
            res,
            monthly_revenue_history=[40_000_000, 42_000_000, 41_000_000],
            horizon_months=3,
            effect_decay_per_month=0.5,
        )
        assert f.months[0].incremental_revenue == pytest.approx(res.incremental_revenue)
        assert f.campaign_total > f.baseline_total
        assert len(f.months) == 3 and not f.is_provisional

    def test_provisional_chain(self, pipeline):
        split, _, outcomes = pipeline
        res = compute_uplift(
            split,
            outcomes,
            window_from_campaign(CAMPAIGN),
            as_of=datetime(2026, 11, 20),
        )
        f = project_from_uplift(
            res, monthly_revenue_history=[1_000_000], horizon_months=1
        )
        assert not res.is_final and f.is_provisional
