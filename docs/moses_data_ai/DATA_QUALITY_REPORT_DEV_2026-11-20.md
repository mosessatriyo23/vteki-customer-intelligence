# Offline data-quality report (FR-CDI-004 / T-CDI-04) — development only

Date 2026-11-20. Synthetic data only. Not acceptance of FR-CDI-004.

## What exists

`services/data/ingestion/quality_report.py` computes, per table of the synthetic inbound contract (`contracts.py`), five metrics, each with `numerator`, `denominator`, `metric_value`, `threshold`, `status`, `offending_records` and up to 100 `offending_row_numbers` (CSV line numbers, header = 1):

| Metric | Numerator (offending) | Denominator |
|---|---|---|
| completeness | rows with any empty non-nullable field (per-field counts also listed) | rows |
| validity | rows with a non-empty value that breaks enum / positive / non-negative integer / date / timestamp format or timezone (+07:00 required); CRM birth_month must be 1–12, member_code/tier presence must match, and populated tier must be BRONZE/SILVER/GOLD/PLATINUM (empty required values remain completeness only) | rows |
| uniqueness | rows whose primary key repeats an earlier row | rows with a non-empty key |
| timeliness | rows with a timestamp/date outside the manifest `observation_period` (`expires_at` excluded), or a timestamp that is naive / not +07:00 (never scored timely) | rows; `NOT_APPLICABLE` for tables without time fields |
| referential_integrity (one per FK) | non-empty FK values not found in the target table's key set | rows with a non-empty FK; `NOT_EVALUABLE` if the target table is absent |

CLI: `python -m services.data.ingestion.quality_report --inbound DIR --output-dir NEW_DIR --max-missing-rate .. --max-invalid-rate .. --max-duplicate-rate .. --max-untimely-rate .. --max-orphan-rate ..` (all five thresholds mandatory).

## Source requirement

- FRD FR-CDI-004 (`requirements/extracted_20261118/FRD_*.txt`, ~lines 7948–8213): compute completeness, validity, uniqueness, timeliness and referential integrity per entity and batch, compare against thresholds; a breach sets `QUALITY_WARNING` and blocks downstream feature refresh until acknowledged with a reason; fields `metric_name, entity, metric_value, threshold, status, acknowledged_by, acknowledged_reason`; audit events `QUALITY_THRESHOLD_BREACH`, `QUALITY_ACKNOWLEDGED`.
- Acceptance example: 8% of transactions missing amount vs a 5% threshold → violation shown, refresh blocked, proceeds only after acknowledgement with actor recorded. TRD 6.2 pipeline diagram (`thresholds ok?` → `QUALITY_WARNING: block downstream`) and TRD T-CDI-04 say the same.
- The FRD states **only the 5% figure, only as an acceptance example** for missing amount. It gives no thresholds for the other metrics, so none are defaulted: thresholds must be passed explicitly. The run below uses 5% for all five purely as a placeholder to exercise the code, not a business decision.

## Semantics and limits

- Breach rule: exact `offending / denominator > threshold` (strict; 5% exactly is not a breach). `metric_value` is rounded to 6 decimals for display only.
- Emits `QUALITY_WARNING` (`quality_warning: true`, `flags`, per-metric `status`, `warning_metrics`). `development_only: true`, `synthetic_data_only: true`.
- **Downstream blocking, acknowledgement (`acknowledged_by` / `acknowledged_reason`) and the two audit events are NOT enforced or emitted** — the JSON says so under `enforcement` (all `false` plus a note). That belongs to the platform (James). T-CDI-04's expected result ("blocked until acknowledged with a recorded actor") is therefore NOT met by this module; only the detection/flag half is.
- Timeliness is "inside the batch's declared observation window", not an ingestion-latency SLA; the FRD defines no such SLA, so none was invented.
- Per-entity only per table within one batch; no cross-batch trend. Rows are not quarantined; this is not the validator (`validator.py` is unchanged and remains the gate for schema/business rules; this report does not replace it).
- Header mismatch, malformed CSV shape, or a non-UTF-8 CSV raises `ValueError` naming the table, rather than being scored. Missing tables are listed in `missing_tables`; their inbound FKs report `NOT_EVALUABLE`, never silently OK.
- Observation window is validated like `BatchValidator`: both bounds present, ISO, timezone +07:00, `from <= to`. Otherwise timeliness is `NOT_EVALUABLE` for every time-bearing table and top-level `window_error` states why (`missing manifest` / `unparseable manifest` / `wrong shape` / `invalid observation_period`). `window_error` is `null` when the window is usable. Top-level `not_evaluable_metrics` lists every `entity:metric:field` skipped, so a reader of `quality_warning` can see what was not scored.
- Manifest binding: computed sha256 / row_count per table and the schema versions are compared with `generation_manifest.json` `tables[*]` and `schema_version`. Differences are listed in `manifest_mismatches`; `manifest_verified` is true only if the list is empty (a missing manifest is unverified). Report `schema_version` is the manifest-declared value (null if absent); `expected_schema_version` is the contract's. The report still computes metrics on mismatching data; it flags rather than blocks.
- `write_quality_report` raises `ValueError` if `report['inbound_dir']` differs from the resolved `inbound` argument.
- Remaining differences vs `BatchValidator` (by design, the validator stays the gate): no cross-table/semantic rules (accounting, membership chain, visits, chronology, date/timestamp window as a hard reject); date columns outside the window count under timeliness, not validity; unsafe empty values in required numeric fields are completeness only; `expires_at` is not window-checked; the validator's `birth_month` non-integer case is counted via the positive-integer rule here.
- Read-only on inputs; writes only `quality_report.json` into a new directory (fails if it exists or if it is inside the inbound dir). Output is `sort_keys` JSON; it embeds the absolute inbound path and per-file sha256, so it is identical for identical inputs at the same path.

