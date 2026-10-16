# Moses — independent Data & AI development handoff (2026-10-15)

Scope: synthetic-data, local development demonstration; no James/Christ business or
production approval implied. Code is separated from ignored `inbound/`, `artifacts/`,
`generator/ground_truth/`, and `chat.md`.

## Executed end-to-end

1. Validated schema-v2 synthetic inbound with `BatchValidator`, source-only EDA to
   `artifacts/eda/dev-run2` (monthly, branch, channel, missing references, purchase
   frequency per CRM source identity). See `docs/eda_development_v1.md`.
2. Recomputed Golden-level RFM/lifecycle/identity-status aggregate EDA from checksummed
   resolver + validated inbound to `artifacts/eda/golden-run1`; never use ground truth
   as matching/model input. See `docs/eda_golden_v1.md`.
3. Development historical features from current identity snapshot (existing PIT v1),
   separate technical PROPOSED future 90-day churn/revenue labels, and stdlib naive
   recency/median baselines with purged chronological cutoff holdout. See
   `docs/point_in_time_features_dev.md` and `docs/model_development_baseline.md`.

Observed synthetic full dataset at +07 cutoff 2026-09-06 23:59:59:
444011 transaction rows; 4506 fingerprint replays removed; 421859 qualifying
purchases; retained revenue 696643476095 IDR. Of these, 12701 qualifying purchases
and 20878101160 IDR remain unattributed to a customer. CRM source-level frequency
never/once/repeat = 13881/11486/35633 out of 61000 source identities.
Golden-level: 50640 provisional resolver profiles; 49416 `PROVISIONAL`, 1224
`REVIEW_REQUIRED`. These are not verified unique real customers.

Development baseline on cutoffs 2026-03-01 and 2026-06-01 (+07): 75002 label rows,
55452 complete eligible joined rows; train 22602, test 32850, purged 0 because
train's 90-day outcome ends before holdout. Naive churn rule accuracy 0.87656 and
balanced accuracy 0.74199; constant train-median revenue baseline holdout MAE
3817698.51 IDR. **These numbers describe a synthetic retrospective diagnostic,
not validated predictive performance or production model quality.** Data generation
and current identity/refund status can overstate quality. `experiment_ready=false`.

## Remaining gates (not part of independently completed scope)

- Identity needs effective-time versioning and review/governance before PIT training.
- Transaction corrections/refund `available_at` and immutable event versions are absent.
- Christ must approve target, eligibility, horizon, lifecycle and CRM use cases. Booking
  propensity cannot be called a booking model without actual booking events.
- James must agree batch master-data repeat semantics, permissions and production DB
  integration; multi-batch PostgreSQL ingestion is not established by this EDA.
- Temporal holdout uses repeated customers and synthetic truth-generation processes;
  leakage tests exclude future event time, **not** future knowledge available later.
- No customer messaging, serving model, production deployment or dashboard integration.

For a new local run use NEW output paths in `artifacts/`. Keep artifacts and .env ignored.
Do not copy results to public documents as actual business findings.
