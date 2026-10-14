# RFM and lifecycle development baseline (PROPOSED)

This is descriptive segmentation, not a final ML point-in-time feature pipeline.
Current resolver snapshot is used retrospectively; historical identity availability
is not versioned. PostgreSQL persistence and business approval remain outstanding.

## Inputs and counting policy

Use validated schema-v2 source CSV and checksummed resolver mapping. All source customer
IDs must be covered. Preserve identity_status PROVISIONAL/REVIEW_REQUIRED from Customer360.
Only COMPLETED/PARTIAL_REFUND transactions with known customer reference are eligible;
actual_revenue is retained revenue in integer IDR. Source business fingerprint replays
are counted once. Never read synthetic ground truth. Refunds assumed settled at purchase
because refund event timestamps are unavailable. Exact fingerprints may collapse genuine
identical purchases. Visits and renewals are not counted as purchases for RFM/lifecycle.

## Time semantics

Cutoff inclusive and timezone +07:00. Rolling windows are (cutoff-N days, cutoff].
RFM window defaults 365 days, minimum 90. Recency uses calendar dates from the most recent
qualifying purchase in observed history, NOT just within the RFM monetary/frequency window.
Never-transacted recency is NULL/blank, not an invented date. Tenure is cutoff date minus
first business join date of eligible source records.

## Fixed RFM score boundaries (PROPOSED, not fitted quantiles)

R: <=30 / 31-60 / 61-90 / 91-180 / >=181 days gives 5/4/3/2/1; no purchase gives 1.
F: 0 / 1-2 / 3-5 / 6-11 / >=12 purchases gives 1/2/3/4/5.
M: 0 / 1-499999 / 500000-1999999 / 2000000-4999999 / >=5000000 IDR gives 1/2/3/4/5.
RFM code concatenates R,F,M. Scores are descriptive business bins, not learned model scores.

## Exclusive lifecycle priority (PROPOSED)

1. REACTIVATED: a purchase within 30 days after >180 days without qualifying purchase;
   requires two observed purchases (not first-ever purchase).
2. LOYAL: tenure >=60 days AND >=5 purchases in 90 days AND revenue90 >=500000.
3. NEW: tenure <=30 days, even if never purchased.
4. NEVER_TRANSACTED: no observed qualifying purchase (fallback for older registrations).
5. CHURNED: recency >365.
6. DORMANT: recency 181-365.
7. AT_RISK: recency 91-180.
8. ACTIVE: >=3 purchases in 60 days.
9. OCCASIONAL: remaining purchasers with recency <=90 (explicit fallback).

Membership is NOT a mandatory condition, so nonmembers can be classified. Churned lifecycle
is observed inactivity, not the future churn90 label. Unobserved pre-window activity cannot
establish reactivation; history censoring remains a limitation. Align WIN_BACK_OFFER to
Dormant only after Christ approves these rules; retention for At Risk is separate.

## Run WSL

```bash
python3 -m services.data.segmentation.cli --inbound inbound/2026-09-06 --resolution artifacts/identity/v11 --cutoff-at 2026-09-06T23:59:59+07:00 --window-days 365 --output artifacts/segmentation/current.csv
python3 -m unittest -v tests.data.test_segmentation
```

Output has golden ID, cutoff, identity status, recency/F/M, window, R/F/M scores/code,
tenure, 60/90-day counts, 90-day revenue, lifecycle and rule_version. Existing outputs
cannot be overwritten. Uses in-memory source aggregates; full-scale performance untested.

Executed 2000-golden fixture: 2031 provisional profiles; ACTIVE 248, AT_RISK 129,
CHURNED 28, DORMANT 121, LOYAL 505, NEVER_TRANSACTED 73, NEW 101, OCCASIONAL 822,
REACTIVATED 4. Tests verify lifecycle boundaries/priorities and future amount isolation.
