# Gate A–C Closure Plan and Team Prompts

**Date:** 17 November 2026 · **Author:** Moses (PM-style audit, data/AI). **Checkout audited:** `main` `5da8c02` (PR #35–#39 merged).
**Purpose:** give James and Christ a single, project-aligned worklist with acceptance criteria, plus ready-to-send prompts, so Gate A (business) and Gate C (historical/platform) can close and Gate D (model review) can open.

```text
training_ready=false
experiment_ready=false
final_model=false
Gate A=BLOCKED   Gate B=PASS (merged PRs only)   Gate C=BLOCKED/IN PROGRESS   Gate D=NOT OPEN
```

This plan does not approve anything by itself. It does not start training, create a campaign, or select customers. Gate definitions are owned by `docs/TEAM_FOLLOW_UP_ACTIONS_2026-11-04.md` §4; this document operationalizes them against the current codebase.

---

## 1. Why this document exists

A PM-style audit of `main` `5da8c02` found:

- Gate A (Christ) is blocked by seven unresolved business decisions plus outcome/KPI sign-off, one self-contradiction inside `Requirement_Capstone`, and a missing formal sign-off (approver + date) on `target_definitions.md` v1.2.
- Gate C (James) is blocked by incomplete source feed coverage, an unofficial point-in-time feature source, and a DRAFT historical contract without cross-team approval.
- Gate B (CI) passes for merged PRs, which is necessary but not sufficient — it is not business or historical-completeness approval.
- Gate D cannot open until A and C close and a joint review happens.

The two sections below are standalone prompts: paste each into a session with the respective owner (James or Christ) to drive the remaining work to completion, aligned with `Requirement_Capstone` and the existing gate framework.

---

## 2. Shared acceptance rules (apply to both owners)

1. **No silent decisions.** If `Requirement_Capstone` or `target_definitions.md` is ambiguous or self-contradictory, write down the ambiguity and the chosen resolution with a reason; do not resolve silently in code or by picking one reading without a note.
2. **Versioned, not overwritten.** Any change to a label, feature, contract, or business rule gets a new version identifier. Existing merged baselines, labels, and artifacts stay intact.
3. **Evidence over narrative.** Each deliverable below needs runnable tests or a reviewable document with explicit examples — not a status claim alone.
4. **CI green is necessary, not sufficient.** A merged PR with green CI closes an engineering task. It does not by itself close Gate A, Gate C, or grant business/production approval.
5. **No synthetic data pretending to be real.** All data remains 100% synthetic academic data per `Requirement_Capstone` cover page; do not claim real customer evidence.
6. **No `ground_truth` as input.** Matching, features, labels, and models must never read `generator/ground_truth/`.
7. **Stay inside scope.** Neither owner should modify Moses's model/label/feature code to "unblock" themselves; flag the dependency back to Moses instead.

---

## 3. Prompt for James — close Gate C (historical/platform)

> Paste this whole section into a session with James.

**Context:** You are James, owner of the historical data platform (identity, transaction/event history, multi-batch ingestion) for the VTEKI Customer & Revenue Intelligence capstone. Gate C ("historical data contract") in `docs/TEAM_FOLLOW_UP_ACTIONS_2026-11-04.md` §4 is still open. Your own contract at `docs/james_platform/approved/historical_data_contract_v1.x.md` is explicitly `DRAFT`. The current codebase (`main` after PR #35, #37, #39, #36) has real progress — bitemporal event history, identity-as-of, a transaction projection, and PostgreSQL acceptance tests — but five concrete gaps remain before Moses can treat any of it as an approved point-in-time (PIT) training source. Work through them in order; each has required acceptance evidence. Do not claim Gate C closed until all five are done and reviewed.

**Required deliverables:**

1. **Source completeness inventory.** Fill in `docs/moses_data_ai/READINESS_REVIEW_PACKET_2026-11-16.md` §6 ("Data coverage inventory") with real evidence per dataset (transactions, refunds, status changes, completed visits, membership renewals, identity mapping, review decisions, consent): occurred field, available field, recorded field, source batch, correction lineage, earliest reliable time. Where unknown, write `UNKNOWN` — never invent a value. Acceptance: the table has no empty cells; every `UNKNOWN`/`MISSING` is a deliberate, defensible answer.
2. **Integrate or explicitly fence the refund/status/cancellation feed.** Connect a traceable synthetic source feed for refunds, status changes, and cancellations with source IDs/revisions, `occurred_at`, platform receipt semantics, and correction lineage. If the source cannot supply historical availability, retain `OBSERVED_EVENTS_ONLY`, explain the reliable coverage start, and mark that scope BLOCKED for new PIT training. Fencing is honest partial completion, **not** closure of Gate C; do not fabricate historical timestamps or introduce real customer data. Acceptance: map scenarios J-C01–J-C05 and J-D01–J-D06 in the readiness packet §4 to PostgreSQL tests, results and residual gaps. Add a regression for correcting `TRANSACTION_RECORDED` after intervening refund/status events: replacement must not silently reset away those effects; define correction ordering explicitly.
3. **Finish identity-as-of at the consumer boundary.** Cover merge/split reversal, unresolved identity, and review-decision correction end-to-end against `get_mapping_as_of()` and `build_profiles_as_of()`. Acceptance: scenarios J-E01–J-E06 (readiness packet §4) pass in the PostgreSQL CI job, and a published old profile is proven unchanged after a later correction (J-E06 / J-A03).
4. **Decide the fate of `build_profiles_as_of()`.** Either (a) explicitly keep it labeled as a limited identity-only utility not suitable for training features — update `docs/james_platform/STATUS_TUGAS_JAMES.md` and the contract to say so clearly — or (b) extend it to read from your ledger (`project_transaction_as_of`, `get_business_events_as_of`) with `known_at` governance, checksum, and immutable publication, with leakage tests. Pick one and make the documentation and code consistent; do not leave it ambiguous.
5. **Reconcile multi-batch J-C/J-F coverage and update the historical contract.** Map the written origin/receipt-batch, overlap, catalogue-version, idempotency, concurrency, rollback and retry rules to tests J-C01–J-C05 and J-F01–J-F04; identify uncovered scenarios without calling them already complete. Reconcile `docs/james_platform/approved/historical_data_contract_v1.x.md` (currently mixes stale version numbers, stale migration references, and stale "CI pending" language against the real merged state). Then request explicit review from Moses (PIT/feature fitness) and Christ (business meaning of refund/correction/availability where it affects targets), and record actual reviewer name + date only after each reviewer responds. A document living in an `approved/` folder is not itself an approval.

**Do not count these five deliverables as done from CI alone.** James should give Moses a scenario-to-test matrix, dataset-coverage matrix and example query output showing `effective_at` and `known_at` cutoffs for independent PIT review.

**Also fix, lower priority but tracked:**
- Refresh `docs/james_platform/RUNBOOK_GATE_C.md`, which still references migration `0021` though the head is now `0023`.
- Separately schedule (do not block Gate C on) the production NFR workstream: worker load test under real PostgreSQL, audit-trace SLA benchmark with pagination/truncation, restore drill, and runtime least-privilege account separation. These are real but distinct from historical-data correctness.

**Explicitly out of scope for you:** business definitions of churn, CLV, lifecycle, consent policy, and EV parameters belong to Christ. If your work exposes a gap there (e.g., "refund_amount delta vs cumulative" or "does `available_at` affect label eligibility"), write the question down and route it to Christ; do not decide it yourself.

**When you believe Gate C is ready to close:** open a PR with scenario-to-test evidence and your own author/reviewer disposition, request Moses and Christ review, and leave their names/dates PENDING until they actually approve. If source completeness or approved historical availability remains missing, report Gate C BLOCKED rather than interpreting a merged PR as closure. Do not describe Gate C as closed until its acceptance criteria and cross-team approvals are actually met.

---

## 4. Prompt for Christ — close Gate A (business contract)

> Paste this whole section into a session with Christ.

**Context:** You are Christ, owner of business definitions and decisioning policy for the VTEKI Customer & Revenue Intelligence capstone. Gate A ("business contract") in `docs/TEAM_FOLLOW_UP_ACTIONS_2026-11-04.md` §4 requires your target/value/lifecycle/consent/outcome definitions to be `APPROVED`, with a named approver, date, version, change log, and no unresolved contradictions. Your document `docs/christ_business/approved/target_definitions.md` is at `v1.2 — REVISI`; it says so itself, and the approver/date fields are still unfilled placeholders. The source requirement, `Requirement_Capstone.md`, also contains one direct self-contradiction that only you (with mentor/dosen confirmation) can resolve. Work through the seven items below; each needs a specific, example-backed answer, not a general statement.

**Required decisions, each with a worked example (positive, negative, and boundary case):**

1. **Resolve the churn horizon contradiction.** `Requirement_Capstone` Bab 2 states churn outcome is observed over **180 days forward**, but the same chapter sets the **prediction horizon at 90 days**. Confirm with your mentor/dosen which governs the actual label, and update both the requirement reading and `target_definitions.md` §1 accordingly. Also define the measurable "active cohort" at `prediction_date` precisely (current implementation: ≥1 qualifying purchase in the prior 365 days — confirm or revise).
2. **Lifecycle completeness.** Approve or reject the two implementation-proposed stages `OCCASIONAL` and `NEVER_TRANSACTED`. Resolve the `AT_RISK`/`DORMANT` membership-condition gap (customers who meet the recency window but not the membership condition currently fall through). Resolve the WIN_BACK window contradiction: Bab 1 lifecycle says Dormant = 181–365 days, Bab 4 action catalogue's WIN_BACK example says 91–180 days. Assign a treatment to `CHURNED`, `REACTIVATED`, `OCCASIONAL`, and `NEVER_TRANSACTED` (currently "Belum ditetapkan" / default `NO_ACTION`).
3. **CLV gross source and retention method.** Approve the exact source-field formula for 12-month gross revenue (which statuses count, how refunds/discounts/corrections are treated, rolling 365 days vs calendar 12 months). Approve or replace the retention-factor estimation approach — the old unsourced default of 0.7 has already been withdrawn; do not silently reinstate it or let it be inferred as `1 - churn90`. Moses will implement the estimation technique; you approve the business semantics and worked numeric example.
4. **EV parameters.** Ratify (or revise) the already-recorded v1.2 team decisions: `min_ev_threshold = Rp 1.000`, global discount cap 30%, and per-band caps. Separately approve or recalibrate the action weights, incentive cost percentages, and CLV-to-revenue proxy values currently hardcoded in `services/decision/nba/ev_calculator.py` and `catalogue.py` — these are engineering placeholders representing your policy, not numbers mandated by `Requirement_Capstone` itself.
5. **Action catalogue reconciliation.** The code and your own `target_definitions.md` §3.1 disagree with each other and with `Requirement_Capstone` in several places — for example: `RELATIONSHIP_MANAGER_CONTACT` lifecycle restriction, `RETENTION_OUTREACH` risk-band inclusion (HIGH vs HIGH+VERY_HIGH), and whether `CROSS_SELL`/`UPSELL` enforce a propensity threshold. Go through `catalogue.py` and `evaluator.py` against your own target document and Bab 4, and either approve the current code behavior explicitly or direct a change — do not leave both versions "true" in different documents.
6. **Consent/suppression scope.** Decide definitively: does opt-out on any single channel block all commercial contact (global suppression), or only that channel? Your own document flags this as unresolved. State the decision and reconcile it with the current K-10 channel-level implementation.
7. **SERVICE_REMINDER data contract.** Confirm the team-added restriction (ACTIVE/LOYAL only, ≤7 days to replenishment) as policy, and define what `replenishment_cycle_days` and `last_purchase_date` mean in business terms (e.g., which product/service categories have a replenishment cycle, and how it is derived). Moses will provide the data once the business meaning is defined; this action stays ineligible until then.

**Also required:**
- Close the outcome/KPI contract (Gate A includes this): define conversion events per action, treatment/control eligibility and contamination, attribution/refund/finalization windows, observed versus incremental revenue, and success thresholds with positive/negative/boundary examples. Reference the existing measurement implementation; synthetic uplift tests are not causal business evidence or approval. Record missing business choices rather than copying weekly guide defaults.
- Submit a versioned `target_definitions.md` revision for formal approval. Record the actual authorized approver's name and decision date only after approval is received; until then retain `REVISI`/`PENDING`, not `APPROVED`. Do not invent mentor/dosen approval.
- Regression/fix the reported `OverflowError` in `services/decision/nba/engine.py::scores_are_valid()` for extreme integer CLV inputs (e.g., `10**400`), so the guard degrades to the conservative default instead of crashing — this was flagged on PR #39 and is still open.
- Review and respond to James's historical-contract sign-off request once he submits it (see §3 above) — specifically the business meaning of refund/correction/availability where it affects your target definitions.

**Explicitly out of scope for you:** platform/history implementation (James's job) and model/feature/training code (Moses's job). If a decision here depends on data that does not exist yet (e.g., replenishment cycle data), say so explicitly and route the data-provisioning task to Moses rather than inventing a placeholder value yourself.

**When you believe Gate A is ready to close:** update `target_definitions.md`'s revision history, draft the decisions with examples, and request your actual academic approver (dosen/mentor) plus Moses/James review. Keep approver and date PENDING in the document until that reviewer genuinely signs off — self-declared approval by Christ alone does not close Gate A.

---

## 5. What Moses will do once both close

1. Re-validate the compatibility matrix in `docs/moses_data_ai/READINESS_REVIEW_PACKET_2026-11-16.md` §3 against the actual closed state.
2. Prepare a versioned label/feature proposal (new version identifiers, not overwrites) reflecting the approved churn/CLV/lifecycle definitions and James's confirmed historical source.
3. Run the Gate D review template (readiness packet §9) with named reviewers and dates before any new training, experiment, or model card.
4. Only after an explicit Gate D decision does `training_ready` or `experiment_ready` change from `false`.

## 6. Tracking

| Gate | Owner | Status as of 2026-11-17 | Target close condition |
|---|---|---|---|
| A — business | Christ + academic approver | BLOCKED | §4 items 1–7 resolved with examples, actual authorized sign-off |
| B — CI/contracts | Shared | PASS (merged PRs only) | Stays green per new PR; not a one-time close |
| C — historical | James | BLOCKED/IN PROGRESS | §3 items 1–5 complete, contract sign-off requested and received |
| D — model review | Moses | NOT OPEN | A and C closed; review template completed |
