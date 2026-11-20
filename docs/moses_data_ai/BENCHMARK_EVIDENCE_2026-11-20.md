# Benchmark evidence — 2026-11-20

**Scope:** evidence/reporting for FRD OBJ01/T01, OBJ02/T04 and TRD §9.7. **Disposition: development evidence only; no winner, promotion, gate approval or serving authorization.** Reviewer pending; approval not granted.

> Metrics are computed on project-generated synthetic data; they characterize the data generator, not real customers, and do not predict production performance.

This report separates fresh evaluation from inspection of existing checksummed results. No training, calibration fitting, new labels, resolver run or customer treatment was performed. Existing artifacts were not overwritten. Synthetic truth was read **only by the evaluation-only identity scorer**, never as a feature, resolver input or training label. Retrospective identity is not an availability-time/PIT guarantee. PROPOSED propensity labels remain pending business approval. Predictive discrimination is not causal uplift or business value.

## 1. Fresh identity evaluation (existing v1.1 mapping)

Executed from repository root `D:\projects\vteki-customer-intelligence` with `.venv\Scripts\python.exe` (Python 3.13.7). The directory below was newly created, not reused:

```powershell
$o='artifacts\evidence_20261120_benchmark_repro'
if (Test-Path $o) { throw 'Use a new evidence directory' }
New-Item -ItemType Directory $o | Out-Null
.venv\Scripts\python.exe generator\evaluate_identity.py --predicted artifacts/identity/v11/mapping.csv --truth generator/ground_truth/identity_mapping.csv | Tee-Object "$o\identity_v11_eval.json"
```

The scoring invocation and `Tee-Object` above reproduce the executed command; the guard makes replay safe (choose a different new directory). The evaluator requires identical source-ID coverage, computes label-invariant pair counts, and rejects duplicate source IDs. It does not compare the literal names of golden IDs.

| Freshly evaluated field | Value |
|---|---:|
| source_count | 61,000 |
| predicted_clusters | 50,640 |
| true_clusters | 50,000 |
| false_merge_clusters | 0 |
| pair_precision | 1.0 |
| pair_recall | 0.9388930010691668 |
| false_positive_pairs | 0 |
| false_negative_pairs | 743 |

**Recall 0.938893 is below the 95% aspiration.** Precision alone is not task closure. This is pair recall on the synthetic source mapping, not customer retention recall, not real-world identity accuracy, and not evidence that ambiguous matches are safe to automate.

SHA-256 pins (repository-relative paths):

```text
54bb4c62585a65eb48a89466c35c261d5ceb49fb9cec703aecdf5e21ccbf3719  artifacts/identity/v11/mapping.csv
af36d867346ce9f6697ca1f4b4678f529d8a9743b247e1f3a2de1b7887e0c4e3  artifacts/identity/v11/resolution_manifest.json
c7cb22d015be5e653fcbd542d94831f8ab6d495c115b479a706af59ee2f8dbf1  generator/ground_truth/identity_mapping.csv
671a037ce6582a805dd2111f7f8806fa920ef7a873da6a0c7dfdf3af44d05e76  generator/evaluate_identity.py
19300d7395a86d5c073635d97aab255e21f7d85fb1e50aaae85eb2a1eca84bfa  artifacts/evidence_20261120_benchmark_repro/identity_v11_eval.json
```

The mapping digest matches `resolution_manifest.json.output_sha256["mapping.csv"]`. Output bytes reflect PowerShell `Tee-Object` encoding/newlines; semantic JSON equality and input pins matter across platforms.

## 2. What was freshly rerun versus read

**Fresh read-only fixed-rule evaluation:**

```powershell
.venv\Scripts\python.exe -m services.data.models.evaluator --source artifacts\models\christ_v12_20261119 --output-dir artifacts\evidence_20261120_benchmark_repro\fixed_rule_churn_eval
```

The existing evaluator rejects an existing output directory, validates the source manifest/training-row checksum and checks inputs unchanged after evaluation. On its 33,779-row June holdout it returned ROC-AUC **0.6590795533802473**, average precision **0.3288708393643551**, Brier **0.15092217057935403**. These match the saved fitted-churn report's fixed-rule comparator. Binary-score top-decile lift remains null, not an inferred ranking result.

