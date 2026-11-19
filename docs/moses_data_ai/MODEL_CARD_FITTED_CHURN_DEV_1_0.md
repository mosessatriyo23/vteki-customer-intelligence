# Model card — fitted churn development 1.0

Date: 2026-11-19. Model `moses-fitted-churn-dev-1.0`; feature `event-time-dev-1.0`; label `christ-churn90-three-events-dev-1.2`.

**Purpose:** reproducible academic synthetic-data experiment and offline scoring. Not approved deployment, campaign selection, causal effect, calibrated risk, or Gate D closure. `training_ready`, `experiment_ready`, `final_model`, `serving_ready` remain false. The older [baseline card](model_card_development_v1.md) describes a different POS-only cohort and remains historical evidence, not this fitted model.

## Target, cohort and inputs

Eligibility: at least one POS COMPLETED/PARTIAL_REFUND, completed physical visit, or membership RENEWAL in `(cutoff-365d, cutoff]`. Churn positive means no qualifying event in `(cutoff, cutoff+90d]`. Complete horizons only. Any-event eligibility follows the explicit development definition; Christ's NEVER_TRANSACTED exclusion still needs reconciliation for event-only customers.

Exactly seven numeric predictors, in order: `recency_days`, `tenure_days`, `purchase_count_365d`, `retained_revenue_365d`, `purchase_count_60d`, `purchase_count_90d`, `retained_revenue_90d`. Missing recency is train-median imputed. IDs, identity status, outcomes, synthetic latent trajectories and ground truth are not predictors. Purchase recency must not be described as visit recency. Revenue features represent retained revenue, not gross CLV.

## Training and evaluation

Fixed seed 42. Logistic regression: train-only median imputer, standard scaler, classifier. Comparator: depth-3 decision tree, minimum leaf 2; fixed recency >90 binary baseline. No test threshold search or test-based fitting. Logistic is the offline demonstration scorer, not an automatically promoted winner.

Train cutoff 2026-03-01 +07:00: 24,066 rows. Test cutoff 2026-06-01 +07:00: 33,779 rows, 5,794 positives / 27,985 negatives. Purged chronological split: 0 rows purged here (March outcome ends before June cutoff). Same customers can appear across cutoffs, reflecting future prediction on existing customers; not an unseen-customer generalization experiment. No separate validation/calibration fold exists in this run.

| Model | ROC-AUC | Average precision | Brier | TP / FN / FP / TN at 0.5 |
|---|---:|---:|---:|---|
| Recency rule | 0.65908 | 0.32887 | 0.15092 | 2143 / 3651 / 1447 / 26538 |
| Logistic | 0.90339 | 0.59112 | 0.09264 | 1987 / 3807 / 1521 / 26464 |
| Shallow tree | 0.89984 | 0.55055 | 0.08733 | 975 / 4819 / 211 / 27774 |

Synthetic ranking improves over recency; recall at 0.5 is not necessarily improved. Brier measures squared probability error, not proof of calibration. No real business uplift, fairness or production accuracy claim follows.

Executed customer-cluster bootstrap (200 repeats, seed 42, percentile CI95) on the fixed holdout: ROC-AUC baseline 0.65248–0.66437, logistic 0.90022–0.90630, tree 0.89610–0.90277. Logistic precision/recall at 0.5: 0.56642 / 0.34294. Descriptive ten-bin ECE: logistic 0.03749, tree 0.01847. No calibration fitting was performed; the interval covers resampling uncertainty, not synthetic source bias or model refitting. Reproducible report: `artifacts/models/churn_diagnostics_20261119/diagnostics.json` with checksummed completion manifest.

## Serialization, inference and explanations

`churn_experiment.py` exports JSON parameters, evaluation and holdout predictions. `churn_inference.py` verifies all output checksums and validates shape/version before reconstructing logistic sigmoid scoring without pickle. Scoring requires exact feature metadata, no labels, no duplicate normalized customer/cutoff, no future cutoff and no cutoff before the latest training outcome boundary.

Log-odds contributions plus intercept reconstruct the model output. They are **mathematical attribution**, not approved causal business reasons. Missing-feature imputations are recorded, not described as observed facts. No membership expiry, complaint or spend-decline explanation is supported by these predictors.

The 6 September snapshot produced 50,640 offline predictions, covering all supplied rows, **not** the eligible campaign population. No risk band, calibration version or producer expiry is fabricated; `valid_until=null`. This output is not the I-04 handoff and cannot enter NBA as governed predictions.

## Provenance and reproduction

Run commands and initial retention evidence: [progress](MOSES_DEVELOPMENT_PROGRESS_2026-11-19.md). Optional ML requirements: `requirements-models.txt`; inference uses JSON and stdlib, fitting requires scikit-learn. Never overwrite artifacts. Local ignored run: `artifacts/models/churn_fitted_dev_20261119_verified/`.

| Artifact | SHA-256 |
|---|---|
| training_rows.csv | `4c1756aa79521a47771a380232a15f3a34c569e65df0731080a9db23d8c304e9` |
| evaluation.json | `7732c1c889ed5e5af3c45847d8d311ec19dde283204161b8460d9b67fd65eca7` |
| holdout_predictions.json | `dbbe84ff7f4744cec7da7e6831582a9440030632491b6a88fcffeaec4be24c0b` |
| model_parameters.json | `07026721f181a09f66e71c86b7b9986b6766b7514e0e41b732b1504b49e539d6` |

## Limitations and team boundary

Current identity mapping is retrospective; final transaction statuses/refunds are not historical known-at evidence. Source observation maturity is synthetic, not certification of historical completeness. James supplies availability/correction/identity-as-of coverage. Christ resolves cohort semantics, retention estimand, reason taxonomy, action policies and target changes. New label/feature meaning requires new versions and retraining; see [revision policy](CHURN_MODEL_REVISION_POLICY_DEV.md). API/persistence/campaign integration is separate.

## Other target inventory — do not substitute churn

- CLV: deterministic business formula and observed aggregates exist; final 12-month retention factor and revenue convention are unresolved. Future 90-day retained revenue is not 12-month CLV.
- Retail propensity 30d: product-item POS sources exist; independent outcome/model work must state proposed cohort and refund semantics.
- Service booking propensity 30d: booking source absent. Completed visits and `generator.labels.service30` service purchases are **not bookings**.
- Membership renewal/upgrade 60d: RENEWAL events exist; upgrade meaning must be decided. A renewal-only experiment must not claim the combined FRD target.
