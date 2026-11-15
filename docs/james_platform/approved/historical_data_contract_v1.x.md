# Historical Data Contract v1.2

**Status:** DRAFT — implementation changes require review; Gate C is not closed
**Owner:** James — Platform & Historical Data
**Approver:** Pending: Moses (point-in-time review), Christ (business value semantics, if applicable), and cross-team Gate C reviewers
**Approval date:** Not approved
**Updated:** 16 November 2026

## Changelog

| Version | Date | Change |
|---|---|---|
| 1.0 | 15 November 2026 | Initial event availability and provenance contract; explicitly draft. |
| 1.1 | 16 November 2026 | Separate transaction-origin and event-receipt batches; define projection/correction rules; persist visit and membership source events; make migration-0013 coverage boundary explicit; record outstanding evidence and source-feed gaps. |
| 1.2 | 16 November 2026 | Add worker job idempotency and cancellation contract; expand PostgreSQL overlap/master-data/snapshot tests, frontend workflow tests, populated-database migration verification, and deploy/recovery runbook. Approval remains pending. |

## 1. Time and provenance

All event times are timezone-aware:

| Field | Meaning |
|---|---|
| `occurred_at` | Source-observed business occurrence time. Never inferred from ingestion time. |
| `available_at` | Time the platform first accepted the event; assigned by PostgreSQL. |
| `recorded_at` | Database recording time; assigned by PostgreSQL. |

New source events require `source_event_id`, `source_version`, `source_batch_id`, and `idempotency_key`. `source_batch_id` identifies the receiving/publishing batch. Transaction events also store `source_transaction_batch_id`, the immutable batch containing the original transaction. Corrections point to the event they replace. Membership renewal events retain their source `previous_event_id`; completed visits retain their source transaction ID as lineage.

The membership/visit `source_version` is the input contract/schema version recorded on the ingestion batch. It is not a claim that the source supplied an event revision number. Transaction event callers must supply the actual source event ID and version; missing values are rejected rather than fabricated.

## 2. Source coverage

| Event family | Available source / behavior | Historical limitation |
|---|---|---|
| Transaction recorded | Existing transaction batch; loader writes an immutable baseline event. | A baseline reflects the transaction record available at ingestion; it does not reconstruct subsequent refund/status changes. If the feed lacks a separate source event ID/version, the legacy baseline leaves those provenance fields missing rather than inventing them. |
| Refund / partial refund | Event append API accepts `REFUND_RECORDED`. | No source refund feed/connector is present in this repository. A missing feed is **MISSING**, not a zero refund or an inferred timestamp. |
| Status change / cancellation | Event append API accepts `STATUS_CHANGED`; cancellation is represented by status `CANCELLED` or `REFUNDED`. | No source status-change feed/connector is present. The current transaction row is not a status history. |
| Correction | Append-only `CORRECTION` event references a prior event. | Corrections must form one chain; correction forks are rejected by projection. |
| Completed visit | `customer_visits.csv` source rows are copied to `source.business_event_history`; `visit_datetime` is the occurrence time and `visit_id` is the source event ID. | Existing history is backfilled when this ledger is first installed; `available_at` then means first captured by this ledger, not original feed arrival. |
| Membership join / renewal | `membership_events.csv` rows are copied to `source.business_event_history`; `occurred_at`, `event_id`, and `previous_event_id` are source-provided. | Same first-capture limitation as visits. Renewal may be used for churn only after point-in-time review. |

The visit/membership backfill preserves source occurrence times and uses database time for first availability/recording. It does not claim that those events were known to the platform at their historical occurrence.

## 3. As-of visibility and deterministic ordering

An event can participate only when:

```text
occurred_at <= effective_at
available_at <= known_at
receiving batch is PUBLISHED
transaction-origin batch is PUBLISHED (transaction events)
```

Queries order by `occurred_at`, `available_at`, `recorded_at`, then database event ID. The final ID tie-break makes events with equal availability deterministic. As-known queries exclude a late event when its `available_at` is after `known_at`; the old cutoff is not recomputed using later knowledge.

Example transaction query and idempotent replay:

```python
state = project_transaction_as_of(
    session,
    source_transaction_id="source-tx-id",
    effective_at=effective_cutoff,
    known_at=knowledge_cutoff,
)

# Retry only with the same source identity, version, batch, and payload.
event = append_transaction_event(
    session,
    source_transaction_id="source-tx-id",
    event_type="REFUND_RECORDED",
    occurred_at=source_refund_time,
    source_batch_id="published-receiving-batch",
    idempotency_key="source:refund-id:version",
    payload={"refund_amount": 100},
    actor_type="SOURCE",
    source_event_id="refund-id",
    source_version="source-revision",
)
```

`source_refund_time` must come from the source event. If the source did not
provide it, the event cannot be represented as historically occurred; do not
substitute receipt time.

