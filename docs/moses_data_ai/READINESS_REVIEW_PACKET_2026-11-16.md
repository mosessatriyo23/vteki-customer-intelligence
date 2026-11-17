# Readiness review packet — Moses / James / Christ

**Tanggal:** 2026-11-16

**Status:** Persiapan review; bukan approval dan bukan pembukaan training

**Pemilik:** Moses

**Tujuan:** Mempercepat verifikasi Gate A–C dengan satu paket evidence yang dapat ditinjau lintas tim.

**Addendum James — 2026-11-17:** Inventory dan scenario disposition di §6
diperbarui dari branch terbaru `james/gate-c-p0-finalize`, berbasis main
`5da8c02`. Isi ini mendokumentasikan bukti dan gap; tidak memberi approval.

## 1. Keputusan status saat ini

PR #33 James sudah merged ke `main` dan CI GitHub pada commit merge lulus. PR tersebut menyediakan fondasi identity mapping history, transaction event history, provenance, batch versioning, dan sebagian PostgreSQL tests.

Namun, kontrak historical data James masih berstatus `DRAFT` dan Gate C belum closed. Gate A dari Christ juga belum final. Karena itu status Moses tetap:

```text
training_ready=false
experiment_ready=false
final_model=false
```

Paket ini hanya berisi matrix, skenario acceptance, coverage inventory, dan template review. Tidak ada label baru, feature contract baru, training, customer selection, atau campaign.

## 2. Evidence index

| Area | Evidence saat ini | Status penggunaan |
|---|---|---|
| Historical contract | `docs/james_platform/approved/historical_data_contract_v1.x.md` | DRAFT; review lintas tim pending |
| James implementation/status | `docs/james_platform/STATUS_TUGAS_JAMES.md` | J-PLAT-01 in progress; J-PLAT-02 partial; J-PLAT-03 pending |
| Business definitions | `docs/christ_business/approved/target_definitions.md` | v1.2 REVISI; approver/date belum lengkap |
| Existing source contract | `services/data/ingestion/contracts.py` | Synthetic schema v2; belum memiliki `available_at` pada CSV source |
| Existing baseline | `docs/moses_data_ai/model_card_development_v1.md` | Synthetic retrospective only; immutable reference |
| Sprint gate | `docs/TEAM_FOLLOW_UP_ACTIONS_2026-11-04.md` | Gate A–C required before Gate D |
| Cross-team implementation | `docs/moses_data_ai/CROSS_TEAM_IMPLEMENTATION_GUIDE.md` | Work packages and gate tracker |

## 3. Compatibility and coverage matrix

Status meanings: `AVAILABLE` = exists and has stated semantics; `PARTIAL` = implementation exists but evidence/scope is incomplete; `MISSING` = no approved source contract; `BLOCKED` = cannot safely use for new training.

| Model/data need | Current source/implementation | Owner | Status | What closes it |
|---|---|---|---|---|
| POS transaction occurrence | `transactions.csv.transaction_datetime`; transaction event baseline | James/Moses | PARTIAL | bitemporal source contract and source lineage |
| Transaction `available_at` | James event history assigns receipt time in PostgreSQL | James | PARTIAL | source feed integration and acceptance tests |
| Refund/status history | Event API supports event types, but source historical feed is not integrated | James | MISSING/PARTIAL | integrated feed + final-state projection |
| Correction chain | `corrects_event_id` exists | James | PARTIAL | deterministic projection and chain/concurrency tests |
| Completed visit | `customer_visits.csv.visit_datetime` | James | BLOCKED for new PIT training | available/recorded semantics and late-event tests |
| Membership renewal | `membership_events.csv.occurred_at` | James/Christ | BLOCKED for new PIT training | availability contract and approved label semantics |
| Consent timing | `consent_events.csv.captured_at`, `expires_at` | Christ/James | BLOCKED for commercial use | approved suppression policy + as-known semantics |
| Identity current mapping | `artifacts/identity/v11/mapping.csv` | Moses | AVAILABLE only for old dev baseline | do not call historical/as-of |
| Identity as-of | `get_mapping_as_of()` and `build_profiles_as_of()` | James | PARTIAL | PostgreSQL consumer tests for split/unresolved/late review correction and immutable published profile |
| Review status as-of | bitemporal `identity.review_decision_history`; current queue is not used retroactively | James/Moses | PARTIAL | PostgreSQL profile consumer tests for correction/revocation and published-profile stability |
| Multi-batch transaction lineage | origin/receipt batch IDs and transaction event ledger | James | PARTIAL | event concurrency, source coverage, batch recovery mapping and exact current-head CI evidence |
| Catalogue version | batch-versioned catalogue references | James | PARTIAL | consumer selection rule and tests |
| Churn target | `christ-churn90-three-events-dev-1.1` | Christ/Moses | DEV ONLY | approved versioned target contract |
| CLV gross source/retention | `clv90` development aggregate; business formula unresolved | Christ/Moses | BLOCKED | approved value definition and retention method |
| Production/experiment use | none | Joint | BLOCKED | Gates A–C + Gate D review |

