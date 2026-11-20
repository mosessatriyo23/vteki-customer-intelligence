# Ingestion validation evidence — 2026-11-20

Branch: `feat/moses-closure-evidence`.

## Update — independent retry succeeded (first run still timed out)

The original timeout evidence below is preserved. A separate validation-only retry with a **new** report path completed successfully:

```powershell
.venv\Scripts\python.exe -m services.data.ingestion.cli --inbound inbound/2026-09-06 --report artifacts/ingestion/validation_20261120_bg_v2/report.json
```

`artifacts/ingestion/validation_20261120_bg_v2/run_status.txt` records `exit=0 seconds=345`; `report.json` reports `valid=true`, `schema_version=2.0.0`, `errors={}`, `rejections=[]`. Its ten row counts match the manifest row counts listed below (2,205,052 rows total). This is **source-only batch validation**, not database load, latency SLA, or proof that an independent repeat always completes within 600 s. The cause of the first >600 s timeout is not established; environment/load differences are possible but unverified. Both report directories are preserved.

## Original attempt: NOT VALIDATED (timed out)

The validation-only run of `services.data.ingestion.cli` did **not complete** within the 600,000 ms tool timeout. The harness reported "Command exceeded timeout of 600000 ms". No matching ingestion CLI process was present in the subsequent process check. No `report.json` was written and no exit code was captured. This is **not** evidence that the batch is valid, and it is not evidence that it is invalid. The run did not produce a verdict.

I did not change the implementation or retry with a different setup.

## Batch

- Path: `inbound/2026-09-06` (the batch referenced in `ingestion_v2.md`). It is local and ignored by git, and it is synthetic.
- Its `generation_manifest.json` declares schema 2.0.0, generator `vteki-synthetic-data` 2.0.0, seed 20260906 and as-of 2026-09-06.
- After the timed-out run, I recomputed SHA-256 for all ten CSVs with `Get-FileHash`. Every hash matches the manifest value below. This is a separate file-integrity check made by me, not the validator's output. It does not show that schema, keys, references or arithmetic are valid.

| File | Manifest rows | Manifest SHA-256 |
|---|---:|---|
| app_events.csv | 76,603 | b3b0d2e21ed7ce1d7f30cb0221d01bdaa44e17b37934976a0f0141d09fc2a499 |
| branches.csv | 20 | 5229854ce684da34b179217cab2ffd22caf40b346e264be354d36283bc45ab39 |
| catalogue_items.csv | 160 | dc37065fef5311edfdb9334ee9ad768e62ecf7399c8c79e908b125dd0769f04d |
| consent_events.csv | 244,000 | 7f689726e0166da94b1dc16c4e03fff7f441a651c9b47a1fbde4a2590d5e7346 |
| crm_customers.csv | 61,000 | 01daade1d8f8e44bf30257ab2803ef421d6c9bf54f64359bbe34776ffbcb684a |
| customer_visits.csv | 204,367 | 1ba5cdc80f278e3e15428dee24bc4e5868ae92ddde00273cfb5f11e923e4c6be |
| membership_events.csv | 63,464 | 986f06300ce200bc7d28ac27797876c1d305da5db6833ba73477eb9d3537737f |
| service_cases.csv | 1,905 | 861391509fe64dd32b0ee400ebb4253bf47f36c4a9a20c6a83eed5ae70e30037 |
| transaction_items.csv | 1,109,522 | 3c26c2c2e8e7adc53b3273986b4f6f3c0616718fba86d0e34e92979fe30d5b8d |
| transactions.csv | 444,011 | 4f11ebe3b35f9fc5234dc12ef7cd6fa52925143f81be06bd2aad87fc88eebed2 |

The ten tables total 2,205,052 declared rows (sum of the column above).

## Command

PowerShell, run from the repo root:

```powershell
.venv\Scripts\python.exe -m services.data.ingestion.cli --inbound inbound/2026-09-06 --report artifacts/ingestion/validation_20261120_6d82c4f0/report.json
```

- The command was wrapped in a script that refused to run if the report path already existed. The path was new, so nothing was overwritten.
- Duration: at least 600 s, until the timeout. The exact duration is unknown because the stopwatch output was lost when the run was killed.
- Exit code: not captured.
- `artifacts/ingestion/validation_20261120_6d82c4f0/report.json` was **not created**. A check after the timeout found no file at that path.
- No `cli` process was left running. The only `python.exe` processes found afterwards were two unrelated `pytest tests/data/test_quality_repor...` runs. I did not start them and did not touch them.

## What this run was and was not

- **Validation-only.** `--sqlite-staging` was not passed, so the CLI would have called `BatchValidator().validate(...)` and nothing else. That is the same code path the CLI takes when only `--report` is given.
- **No database loading.** Neither SQLite staging nor PostgreSQL was used. This is not a PostgreSQL integration run. The separate SQLite staging path was not exercised.
- **Ground truth was not used.** The CLI is source-only. The manifest's `ground_truth_tables` and `ground_truth_checksums_sha256` sections (for example `identity_mapping.csv`) are not read as input. `ingestion_v2.md` states this behaviour. I did not verify it with a run.
- **No predictor involvement.** Nothing here trains, scores or evaluates a model.

## Likely cause and what is unproven

`ingestion_v2.md` lists "production-sized ingestion performance test and bounded-memory semantic indexes" as a remaining gate. That batch is about 2.2 million rows, with 1.1 million item rows. Its prior documented validation runs used 500 and 2,000 golden customers, not this 50,000-customer batch. A performance limit is consistent with the timeout, but I did not profile the run, so it is a hypothesis. A hang or a defect has not been ruled out.

## Verification performed

- Confirmed the branch is `feat/moses-closure-evidence`. `git status --porcelain` showed no changes before the run.
- Confirmed `.venv\Scripts\python.exe` exists and that `artifacts/ingestion` did not exist beforehand.
- Read `services/data/ingestion/cli.py`. Without `--sqlite-staging` it only validates and prints JSON. It writes the report after validation, which is why a killed run left no report.
- Confirmed no report file exists after the timeout.
- Recomputed the ten CSV SHA-256 hashes: all match the manifest. Row counts were not recounted.
- `git status` after the run shows other uncommitted files that I did not create (other docs, `quality_report.py` and tests). I did not stage or commit anything.

## Next step (not done)

Run the same command with no timeout limit, or run it in the background, using a new report path. To find the slow stage, profile it or run it on a smaller batch such as the 500-customer one. Treat the batch as validated only after a report with `valid: true` exists and its row counts and checksums match the manifest above.
