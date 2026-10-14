# Customer360 development snapshot (PROPOSED, not training features)

`services/data/customer360/profile.py` aggregates observable source events using resolver
mapping only, never ground truth. `cli.py` writes a cutoff snapshot. Contract columns:

- golden_customer_id: provisional resolver cluster ID.
- cutoff_at: timezone-aware inclusive event cutoff, +07:00.
- identity_status: PROVISIONAL or REVIEW_REQUIRED (no approved identity assertion).
- source_identity_count: source records joined by cutoff.
- first_join_date: earliest business join date among those records.
- transaction_count: source-fingerprint-deduplicated COMPLETED/PARTIAL_REFUND transactions.
- retained_revenue: sum actual_revenue from those transactions.
- last_transaction_at: most recent included qualifying transaction.
- visit_count: completed visit events by cutoff.
- renewal_count: renewal events by cutoff.

Missing transaction customer references are not attributed to invented customers. Source
CRM checksum and resolution output checksums/coverage are verified. Other source files
must be validated by ingestion before consumption; this is not a replacement validator.

```bash
python3 -m services.data.customer360.cli --inbound inbound/2026-09-06 --resolution artifacts/identity/v11 --cutoff-at 2026-09-06T23:59:59+07:00 --output artifacts/customer360/current.csv
```

LIMITATIONS: current identity mapping is used retrospectively, so historical identity
availability is not point-in-time versioned. Do not use these snapshots as training
features yet. Refunds are assumed settled at transaction time; there are no timed refund
events. Fingerprint dedup can collapse genuinely identical transactions. Visit/renewal
metrics currently count source event records (no cross-source event entity resolution).
Raw data and all profile inputs are in-memory: full-scale memory/performance testing is
outstanding. No consent eligibility, RFM, lifecycle or production PostgreSQL profile is
claimed implemented. Separate ingestion and identity review contracts remain required.

Executed test validates generated 20-customer snapshot, cutoff filtering, future amount
mutation isolation, provisional status, invalid timezone and corrupted mapping rejection.
