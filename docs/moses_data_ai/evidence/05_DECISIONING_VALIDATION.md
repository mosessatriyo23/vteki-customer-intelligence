# 05 — Decisioning validation handoff (development only)

**As of:** 2026-11-17 · **Requested by:** James. **Joint ownership:** Christ owns business policy/decisioning approval; Moses integrates model/score contracts and reports evidence; James owns historical platform contract. **Reviewer:** pending (Christ / James / Moses); **approval date:** not granted. Checkout includes `main` `7e09616` (Christ PR #39) and Moses PR #38 `aa2a23d`.

```text
training_ready=false
experiment_ready=false
final_model=false
```

## Business contract versus implementation

`docs/christ_business/reference/Requirement_Capstone.md` Bab 3 demands five independent inputs: predictive score, business eligibility, consent, contact-frequency cap, product suitability/availability; protective failure selects `NO_ACTION`. Bab 4 lists 11 actions including `NO_ACTION`, with severe complaint blocking promotions; Bab 5 defines `EV = propensity × expected_revenue_contribution × action_weight − incentive_cost_estimate`, below-threshold `NO_ACTION`. A high score is not authorization to send. The document describes 2 contacts/14 days only as an **example** and leaves EV weights, costs and threshold unspecified. Its version/approver placeholders remain open; the Bab 1 dormant window (181–365 days) conflicts with the Bab 4 WIN_BACK example (91–180 days). Christ must decide policy, not Moses.

Development code exists under `services/decision/nba/` (including `engine.py`, `ev_calculator.py`) and tests under `tests/decision/` (including `test_e2e_decision_flow.py`, `test_nba_engine.py`, `test_phase4_hardening.py`, `test_ev_calculator.py`). PR #39 added synthetic closed-loop tests and invalid-score fail-closed behavior; this is **consumer-side development evidence**, not Moses predictive scores, approved policy or real-world closed-loop outcome validation. Any score adapter must respect `AIScores`' native `int`/`float` finite probabilities in `[0,1]` and finite nonnegative CLV, with expired/missing scores conservatively handled. No model score feed was validated in an authorized campaign.

## Tests: present is not executed

- **Actually executed locally:** `python -m unittest tests.data.test_ingestion tests.data.test_ingestion_negative tests.data.test_data_leakage tests.data.test_pit_features tests.data.test_model_baseline tests.data.test_model_diagnostics tests.data.test_model_evaluator tests.data.test_business_clv tests.data.test_clv_features tests.data.test_model_label_readiness tests.data.test_drift_monitoring` — **54 passed, 13.420s**. This is the data/model development suite, **not** the decision suite.
- **Decision suite attempted locally:** `python -m unittest discover -s tests/decision` — import failures, **not passing**. `python -c "import pytest"` confirmed `ModuleNotFoundError: No module named 'pytest'` in this environment. Do not count attempted decision tests as validated locally. For reproduction in a provisioned test environment, install declared test dependencies first, then run `python -m pytest tests/decision`; the latter is an instruction, **not** a locally completed result.
- **Existing CI evidence only:** `gh pr view 39 --json statusCheckRollup` on 2026-11-17 showed PR #39 merged, with SUCCESS for its two Quality, Security and Backend Tests checks and frontend checks (e.g. [CI job](https://github.com/mosessatriyo23/vteki-customer-intelligence/actions/runs/43978300618/job/133687891609)). CI checks on that PR do **not** establish local decision-suite passage on this checkout, business approval, complete historical data or production readiness.

## Open risk and required acceptance

Reviewed, **not fixed**: `services/decision/nba/engine.py::scores_are_valid` calls `math.isfinite(value)` on native integers. An extremely large integer such as `10**400` can raise `OverflowError` rather than return false, contradicting fail-closed intent; Christ owns regression/fix and review. Do not present the current guard as universally fail-closed. Also reconcile scoring validity/expiration and three reason codes against the final Christ contract; no finished Moses production score interface exists. Verify opt-out, severe complaints, caps, eligibility, suitability and `NO_ACTION` priority with approved boundary examples, not merely a happy-path integration test. Human approval, monitoring/rollback and historical audit reconstruction are still needed before real use.

**Disposition:** development validation evidence only. Joint Christ–Moses review remains pending; James must validate historical platform prerequisites; no approval date, deployment, sending or experiment authorization has been granted.