## 4. Transaction final-state projection

`project_transaction_as_of()` projects the visible append-only event set for an `effective_at` and `known_at`. It returns status, gross, discount, cumulative refund, net amount, actual revenue, cancellation flag, contributing event IDs, and `source_coverage="OBSERVED_EVENTS_ONLY"`.

Rules:

1. `TRANSACTION_RECORDED` establishes the amount/status baseline. Amounts are non-negative integer IDR; `net_amount` must equal `gross_amount - discount_amount`.
2. `REFUND_RECORDED.refund_amount` is a positive integer increment. Multiple visible refunds add; cumulative refund cannot exceed net amount.
3. `STATUS_CHANGED.status` is the latest visible status in deterministic event order. `CANCELLED` and `REFUNDED` have zero actual revenue; otherwise actual revenue is `net_amount - refund_amount`.
4. A correction replaces the effect of its referenced event; it is not an additional refund or status update. A correction of a correction replaces the same root effect. A correction must reference an event for the same transaction. Each event may have at most one visible correcting child; forks are invalid.
5. An event superseded by a visible correction is excluded from financial/status application. A correction not yet visible at the requested cutoffs has no effect.
6. Projection is over **observed events only**. Since the source refund/status feeds are not integrated, the returned arithmetic is not proof of complete historical revenue and must not be used as a training label/feature.
7. Replaying an identical idempotency key and payload returns the original event. Reusing the key with different content is rejected. PostgreSQL uniqueness arbitrates concurrent insert races.

## 5. Batch and correction decision table

| Case | Contract decision |
|---|---|
| Exact duplicate batch and identical manifest checksums | Return `ALREADY_LOADED`; do not rewrite batch or event publication metadata. |
| Same batch ID but changed checksums or incomplete prior batch | Reject and require manual investigation. |
| Overlapping source primary key in a different batch | Reject atomically; source IDs are globally unique in the current source tables. Do not silently overwrite master/source rows. |
| Same source event ID and version retried with same idempotency key | Resolve to the original event without adding another financial/status effect. |
| Same idempotency key with changed event payload or provenance | Reject; do not mutate the original event. |
| Event for a transaction from a later receiving batch | Keep original `source_transaction_batch_id`; set `source_batch_id` to the new receiving batch. Both batches must be published before as-of query returns it. |
| Late event | Preserve the source `occurred_at`; set availability/recording to database receipt time. Earlier `known_at` excludes it. |
| Master-data update | Current loader treats shared branch data as immutable and validates equality. Versioned catalogue references use `(item_code, source_batch_id)`; a child uses the catalogue version from its own batch. |
| Retry / concurrency | Per-batch advisory lock plus checksum lookup; event idempotency uses a database unique key and atomic conflict handling. |
| Worker job retry | Use an optional stable `idempotency_key`; identical kind/payload/attempt limit returns the existing job, while changed content with that key is rejected. |
| Worker cancellation | Queued jobs become `cancelled`; running jobs become `cancel_requested`, then the worker terminates its handler process and records `cancelled`. Cancellation cannot reverse an external side effect already completed; handlers must be retry-safe/idempotent. |
| Partial failure | Ingestion writes raw, typed, event, and publish state in one database transaction. Any failure rolls the transaction back; a failed batch must not appear PUBLISHED. |
| Recovery | Retry an uncommitted identical batch. A persisted non-PUBLISHED batch is an investigation blocker, not an automatic success-shaped retry. |
| Publish order | Each batch publishes atomically after its rows and event history are written. No global ordering between independent batches is implied. |
| Correction | Append a new event referencing the event it replaces. Corrections do not mutate old rows; correction branches are rejected. |
| Snapshot replay | Identical versioned payload is a no-op; a different payload under the same composite key is rejected by snapshot persistence. |

## 6. Identity history boundary

Migration 0013 creates a `BASELINE` at migration time. It does **not** reconstruct identity changes before migration 0013. New installations now set baseline `effective_at` to migration time. Reads also fence legacy migration-0013 baseline rows at their `recorded_at`, so their former `assigned_at` value cannot imply unsupported pre-migration coverage.

`get_mapping_as_of_result()` reports:

- `AVAILABLE`: mapping rows exist within coverage;
- `BLOCKED`: requested effective cutoff predates known history coverage;
- `UNKNOWN`: no usable mapping history exists at the requested cutoff.

`get_mapping_as_of()` raises `IdentityHistoryCoverageError` for a blocked cutoff. Unresolved sources are not assigned a fabricated Golden ID. Current `review_queue` is not an as-of review history; it must not be used to claim historical review status.

## 7. Customer 360 scope

`build_profiles_as_of()` is a **limited identity-aware profile utility**, not the official historical feature/training source. Only its identity mapping lookup is bitemporal. It still reads inbound transaction, visit, membership, and review-queue snapshots; these inputs do not all satisfy:

