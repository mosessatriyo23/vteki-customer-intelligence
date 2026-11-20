# Verified metadata and renewal-membership importance

Development-only evidence slice. No model promotion or acceptance of production performance.

## Inventory

`model_inventory.py` now exposes `evidence_metadata`: named values and per-field filename/checksum sources from already-verified evaluation/parameter bytes. Missing/invalid/conflicting declarations remain null. No algorithm or hyperparameter inference from a logistic key.

Local output: `artifacts/models/inventory_metadata_20261120_subagent_01/inventory.json` (Git-ignored), six existing experiments verified. All six lack explicit algorithm/hyperparameters; two ablation experiments additionally lack sklearn version/serialization. Old artifacts were not modified. A separate training-generator change is needed to record actual estimator metadata for future artifacts.

## Renewal-membership importance

`model_importance --kind renewal60_membership --membership-dir ...` reconstructs the experiment's temporal holdout, uses membership-native features and saved logistic arithmetic, verifies source provenance, and does not refit. Isotonic-bearing artifacts are refused rather than silently treated as raw logistic.

Actual local run:

```powershell
.venv\Scripts\python.exe -m services.data.models.model_importance --kind renewal60_membership --model-dir artifacts/models/renewal_membership_exploratory_20261119 --labels-dir artifacts/models/propensity_labels_20261119 --membership-dir artifacts/features/membership_20260301_20260601_dev --output-dir artifacts/models/importance_renewal_membership_20261120_v1 --repeats 5 --min-n 30
```

8,465 holdout rows. Exploratory/post-holdout-inspection warnings retained, independent_confirmation=false. No membership segment performance is invented; segment output intentionally empty with a limitation. These are permutation AUC-drop associations, not causal effects or distinct business reasons.

Both additions independently reviewed: no required findings. Focused inventory + importance suites: 48 passed. Full combined gate is pending until concurrent training/calibrated-importance work stabilizes; do not infer full-suite success from these focused results.
