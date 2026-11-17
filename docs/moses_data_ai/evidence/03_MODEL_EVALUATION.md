# 03 — Model evaluation evidence (development only)

**As of:** 2026-11-17 · **Scope:** synthetic capstone data; checkout includes `main` `7e09616` and Moses PR #38 `aa2a23d`. **Reviewer:** pending (Christ / James / Moses). **Approval date:** not granted. `training_ready=false`, `experiment_ready=false`, `final_model=false`.

## Requirement and evaluation target

`docs/christ_business/reference/Requirement_Capstone.md` Bab 2 calls for a 90-day prediction horizon, 30-day score validity, risk bands and at least three business reason codes; Bab 2.1 also says no transaction **and** visit for **180 days forward**, with no membership renewal. That 180/90 contradiction and the measurable active cohort require Christ's written decision. Bab 2.2 specifies **gross revenue** historical 12 months plus projected 12 months with a retention factor, not a 90-day revenue target. The template's version/approver fields are unfilled. Neither a fitted model nor production score/validity/reason-code contract is approved.

## What was actually measured

| Evidence | Target / method | Results and limitations |
|---|---|---|
| `../sprint_gate_status_2026-11-14.md` (synthetic diagnostic, not rerun for this report) | `christ-churn90-three-events-dev-1.1`, 90-day transaction/visit/renewal outcome; **fixed binary recency >90d heuristic**, not fitted ML | 75,002 customer/cutoff labels; 55,452 eligible complete rows; purged temporal split 22,602 March train / 32,850 June holdout, 0 purged. June churn 5,558/32,850 (16.92%); holdout ROC-AUC 0.664, average precision 0.344, Brier 0.141, recall 36.97%, balanced accuracy 66.40%. Binary scores tie: top-decile lift is null, not evidence of ranking or calibration. |
| `../model_card_development_v1.md` (older retrospective diagnostic) | **Purchase-only** `churn90` and `clv90` future `actual_revenue`; fixed recency churn / train-median CLV baseline | 22,602 train / 32,850 holdout; recency accuracy 0.87656, balanced accuracy 0.74199, sensitivity 0.51323, specificity 0.97075; `clv90` median MAE 3,817,698.51 IDR, mean MAE 3,899,626.65 IDR. These are different targets and **must not** be compared as if they were results on the three-event cohort. The `clv90` MAE is **not** a predictive metric for business 12-month CLV. |

`services/data/models/evaluator.py` validates complete eligible rows and Christ label version, evaluates the fixed rule with purged temporal split, and explicitly returns all readiness flags false. It does not fit a new estimator. Synthetic retrospective identity, event availability, refunds/status lineage and business definition gaps prevent real-world performance, calibration, fairness or campaign claims. Ground truth remains evaluation-only.

## Reproduction and scope of local checks

Actual local command reported on this checkout:

```powershell
python -m unittest tests.data.test_ingestion tests.data.test_ingestion_negative tests.data.test_data_leakage tests.data.test_pit_features tests.data.test_model_baseline tests.data.test_model_diagnostics tests.data.test_model_evaluator tests.data.test_business_clv tests.data.test_clv_features tests.data.test_model_label_readiness tests.data.test_drift_monitoring
```

**54 tests passed in 13.420s** (historical, not rerun for this refresh). These are development unit/regression checks (including event-time leakage and evaluator contracts), **not** a fresh metric run, a bitemporal certification, or evidence of training. To run the evaluator *given an existing compatible baseline output directory* (containing `model_manifest.json` and `training_rows.csv`), use `python -m services.data.models.evaluator --source <baseline-output-dir> --output-dir <new-empty-evaluation-dir>`; this report does not claim that command was rerun. Do not substitute unit-test passage for the historical diagnostic above. Do not create a candidate or claim new metrics from this report.

**CI status refresh (2026-11-17, `gh` CLI):** PR #38 (`885b675`, merged 08:54:10Z) final head `f97fe51` and the `main` merge-commit push run ([44050705428](https://github.com/mosessatriyo23/vteki-customer-intelligence/actions/runs/44050705428)) both show SUCCESS. This is CI status only; the model-evaluation metrics table above is unchanged and was not rerun.

**Decision:** model readiness review Gate D not open. Obtain Christ's approved target/CLV rules, James's tested historical availability and identity-as-of evidence, and independent review before proposing a versioned new label/model or any experiment. **Reviewer sign-off: pending; approval date: not granted.**
