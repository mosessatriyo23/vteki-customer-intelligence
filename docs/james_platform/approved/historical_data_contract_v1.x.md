# Historical Data Contract v1.7

**Status:** DRAFT — implementation changes require review; Gate C is not closed
**Owner:** James — Platform & Historical Data
**Approver:** Pending: Moses (point-in-time review), Christ (business value semantics, if applicable), and cross-team Gate C reviewers
**Approval date:** Not approved
**Updated:** 17 November 2026

## Changelog

| Version | Date | Change |
|---|---|---|
| 1.0 | 15 November 2026 | Initial event availability and provenance contract; explicitly draft. |
| 1.1 | 16 November 2026 | Separate transaction-origin and event-receipt batches; define projection/correction rules; persist visit and membership source events; make migration-0013 coverage boundary explicit; record outstanding evidence and source-feed gaps. |
| 1.2 | 16 November 2026 | Add worker job idempotency and cancellation contract; expand PostgreSQL overlap/master-data/snapshot tests, frontend workflow tests, populated-database migration verification, and deploy/recovery runbook. Approval remains pending. |
| 1.3 | 16 November 2026 | Prevent `build_profiles_as_of()` from deriving historical identity status from the static review queue; emit `UNKNOWN` until bitemporal review-decision history exists. |
| 1.4 | 16 November 2026 | Add append-only bitemporal identity review decision history with correction/revocation, as-of projection, independent identity coverage marker, PostgreSQL tie-order test, and role grants. |
| 1.5 | 17 November 2026 | Reconcile status statements with merged main, record latest merged acceptance CI, and make remaining verified/blocked conditions and snapshot readiness explicit. |
| 1.6 | 17 November 2026 | Add PostgreSQL acceptance coverage for review-decision correction/revocation as-of cutoffs; local PostgreSQL execution remains pending. |
| 1.7 | 17 November 2026 | Define replacement ordering for correction of a transaction baseline and preserve later refund/status effects; add unit and PostgreSQL regressions plus published-profile stability coverage. |

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