### Important source-contract observation

The current synthetic CSV source contract contains business timestamps such as `transaction_datetime`, `visit_datetime`, membership `occurred_at`, and consent `captured_at`, but it does not contain a source-level `available_at`. PostgreSQL event history can assign platform receipt time for events recorded there, but that does not reconstruct historical availability of old CSV records. Do not interpret a database-generated receipt timestamp as the original source availability time.

## 4. Acceptance scenarios for James

These are test scenarios and expected outcomes, not new business decisions. Exact event/status semantics must be confirmed by James and Christ where indicated.

### A. Bitemporal event visibility

| ID | Setup | Expected result |
|---|---|---|
| J-A01 | Event `occurred_at=2026-03-01`, `available_at=2026-03-05`; query `effective_at=2026-03-02`, `known_at=2026-03-02` | Event excluded |
| J-A02 | Same event; query `known_at=2026-03-05` | Event can be included if effective cutoff allows it |
| J-A03 | Late event arrives after an old snapshot is published | Existing snapshot is unchanged; new output/version is required |
| J-A04 | Naive timestamp or caller-supplied receipt timestamp | Reject; authoritative receipt time is platform/database assigned |

### B. Idempotency and provenance

| ID | Setup | Expected result |
|---|---|---|
| J-B01 | Replay same idempotency key and identical payload | No duplicate; return existing event |
| J-B02 | Reuse idempotency key with changed payload | Reject |
| J-B03 | Missing source event ID/version pair | Reject if contract requires the pair |
| J-B04 | Event references transaction absent from claimed source batch | Reject with no partial publication |
| J-B05 | Event appended to unpublished batch | Reject |

### C. Cross-batch event history

| ID | Setup | Expected result |
|---|---|---|
| J-C01 | Transaction recorded in batch A; refund received in batch B | Supported only if contract permits; preserve origin and receipt batch separately |
| J-C02 | Status correction in batch C references event from batch B | Lineage preserved; correction is a new append-only event |
| J-C03 | Replay batch B after partial failure | Idempotent; no duplicate or orphan |
| J-C04 | Concurrent publication of same event | One authoritative event; conflict is rejected or safely serialized |
| J-C05 | Batch B rollback | No batch appears published; unrelated published batch A remains valid |

### D. Final-state projection

| ID | Setup | Expected result |
|---|---|---|
| J-D01 | Recorded transaction then partial refund | Projection follows approved gross/refund/status rule |
| J-D02 | Multiple refunds | No double-counting; total bounded by approved contract |
| J-D03 | Correction of refund or transaction baseline | Correction substitutes the root effect at its original logical position; later visible effects are replayed after it |
| J-D04 | Correction chain A → B → C | Same final state regardless of valid replay order |
| J-D05 | Query before correction availability | Correction excluded; earlier known state returned |
| J-D06 | Query after correction availability | Corrected state returned; raw lineage remains auditable |

### E. Identity as-of and profile stability

