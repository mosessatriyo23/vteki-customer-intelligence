"""
test_catalogue_k06.py — `required_fact_package` di catalogue.py (kontrak K-06) harus
sesuai perilaku kode yang sebenarnya.

Daftar fakta TIDAK ditebak: test ini menjalankan uji sensitivitas (ubah satu field, lihat
apakah kelayakan atau Expected Value berubah) terhadap `check_business_eligibility` dan
`ev_calculator`, lalu membandingkannya dengan `required_fact_package` tiap aksi.
Jika aturan kelayakan/EV berubah, test ini gagal dan mengingatkan agar katalog diperbarui.

Jalankan: python -m pytest tests/decision/test_catalogue_k06.py -v
"""

import random
from dataclasses import fields
from datetime import datetime

import pytest

from services.decision.nba import ev_calculator as ev
from services.decision.nba.catalogue import ACTION_CATALOGUE
from services.decision.nba.engine import AIScores, EligibilityProfile
from services.decision.nba.evaluator import check_business_eligibility

NOW = datetime(2026, 11, 5)

SCORE_DOMAIN = {
    "churn_score": [0.1, 0.35, 0.65, 0.9],
    "churn_risk_band": ["LOW", "MEDIUM", "HIGH", "VERY_HIGH"],
    "propensity_purchase": [0.1, 0.5, 0.9],
    "propensity_renew": [0.1, 0.5, 0.9],
    "clv_amount": [1e5, 6e5, 2e6],
    "clv_tier": ["INSUFFICIENT_HISTORY", "SILVER", "GOLD", "PLATINUM"],
    "lifecycle_stage": [
        "NEW",
        "ACTIVE",
        "LOYAL",
        "AT_RISK",
        "DORMANT",
        "CHURNED",
        "OCCASIONAL",
    ],
}
ELIG_DOMAIN = {
    "tenure_days": [10, 59, 60, 300],
    "membership_days_remaining": [-5, 5, 15, 16, 100],
    "has_active_membership": [True, False],
    "has_active_win_back_offer": [True, False],
}
DOMAIN = {**SCORE_DOMAIN, **ELIG_DOMAIN}

# Aksi yang dipicu di luar aturan kelayakan EV (jalur suppression), bukan dari uji sensitivitas.
SPECIAL = {"COMPLAINT_RESOLUTION": ["complaint_ticket_status"], "NO_ACTION": []}


def _outcome(action_id, state):
    scores = AIScores(
        customer_id="C",
        score_generated_at=NOW,
        **{k: state[k] for k in SCORE_DOMAIN},
    )
    elig = EligibilityProfile(customer_id="C", **{k: state[k] for k in ELIG_DOMAIN})
    action = ACTION_CATALOGUE[action_id]
    eligible = check_business_eligibility(action_id, scores, elig) is None
    propensity = ev.get_propensity(action_id, scores, False)
    revenue = ev.estimate_expected_revenue(scores.clv_amount, action_id)
    cost = ev.estimate_incentive_cost(action.incentive_band, scores.clv_amount)
    value = ev.calculate_expected_value(propensity, revenue, action.action_weight, cost)
    return eligible, propensity, round(value, 4)


def _sensitive_fields(action_id, iterations=1500):
    rng = random.Random(7)
    found = set()
    for _ in range(iterations):
        state = {k: rng.choice(v) for k, v in DOMAIN.items()}
        base = _outcome(action_id, state)
        for name, values in DOMAIN.items():
            if name in found:
                continue
            changed = dict(state, **{name: rng.choice(values)})
            if _outcome(action_id, changed) != base:
                found.add(name)
    return sorted(found)


BUSINESS_ACTIONS = [a for a in ACTION_CATALOGUE if a not in SPECIAL]


@pytest.mark.parametrize("action_id", BUSINESS_ACTIONS)
def test_required_fact_package_matches_actual_dependencies(action_id):
    declared = sorted(ACTION_CATALOGUE[action_id].required_fact_package)
    assert declared == _sensitive_fields(action_id)


@pytest.mark.parametrize("action_id", BUSINESS_ACTIONS)
def test_facts_are_real_data_fields(action_id):
    known = {f.name for f in fields(AIScores)} | {
        f.name for f in fields(EligibilityProfile)
    }
    for fact in ACTION_CATALOGUE[action_id].required_fact_package:
        assert fact in known, fact


@pytest.mark.parametrize("action_id", list(SPECIAL))
def test_special_actions(action_id):
    assert ACTION_CATALOGUE[action_id].required_fact_package == SPECIAL[action_id]


def test_only_no_action_has_empty_fact_package():
    empty = [a for a, v in ACTION_CATALOGUE.items() if not v.required_fact_package]
    assert empty == ["NO_ACTION"]