# Identity and review use the same effective and knowledge cutoffs.
identity = registry.get_mapping_as_of_result(
    effective_at=effective_cutoff,
    recorded_at=knowledge_cutoff,
)
profiles = build_profiles_as_of(
    inbound_dir,
    resolution_dir,
    effective_cutoff,
    session,
    recorded_at=knowledge_cutoff,
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
5. The replacement effect is replayed at the corrected root event's original logical position. The correction itself must still satisfy both cutoffs (`occurred_at <= effective_at`, `available_at <= known_at`). Later visible refund/status events are then replayed over the corrected base; a later correction to `TRANSACTION_RECORDED` must not erase those intervening events. A correction not yet visible at the requested cutoffs has no effect.
6. Projection is over **observed events only**. Since the source refund/status feeds are not integrated, the returned arithmetic is not proof of complete historical revenue and must not be used as a training label/feature.
7. Replaying an identical idempotency key and payload returns the original event. Reusing the key with different content is rejected. PostgreSQL uniqueness arbitrates concurrent insert races.

For independent PIT review, pass the same pair of cutoffs to every consumer:
`effective_at` bounds business occurrence; `known_at` (named `recorded_at` in
the identity mapping API) bounds platform knowledge. The identity result must
be `AVAILABLE`; `BLOCKED` or `UNKNOWN` must stop the build. A profile result
from `build_profiles_as_of()` remains an identity-aware utility only and is
not a training snapshot.

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
| Correction | Append a new event referencing the event it replaces. The replacement is applied at the root event's original logical position after the correction becomes visible; subsequent events are replayed over it. Corrections do not mutate old rows; correction branches are rejected. |
| Snapshot replay | Identical versioned payload is a no-op; a different payload under the same composite key is rejected by snapshot persistence. |

## 6. Identity history boundary

Migration 0013 creates a `BASELINE` at migration time. It does **not** reconstruct identity changes before migration 0013. New installations now set baseline `effective_at` to migration time. Reads also fence legacy migration-0013 baseline rows at their `recorded_at`, so their former `assigned_at` value cannot imply unsupported pre-migration coverage.

`get_mapping_as_of_result()` reports:

- `AVAILABLE`: mapping rows exist within coverage;
- `BLOCKED`: requested effective cutoff predates known history coverage;
- `UNKNOWN`: no usable mapping history exists at the requested cutoff.

`get_mapping_as_of()` raises `IdentityHistoryCoverageError` for a blocked cutoff. Unresolved sources are not assigned a fabricated Golden ID. Current `review_queue` is not an as-of review history; it must not be used to claim historical review status. Review status comes from the bitemporal decision journal described below.

Migration 0023 persists `identity.identity_history_coverage` independently of
the number of baseline rows. If migration 0013 found no mappings, coverage
begins at migration 0023 time; an empty baseline is not treated as evidence of
complete earlier history. A knowledge cutoff before the coverage marker was
recorded returns `UNKNOWN`; an effective cutoff before coverage returns
`BLOCKED`.

Migration 0013 records the mapping baseline at migration time only. It does
not reconstruct identity changes before migration 0013.

Migration 0022 adds `identity.review_decision_history`. New decisions carry
`occurred_at`, database-assigned `available_at` and `recorded_at`,
`source_event_id`, `source_version`, receiving `source_batch_id`, an
idempotency key, reviewer, correlation, and rationale. Existing audit decisions
are backfilled using their actual `performed_at`; availability starts at the
backfill migration because earlier availability is unknown.

Corrections append a new event linked to the current chain head; revocations
append a null-action event. Corrections that predate the decision they revise,
forks, and conflicting retries are rejected. The as-of query applies only
events satisfying `occurred_at <= effective_at` and both receipt timestamps
`<= known_at`. It does not read mutable `review_queue.status` or the static CSV.
An approved merge is reported as `APPROVED` only when the as-of mapping also
shows the reviewed identities in one Golden ID; otherwise the profile is
`UNKNOWN`. A rejected decision is `REJECTED` only while the identities remain
separate. The decision journal does not itself rewrite identity mappings:
corrections that alter a merge/split must also append the corresponding
`identity_mapping_history` events through the reviewed mapping workflow.

`build_profiles_as_of()` now derives identity status from that bitemporal
decision journal. Status stays `UNKNOWN` where no suitable decision history
exists; it never imports the current review queue state retroactively.

## 7. Customer 360 scope

`build_profiles_as_of()` is a **limited identity-aware profile utility**, not the official historical feature/training source. Only its identity mapping lookup is bitemporal. It still reads inbound transaction, visit, and membership snapshots; these inputs do not all satisfy:

```text
effective_at <= feature_cutoff
available_at <= known_at
```

The function therefore does not guarantee historical refund/status values or completeness of inbound sources. The non-as-of `build_profiles()` path reads the static review queue for current development status. The as-of path uses bitemporal review decisions when suitable history exists and emits `UNKNOWN` otherwise. It is not an official historical feature/training source: immutable snapshot publication with registry/rule versions, source batch, `known_at`, checksum, and complete point-in-time inputs is not implemented. Until a reviewed official snapshot contract exists: `training_ready=false`, `experiment_ready=false`, `final_model=false`.

## 8. Acceptance test matrix

Implemented test coverage in the follow-up:

- Pure projection: transaction + partial/multiple refunds; correction chain; correction fork rejection; status ordering with equal availability; replay order independence; late correction excluded at earlier `known_at`; correction to the transaction baseline preserves refunds/status events between the original baseline and correction.
- PostgreSQL test definitions: event from transaction batch A received in B and corrected/status-changed in C; origin/receipt batch lineage; late-event visibility; idempotent retry; conflicting idempotency payload; correction chain; status before/after effective cutoff; visit/membership source provenance and as-of visibility; only PUBLISHED business-event batches are readable; source-ID overlap and master-data update rejection; snapshot replay immutability; unique worker idempotency key.
- Identity unit test: migration baseline is BLOCKED before coverage and available from migration time.
- Identity review unit tests: decision as-of, late correction visibility, linear correction/revocation, idempotent retry, correction/mapping consistency, and coverage marker behavior when baseline rows are empty.
- PostgreSQL acceptance: identity review receipt timestamp cannot be backdated, history rejects update/delete, and transaction event ordering is deterministic when database availability timestamps tie. The current task branch adds review correction/revocation as-of coverage, baseline-correction-after-refund/status coverage, and old-profile replay stability; these new PostgreSQL cases have not yet run because no test PostgreSQL URL is configured.
- Customer360 regression: changing the static review queue cannot make
  `build_profiles_as_of()` claim historical `REVIEW_REQUIRED`; status is
  `UNKNOWN` until review history is available.
- Worker unit tests: retry/backoff, hard timeout, child-process cancellation, stale claim fencing, and recovery of a cancelled job.
- Frontend E2E definitions: campaign approval followed by audit trace reconstruction, plus identity review creation/decision. Existing cases cover login, role-gated navigation, and NBA override.
- A PostgreSQL migration-upgrade fixture starts from revision 0014 with populated transaction, visit, and membership tables, upgrades to head, and checks event lineage and preserved occurrence times.

PR #36 acceptance CI at commit `1082182c738283973ff11f9cf2f564b180d4ada2`
passed backend/quality, frontend build, and frontend RBAC E2E jobs in
[run 44051345769](https://github.com/mosessatriyo23/vteki-customer-intelligence/actions/runs/44051345769).
The tests added by PR #36 validate event effective/knowledge boundaries,
idempotency conflict rejection, and timezone-aware inputs. These checks ran on
the PR head before merge; they do not prove external refund/status feed
completeness, production operation, or cross-team approval. Earlier runs cited
in the history below validate earlier commits only.

Still required before Gate C:

- Review-decision correction/revocation has unit coverage and a new PostgreSQL
  as-of acceptance test on `james/gate-c-p0-finalize`; the test has not run
  locally because `VTEKI_TEST_POSTGRES_URL` is unset. CI execution is pending.
- Integrate actual refund/status/cancellation/correction source feeds and
  prove coverage completeness. Do not synthesize missing events.
- Extend identity tests for unresolved state and merge/split stability of
  published snapshots. The branch adds an unresolved-profile unit test and a
  PostgreSQL old-knowledge profile replay assertion; full PostgreSQL merge/split
  correction coverage remains pending.
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
| Follow-up implementation PR | [PR #35](https://github.com/mosessatriyo23/vteki-customer-intelligence/pull/35), merged. It does not represent cross-team approval. |
| Latest relevant merged acceptance PR | [PR #36](https://github.com/mosessatriyo23/vteki-customer-intelligence/pull/36), commit `1082182c738283973ff11f9cf2f564b180d4ada2`; PR #37 subsequently fixed migration query qualification. Both are included in main at `5da8c02`. |
| PR #36 CI | [Workflow run 44051345769](https://github.com/mosessatriyo23/vteki-customer-intelligence/actions/runs/44051345769): backend/quality, frontend production build, and frontend RBAC E2E passed. |
| PR #37 migration-fix CI | [Workflow run 43822247224](https://github.com/mosessatriyo23/vteki-customer-intelligence/actions/runs/43822247224): backend/quality, frontend production build, and frontend RBAC E2E passed for migration query qualification. |
| Earlier PostgreSQL acceptance | PR #35 [run 43747326104](https://github.com/mosessatriyo23/vteki-customer-intelligence/actions/runs/43747326104) ran 11 tests at that earlier migration head; it does not validate migrations 0022/0023 or the current complete test tree. |
| Earlier local full suite | Historical result on the preceding implementation branch: 852 passed, 0 skipped against disposable PostgreSQL 15. Not verification of current `main` or this update. |
| Earlier local PostgreSQL acceptance | Historical result: `tests/integration/test_postgres_platform.py` 15 passed; not verification of current `main` or this update. |
| Earlier local patch checks | Historical result: focused tests 13 passed; Ruff, Black, and MyPy for `services/data/customer360` passed. |
| Ruff / Black / MyPy / Alembic | Earlier local results are historical; verify current head before making a release claim. Alembic head is `0023_identity_history_coverage_marker`. |
| James | Owner; implementation is on main. This contract remains DRAFT. |
| Moses | Point-in-time review pending. |
| Christ | Business-value review pending if definitions affect targets. |
| Cross-team Gate C | Pending. |

Approval date remains **not approved**. The `approved/` directory name is not approval evidence.

The repository main branch contains the v1.4 implementation and subsequent PR
#36 acceptance tests and PR #37 migration fix. The current task branch is based
on main commit `5da8c02`; linked CI is existing merged-PR evidence and does not
run against this update. Local relevant tests on the task branch: 26 passed
and 18 PostgreSQL tests skipped because `VTEKI_TEST_POSTGRES_URL` is unset;
Ruff lint and format checks passed for changed Python files. PostgreSQL execution
and CI for a PR containing this update remain pending.

The CI evidence listed above does not close
remaining feed-coverage, historical identity, official-snapshot, production
operations, or approval gaps. See
[James deploy and recovery runbook](../RUNBOOK_GATE_C.md).

## 10. Training and ground-truth safeguards

Until P0 tests, source-feed validation, and cross-team approval are complete, Moses must not publish new labels/features, train a new model, open campaigns, or enable production scoring from these projections. Synthetic ground truth remains prohibited as matching input, feature, label, and training data.
