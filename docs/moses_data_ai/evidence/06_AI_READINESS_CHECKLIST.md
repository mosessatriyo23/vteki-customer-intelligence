# 06 — AI readiness checklist and cross-team handoff

> **Catatan historis (2026-11-21):** checklist dan status Gate A–D di bawah mencerminkan 2026-11-17 dan tidak diperbarui; tidak ada sign-off baru. Status terkini: [handoff Moses](../MOSES_CURRENT_HANDOFF.md).

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
| B — engineering | **PARTIAL; merged CI verified** | PRs #38, #36 and #40 are merged with successful final-head checks and merge-commit CI (refresh below). Engineering CI is not business/historical approval or Gate B sign-off. |
| C — historical | **BLOCKED** | James: complete original-source refund/status availability, as-of aggregation and provenance/identity acceptance; DRAFT contract review by James/Christ/Moses. |
| D — model review | **NOT OPEN** | Gates A–C close, then versioned proposal and explicit reviewers/approval before a new label/feature/model or experiment. |

## CI evidence refresh — 2026-11-17 (GitHub CLI; not approval)

`gh pr view <number> --json state,mergedAt,headRefOid,mergeCommit,statusCheckRollup` and `gh run view <run-id> --json headSha,event,conclusion,jobs` show:

| PR | Merge (UTC) / commit | Final PR-head checks | `main` merge-commit push CI |
|---|---|---|---|
| [#38](https://github.com/mosessatriyo23/vteki-customer-intelligence/pull/38) | 08:54:10 · `885b675` | `f97fe51`: backend/quality, frontend build, RBAC E2E SUCCESS | [run 44050705428](https://github.com/mosessatriyo23/vteki-customer-intelligence/actions/runs/44050705428) SUCCESS, three jobs |
| [#36](https://github.com/mosessatriyo23/vteki-customer-intelligence/pull/36) | 09:02:12 · `5da8c02` | `1082182`: same three checks SUCCESS | [run 44051870098](https://github.com/mosessatriyo23/vteki-customer-intelligence/actions/runs/44051870098) SUCCESS, three jobs |
| [#40](https://github.com/mosessatriyo23/vteki-customer-intelligence/pull/40) | 09:32:17 · `cad7364` | `036398c`: same three checks SUCCESS | [run 44056472864](https://github.com/mosessatriyo23/vteki-customer-intelligence/actions/runs/44056472864) SUCCESS, three jobs |

This refresh verifies recorded GitHub CI only; no local tests or historical metrics were rerun. CI does not resolve Gates A/C, certify availability-aware features, or supply reviewer sign-off; Gate D remains NOT OPEN.

## Review sign-off form (leave blank until real decision)

| Role | Named reviewer | Decision (APPROVED / REJECTED / PENDING) | Date (ISO) | Evidence link |
|---|---|---|---|---|
| Christ — business definition/policy | — | PENDING | — | — |
| James — historical platform/data contract | — | PENDING | — | — |
| Moses — data/model validation | — | PENDING | — | — |
| Cross-team gate owner | — | PENDING | — | — |

No real campaigns, real messages, customer selection or use of `ground_truth` as an input. Existing baselines/labels remain intact and versioned; no training was performed for this packet.
