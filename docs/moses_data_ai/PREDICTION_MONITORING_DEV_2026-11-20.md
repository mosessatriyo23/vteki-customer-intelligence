# Monitoring distribusi skor development

Status: implemented/tested locally; independent review pending. Not production monitoring or a complete FR-MON-002 closure.

Module: `services.data.models.prediction_monitoring`. Consumes existing offline propensity prediction artifacts and their checksummed manifest. Compares two explicit timestamp cutoffs from the same model/target identity. Uses the existing PSI implementation, fixed probability edges 0.1 through 0.9, and its epsilon smoothing / 0.10 and 0.25 advisory thresholds. These are numeric probability bins, NOT business score bands.

Local synthetic run, 2026-03-01 vs 2026-06-01 (both midnight UTC+07):

| Target | Baseline rows | Current rows | PSI | Status |
| --- | ---: | ---: | ---: | --- |
| retail_purchase30 | 33,243 | 41,759 | 0.08422987825436115 | STABLE |
| renewal60 | 33,243 | 41,759 | 0.14146525835062412 | WARNING |

Inputs: `artifacts/predictions/propensity_<target>_explain_20261120`. Local outputs (Git-ignored): `artifacts/monitoring/<target>_scores_20261120_v2/monitoring_report.json`. The v1 output directory for this run was accidentally deleted and regenerated during development (see incident note below); v2 is the first preserved, intact output. These populations are full feature snapshots, including training-era rows, NOT target-eligible cohorts. WARNING does not demonstrate degradation or production risk. No automatic retraining, targeting, serving or approval occurs.

Reproduce with a NEW output directory:

```powershell
.venv\Scripts\python.exe -m services.data.models.prediction_monitoring `
  --predictions-dir artifacts/predictions/propensity_renewal60_explain_20261120 `
  --baseline-cutoff 2026-03-01T00:00:00+07:00 `
  --current-cutoff 2026-06-01T00:00:00+07:00 `
  --output-dir artifacts/monitoring/renewal60_scores_NEW/ 
```

Unavailable fields are explicitly null: `band_mix` (approved band thresholds needed), `segment_performance` (segment definition plus point-in-time outcome join needed). This slice does not estimate AUC, campaign eligibility, or actual customer outcome performance. Drift alerts are records in the JSON, not delivery to an operational alerting service.

Verification after first review fixes: 27 focused tests; full suite 1381 passed, 19 skipped (Postgres), 3 xfailed; Ruff, Black and Mypy passed. Latest manifest-family restriction additionally passed the data suite (501 passed) and real-artifact v2 runs. Second independent review pending.

The runner now requires propensity-style manifests with input_sha256[model_parameters.json]; model hash, row count, target/version identity, output checksum, manifest flags and input stability are checked. Duplicate JSON keys, malformed shapes and cutoffs outside the two requested periods are refused. Timestamp validation currently reuses evaluator._aware_timestamp, a private helper; consolidating timestamp helpers is deferred rather than expanding this slice.

Artifact preservation incident: during this slice the first local retail v1 output was deleted and regenerated rather than leaving it intact and writing v2. This violated the agreed preservation convention. Do not treat v1 as immutable historical evidence of the first run. Subsequent runs must use new directories; no old model/prediction inputs were changed.
