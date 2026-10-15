# Future labels and baseline evaluation — development only

This stage creates **PROPOSED**, retrospective 90-day outcomes and a deterministic
standard-library baseline. It is a pipeline check, not a production model, final
experiment, causal result, or claim of leakage-free model quality. Every manifest and
label row declares `experiment_ready=false`; the manifest also declares
`final_model=false`.

## Label contract

For each feature cutoff and current-snapshot Golden ID:

- qualifying purchases are deduplicated `COMPLETED`/`PARTIAL_REFUND` transactions;
- eligibility requires at least one purchase in `(cutoff - 365 days, cutoff]`;
- `churn90=1` means an eligible customer has no purchase in
  `(cutoff, cutoff + 90 days]`;
- `clv90` is summed future `actual_revenue` in that same window;
- the lower future boundary is exclusive and upper boundary inclusive;
- an outcome is complete only when the full horizon ends by 23:59:59.999999 +07 on
  the generation manifest's `as_of_date`;
- incomplete churn and CLV values are null. Ineligible churn is null. Label output keeps
  all customer/cutoff rows for audit, but training rows include only complete eligible
  outcomes.

`--horizon-days` is configurable and recorded, though target names remain the proposed
`churn90`/`clv90` contract. Use 90 for comparable runs. Ground-truth generator artifacts
are prohibited by ingestion validation and are never read.

Labels remain separate from feature construction. Feature rows are generated using only
events at or before the cutoff, then joined by `(golden_customer_id, cutoff_at)` after
label construction. Thus labels are never feature columns or inputs to feature logic.

## Baselines and temporal evaluation

The latest complete cutoff is the test holdout; earlier rows whose outcome window ends
after that feature time are purged, then all remaining complete eligible rows train it.
An empty purged train or test set is rejected. There is deliberately no
customer-random split, which would mix time periods and overstate readiness.

The churn rule is fixed and not fitted: predict churn when `recency_days > 90` (or
recency is missing). Reported test metrics are TP/TN/FP/FN, accuracy, sensitivity,
specificity, and balanced accuracy. If one class is absent, balanced accuracy equals the
available class recall rather than inventing a missing-class recall.

CLV prediction is the constant median of **train-cutoff outcomes only**. Test MAE is the
primary reported CLV metric; the train mean and its test MAE are included as a transparent
comparison. Counts and exact train/test cutoff lists are recorded. No sklearn or other ML
package is required.

## Known leakage/readiness limitations

This is event-time evaluation over a current data snapshot. Resolver clusters are applied
retrospectively, so historical identity knowledge is unavailable. Current transaction
status, refunds, and `actual_revenue` may contain information not available at the old
cutoff because source availability timestamps and versioned refund events do not exist.
Consequently metrics are diagnostics only and must not be presented as final performance
or used to launch an experiment.

## Run

Use at least two cutoffs whose 90-day windows are complete and a new output directory:

```bash
python3 -m services.data.models.cli \
  --inbound inbound/2026-09-06 \
  --resolution artifacts/identity/v11 \
  --cutoff-at 2026-03-01T23:59:59+07:00 \
  --cutoff-at 2026-06-01T23:59:59+07:00 \
  --horizon-days 90 \
  --output-dir artifacts/models/dev-baseline-run1
```

The CLI validates the full inbound batch and resolver checksums, detects input mutation,
and writes `labels.csv`, complete eligible `training_rows.csv`, `metrics.json`, and
`model_manifest.json`. Input/output SHA-256 checksums are recorded. The manifest is the
last completion marker; a directory without it is incomplete and must not be consumed.
Existing output directories and nested input/output paths are rejected.