```text
dd02ffac8ce42d7b2b97eff90fafc1c577ea86bfe76b9582ea275f64b41b90ea  artifacts/evidence_20261120_benchmark_repro/fixed_rule_churn_eval/evaluation.json
cf8c6c377540293364f0010c6dfe0adbf102e9d3a6570807021c3b64423b0cd5  artifacts/evidence_20261120_benchmark_repro/fixed_rule_churn_eval/evaluation_manifest.json
```

**Verified saved results, not fresh fitted-model reproduction:** every table in §§3–4 was read from the evaluation files pinned in §5, after recomputing **every output digest** in the corresponding saved manifest (including predictions and parameters/calibration artifacts). All matched. Each manifest's `input_sha256` equals `input_sha256_after`; each recorded input digest was also matched against the existing source file at the paths in §6. This verifies saved-artifact integrity, not provenance signatures or correctness of the original training procedure. Fitted experiment/calibration entrypoints were deliberately not rerun because they fit models/calibrators. No fresh fit is implied by reading them.

## 3. Saved model comparisons (six decimals, no winner)

AP means average precision, not trapezoidal PR-AUC; lower Brier is better. Comparisons are within each source experiment, not across different target cohorts.

| Saved experiment / model | ROC-AUC | AP | Brier |
|---|---:|---:|---:|
| Churn90 fixed recency rule | 0.659080 | 0.328871 | 0.150922 |
| Churn90 logistic | 0.903389 | 0.591125 | 0.092640 |
| Churn90 shallow tree | 0.899839 | 0.550555 | 0.087331 |
| Retail purchase30 train-base-rate | 0.500000 | 0.362571 | 0.287516 |
| Retail purchase30 fixed rule | 0.684232 | 0.479700 | 0.364199 |
| Retail purchase30 logistic | 0.679816 | 0.499545 | 0.267696 |
| Renewal60 POS-only train-base-rate | 0.500000 | 0.542942 | 0.249637 |
| Renewal60 POS-only fixed rule | 0.498880 | 0.542386 | 0.479740 |
| Renewal60 POS-only logistic | 0.465716 | 0.516083 | 0.251365 |
| Renewal60 membership-only exploratory train-base-rate | 0.500000 | 0.542942 | 0.249637 |
| Renewal60 membership-only exploratory logistic | 0.649239 | 0.616232 | 0.228393 |

Unfavorable results are retained: the retail logistic AUC is below its fixed rule; POS-only renewal logistic AUC is below chance and Brier is worse than its base-rate comparator. Churn tree Brier is better than logistic but at threshold 0.5 it finds only 975 of 5,794 positives, versus logistic 1,987 and fixed rule 2,143. There is no universally superior model, approved operating point or production winner.

### Cohorts must remain distinct

- **Churn:** `christ-churn90-three-events-dev-1.2`, June cutoff `2026-06-01T00:00:00+07:00`, 33,779 holdout rows / 5,794 positives. Raw fitted experiment trains on 24,066 March rows. Do not substitute the older v1.1 diagnostic or purchase-only target.
- **Retail:** `moses-retail-purchase30-proposed-dev-1.0`, June holdout 27,647 / 10,024 positives. Purchase outcome overlaps purchase-behavior features; apparent signal may be habit rather than intervention responsiveness.
- **Renewal:** `moses-membership-renewal60-proposed-dev-1.0`, June holdout 8,465 / 4,596 positives; March training 8,087. POS-only predictors do not contain membership expiry/tier/tenure. Renewal is not upgrade.
- **Membership exploratory:** same renewal target and counts, membership-only predictors, no combined POS/membership model. Its label-input checksums match POS renewal, but this is a post-holdout-inspection follow-up, **not independent confirmation**. The saved ablation describes 1,236 negative-days-to-expiry holdout rows with zero positives versus 7,229 rows in the 0–60-day window containing all 4,596 positives. Eligibility structure and generator behavior constrain interpretation; this is not proof of transferable membership propensity.

## 4. Saved calibration comparisons (within each calibration run)

