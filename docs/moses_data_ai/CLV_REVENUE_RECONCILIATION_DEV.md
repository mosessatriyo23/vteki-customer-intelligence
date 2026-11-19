# CLV revenue reconciliation — development review, 2026-11-19

**Status: decision requested; no CLV behavior changed.** Christ's [`target_definitions.md` v1.3 §2.1](../christ_business/approved/target_definitions.md) (lines 77–112) says rolling 365 days, `COMPLETED`/`PARTIAL_REFUND`, prefer POS `net_amount` over `gross_amount` when available, and count partial refunds at the amount retained by the business. It simultaneously calls the result **Gross Revenue** (lines 91 and 111–112). The document header still says mentor approval and team review are pending. This note does not grant approval or establish a new revenue definition.

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
3. **After written decisions and review:** Add valid discounted and partially refunded fixtures covering historical total, average and projected component; retain status/window/dedup assertions. Update the feature and its consumers together only after the mapping and PIT semantics are agreed. `business_clv.py`'s pure formula itself needs no revenue-field fallback.

## Validation (current behavior only)

```powershell
python -m unittest tests.data.test_clv_features tests.data.test_business_clv
```

At this review the command passed (17 tests). **No new regression test was added:** the current fixture contradicts the ingestion accounting invariant, and a single expected amount cannot be asserted as approved while the gross/net/retained mapping and time-of-knowledge are unresolved. The numerical table above is a decision aid, not a new test oracle or production CLV result.
