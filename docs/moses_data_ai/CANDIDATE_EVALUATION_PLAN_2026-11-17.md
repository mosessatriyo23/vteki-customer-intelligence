# Candidate evaluation plan (unexecuted) — Data/AI candidates vs development baseline

**Date:** 2026-11-17 · **Status:** plan only, **not run**. No training, no new result numbers, no new model/label version, no approval. `training_ready=false`, `experiment_ready=false`, `final_model=false`. Assumes `docs/christ_business/reference/Requirement_Capstone.md` as baseline business reference and the current development baseline (`services/data/models`, `docs/moses_data_ai/model_development_baseline.md`, `sprint_gate_status_2026-11-14.md`) as the comparator to beat, not the target. Pairs with [`RETENTION_METHOD_PROPOSAL_2026-11-17.md`](RETENTION_METHOD_PROPOSAL_2026-11-17.md) for CLV; this plan covers churn/propensity and CLV candidate evaluation mechanics generically and does not resolve the open Bab 2.1/2.2 questions itself.

See the [2026-11-18 unblock handoff](MOSES_UNBLOCK_HANDOFF_2026-11-18.md) for independent churn decisions and the three distinct, unimplemented propensity outcomes. It does not open this plan's entry gate.

## Entry gate before any candidate is evaluated

1. Christ-approved, versioned target contract: unambiguous churn outcome window and active cohort (Bab 2.1 180 vs 90-day conflict resolved), CLV gross-revenue convention and retention method/factor source, lifecycle thresholds without overlap/gap ambiguity (Bab 1), reason-code allowlist.
2. James-verified historical/point-in-time feed: `available_at`/`known_at` lineage, identity-as-of resolution, refund/status final-state history, satisfying Gate C.
3. Gates A–C closed and Gate D review scheduled (per `READINESS_REVIEW_PACKET_2026-11-16.md` §7). Absent any of the above, this plan stays unexecuted; do not substitute unit-test passage or diagnostic runs for these approvals.

## Candidate universe (to be populated later, not training targets today)

Any candidate must declare: estimator family, target definition version, feature set version and cutoff, training window, and whether it is a change to churn, propensity, or CLV. Examples of candidate classes to slot in once approved: fitted probabilistic classifier for churn (vs. fixed recency-threshold baseline), survival/hazard model or matured-cohort empirical estimator for 12-month retention feeding CLV (per the retention proposal), and any propensity model for Bab 3/4 inputs. No specific algorithm or hyperparameter is pre-selected here.

## Temporal split design

- Use purged, time-ordered splits consistent with the current baseline: pick cutoffs whose full outcome horizon is complete as of a frozen generation `as_of_date`; the most recent complete cutoff(s) form the holdout, strictly after all training cutoffs. Reject any split leaving an empty purged train or test set.
- Purge training cutoffs whose outcomes are not fully observable by the frozen training-data availability cutoff; specify any additional embargo from measured settlement lag rather than asserting a universal gap. Feature lookback overlap alone does not imply leakage when point-in-time controls hold.
- For model selection, use a validation cutoff strictly between train and holdout (three-way split) or walk-forward cutoffs; the final holdout is evaluated once per candidate family, not repeatedly tuned against.
- No customer-random split. Returning customers may appear at successive temporal cutoffs if no future information crosses the training boundary; report overlap and cluster uncertainty by customer. A separate customer-disjoint diagnostic measures generalization to unseen customers.
- Record exact cutoff lists, counts per split, and purge/gap counts for every candidate run, matching the transparency already required by the baseline.

## Leakage checks (must pass before any metric is trusted)

- Event-time check (existing pattern in `tests/data/test_data_leakage.py`): inject synthetic future transactions dated after a cutoff and confirm candidate features/scores at that cutoff are unchanged.
- Point-in-time/availability check: where James's feed supports it, confirm a record whose `known_at`/`available_at` is after cutoff is excluded even if its event time is before cutoff; block the check (mark unavailable, not passed) if the feed does not yet carry that distinction.
- Identity-as-of check: confirm identity clusters used for features reflect only resolution state as of the cutoff, not retrospective/final clusters, once Gate C provides that capability; otherwise record as an open limitation, not a false pass.
- Label/feature separation check: features must be constructed independently of label logic and joined only by `(customer_id, cutoff)`; assert no label column or its derivative appears among candidate inputs.
- Ground-truth generator isolation: confirm the candidate pipeline never reads generator ground-truth artifacts (ingestion validation should reject such reads).
- Any leakage check failure blocks metric reporting for that candidate; it is not a tunable warning.

