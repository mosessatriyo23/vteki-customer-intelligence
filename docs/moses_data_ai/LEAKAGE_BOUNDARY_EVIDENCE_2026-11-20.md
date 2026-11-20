# Leakage-boundary evidence — 2026-11-20

## Scope and conclusion

Supporting development evidence for FRD **FR-FTM-002, FR-CHN-001, T-05** and TRD **§9.1 controls 1–4, T-ML-02**. This is **synthetic EVENT-TIME only**, not a certification of those requirements in production. No real event-time leakage was exposed, and no production code or model manifest was changed.

New regression file: `tests/data/test_leakage_boundary.py` (**3 collected cases**: one source/label/inference case and two fitted-report allowlist cases).

## Exactly what the tests prove

1. Generate 20 synthetic customers with seed `20260906`, observation date `2026-09-06`, and resolve identities once. Keep that current identity snapshot fixed. Build real feature rows at `2026-06-01T12:00:00+07:00` and at cutoff + 90 days + 1 second.
2. Append three large completed ECOM transactions (with matching item rows): cutoff + 1 day, exactly cutoff + 90 days, and cutoff + 90 days + 1 second. Also append a completed visit and membership renewal at exactly cutoff + 90 days. Reuse source references, not latent identity/ground-truth fields; refresh fixture counts/checksums using the existing helper.
3. Rebuild through the real `build_features`: **all cutoff feature dictionaries remain exactly equal** despite those future transactions, visit and renewal. This includes events exactly at and just after the 90-day outcome boundary.
4. Build Christ-event labels with real `build_labels` and join using real `join_training_rows`. Joined rows are nonempty, contain exactly the `TRAINING_FIELDS` allowlist, and their predictor vectors remain equal before/after injection. For the mapped customer, `clv90` increases by exactly **1,999,999,998**: the first two transactions enter the inclusive outcome window `(cutoff, cutoff+90d]`, while the endpoint + 1 second transaction does not. This explicitly demonstrates outcome data changing on the label side without changing cutoff predictors.
5. **Positive control:** at the later cutoff, the mapped customer's `purchase_count_90d` and `retained_revenue_90d` increase. The unchanged earlier snapshot is therefore not a vacuous test of an ignored source.
6. Execute real churn and propensity fitting on the existing deterministic two-class synthetic experiment helpers (not mocks). For churn and each independent propensity target (`retail_purchase30`, `renewal60`), assert the returned report's `features` equals its module's `FEATURES`, is a subset of feature fields and `TRAINING_FIELDS`, and excludes every non-key churn/propensity label field and every `ground_truth`-named predictor. The real training/fitting paths select only these seven predictors:
   - `recency_days`, `tenure_days`
   - `purchase_count_365d`, `retained_revenue_365d`
   - `purchase_count_60d`, `purchase_count_90d`, `retained_revenue_90d`
7. Fit and serialize a real retail propensity experiment through `propensity_experiment.run`, reload with `propensity_inference.load_model`, and score the generated cutoff snapshots using real `predict_rows` with the same fixed generation timestamp. **Complete inference outputs are exactly equal before/after source injection.**

The generated source cohort is used for source → feature → label/join and inference invariance. Fitting uses the existing separate deterministic two-class experiment fixture; this is connected boundary regression evidence, **not** a claim that the 20 generated customers supplied an end-to-end training population. Renewal inference invariance and the 30/60-day propensity label endpoints are not independently tested here. Existing propensity label/experiment tests cover those separate contracts.

## Important limits / remaining work

- **Not `known_at` / availability-time safe.** No delayed-arrival, correction history, refund/status availability version or bitemporal reconstruction is simulated.
- **Not identity-as-of safe.** Identity remains `CURRENT_SNAPSHOT_RETROSPECTIVE`; resolver history is not reconstructed. `training_ready` remains false.
- Source append helpers update metadata, but these tests call feature/label builders directly; they do **not** claim a post-injection `BatchValidator`-certified business lifecycle. The synthetic visit/renewal isolates event-time filtering rather than proving a valid real membership chain.
- Predictor exclusion is checked on real fit reports and the explicit allowlist, not by relying on a source-code substring search. It does not constitute a general information-flow proof or a ground-truth filesystem sandbox test.
- **Model manifests still lack `leakage_check_result`.** This document does not populate that field, claim independent validator approval, promote models, or change serving/training readiness. Registry/governance closure remains separate.
- Synthetic metric behavior is not evidence about real customer performance or production readiness.

## Verification and failures

All commands use `.venv\Scripts\python.exe`.

| Command | Result |
| --- | --- |
| `-m pytest tests/data/test_leakage_boundary.py -q --tb=short` | **3 passed** |
| `-m pytest tests/data -q -x` | **561 passed**, 47.08 seconds |
| `-m ruff check tests/data/test_leakage_boundary.py` | All checks passed |
| `-m ruff format --check tests/data/test_leakage_boundary.py` | 1 file already formatted |
| `-m black --check tests/data/test_leakage_boundary.py` | 1 file would be left unchanged |

Initial test development produced **1 failed, 2 passed** because the injected renewal used a date-only `expires_at`, causing naive/aware datetime comparison at the later cutoff. Correcting the new fixture to an aware ISO timestamp matching generated membership events resolved it. This was a test-data construction error, **not an observed leakage defect**; no production fix was necessary. No artificial red run or weakened assertion was used to manufacture evidence. The behavior checks passed against existing production code after correcting that fixture. The full data-suite count includes other agents' concurrent work present in the working tree; it is not attributed solely to this test file.