| ID | Setup | Expected result |
|---|---|---|
| J-E01 | Mapping merge recorded after cutoff | Earlier cutoff uses earlier mapping |
| J-E02 | Mapping split recorded after cutoff | Earlier cutoff does not silently split |
| J-E03 | Unresolved/review-required decision recorded after cutoff | Earlier snapshot does not use future review decision |
| J-E04 | Cutoff before history baseline | Explicit unavailable/blocked result; no invented historical mapping |
| J-E05 | New review queue row after cutoff | Old profile status unchanged |
| J-E06 | Replay same profile composite key/payload, including after a later identity correction | Old published payload and publication metadata remain unchanged; a changed payload under the same key is rejected |

### F. Multi-batch and catalogue

| ID | Setup | Expected result |
|---|---|---|
| J-F01 | Two batches contain overlapping business/source IDs | Contract defines reject, version, or merge behavior; no silent overwrite |
| J-F02 | Same catalogue item code in two batch versions | Consumer selects explicit batch/version; no implicit global current row |
| J-F03 | Child transaction item references catalogue version | Foreign key and projection resolve the intended version |
| J-F04 | Retry after worker interruption | Idempotent recovery without partial snapshot |

## 5. Acceptance scenarios for Moses/Christ review

### Christ business decisions needed

- Confirm whether POS `COMPLETED`/`PARTIAL_REFUND`, completed visit, and renewal are all churn-negation events for the approved target.
- Confirm whether eligibility is prior qualifying purchase only, or “registered and active” with additional rules.
- Confirm whether `available_at` affects label eligibility/observability or only feature construction.
- Approve boundary behavior for cutoff and horizon.
- Approve gross revenue field and 12-month interpretation.
- Approve refund/correction treatment and retention-factor method.
- Approve lifecycle priority, `UNCLASSIFIED`, `OCCASIONAL`, `NEVER_TRANSACTED`, and service/commercial treatment.
- Approve treatment of `PROVISIONAL`, `REVIEW_REQUIRED`, and unresolved identity.

### Moses verification after James/Christ evidence

- Check that every approved source field maps to one feature/label input.
- Check that no feature uses data with `available_at > known_at`.
- Check identity registry and review status are both as-of.
- Check event projection is used instead of raw event rows for monetary/status features.
- Check incomplete horizon remains null.
- Check old baseline remains unchanged and a new version is created.

## 6. Data coverage inventory to complete

Inventory checked against source contracts, models, migrations, and event
services on branch `james/gate-c-p0-finalize` at base `5da8c02`. `UNKNOWN`
and `MISSING` are deliberate coverage findings. For legacy rows, database
capture time is not evidence of when an external source first made a fact
available.

