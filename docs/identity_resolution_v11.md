# Identity baseline v1.1 — incremental registry and review (PROPOSED)

Baseline v1.0 remains documented in identity_resolution_v1.md. No claim of production
readiness or calibrated confidence is made.

## Recall improvement

`--synthetic-aliases` is opt-in, disabled by default. It strips only trailing `+src[0-9]+`
on four generator domains (example.id, mail.id, inbox.id, customer.test). It neither
strips arbitrary plus aliases nor Gmail/provider dots. This is an explicit fixture
normalization assumption, not a universally valid email rule. Matching still requires
at least two identifier agreements plus name/demographic evidence. Single-attribute
AUTO_MATCH remains forbidden. Evaluation truth is NEVER an input to this policy.

Executed results:

| Dataset | Precision | Pair recall | False merge clusters | Predicted clusters |
|---|---|---|---|---|
| 2000 golden / 2440 source | 1.0 | .914460 | 0 | 2031 |
| 50000 golden / 61000 source | 1.0 | .938893 | 0 | 50640 |

Full-data baseline v1.0 pair recall was .858952. Target 95% duplicate recall is NOT
claimed met. Skipped oversized blocks and missing-attribute pairs still need review.
Performance on this deliberately structured synthetic generator does not demonstrate
production performance. Do not tune arbitrary merge thresholds just to meet a benchmark.

## Review outputs

CLI writes mapping.csv, decisions.csv, review_queue.csv (REVIEW pairs only),
oversized_blocks.json and resolution_manifest.json with source/output checksums and
policy/registry metadata. KEEP_SEPARATE pairs are retained in decisions. Review queue
is a proposed worklist, not an implemented human approval/override workflow.

## Published IDs

`--prior-mapping` accepts only resolver schema (source_customer_id,golden_customer_id,
resolver_version). Synthetic truth schema is rejected. Full snapshots must contain
all previously published sources. A cluster with one existing published ID retains
that ID, even if a lower source anchor arrives. Joining two old IDs or splitting an
old cluster raises ValueError requiring review. Nothing is silently merged or split.
No prior mapping is overwritten by this CLI. Users should retain/version reviewed
mapping outputs as the development registry. Database registry, concurrent updates,
merge aliases and audited manual review approvals are outstanding.

```bash
python3 -m services.data.identity.cli --source inbound/2026-09-06/crm_customers.csv --output-dir artifacts/identity/v11 --synthetic-aliases
# Next full snapshot, only with a reviewed prior resolver mapping:
python3 -m services.data.identity.cli --source inbound/2026-09-06/crm_customers.csv --output-dir artifacts/identity/next --synthetic-aliases --prior-mapping artifacts/identity/v11/mapping.csv
python3 generator/evaluate_identity.py --predicted artifacts/identity/v11/mapping.csv --truth generator/ground_truth/identity_mapping.csv
```

No commit/push/merge is performed in this step. Generator source CSVs are unchanged.