Calibration runs use December training, March calibration, June test. They are **not recalibrations of the March-trained fitted experiment above**. The June test has already been inspected in prior experiments; it is not a new independent holdout. Thresholds were selected on the calibration fold, not authorized for production.

| Saved run / test scores | ROC-AUC | AP | Brier | Descriptive ECE |
|---|---:|---:|---:|---:|
| Churn uncalibrated | 0.896485 | 0.544570 | 0.095348 | 0.027442 |
| Churn calibrated | 0.894469 | 0.531762 | 0.099053 | 0.045115 |
| Retail uncalibrated | 0.708751 | 0.579663 | 0.218642 | 0.132578 |
| Retail calibrated | 0.706523 | 0.568258 | 0.249749 | 0.206819 |
| POS renewal uncalibrated | 0.578672 | 0.593391 | 0.346026 | 0.280704 |
| POS renewal calibrated | 0.614736 | 0.609830 | 0.231207 | 0.014579 |

**Churn and retail calibration worsen both Brier and ECE.** Churn calibrated scores at fixed 0.5 have zero recall (0 true positives); the calibration-selected 0.25343041164939795 threshold yields recall 0.8835001725923369 but 5,880 false positives. Retail's selected calibrated threshold 0.39465875370919884 yields recall 0.87719473264166 and 13,336 false positives. Renewal calibration improves these descriptive score metrics but selected threshold 0.5 yields recall 0.9980417754569191 with 3,515 false positives and specificity 0.09149651072628587. High recall alone is not success.

Calibration train/calibration/test counts: retail **11,405 / 18,678 / 27,647**; renewal **5,181 / 8,087 / 8,465**. Churn calibration has **24,066** March calibration rows and **33,779** June test rows. Do not merge these cohorts or claim that calibration independently replicated the raw fitted-model result.

## 5. Saved result and manifest SHA-256 ledger

All paths below are relative to `artifacts/models/`. In each pair the first path is the manifest; the second is the evaluated report. All declared manifest outputs were verified, not only these report files.

```text
b59d42970043a122092bd789c37a40420db4861a4cfcf5930e91482764619e60  churn_fitted_dev_20261119_verified/experiment_manifest.json
7732c1c889ed5e5af3c45847d8d311ec19dde283204161b8460d9b67fd65eca7  churn_fitted_dev_20261119_verified/evaluation.json
3b7e5b3ba03a0b3ab74b0be90e92eab9b1b53eba2f72d0637ef49d5127652a7a  churn_calibration_20261119/calibration_manifest.json
b56ad371d01e38ab8a53c4c9a9478c6d55805b48b865684668be72d087419136  churn_calibration_20261119/calibration_evaluation.json
c6d8c9d929e37537cc45949fc56ca1035b010cb4ce73dde403ad6522fd657309  propensity_retail_20261119/experiment_manifest.json
b3d7a01badfb7ebe9207f73d08bb5dada05ff7531164e1b1af76d594e1297f52  propensity_retail_20261119/evaluation.json
b633fc0ee73a779dca0a7a254fce65589dfb9847736d68e454b271a1a87cc80f  propensity_retail_calibration_20261120/calibration_manifest.json
8cbc253d5b15ea505f659cda37e86f9783aa92c55bca29db0e80482b62d592c0  propensity_retail_calibration_20261120/calibration_evaluation.json
fc31bb5da59a843d8bf49f509e4854ef38f3c3c108c62aa60e1e05f428860061  propensity_renewal_20261119/experiment_manifest.json
8ed525c317c88fc002b2bad22d4245f7aa9bd0044319c603804d788e9c069238  propensity_renewal_20261119/evaluation.json
a824c7ce1537824153d9d10bd2eff5f17880f99a85d8132a0acb6e248d517a5d  propensity_renewal_calibration_20261120/calibration_manifest.json
371a9b5a9d69715f5e31550b3887d4fcc0a7d28ec73f72418a9f4f56b08b06ce  propensity_renewal_calibration_20261120/calibration_evaluation.json
bab157f3326420f9d6149594466b4d74345809f8c2cd104d646b9cf20045d3dd  renewal_membership_exploratory_20261119/experiment_manifest.json
4c2826bc892e37a3a870cff0e2afea01f9d309303c397200c0eea15672e47793  renewal_membership_exploratory_20261119/evaluation.json
9ca9790d1573a1aca939887cb6e51b209db52fc6994aea199cbc78cb19d8f8cc  renewal_ablation_reviewed_20261119/experiment_manifest.json
149ea5963581cf45f58c86e186b5af86a0a85ecfcc74c8753c06f02e1fe41665  renewal_ablation_reviewed_20261119/evaluation.json
```