## Tests

`tests/data/test_quality_report.py`: 26 test cases (9 original + 17 for review fixes), all pass. Original: 8% missing vs 5% threshold, clean fixture, duplicates, orphan FK, validity/timeliness vs window, exact-fraction comparison, bounded thresholds, determinism/no-overwrite/output outside inbound, CLI. New: mixed-timezone / naive / reversed window (4 params) gives `NOT_EVALUABLE` + `window_error`; valid window has no error; missing/unparseable/wrong-shape reasons; `not_evaluable_metrics`; naive / +00:00 / `Z` timestamps invalid and untimely (3 params); CRM birth_month / member_code-tier / tier enum; non-UTF-8 CSV names table; manifest binding verified; sha256+row_count mismatch reported; manifest schema_version mismatch flagged; missing manifest unverified; writer rejects mismatched `inbound_dir`. All new tests were written first and confirmed red (17 failed, 9 passed) before the fix.

Checks: `pytest tests/data/test_quality_report.py` 26 passed; `black --check`, `ruff check` clean; `mypy services/data/ingestion/quality_report.py` no issues. Full repo suite (combined branch, 2026-11-20): 1458 passed, 19 skipped (PostgreSQL, not acceptance), 3 xfailed; Ruff, Black and Mypy clean.

## Real batch run

**v1 (`artifacts/ingestion/quality_20261120_v1`) predates these fixes** (no manifest binding, no `window_error`, naive timestamps not flagged, CRM rules absent). It is kept unchanged; v2 supersedes it.

Input `inbound/2026-09-06` (synthetic generator 2.0.0, read-only), output `artifacts/ingestion/quality_20261120_v2/quality_report.json`. Thresholds 0.05 on all five (placeholder, not a business decision). All 10 tables present.

Result: **`quality_warning=false`**, `manifest_verified=true`, `manifest_mismatches=[]`, `window_error=null`, `not_evaluable_metrics=[]`, `schema_version` `2.0.0`. 54 metrics: 51 `OK`, 3 `NOT_APPLICABLE`; total offending records 0; 2,205,052 rows across tables.

| Table | Rows | sha256 (prefix) |
|---|---:|---|
| app_events | 76,603 | b3b0d2e2 |
| branches | 20 | 5229854c |
| catalogue_items | 160 | dc37065f |
| consent_events | 244,000 | 7f689726 |
| crm_customers | 61,000 | 01daade1 |
| customer_visits | 204,367 | 1ba5cdc8 |
| membership_events | 63,464 | 986f0630 |
| service_cases | 1,905 | 86139150 |
| transaction_items | 1,109,522 | 3c26c2c2 |
| transactions | 444,011 | 4f11ebe3 |

`timeliness` is `NOT_APPLICABLE` for branches, catalogue_items, transaction_items (no time fields). Counts match v1 and the manifest, and the new stricter validity/timezone/CRM rules found nothing. This shows the report runs at full size, **not** that the breach path works on real data (fixtures only).

## Remaining for FR-CDI-004

Business-approved per-metric thresholds; persistence of metric records; per-batch status lifecycle; downstream refresh block; acknowledgement API with actor/reason; audit events; a quality page. These are platform/James work and are not claimed.