## Metrics

**Churn (binary):**
- Primary reporting: ROC-AUC, `average_precision` (AP, not trapezoidal PR-AUC), Brier score, calibration curve/reliability bins.
- Secondary at the required decision threshold(s)/risk bands (`<0.30`, `0.30–<0.60`, `0.60–<0.80`, `≥0.80` per Bab 2.1): TP/TN/FP/FN, accuracy, sensitivity, specificity, balanced accuracy — consistent with the existing baseline evaluator so results are comparable.
- Ranking usefulness: lift/decile table; if scores are degenerate (e.g., tied binary baseline), report lift as null rather than fabricated, as the current evaluator already does.
- If one class is absent in a split, mark undefined discrimination/class-specific metrics unavailable with the class counts; do not invent a score.

**CLV (continuous, gross revenue per approved convention):**
- Primary: MAE and (if distribution supports it) median absolute error, reported against both a trivial baseline (train median/mean, current pattern) and the candidate.
- Secondary: calibration of aggregate predicted vs. actual revenue by decile/segment, and, if a retention-factor-based projection is used, reporting of the effective factor distribution and its sensitivity range from the retention proposal — not a single point claim.
- Always report mature-label counts, purge/censor counts, and exclude incomplete-horizon rows from point MAE; for any survival-informed projection, separately report the survival/retention diagnostic (e.g., Brier on event, concordance) rather than conflating it with revenue MAE.

**Common reporting requirements:**
- Report counts (train/validation/holdout rows, eligible/mature/purged/censored), not only aggregate scores.
- Report an uncertainty range (e.g., bootstrap CI) alongside every headline metric; do not present a single number as precise ground truth.
- Explicitly restate target/version, feature version, cutoff list, and data snapshot identity for reproducibility.

## Baselines to compare against

- Churn: existing fixed recency-threshold rule (`recency_days > 90`) exactly as implemented in `services/data/models/baseline.py`, not a re-tuned threshold.
- CLV: existing constant train-median (and train-mean, for transparency) predictor, exactly as implemented.
- Any new candidate must be run on the **same** cutoffs/splits as the development baseline for the comparison to be meaningful; if cutoffs differ, report both results without implying equivalence.
- Pre-register acceptable trade-offs, minimum sample sizes, and a primary selection metric with reviewers before running; report all metrics and uncertainty. No single favorable statistic or CI overlap rule constitutes promotion approval.

## Reporting and gating

- Every evaluation artifact must carry `training_ready`, `experiment_ready`, `final_model` flags exactly reflecting actual state; this plan does not pre-set any of them to true.
- Produce one report per candidate run containing: target/version, data snapshot and checksum references, split description, leakage-check outcomes (pass/fail/not-applicable with reason), full metric table with uncertainty, and known limitations (e.g., synthetic retrospective identity, missing availability history) inherited from the baseline's documented caveats.
- No report in this plan may claim "approved," "final," "production-ready," or supersede `CAPSTONE_REQUIREMENT_ALIGNMENT.md`/`READINESS_REVIEW_PACKET_2026-11-16.md` gate status. A candidate clearing all checks still requires independent review (Christ for business target/CLV sign-off, James for historical/PIT evidence, and Gate D review) before any promotion, scoring service wiring, or experiment is started.
- If any entry-gate item (business contract, historical feed, Gate A–C closure) is still open when someone attempts to run this plan, the run must stop and record the specific blocking item rather than substituting an assumption.

## Explicit non-goals of this document

This plan does not train anything, does not report any metric value, does not introduce a new label or feature version, and does not grant approval to begin training. It only specifies how a future, approved candidate evaluation would be structured so that when gates close, evaluation can start without re-deriving these controls under time pressure.
