# Source EDA development v1

Reproducible descriptive report from validated synthetic inbound CSV, without reading
identity ground truth or exporting customer PII. This is an initial source-level EDA,
not a complete Golden Customer/RFM analysis or evidence about real customer behavior.

```bash
python3 -m services.data.eda.cli \
  --inbound inbound/2026-09-06 \
  --cutoff-at 2026-09-06T23:59:59+07:00 \
  --output-dir artifacts/eda/dev-run2
```

Use a new output directory. Outputs: report.md, summary.json, eda_manifest.json.
Manifest is written last as a completion marker; directory publication is not atomic.
Consumers should verify output hashes. The CLI validates the full batch and checks
input hashes before/after analysis. No PostgreSQL or network service is used.

## Semantics

- Transaction event cutoff inclusive, timezone +07:00.
- Raw status counts are before fingerprint dedup; other transaction metrics are after it.
- Fingerprint policy matches development Customer360; genuinely identical purchases may
  be collapsed. This is not complete cross-source business event resolution.
- Qualifying purchases: COMPLETED/PARTIAL_REFUND; money uses integer actual_revenue IDR.
- Missing customer references stay in monthly/branch/channel business totals but are
  not attributed to customers. Missing-reference rows include all deduplicated statuses.
- Frequency counts are per eligible CRM source identity, NOT Golden Customer. Identity
  duplicates can inflate never/once counts; do not compare directly with lifecycle counts.
- CRM missing-field statistics describe the complete current snapshot, not historical
  field availability. Refund/status changes lack historical versions. Not training-ready.
- Only months with qualifying purchases are emitted, including partial boundary months.
  Reporting spans 19 calendar month buckets across an approximately 18-month simulation;
  monthly totals do not establish growth without exposure/partial-month adjustment.

## Executed full existing dataset (no regeneration)

Cutoff 2026-09-06T23:59:59+07:00:

- Observed transaction rows: 444011.
- Fingerprint replay rows removed: 4506; remaining rows: 439505.
- Qualifying purchases: 421859; retained revenue: 696643476095 IDR.
- Missing-reference deduplicated rows: 13197.
- Unattributed qualifying purchases: 12701; retained revenue: 20878101160 IDR.
- Source identities never/once/repeat: 13881 / 11486 / 35633 (total 61000).

Generated artifacts remain ignored in artifacts/eda/dev-run1, not committed. These are
synthetic descriptive totals, not production KPIs. RFM distributions, identity-review
impact, plots and real-data business interpretation remain future EDA scope.
