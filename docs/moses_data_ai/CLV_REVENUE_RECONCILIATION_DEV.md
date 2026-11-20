# CLV revenue reconciliation — development review, 2026-11-19 (updated 2026-11-20)

**Status: decision still requested. `build_clv_aggregates` (gross) is unchanged.
A new, separately versioned sibling exists:
`services/data/models/clv_features.py::build_clv_actual_revenue_aggregates`
(`feature_version="clv-actual-revenue-365d-dev-1.0-christ-v1.4"`), covered by
`tests/data/test_clv_features.py::ClvActualRevenueTests`. It sums the
ingestion-provided `actual_revenue` field (net of discount and any refund
recorded as of the source) instead of `gross_amount`, matching Christ's v1.4
wording that the historical CLV figure should be `actual_revenue`
(`target_definitions.md` v1.4 §2.1). Nothing consumes this builder yet —
`clv_projection.py` still only accepts gross inputs — and this does not
resolve the open items below: it is not approved, it does not prove
availability-time (`known_at`) correctness, and no `training_ready`/tier
decision depends on it.** Christ's [`target_definitions.md` v1.3 §2.1](../christ_business/approved/target_definitions.md) (lines 77–112) says rolling 365 days, `COMPLETED`/`PARTIAL_REFUND`, prefer POS `net_amount` over `gross_amount` when available, and count partial refunds at the amount retained by the business. It simultaneously calls the result **Gross Revenue** (lines 91 and 111–112). The document header still says mentor approval and team review are pending. This note does not grant approval or establish a new revenue definition.

## Exact discrepancy

`services/data/models/clv_features.py::build_clv_aggregates` filters status and `(cutoff - 365 days, cutoff]` correctly, but sums **only `gross_amount`** for both statuses (line 77). It ignores `discount_amount`, `net_amount`, `refund_amount` and `actual_revenue` in its calculation; its `historical_spend_12m_gross` and `average_transaction_value_12m` therefore overstate retained revenue whenever a qualifying transaction has a discount or partial refund. `business_clv.py::calculate_business_clv` takes precomputed numbers and cannot fix the upstream amount: it uses the historical spend and average to calculate both historical and projected components. `tests/data/test_clv_features.py::test_window_status_gross_revenue_and_deduplication` currently asserts gross 100 + 200 = 300 (average 150), despite supplying `net_amount=90` for both rows; the partial-refund fixture is **internally invalid** (`gross=200`, `discount=10`, `net=90`) under the ingestion rule `net_amount = gross_amount - discount_amount`. The calculator tests supply numbers directly and do not exercise ingestion or field mapping. Existing green tests are not evidence of Christ convention compliance.

The validated `transactions.csv` contract (`services/data/ingestion/contracts.py`) **requires** all four amounts (`gross_amount`, `net_amount`, `refund_amount`, `actual_revenue`); these are not optional in schema v2. The generator accounting rule (`docs/moses_data_ai/generator_business_decisions.md`) and event projection (`services/data/ingestion/transaction_events.py`) set `net_amount = gross_amount - discount_amount` and, for non-cancelled transactions, `actual_revenue = net_amount - refund_amount`. Thus `net_amount` alone does **not** account for a partial refund. The former document explicitly flags missing refund timestamps in legacy synthetic rows; versioned as-known refund evidence remains a separate prerequisite for production/PIT claims.

### Worked example (valid schema-v2 amounts, same customer, both inside the rolling window)

| status | gross_amount | discount_amount | net_amount | refund_amount | actual_revenue | Current CLV aggregate | Net-only interpretation | Retained interpretation |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `COMPLETED` | 100 | 10 | 90 | 0 | 90 | 100 | 90 | 90 |
| `PARTIAL_REFUND` | 200 | 20 | 180 | 50 | 130 | 200 | 180 | 130 |
| **Historical total** | | | | | | **300** | **270** | **220** |

With two transactions, the corresponding average transaction values are **150**, **135**, and **110** IDR; frequency is 2/12 per month under current code. For an illustrative *symbolic* retention factor `R` (not an approved estimate), `business_clv.py` would calculate `300 + 300R`, `270 + 270R`, or `220 + 220R`, respectively. The current figure exceeds net-only by 30 IDR and retained revenue by 80 IDR. No value of `R` is assumed here. In particular, choosing `net_amount` for the partial refund would still exceed the business's retained amount by 50 IDR.

## Decisions needed before changing the feature

1. **Christ / business approver:** Confirm explicitly whether the CLV historical and average amounts should be `actual_revenue` for both qualifying statuses (equivalent to `net_amount` for `COMPLETED`, and `net_amount - refund_amount` for `PARTIAL_REFUND`), or another mapping. Reconcile the term **Gross Revenue** with the net-after-discount / after-refund instruction and specify the field/definition used in tiers and output labels. Clarify whether any legacy source without `net_amount` may fall back to `gross_amount`, given schema v2 requires `net_amount`; if yes, define provenance and validation. Do not silently call retained revenue gross before this decision.
2. **James / Moses:** Verify the trusted as-of source, accounting invariants, status/refund version and `known_at` coverage; a final-state `actual_revenue` read at a past cutoff can leak a later refund. Confirm how to handle missing, malformed or contradictory amount fields and whether an updated feature/output name or version is needed. This does not unblock `training_ready` or approve a retention factor.
3. **After written decisions and review:** Point `clv_projection.py` (or a new wrapper) at `build_clv_actual_revenue_aggregates` instead of the gross builder, once the mapping and PIT semantics are agreed. `business_clv.py`'s pure formula itself needs no revenue-field fallback.

## Update, 2026-11-20: a separately versioned `actual_revenue` builder now exists

`services/data/models/clv_features.py::build_clv_actual_revenue_aggregates`
(`feature_version="clv-actual-revenue-365d-dev-1.0-christ-v1.4"`) sums the
ingestion-validated `actual_revenue` field instead of `gross_amount`, using the
same status filter, 365-day window, and dedup/conflict rules as the gross
builder. It trusts `actual_revenue` as already validated by ingestion
(`services/data/ingestion/validator.py`, `transaction_events.py`) and does not
re-derive or re-check `net_amount - refund_amount` itself; a non-digit or
negative `actual_revenue` is rejected the same way `gross_amount` already was.
`tests/data/test_clv_features.py::ClvActualRevenueTests` covers a discounted
row, a partial refund, the 365-day boundary, a cancelled row (`actual_revenue`
fixed at 0 under the generator's accounting rule), and a same-ID conflict
between a `COMPLETED` and a later `PARTIAL_REFUND` record. The original gross
builder, `build_clv_aggregates`, is unchanged and still the only one consumed
by `clv_projection.py`.

**This does not resolve items 1–2 above.** It gives Christ and James a
correctly-computed `actual_revenue` figure to compare against the existing
gross figure (see the worked example), but: the mapping is still Christ's
decision pending mentor approval of v1.4; nothing proves `actual_revenue` was
known at the historical `cutoff` rather than updated later by a subsequent
refund (James/Moses, item 2); and no consumer, tier boundary, or
`training_ready` flag depends on this builder yet.

## Validation

```powershell
.venv\Scripts\python.exe -m pytest tests/data/test_clv_features.py tests/data/test_clv_projection.py tests/data/test_business_clv.py -q
```

Before the review fixture corrections, this command passed **50 tests**.
The CLV feature module contains 5 existing and 4 new test functions; unittest
subtests are not additional pytest test cases. Re-run after subsequent edits.
The numerical table above remains a decision aid, not an approved production
CLV result.
