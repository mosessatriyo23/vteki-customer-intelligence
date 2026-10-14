# Identity CLI hardening — executed regression

CLI now exposes a callable `run(source, output_dir, synthetic_aliases=False,
prior_mapping=None)` and versioned output contracts. Published output directories must
not be overwritten; use a new empty directory for every run. Output directories cannot
contain source files or prior registries. Input/prior checksums are checked before output
creation, and semantic prior-registry failures do not publish outputs. CSV files are
written through temporary files; however the complete multi-file directory publication
is NOT atomic and process-crash recovery is still outstanding. Consumers must verify
resolution_manifest.json and its output checksums before use.

`tests/data/test_identity_cli.py` tests output schemas/review counts/checksums,
reproducible mapping bytes, prior registry schema rejection for truth, preserving a
published ID, refusing output overwrite, and conflicting prior merges leaving no output.
All 24 generator/business/ingestion/identity tests passed in the executed regression.

This stage does not implement PostgreSQL registry or human review approvals. Published
IDs require a reviewed prior mapping; schema validation alone cannot establish that a
registry was genuinely reviewed. Maintain provenance and access controls operationally.

Next: agree Customer360 profile/event contracts with explicit provisional identity/review
status. Never treat the resolver's heuristic_score as calibrated probability. Do not train
models on evaluation ground truth or on future events.
