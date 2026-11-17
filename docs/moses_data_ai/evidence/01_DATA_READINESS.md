# 01 — Data readiness, quality and lineage (synthetic development)

**Date:** 2026-11-17. **Business source:** `docs/christ_business/reference/Requirement_Capstone.md` (local equivalent: `requirements/extracted_text/Requirement_Capstone.txt`). **Owner:** Moses (quality and input inventory); James (platform provenance/history). **Reviewer:** pending. **Approval date:** not granted.

```text
training_ready=false
experiment_ready=false
final_model=false
status=BLOCKED_FOR_NEW_MODEL
```

## Quality evidence (VERIFIED for synthetic fixtures only)

`services/data/ingestion/validator.py` validates source schema, required values, cross-table references, arithmetic, chronology, duplicate primary keys, manifest row counts and SHA-256 checksums; it rejects invalid batches. `services/data/ingestion/contracts.py` describes the synthetic CSV contract. These checks do not measure real-world accuracy, complete refunds or business definitions. No `ground_truth` was used for matching, feature construction, labels or model inputs.

Executed on checkout containing `main` `7e09616` and Moses PR #38 `aa2a23d`:

```powershell
python -m unittest tests.data.test_ingestion tests.data.test_ingestion_negative tests.data.test_data_leakage tests.data.test_pit_features tests.data.test_model_baseline tests.data.test_model_diagnostics tests.data.test_model_evaluator tests.data.test_business_clv tests.data.test_clv_features tests.data.test_model_label_readiness tests.data.test_drift_monitoring
```

**54 passed in 13.420s**, including quality and negative-ingestion tests. This command does not run PostgreSQL integration tests. For a reproducible per-batch validation report, use `python -m services.data.ingestion.cli --inbound <synthetic-inbound> --report <new-report-path>` as documented in `../ingestion_v2.md`; no fresh per-batch report is claimed here.

## Lineage and usability inventory

| Input | Observed source/lineage | Status for new PIT model |
|---|---|---|
| POS transactions | `transactions.csv` business timestamp and batch manifest/checksum; James transaction event history distinguishes origin and receipt batch | **BLOCKED:** historical refund/status/cancellation feed and original CSV availability completeness unproved; projection is `OBSERVED_EVENTS_ONLY` |
| Completed visits and membership renewals | source CSV event times; James event history captures platform receipt on ingestion | **BLOCKED:** receipt time assigned during ingestion is not proof of original historical availability |
| Identity mapping and review | registry histories and coverage marker added by James; as-of APIs exist | **PARTIAL:** pre-migration coverage cannot be reconstructed; review/merge reversal and full profile stability require acceptance |
| CLV gross revenue and retention | business formula in Capstone Bab 2.2; development calculator takes explicit retention | **BLOCKED:** approved source gross/refund accounting, rolling/calendar 12m semantics and retention method not established |
| Consent and suitability | decisioning contract/guardrails in Christ code | **PARTIAL:** permission/status availability and complete product/business eligibility history not certified for model/activation use |

This is an inventory of evidence, not a claim that unavailable timestamps can be inferred. For field-by-field source coverage and James acceptance scenarios use `../READINESS_REVIEW_PACKET_2026-11-16.md` and `docs/james_platform/approved/historical_data_contract_v1.x.md` (DRAFT). Those older inventories are historical snapshots; prefer current James contract for updated implementation details, while preserving unknown/unproven source semantics.

**Closure needs:** James's feed/lineage coverage and cross-team historical sign-off; Christ's explicit target and gross-value decisions and signed version; then re-run quality/lineage checks over the proposed immutable input version. CI and synthetic checks do not constitute data-owner approval.
