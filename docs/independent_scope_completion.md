# Independent Data & AI development scope — completion handoff

Status: **COMPLETE for synthetic development scope**, not production/model approval.
Date: 2026-10-16. Ground truth remains evaluation-only and is never matching/model input.

## Delivered in main + this diagnostics change

1. Reproducible schema-v2 synthetic generation and full batch quality audit.
2. Source-only validation/staging plus conservative identity resolver and review queue.
3. Development Customer360, RFM/lifecycle, source EDA and aggregate Golden EDA.
4. Event-time historical features marked `training_ready=false`.
5. Separate PROPOSED future churn/revenue labels with complete-horizon filtering.
6. Purged chronological baseline evaluation and aggregate error diagnostics.
7. Model card, checksummed manifests, future-mutation tests and no-PII EDA outputs.

## Reproduce local diagnostics

Run the prior development baseline with new ignored output paths, then:

```bash
python3 -m services.data.models.diagnostics \
  --source artifacts/models/dev-baseline-run1 \
  --output-dir artifacts/models/diag-run2
```

Expected outputs: `diagnostics.json`, `report.md`, `diagnostics_manifest.json`.
The command verifies the model manifest and output hashes before analysis, rejects
non-development manifests, duplicate keys, incomplete/ineligible training rows, invalid
future windows and overwrite attempts. Artifacts remain ignored and must not be committed.

## Executed full synthetic baseline diagnostic

Holdout 2026-06-01: 32850 complete eligible rows, churn prevalence 20.59%.
Recency rule: TP 3471, FN 3292, FP 763, TN 25324; accuracy 87.66%, balanced
accuracy 74.20%, sensitivity 51.32%, specificity 97.08%. Always-non-churn accuracy
is already 79.41% and balanced accuracy 50%, showing why raw accuracy is insufficient.
Median-outcome revenue baseline MAE is 3817698.51 IDR versus mean baseline
3899626.65 IDR. These are synthetic retrospective engineering diagnostics only.

## Explicit close criteria

- Code/tests/docs/checksums are reproducible and reviewable: complete.
- Independent EDA → event-time features → proposed labels → baseline → diagnostics: complete.
- Real-world training readiness: **BLOCKED by design**.
- Production deployment/campaign/serving: out of scope and prohibited.

## Required external decisions before reopening model development

James/platform: effective-time identity registry, immutable event versions and `available_at`,
refund/status history, multi-batch source semantics, production persistence/permissions.
Christ/business: target event, horizon, eligibility/exclusions, value definition, KPI,
consent/treatment rules. Both: acceptance criteria, historical backfill and production
monitoring/rollback. Booking propensity requires genuine booking events.

Do not reopen this scope merely to improve synthetic scores. Reopen only when an approved
contract or new versioned historical dataset resolves at least one readiness blocker.
