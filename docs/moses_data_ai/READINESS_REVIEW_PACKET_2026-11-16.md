# Readiness review packet — Moses / James / Christ

**Tanggal:** 2026-11-16

**Status:** Persiapan review; bukan approval dan bukan pembukaan training

**Pemilik:** Moses

**Tujuan:** Mempercepat verifikasi Gate A–C dengan satu paket evidence yang dapat ditinjau lintas tim.

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
| Identity as-of | `get_mapping_as_of()` and `build_profiles_as_of()` | James | PARTIAL | pre-baseline scope, split/unresolved/review-as-of tests |
| Review status as-of | current static `review_queue.csv` used by profile builder | James/Moses | BLOCKED | bitemporal review decision history |
| Multi-batch transaction lineage | batch IDs and transaction event baseline | James | PARTIAL | cross-batch event, overlap, retry, rollback tests |
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
| J-D03 | Correction of refund | Projection changes only according to deterministic correction rule |
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
| J-E06 | Replay same profile composite key/payload | No metadata replacement |

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

James and Moses should fill the following table from actual source/platform evidence. `UNKNOWN` is a valid answer; it must not be replaced with an assumption.

| Dataset/event | Occurred field | Available field | Recorded field | Source batch | Correction lineage | Earliest reliable time | Evidence/link |
|---|---|---|---|---|---|---|---|
| Transactions | `transaction_datetime` | UNKNOWN for old CSV / platform event for new records | platform event | yes | partial | UNKNOWN | pending |
| Refunds | UNKNOWN/source feed pending | UNKNOWN | platform event | pending | pending | UNKNOWN | pending |
| Status changes | `status` snapshot only | UNKNOWN | platform event | pending | pending | UNKNOWN | pending |
| Completed visits | `visit_datetime` | UNKNOWN | UNKNOWN | pending | no current lineage | UNKNOWN | pending |
| Membership renewals | `occurred_at` | UNKNOWN | UNKNOWN | pending | `previous_event_id` source relation | UNKNOWN | pending |
| Identity mapping | effective history partial | `recorded_at` partial | `recorded_at` | batch | decision history partial | migration baseline | pending |
| Review decisions | current queue only | UNKNOWN | UNKNOWN | pending | pending | UNKNOWN | pending |
| Consent | `captured_at`/`expires_at` | UNKNOWN | UNKNOWN | pending | pending | UNKNOWN | pending |

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
