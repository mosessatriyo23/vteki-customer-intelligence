# Model card — retrospective synthetic baseline v1

## Intended purpose

Verify that the technical path from validated synthetic source data through current-snapshot
identity mapping, event-time features, future labels and chronological evaluation works.
This is **not** a production model, experiment, causal estimate, campaign policy, or evidence
of real customer behavior.

## Targets (PROPOSED)

Eligible customer: at least one qualifying purchase in `(cutoff-365d, cutoff]`.
`churn90=1`: no qualifying purchase in `(cutoff, cutoff+90d]`. `clv90`: integer IDR
`actual_revenue` summed over that future window. Incomplete horizons are null and excluded.
Rules are technical proposals awaiting business approval.

## Inputs and evaluation

Feature v1 includes recency, tenure, purchase counts (60/90/365d), retained revenue
(90/365d), identity status and explicit retrospective identity policy. Ground truth is
never a matching or model input. The latest complete cutoff is holdout; earlier outcomes
that extend beyond holdout feature time are purged. Churn baseline is fixed recency >90d;
CLV baseline is train-outcome median. Diagnostics compare always-non-churn and train mean.

## Executed synthetic diagnostic

Cutoffs: 2026-03-01 and 2026-06-01 +07. Train 22602, holdout 32850, purged 0.
Recency rule: accuracy 0.87656, balanced accuracy 0.74199, sensitivity 0.51323,
specificity 0.97075. This reveals substantial missed churn positives despite high raw
accuracy. Median revenue baseline MAE 3817698.51 IDR; mean baseline MAE 3899626.65 IDR.
These values must not be presented as final predictive performance.

## Readiness decision: BLOCKED

Every run remains `training_ready=false`, `experiment_ready=false`, `final_model=false`.
Blockers: synthetic data, retrospective current identity mapping, unversioned transaction
status/refunds, missing availability timestamps and unapproved target/eligibility rules.
The readiness gate in diagnostics intentionally records fixed blockers; it is not an
approval service and cannot turn true until contracts/data are independently redesigned.

## Prohibited uses

No customer selection, automated decision, offer allocation, campaign messaging, booking
propensity claim, production serving, fairness conclusion or business KPI claim. Do not
compare identity status groups as protected-group fairness evidence. Aggregates may be
used only for internal engineering diagnostics with the synthetic-development label.

## Required before production modeling

Versioned effective-time identity registry; immutable event/correction/refund availability;
real target and eligibility approval; consent/exclusion policy; repeated historical cutoffs;
leakage and quality gates; appropriate baselines/model selection; subgroup and calibration
review; deployment, monitoring, rollback and human-approval design.