| Dataset/event | Occurred field | Available field | Recorded field | Source batch | Correction lineage | Earliest reliable time | Evidence/link |
|---|---|---|---|---|---|---|---|
| Transactions | `transaction_datetime` in source row; copied as `occurred_at` for `TRANSACTION_RECORDED` baseline | Legacy migration-0015 baseline uses transaction row `created_at`; original source `available_at` is **UNKNOWN**. New ledger events receive database `available_at`. | Ledger database `recorded_at`; legacy value is not proof of source arrival. | Transaction origin batch and event receipt batch are separate for events. | `corrects_event_id` for ledger corrections; no corrections reconstructed from the legacy transaction row. | Source occurrence can be read from stored transaction dates; trustworthy point-in-time availability begins with actual ledger receipt capture. Pre-ledger availability is **UNKNOWN**. | `migrations/versions/0015_transaction_event_history.py`, `0016_transaction_event_provenance.py`; `source.transaction_event_history` |
| Refund / partial refund | Source event `occurred_at` required; feed not present | **MISSING** from source; platform DB receipt time only when an event is explicitly appended | DB-assigned `recorded_at` on appended event | Required receiving batch; origin transaction batch retained | `corrects_event_id` supported by ledger | No reliable external-feed start date: **UNKNOWN / BLOCKED** for new PIT training | Contract §2 and `services/data/ingestion/transaction_events.py`; no refund connector in repository |
| Status changes / cancellation | Feed `occurred_at` required; current transaction `status` is a snapshot, not history | **MISSING** from source; DB receipt time only for appended events | DB-assigned `recorded_at` on appended event | Required receiving batch; transaction origin retained | `corrects_event_id` supported by ledger | No reliable source-history start date: **UNKNOWN / BLOCKED** for new PIT training | Contract §2; current status enum in `services/data/ingestion/transaction_events.py` |
| Completed visits | `customer_visits.csv.visit_datetime` | DB `available_at` when first copied to business-event ledger; original source availability **UNKNOWN** | DB `recorded_at` when ledger captures event | `source_batch_id` retained | `lineage_reference` points to source transaction where present; no correction chain | Ledger first-capture boundary starts at migration 0020 for existing rows; exact per-row receipt is stored; prior availability **UNKNOWN** | `migrations/versions/0020_business_event_history.py`; `source.business_event_history` |
| Membership join / renewal | `membership_events.csv.occurred_at` | DB `available_at` when first copied to ledger; original source availability **UNKNOWN** | DB `recorded_at` at ledger capture | `source_batch_id` retained | Source `previous_event_id` retained as lineage; no correction chain | Ledger first-capture boundary starts at migration 0020 for existing rows; exact per-row receipt is stored; prior availability **UNKNOWN** | `migrations/versions/0020_business_event_history.py`; `source.business_event_history` |
| Identity mapping | `identity_mapping_history.effective_at` | **UNKNOWN** as a separate source-availability field; journal `recorded_at` is when platform recorded the decision | `recorded_at` | `source_batch_id` stored per mapping history row | Merge/split are appended mapping events; no generic `supersedes` pointer | Migration-0013 baseline / `identity_history_coverage.coverage_started_at`; no reconstruction before migration 0013 | `migrations/versions/0013_identity_mapping_history.py`, `0023_identity_history_coverage_marker.py`; `services/data/identity/registry.py` |
| Identity review decisions | `review_decision_history.occurred_at` (legacy audit backfill uses `performed_at`) | Database-assigned `available_at`; legacy availability starts only at migration-0022 backfill | Database-assigned `recorded_at` | Receiving/source batch retained from review queue | `supersedes_event_id` links correction/revocation chain | New journal availability begins at receipt; legacy exact first-availability before backfill is **UNKNOWN** | `migrations/versions/0022_identity_review_decision_history.py`; `services/data/identity/registry.py` |
| Consent | `consent_events.captured_at`; `expires_at` is expiry, not availability | **UNKNOWN**; CSV contract has no `available_at` | Table has `created_at` at ingestion, but it is not a source-availability timestamp | `source_batch_id` exists | No correction-lineage field; later consent rows do not identify which event they supersede | **UNKNOWN** for PIT availability and source history start | `services/data/ingestion/contracts.py`; `migrations/versions/0009_data_contracts_and_persistent_identity.py`; business policy owner is Christ |

### Scenario-to-test disposition

Status separates test presence from execution evidence. PostgreSQL cases added
on this branch remain unexecuted until a PostgreSQL CI run is available.

