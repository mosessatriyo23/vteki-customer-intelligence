# I-04 prediction handoff — Moses proposal, 2026-11-18

**Status: DRAFT / NOT APPROVED / NOT WIRED.** Synthetic development only.
`training_ready=false`, `experiment_ready=false`, `final_model=false`.
Source: supplied TRD v0.9 PDF pp.71,79 (I-04); FRD v0.9 pp.38,58–59; Requirement_Capstone Bab 2.
This is a proposed interface, not a new feature/label version or permission to train.
Consumer review: James/Christ PENDING. Authorized approval: PENDING; date blank.

## 1. Wire fields and proposed validation

TRD supplies the field names below. Detailed wire types/nullability below are **proposals** pending joint review; do not silently treat them as approved INTG-v1.0.

| Field | Proposed type and rule |
|---|---|
| `prediction_id` | Nonempty unique string; immutable; replay same ID with different content rejects |
| `customer_id` | Golden UUID string; never integer legacy ID; explicit mapping from producer `golden_customer_id` |
| `prediction_type` | `CHURN`; separate propensity target identifiers agreed before publishing (see §3) |
| `score` | JSON number, finite [0,1], not bool; this probability schema is not a CLV money record |
| `band` | Nonempty string from versioned target-specific band configuration; not inferred using consumer defaults |
| `reason_codes` | At least 3 distinct substantiated reasons; objects `{code,label,direction,contribution}` |
| `model_version` | Nonempty immutable model reference; no placeholder claimed as trained model |
| `feature_set_version` | Nonempty reference identifying exact input definitions |
| `prediction_date` | ISO date; score reference date, not ingestion/publication time |
| `outcome_window_end` | ISO date after prediction date; approved target horizon |
| `valid_until` | ISO date, explicit producer expiry; consumer must not derive a longer expiry |
| `calibration_version` | Nonempty artifact reference for calibrated serving; rules-only mode must not fabricate one |

Reason direction vocabulary, contribution units/method, band-config lookup, exact expiry timezone and date boundary require joint agreement. Reason contribution must come from the declared explanation method, not an invented probability decomposition. Missing/unavailable prediction is an explicit absence plus decision metadata, **not** a valid score of zero. Null calibration/missing explanations cannot be silently accepted as a fully governed prediction.

Date-only fields come from TRD; implementation must agree how they map to timezone-aware decision timestamps. Add boundary tests for before/on/after `valid_until` once decided. Until then no runtime expiry adapter is authorized by this draft. Thirty-day score validity is separate from the 90/180-day outcome question.

## 2. Existing code is not this interface

`services/data/models/score_contract.py::validate_score_handoff` validates the existing development `AIScores` dataclass only. It does not check I-04, golden UUID shape, model status, per-target lineage or producer expiry. Passing it does not authorize serving.

| Current `AIScores` | I-04 adapter requirement |
|---|---|
| `customer_id` arbitrary string | Resolve/validate golden UUID; no integer fallback |
| `churn_score`, `churn_risk_band` | Reference the exact CHURN prediction and band configuration |
| `propensity_purchase` | Cannot losslessly represent both service booking and retail purchase |
| `propensity_renew` | Must identify the approved renewal/upgrade target and its horizon |
| `score_generated_at` | Not a replacement for prediction date, outcome end and producer expiry |
| `reason_codes: list[str]` | Cannot preserve per-target structured explanations/contributions |
| `clv_amount`, `clv_tier`, `lifecycle_stage` | Separate versioned value/profile/segment context, not probabilistic prediction fields |

Do not implement a lossy adapter by merging propensity targets, stripping versions, copying reasons between targets or refreshing expired scores. Extend the receiving context deliberately after joint review. No producer is currently wired to emit I-04 records.

## 3. Target and band decisions

FRD specifies independent business outcomes: service booking 30 days, retail purchase 30 days, membership renewal/upgrade 60 days. Suggested wire names `PROPENSITY_SERVICE_BOOKING`, `PROPENSITY_RETAIL_PURCHASE`, `PROPENSITY_MEMBERSHIP_RENEWAL` are **proposed, not frozen**. Decide whether upgrade shares the last target or requires a separate definition. Positive-count minimum, eligibility, qualifying status and high-band threshold remain pending. These labels/models are not implemented; no training is started here.

Capstone churn cutoffs imply proposed non-overlapping intervals LOW [0,.30), MEDIUM [.30,.60), HIGH [.60,.80), VERY_HIGH [.80,1]. FRD says bands follow baseline review; record a decision before adopting this configuration. Do not apply churn cutoffs to propensity automatically.

## 4. Consumer acceptance fixtures to implement after agreement

- Valid golden UUID joins profile, segment and prediction without legacy-ID substitution.
- NaN/infinity/bool/out-of-range/oversized numeric input rejects without overflow.
- Wrong customer, missing versions, duplicate/unsupported reasons reject governed handoff.
- Producer-shortened expiry is respected; generated-at plus 30 days never overrides it.
- Two propensity targets remain distinct and each retains model/feature/calibration lineage.
- Suspended model causes explicit `model_unavailable` rules-only handling; no fabricated prediction.
- Expired versus missing versus suspended prediction have separately agreed dispositions; protective checks never relax.
- Persisted decision retains exact prediction/model/rule evidence; later changes do not rewrite it.

## 5. Handoff now

James/Christ can review these fields and build mock contract tests without waiting for training. Runtime wiring depends on their approved context/ID/expiry decisions and persisted source contracts. See [Moses unblock packet](MOSES_UNBLOCK_HANDOFF_2026-11-18.md) for independent churn decisions, snapshot request and coverage limits. Approval remains PENDING; no sender may approve on behalf of a consumer or mentor.
