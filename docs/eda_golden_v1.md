# Golden Customer descriptive EDA v1

Aggregate profiles recomputed with `build_segments(inbound, resolution, cutoff)` after validating the synthetic batch through `BatchValidator`. Existing profile/segment artifacts are not trusted or read. `build_segments` validates the resolver manifest checksums and exact source coverage, then derives profiles and revenue at the cutoff. This validates resolver provenance, not identity accuracy; it does not rerun the identity-matching algorithm.

```bash
python3 -m services.data.eda.golden \
  --inbound inbound/2026-09-06 \
  --resolution artifacts/identity/v11 \
  --cutoff-at 2026-09-06T23:59:59+07:00 \
  --output-dir artifacts/eda/golden-run1
```

The callable writes to a new directory only: `summary.json`, `report.md`, and `eda_manifest.json`. Manifest hashes for source and resolver exist before and after recomputation and inside batch validation; outputs are checksummed. No PostgreSQL or network is used. Overwrite attempts are rejected so publication is not silent.

## What is reported

- RFM quantiles, minima and maxima without exporting customer IDs or PII: `recency_days`, `frequency`, `monetary`, `r_score`, `f_score`, `m_score`, `tenure_days`, `transactions_60d`, `transactions_90d`, `revenue_90d`. Recency omits never-transacted customers and is counted in the missing field.
- Lifecycle stage counts under `lifecycle-proposed-1.0` with their numeric window distributions.
- Identity statuses from the recomputed mapping as aggregate counts: totals and breakdowns of purchase frequency and retained revenue (`PROVISIONAL` versus `REVIEW_REQUIRED`).
- Distributions use one observation per eligible Golden Customer, not per source record. Outputs contain aggregate statistics only, never per-customer entries.

No ground truth is read. The generator separates evaluation truth into `ground_truth_dir` in tests and production validation forbids truth files inside the batch.

## Semantics and limitations

- Transaction cutoff is inclusive; timezone must be `+07:00`. Future events do not alter the aggregates.
- Source batch validation covers schema version, hashes, foreign keys, transaction accounting, and chronology.
- RFM and lifecycle come from the development segmentation rules; they are not training features or real behavioral findings.
- Identity statuses reflect provisional resolver output, not adjudicated identities. PII fields from `crm_customers.csv` are never serialized into outputs.
- Revenue is integer `actual_revenue` IDR for qualifying purchases after fingerprint deduplication. Quantiles use linear interpolation.
