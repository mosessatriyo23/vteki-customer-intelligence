# Moses sprint progress and readiness gates — 2026-11-14

## Scope and decision

This is a status update, not a reopening of the completed independent Moses scope. The original Sprint 0–5 work for synthetic generation/audit, ingestion development, identity/Customer360, RFM/lifecycle, event-time features, proposed labels, baseline diagnostics, and handoff is complete for engineering development. The follow-up sprint gate in `docs/TEAM_FOLLOW_UP_ACTIONS_2026-11-04.md` controls any new target/model work.

Status remains:

```text
training_ready=false
experiment_ready=false
final_model=false
```

No production scoring or outbound campaign is authorized. Ground truth remains evaluation-only and must not be used for matching or model input. Existing baseline/labels are immutable historical development references; any future approved changes must use a new version and changelog.

## Work completed in the follow-up

- PR #27: as-of CLV aggregates and order-safe deduplication; merged. CLV business formula is still not approved for final use, and explicit retention remains required.
- PR #29: churn outcome boundary regression tests; merged.
- PR #30: privacy-safe outcome/lifecycle aggregate reporter; merged.
- PR #31: fixed-rule churn evaluator with temporal metrics and strict input validation; merged at `9e84ba069b73b02f8a9c73da6345527f06999cfa` after CI passed.
- Latest local regression after merge: 23 model/segmentation/outcome/CLV tests passed; Ruff, Black, and `git diff --check` passed.

## Synthetic diagnostic evidence (not production performance)

Run inputs: `inbound/2026-09-06`, identity snapshot `artifacts/identity/v11`; cutoffs 2026-03-01 and 2026-06-01 +07. Local ignored artifacts are under `artifacts/models/christ-diagnostic-run2/` and are not committed.

- Churn label version: `christ-churn90-three-events-dev-1.1`; horizon 90 days.
- 75,002 customer/cutoff labels; 55,452 complete and eligible training rows.
- Purged temporal split: 22,602 train rows (March cutoff), 32,850 holdout rows (June cutoff), 0 purged rows.
- June observed churn prevalence: 5,558 / 32,850 = 16.92%.
- Fixed recency rule holdout: ROC-AUC 0.664, average precision 0.344, Brier 0.141; recall 36.97%, balanced accuracy 66.40%.
- These metrics evaluate a fixed binary heuristic, not a fitted ML model. Average precision/Brier are limited by the binary score; top-decile lift is intentionally null because the score ties do not define a meaningful decile.
- Lifecycle snapshots: March 33,243 profiles with 0 CHURNED; June 41,759 profiles with 46 CHURNED and 18 UNCLASSIFIED. UNCLASSIFIED is retained where membership expiry evidence does not satisfy the approved lifecycle guard. These rules remain proposed pending business approval.
- Ineligible label rows remain null for churn; they are not treated as negative outcomes.

## Gate assessment

| Gate | Status | Evidence / remaining work |
|---|---|---|
| A — business contract | BLOCKED | `target_definitions.md` v1.2 is REVISI; formal approver/date absent. Resolve churn confirmation, CLV gross source/retention method, lifecycle priorities/boundaries/treatment, consent/suppression, outcome/KPI semantics. |
| B — CI and contract tests | PASS for merged evaluator change | PR #31 CI passed. This does not approve business definitions or historical-data availability. |
| C — historical data contract | BLOCKED | James/platform needs meaningful `available_at`, immutable refund/status lineage, effective-time identity reconstruction, and tested multi-batch semantics. |
| D — model readiness review | NOT OPEN | Do not publish new labels/features or train/compare a new ML estimator until Gates A–C are satisfied and reviewed. |

## Next actions and owners

1. **Christ:** publish formally approved, versioned decision tables for churn, CLV/value, lifecycle/treatment, consent/suppression, and outcome/KPI; record approver, approval date, examples, and change log.
2. **James:** provide tested historical availability/effective-time contracts, immutable transaction/refund/status history, identity-as-of reconstruction, and multi-batch PostgreSQL evidence.
3. **Moses:** preserve the development baseline; review new approved contracts with Christ and James; then prepare a versioned feature/label proposal and model card for Gate D review. No new training before that review.
4. **Joint:** agree acceptance criteria, data backfill coverage, human approval, and monitoring/rollback before any real-world experiment or campaign integration.

## Explicit exclusions

- No booking propensity model without genuine booking outcome events.
- No inferred retention factor or replenishment cycle.
- No campaign/message sending; nudges remain drafts requiring human approval.
- No commercial use of PROVISIONAL/REVIEW_REQUIRED identities without an approved policy.
- No production, fairness, causal uplift, or real-customer performance claims from synthetic diagnostics.
