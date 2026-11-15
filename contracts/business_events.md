# Business event contracts

These are observable inbound records. They must not contain latent trajectory or identity-ground-truth fields. UTF-8 CSV uses a header even when empty; timestamps are ISO-8601.

## `membership_events.csv`

| Field | Meaning |
|---|---|
| `event_id` | Deterministic event identifier |
| `source_customer_ref` | `crm_customers.crm_customer_id` |
| `member_code` | Nonempty source member code |
| `event_type` | `JOIN` or `RENEWAL` |
| `occurred_at` | Observed business event time |
| `period_start` | Contract period start |
| `expires_at` | Contractual period end, exactly 180 days after start; it may be beyond the observation end and is not a future observed event |
| `membership_tier` | `BRONZE`, `SILVER`, `GOLD`, or `PLATINUM` |
| `previous_event_id` | Empty for JOIN; prior event for RENEWAL |

A membership chain begins at CRM `join_date` (00:00 in the generation timezone). Renewal starts one day after expiry, is generated with probability 0.65 only when that date is observed, and preserves or upgrades one tier. The generator does not merge source customer records.

## `customer_visits.csv`

| Field | Meaning |
|---|---|
| `visit_id` | Deterministic identifier |
| `source_customer_ref` | Nonempty transaction customer reference |
| `source_transaction_id` | Retained source transaction |
| `branch_code` | POS branch |
| `visit_datetime` | Transaction timestamp |
| `status` | `COMPLETED` |

One visit is derived from each `COMPLETED` or `PARTIAL_REFUND` POS transaction having a customer reference. Exact source replays are removed by a business fingerprint. An optional duplicate-ID map can identify known replays. The fallback can collapse two genuine purchases whose observable business fields are identical; no truth identity mapping is read.

## Persisted business-event history

The PostgreSQL loader copies completed visits and membership JOIN/RENEWAL rows
to `source.business_event_history`. `occurred_at` comes from `visit_datetime`
or `occurred_at`; `source_event_id` comes from `visit_id` or `event_id`;
`source_version` is the input schema version on the batch; and
`source_batch_id` identifies the batch receiving the source row.
`available_at` and `recorded_at` are assigned by the database when this event
ledger first accepts the row. `lineage_reference` retains the source
transaction ID for visits and `previous_event_id` for membership events.

Existing source rows are backfilled when the ledger migration runs. Their
availability is therefore the first-capture time in this ledger, not proof of
when the platform first received them historically. No refund/status feed is
present in these CSV contracts; those missing events must not be synthesized.

## Model labels

`generator.labels.make_labels` produces source-customer cohorts only when CRM `join_date <= prediction_at`. Outcome windows are right-closed and prediction-exclusive. `outcome_complete=1` requires observation through prediction + 90 days; otherwise all outcomes are blank. `churn90` is false when a positive eligible transaction, completed visit, or renewal occurs in 90 days. Retail/service labels use transaction items in 30 days; renewal uses 60 days. Historical and future refund-adjusted values are separate, preventing post-prediction leakage.