```text
effective_at <= feature_cutoff
available_at <= known_at
```

The function therefore does not guarantee historical refund, status, or review state. Official historical snapshots still need registry/rule versions, source batch, `known_at`, checksum, immutable publication semantics, and acceptance tests. Until then: `training_ready=false`, `experiment_ready=false`, `final_model=false`.

## 8. Acceptance test matrix

Implemented test coverage in the follow-up:

- Pure projection: transaction + partial/multiple refunds; correction chain; correction fork rejection; status ordering with equal availability; replay order independence; late correction excluded at earlier `known_at`.
- PostgreSQL test definitions: event from transaction batch A received in B and corrected/status-changed in C; origin/receipt batch lineage; late-event visibility; idempotent retry; conflicting idempotency payload; correction chain; status before/after effective cutoff; visit/membership source provenance and as-of visibility; only PUBLISHED business-event batches are readable; source-ID overlap and master-data update rejection; snapshot replay immutability; unique worker idempotency key.
- Identity unit test: migration baseline is BLOCKED before coverage and available from migration time.
- Worker unit tests: retry/backoff, hard timeout, child-process cancellation, stale claim fencing, and recovery of a cancelled job.
- Frontend E2E definitions: campaign approval followed by audit trace reconstruction, plus identity review creation/decision. Existing cases cover login, role-gated navigation, and NBA override.
- A PostgreSQL migration-upgrade fixture starts from revision 0014 with populated transaction, visit, and membership tables, upgrades to head, and checks event lineage and preserved occurrence times.

The preceding PostgreSQL CI run migrated through 0020 and passed all 11
`test_postgres_platform.py` tests. The new PostgreSQL tests and populated
migration-upgrade fixture are awaiting CI on the follow-up commit; local
PostgreSQL/Docker is unavailable, so their results must not be inferred from
the preceding run.

Still required before Gate C:

- Test equal database `available_at` values in PostgreSQL; current tie-order
  acceptance is covered by the pure deterministic projection test.
- Integrate actual refund/status/cancellation/correction source feeds and
  prove coverage completeness. Do not synthesize missing events.
- Extend identity tests for review-required history, corrected/revoked
  decisions, unresolved state, and merge/split stability of published
  snapshots.
- Publish immutable snapshot checksums/`known_at` and complete all feature
  inputs only if/when an official historical training snapshot is approved.
- Build official end-to-end feature snapshots or keep the current utility
  out of Moses training.
- Record Moses/Christ/cross-team semantic review and explicit approval.

Platform follow-up still requires production-like worker/advisory-lock/load
testing, audit trace benchmark at representative volume, and restore drill.
Physical table partitioning remains a data-volume/retention decision and is
not implemented without an approved design.

## 9. Evidence and approval

| Evidence / review | Status |
|---|---|
| PR #33 merge and its CI | Reported by reviewer; historical PR reference: [PR #33](https://github.com/mosessatriyo23/vteki-customer-intelligence/pull/33). It does not validate this follow-up change. |
| Follow-up implementation PR | [PR #35](https://github.com/mosessatriyo23/vteki-customer-intelligence/pull/35), draft, commit `3ccbc666aaaae04e03ac03a150d72981d579e2bd`. |
| Follow-up CI | [Workflow run 43747326104](https://github.com/mosessatriyo23/vteki-customer-intelligence/actions/runs/43747326104): all jobs passed. |
| PostgreSQL acceptance result | [PostgreSQL CI job](https://github.com/mosessatriyo23/vteki-customer-intelligence/actions/runs/43747326104/job/132913394806): migrations succeeded and all 11 `test_postgres_platform.py` tests passed. |
| Local full test suite | 831 passed; 11 PostgreSQL tests skipped locally because no PostgreSQL URL/service was available. |
| Ruff / Black / MyPy / Alembic | Ruff passed after import sorting; Black check passed for 90 Python files; MyPy passed for 88 source files; Alembic has one head, `0020_business_event_history`. |
| James | Draft owner; implementation submitted for review in PR #35. |
| Moses | Point-in-time review pending. |
| Christ | Business-value review pending if definitions affect targets. |
| Cross-team Gate C | Pending. |

Approval date remains **not approved**. The `approved/` directory name is not approval evidence.

The next follow-up commit adds migration 0021 and more acceptance tests.
Its CI result must be linked here only after the actual run completes.
See [James deploy and recovery runbook](../RUNBOOK_GATE_C.md).

## 10. Training and ground-truth safeguards

Until P0 tests, source-feed validation, and cross-team approval are complete, Moses must not publish new labels/features, train a new model, open campaigns, or enable production scoring from these projections. Synthetic ground truth remains prohibited as matching input, feature, label, and training data.