| Scenario | Test/evidence | Current disposition |
|---|---|---|
| J-A01/A02 | `test_postgres_transaction_event_bitemporal_correction`; J-A04 also `test_postgres_transaction_event_rejects_conflicting_replay_and_naive_time` | Implemented; previous merged CI evidence exists; rerun for this branch pending. |
| J-A03 | `test_postgres_customer360_snapshot_replay_is_immutable` checks replay immutability, not late-event end-to-end publication | Partial; explicit event-arrival-after-published-snapshot case remains missing. |
| J-B01/B02/B03 | `test_postgres_transaction_event_bitemporal_correction`, `test_postgres_transaction_event_rejects_conflicting_replay_and_naive_time` | Implemented; prior PR CI evidence, not rerun on this branch. |
| J-B04/B05 | `append_transaction_event()` checks transaction existence and PUBLISHED receipt batch; no dedicated isolated failure/no-partial-publication assertion for both cases | Partial; add PostgreSQL assertions if used as Gate C close evidence. |
| J-C01/C02 | `test_postgres_transaction_event_bitemporal_correction` | Implemented: origin/receipt batch separation, correction lineage and as-of visibility; prior PR #35 CI evidence. |
| J-C03/C05 | `test_postgres_ingestion_failure_rolls_back_and_retry_recovers`, `test_postgres_multi_batch_ingestion_isolated_and_idempotent` | Implemented for ingestion batches; prior CI evidence is tied to its tested head. |
| J-C04 | `test_postgres_concurrent_duplicate_batch_is_idempotent` covers same-batch concurrency; no concurrent duplicate transaction-event append test | Partial; event unique-key conflict behavior is implemented, concurrency acceptance remains missing. |
| J-D01/D02 | `test_postgres_transaction_event_bitemporal_correction`; `test_projection_sums_multiple_refunds_without_double_counting` | Implemented for observed event arithmetic; feed completeness is `MISSING`, so not label-ready. |
| J-D03/D04/D05/D06 | `test_correction_chain_replaces_original_refund_independent_of_input_order`, `test_late_correction_does_not_change_earlier_known_projection`, `test_postgres_transaction_event_bitemporal_correction`; new baseline-correction regression in `test_transaction_events.py` | Unit cases run locally; PostgreSQL baseline-correction case added in this branch and pending CI. Raw ledger rows remain append-only. |
| J-E01 | `test_postgres_customer360_uses_identity_mapping_as_of` | PostgreSQL merge/as-of test exists; prior CI evidence at earlier head. |
| J-E02 | `test_identity_split_as_of_preserves_prior_mapping_without_forcing_unknowns`; split assertion added to `test_postgres_customer360_uses_identity_mapping_as_of` | Unit case ran locally; new PostgreSQL profile split case is defined but unexecuted. |
| J-E03 | `test_postgres_identity_review_correction_and_revocation_are_as_of` and review correction assertion added to `test_postgres_customer360_uses_identity_mapping_as_of` | Decision ledger and profile consumer corrections have PostgreSQL test definitions; both new cases are unexecuted pending CI. Profile revocation consumer case remains missing. |
| J-E05 | `test_build_profiles_as_of_does_not_use_static_review_queue_status` | Unit regression exists; PostgreSQL profile test for a queue/decision created after the historical cutoff remains missing. |
| J-E04 | `test_migration_baseline_does_not_claim_pre_migration_identity_history`, `test_identity_coverage_marker_blocks_even_when_baseline_table_is_empty` | Unit-tested; migration marker PostgreSQL migration execution is in migration CI, but full consumer boundary needs additional evidence. |
| J-E06 / J-A03 | `test_postgres_customer360_snapshot_replay_is_immutable`; old-knowledge profile replay assertion added to `test_postgres_customer360_uses_identity_mapping_as_of` | Generic composite-key replay was previously covered; new test asserts old profile metadata/payload replay remains unchanged after later merge/split events. New assertion is unexecuted pending PostgreSQL CI. |
| J-F01 | `test_postgres_rejects_source_id_overlap_across_batches_atomically` | PostgreSQL test exists; prior CI evidence at earlier head. |
| J-F02/F03 | `test_postgres_multi_batch_ingestion_isolated_and_idempotent`, catalogue child batch foreign-key assertion | PostgreSQL coverage exists; current CI must be tied to exact run/commit before claiming complete. |
| J-F04 | `test_postgres_ingestion_failure_rolls_back_and_retry_recovers` | Batch recovery test exists; verify CI run for current branch before release claim. |

Latest locally-run focused tests on the current branch: **26 passed, 18
skipped**; skipped tests require `VTEKI_TEST_POSTGRES_URL`. The new PostgreSQL
tests therefore have no execution result yet.

### PIT query/replay example for Moses

This is a query shape for review, not customer data or a completeness claim.
Use identical cutoffs for feature inputs; old knowledge `K1` must not include
an event first received after `K1`.

