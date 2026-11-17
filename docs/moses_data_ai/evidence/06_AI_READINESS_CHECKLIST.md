# 06 — AI readiness checklist and cross-team handoff

**Date:** 2026-11-17. **Scope:** synthetic development only. **Owner:** Moses. **Reviewer sign-off:** PENDING. **Approval date:** NOT GRANTED. **Author of checklist is not an approver.**

```text
training_ready=false
experiment_ready=false
final_model=false
Gate D=NOT OPEN
```

Status legend: **VERIFIED (bounded)** = evidence reviewed for the specific stated development scope; **BLOCKED** = necessary evidence/decision missing; **NOT RUN** = no test/result; no row implies production readiness.

| Evidence request from James | Status | Evidence | Reviewer / approval |
|---|---|---|---|
| 01 Data Readiness + quality/lineage | **VERIFIED (synthetic validation only); BLOCKED for PIT training** | [`01_DATA_READINESS.md`](01_DATA_READINESS.md); 54 local unit/regression tests; source availability/feeds unproved | Moses author; James platform review PENDING; Christ business review PENDING; date NOT GRANTED |
| 02 Feature Validation + leakage | **VERIFIED (event-time T+1/T+2 only); BLOCKED for bitemporal** | [`02_FEATURE_VALIDATION.md`](02_FEATURE_VALIDATION.md); synthetic leakage positive control; not `known_at`-safe | Moses author; James historical review PENDING; date NOT GRANTED |
| 03 Churn & CLV Model Evaluation | **VERIFIED (older synthetic diagnostics only); BLOCKED as Capstone model evaluation** | [`03_MODEL_EVALUATION.md`](03_MODEL_EVALUATION.md); three-event recency rule and older purchase-only CLV90 baseline kept separate | Moses author; Christ target/value review PENDING; date NOT GRANTED |
| 04 Experiment Comparison | **NOT RUN / BLOCKED** | [`04_EXPERIMENT_COMPARISON.md`](04_EXPERIMENT_COMPARISON.md); no candidate estimator, online experiment or winner | Moses author; Gate D reviewers PENDING; date NOT GRANTED |
| 05 Decisioning Validation | **VERIFIED (Christ's existing CI development checks only); BLOCKED for end-to-end model/real campaign** | [`05_DECISIONING_VALIDATION.md`](05_DECISIONING_VALIDATION.md); local decision suite not run due to missing pytest | Christ policy reviewer PENDING; Moses adapter review PENDING; date NOT GRANTED |

## Gate decision (not sign-off)

| Gate | Status | Next required owner evidence |
|---|---|---|
| A — business | **BLOCKED** | Christ: resolve Capstone's 180-day-forward churn vs 90-day horizon, measurable active cohort, CLV gross/retention/window, lifecycle fallback and approved version with reviewer/date. Verbal direction allows technical development but is not sign-off. |
| B — engineering | **PARTIAL** | Existing merged PRs have green CI. Moses PR #38/validation reports need green checks on the final commit; no CI result is business approval. |
| C — historical | **BLOCKED** | James: complete original-source refund/status availability, as-of aggregation and provenance/identity acceptance; DRAFT contract review by James/Christ/Moses. |
| D — model review | **NOT OPEN** | Gates A–C close, then versioned proposal and explicit reviewers/approval before a new label/feature/model or experiment. |

## Review sign-off form (leave blank until real decision)

| Role | Named reviewer | Decision (APPROVED / REJECTED / PENDING) | Date (ISO) | Evidence link |
|---|---|---|---|---|
| Christ — business definition/policy | — | PENDING | — | — |
| James — historical platform/data contract | — | PENDING | — | — |
| Moses — data/model validation | — | PENDING | — | — |
| Cross-team gate owner | — | PENDING | — | — |

No real campaigns, real messages, customer selection or use of `ground_truth` as an input. Existing baselines/labels remain intact and versioned; no training was performed for this packet.