## 6. Exact input paths and hashes

These files were read, not regenerated. The source manifest pins the full input/output chain; digest agreement is not a production data-readiness certificate.

```text
7d99b99654e2a2b837b56dddb31e1c6f317d40231abec161db8d543c654bfc99  artifacts/models/christ_v12_20261119/model_manifest.json
4c1756aa79521a47771a380232a15f3a34c569e65df0731080a9db23d8c304e9  artifacts/models/christ_v12_20261119/training_rows.csv
42ad18e0dbf72a181411e45bcff0bb0fe0bb0c2e9840f04e19d5aa7b71592226  artifacts/models/christ_v12_3cut_20261119/model_manifest.json
70a92a47a2e69247cf78b93e2b76690274765cba6a16d53eb2233095dec6faba  artifacts/models/christ_v12_3cut_20261119/training_rows.csv
8a310a60c5cb9cfdea1cd5655e650bc6d988cf37c809fb46939a3c2010ec32b7  artifacts/features/propensity_20260301_20260601_dev/feature_manifest.json
5e3ddb69a8c4557a2700d0fbf7497fcadcfe8ba40510c547bb64e33c9b68a469  artifacts/features/propensity_20260301_20260601_dev/features.csv
e0d2c13309f7d4cbd5a250fc9f5236ab2422daa6a80b259a1417de2fe01c7682  artifacts/models/propensity_labels_20261119/propensity_labels.csv
e6783ba593e43c2ed78ca6d9a5a3a0b5de1689a9eb8e3571098d7b71b7ba7f34  artifacts/models/propensity_labels_20261119/propensity_manifest.json
14ff67404684e5a4982daad9435752ca43e144ae830035f463bc618fee7b9ac6  artifacts/features/propensity_3cut_20261119/feature_manifest.json
55401b1c62eb4add85acfe59ae3cae60b026711d4793d05ad06bf358de850ea6  artifacts/features/propensity_3cut_20261119/features.csv
a6db273815ba523979888399c5f7ee2ab69fbdfc3fd2482d092bbee0c02529ef  artifacts/models/propensity_labels_3cut_20261119/propensity_labels.csv
886424e2b2b31327c8188062543ee5a2e6fa37a516124d7ebc55188209c5230d  artifacts/models/propensity_labels_3cut_20261119/propensity_manifest.json
1841774c582b2684feb52e652bac8a7f8090c7c2b0ffb7afebb5ff86839e17e5  artifacts/features/membership_20260301_20260601_dev/membership_features.csv
8a1b677be97d50c2ff637a19d103379ea426770b48f84d03a871946e719468ec  artifacts/features/membership_20260301_20260601_dev/membership_manifest.json
```

Raw churn and fresh rule evaluation use `christ_v12_20261119`; calibrated churn uses `christ_v12_3cut_20261119`. Raw retail/POS renewal use the two-cut propensity features/labels; calibrated retail/POS renewal use the three-cut sources. Membership and ablation use membership features plus the two-cut propensity labels.

## 7. Limits and next decision

This is a dated update to the historical [experiment comparison](evidence/04_EXPERIMENT_COMPARISON.md), not a rewrite of its 2026-11-17 state. Identity recall remains below aspiration. Saved comparisons now exist, but synthetic, retrospective, reused-holdout evidence does not authorize a model winner, training readiness, experiment readiness, final model status or production thresholds. Business approval of targets, independently verified availability-time data, an independent evaluation design, protective decision inputs and explicit human review remain separate requirements. No real-customer impact, revenue gain, CLV success or causal campaign effect is established here.