```python
state_k1 = project_transaction_as_of(
    session,
    source_transaction_id=synthetic_test_transaction_id,
    effective_at=effective_cutoff,
    known_at=knowledge_cutoff_k1,
)
state_k2 = project_transaction_as_of(
    session,
    source_transaction_id=synthetic_test_transaction_id,
    effective_at=effective_cutoff,
    known_at=knowledge_cutoff_k2,
)

identity_k1 = registry.get_mapping_as_of_result(
    effective_at=effective_cutoff,
    recorded_at=knowledge_cutoff_k1,
)
profile_k1 = build_profiles_as_of(
    inbound_dir, resolution_dir, effective_cutoff, session,
    recorded_at=knowledge_cutoff_k1,
)
```

Review the returned `status`, `event_ids`, amounts, `source_coverage`, mapping
coverage status, and profile composite key. Expected safety properties: the
late event is absent at `K1`; it may appear at `K2`; `source_coverage` remains
`OBSERVED_EVENTS_ONLY`; profile replay at the same effective/knowledge cutoff
retains its original published payload and metadata. The current profile
builder is identity-aware only and is **not** a model feature source.

## 7. Gate tracker

| Gate | Current status | Required close evidence |
|---|---|---|
| Gate A — business | BLOCKED | Christ-approved versioned target/value/lifecycle/consent/outcome contracts with approver/date/examples |
| Gate B — CI/contracts | PASS for merged PRs, not business approval | Relevant implementation PR CI, unit/contract/security tests, no bypass |
| Gate C — historical | BLOCKED / IN PROGRESS | J-A through J-F relevant tests, source feed integration, final-state projection, identity-as-of verification, cross-team approval |
| Gate D — model review | NOT OPEN | Gates A–C closed; versioned label/feature proposal and explicit review |

## 8. What can be done while waiting

- James can implement the acceptance tests without changing business definitions.
- Moses can review schemas, manifests, and compatibility mappings; only report availability as `UNKNOWN` where unproven.
- Christ can resolve business boundary tables and provide worked examples.
- Moses can run existing synthetic diagnostics and regression tests as engineering checks only.
- The existing baseline, labels, and artifacts remain versioned references.

Do not do the following before Gates A–C:

- train a new ML estimator;
- make a new target/feature version based on assumptions;
- use raw correction/refund events as final transaction state;
- claim identity-as-of is complete before its coverage boundary is known;
- use `ground_truth` as matching/model input;
- select customers, send campaigns, or claim production performance.

## 9. Gate D review template

Complete only after Gate A–C evidence is attached.

```text
Approved churn contract: <version / approver / date>
Approved value contract: <version / approver / date>
Approved lifecycle/treatment contract: <version / approver / date>
Approved consent/outcome contracts: <versions / approvers / dates>
Historical contract: <version / status>
Earliest reliable identity-as-of: <time or UNKNOWN>
Earliest reliable event availability: <time or UNKNOWN>
Refund/status projection: <version / tests>
Multi-batch evidence: <CI URL / PostgreSQL test result>
Feature version proposal: <version>
Label version proposal: <version>
Baseline comparison plan: <link>
Leakage controls: <list>
Prohibited uses: <list>
Reviewers: <names>
Decision: training_ready=<false>; experiment_ready=<false>; final_model=<false>
Conditions before changing any flag: <list>
```

## 10. References

- `docs/james_platform/approved/historical_data_contract_v1.x.md`
- `docs/james_platform/STATUS_TUGAS_JAMES.md`
- `docs/TEAM_FOLLOW_UP_ACTIONS_2026-11-04.md`
- `docs/moses_data_ai/CROSS_TEAM_IMPLEMENTATION_GUIDE.md`
- `docs/moses_data_ai/sprint_gate_status_2026-11-14.md`
- `docs/moses_data_ai/model_card_development_v1.md`
- `docs/christ_business/approved/target_definitions.md`
- `services/data/ingestion/contracts.py`
- `services/data/ingestion/transaction_events.py`
- `services/data/identity/registry.py`
- `services/data/customer360/profile.py`
