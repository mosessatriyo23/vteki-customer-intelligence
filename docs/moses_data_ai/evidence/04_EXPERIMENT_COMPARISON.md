# 04 — Experiment / candidate comparison status

**As of:** 2026-11-17 · **Requested development evidence:** James. **Owner:** Moses; business review Christ; platform review James. **Reviewer:** pending. **Approval date:** not granted. Checkout: `main` `7e09616` plus PR #38 `aa2a23d`.

```text
training_ready=false
experiment_ready=false
final_model=false
candidate_comparison=NOT RUN / BLOCKED
```

## Requirement and actual scope

Business source: `docs/christ_business/reference/Requirement_Capstone.md`, especially Bab 2 (churn and gross-revenue 12-month CLV), Bab 3–5 (independent protective inputs and EV). No new estimator, feature, label, training run, model search, A/B campaign, or customer treatment was created for this report. There is no candidate estimator result to publish and no model winner. Historical fixed-rule diagnostics are not an estimator comparison or experiment authorization.

## Available historical reference comparisons (not candidate ML experiments)

| Reference | Actual evidence | What may be concluded |
|---|---|---|
| Legacy purchase-only retrospective baseline, `../model_card_development_v1.md` | Fixed recency rule; train-outcome median versus train mean for **90-day `actual_revenue`**. Median MAE 3,817,698.51 IDR; mean MAE 3,899,626.65 IDR, train 22,602 / holdout 32,850. The card says diagnostics also compare always-non-churn, but does not publish its numerical result. | Only the reported constant revenue references can be compared on that legacy target. No inferred constant-churn metric, statistical significance or business 12-month CLV conclusion is asserted. These are constants/rules, not trained candidate estimators. |
| Three-event churn diagnostic, `../sprint_gate_status_2026-11-14.md` | Fixed recency rule on `christ-churn90-three-events-dev-1.1`; ROC-AUC 0.664, AP 0.344, Brier 0.141, recall 36.97%, balanced accuracy 66.40%; holdout prevalence 16.92%. | Single heuristic diagnostic only. The purchase-only card's metrics are a different target; they are not a before/after model improvement comparison. Binary ties make top-decile lift null. |
| Proposed candidate estimator | **NOT RUN / BLOCKED**; no estimator, tuning, new feature set, candidate metric or artifact | No ranking, selection, promotion or improvement claim. |
| Online / randomized business experiment | **NOT RUN / BLOCKED** | No causal uplift, ROI, campaign or real-customer claim. |

## Local evidence versus historical artifacts

The historical local regression command passed **54 tests in 13.420s** (not rerun for this refresh):

```powershell
python -m unittest tests.data.test_ingestion tests.data.test_ingestion_negative tests.data.test_data_leakage tests.data.test_pit_features tests.data.test_model_baseline tests.data.test_model_diagnostics tests.data.test_model_evaluator tests.data.test_business_clv tests.data.test_clv_features tests.data.test_model_label_readiness tests.data.test_drift_monitoring
```

This validates development contracts, not candidate predictive performance. Historical metric runs above were not rerun for this report or the 2026-11-17 CI refresh. PR #38 has since merged (`885b675`, final-head checks SUCCESS); its `main` merge-commit push [CI run 44050705428](https://github.com/mosessatriyo23/vteki-customer-intelligence/actions/runs/44050705428) succeeded. This does not constitute an experiment or gate approval. For an existing compatible three-event baseline output, the inspected evaluator API is:

```powershell
python -m services.data.models.evaluator --source <baseline-output-dir> --output-dir <new-empty-evaluation-dir>
```

The source must contain its checksummed `training_rows.csv` and `model_manifest.json`; output must not exist. This command evaluates the existing fixed rule only. It is not a candidate-training command or permission to generate new labels.

## Conditions before any actual comparison

1. Christ must resolve the same-document 180-day outcome versus 90-day horizon conflict, active-cohort semantics and formal approval/version; specify CLV gross source, time window and retention method without an invented default or `1-churn90` proxy.
2. James must supply tested historical availability, immutable corrections/refunds/status, identity-as-of and multi-batch evidence; event-time leakage tests alone do not certify bitemporal correctness.
3. Gates A–C and Gate D review must explicitly authorize a versioned proposal before any new training. Only then agree a frozen cohort/split, leakage controls, metrics, candidate/baseline design and acceptance criteria with reviewers. No hypothetical candidate result is represented here.
4. Experiments additionally require independent consent/eligibility/contact/suitability protections, human approval, monitoring and rollback. Ground truth remains evaluation-only.

**Disposition:** preserve existing development references; no experiment or promotion. **Reviewer pending; approval date not granted.**
