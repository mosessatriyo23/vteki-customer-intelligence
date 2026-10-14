# Ingestion schema v2 — development baseline

Branch: `feat/data-ingestion-quality-v2`.

## Inspection findings

On inspected main, migrations/versions contains only .gitkeep; there are no ORM models,
Alembic configuration or ingestion implementation. PostgreSQL 15 is configured in
Compose, but application Dockerfiles referenced by Compose are absent. Do not claim
production PostgreSQL integration is complete.

## Implemented

- `services/data/ingestion/contracts.py`: explicit ordered source schema 2.0.0, nullability,
  PK/FK, integer constraints, dates, timestamps and principal enums.
- `validator.py`: source-only streaming validation, checksum verification, strict headers,
  manifest counts, disk-backed PK/FK checks, monetary reconciliation, customer chronology,
  membership chains, consent expiry, and transaction-backed visits.
- `staging.py`: development SQLite raw JSON staging, transactional all-or-nothing batch,
  content/config-derived batch ID and idempotent replay. Post-load hashes detect files
  changed between validation and ingestion.
- `cli.py`: validate-only or development staging CLI with optional JSON rejection report.
- `tests/data/test_ingestion.py`: valid batch, schema/checksum rejection, ground truth
  declaration rejection, deliberate null customer reference, idempotency and rollback.
- `tests/data/test_ingestion_negative.py`: duplicate PK, unknown FK, invalid type/enum/time,
  and header mismatch.

## Commands (WSL)

```bash
python3 -m services.data.ingestion.cli --inbound inbound/2026-09-06 --report artifacts/ingestion/validation.json
python3 -m services.data.ingestion.cli --inbound inbound/2026-09-06 --sqlite-staging artifacts/ingestion/staging.sqlite --report artifacts/ingestion/load.json
python3 -m unittest -v tests.data.test_ingestion tests.data.test_ingestion_negative
```

Source input contains only the 10 allowlisted CSV names. Ground truth declarations in
manifest `tables` are rejected. The separate `ground_truth_tables` manifest section is
not loaded or read. Phone/email noise and blank transaction customer references are
preserved, not merged or dropped.

## James handoff (PROPOSED)

PostgreSQL staging needs `ingestion_batches` (batch ID unique, schema/seed/as-of/checksums,
loaded_at/status) and `ingestion_raw_rows` (batch ID, source table, source ID, JSONB
payload; composite unique key). A rejected batch must expose validation reasons and
must not publish partial accepted rows. Use a separate evaluation-only role/schema
for ground truth; ingestion must not require access to it. Implement typed business
tables and Alembic migrations together after agreeing naming and ORM ownership.

SQLite is development-only and does not demonstrate PostgreSQL transactions/COPY,
concurrency or production permission isolation. No migration is applied to James's work.

## Executed validation

12 generator/business/ingestion regression tests PASS. SQLite staging runs also passed
for 500 golden customers (610 source, 4344 transactions, 10905 items) and 2000 golden
customers (2440 source, 17922 transactions, 44902 items), generated/stored outside repo.

## Remaining gates

- Additional negative tests for semantic chains/chronology and all conditional enums.
- Persist complete quarantine records (current report limits examples to 100; error counts
  cover all detected violations). Current policy rejects entire invalid batch, not partial loading.
- Production-sized ingestion performance test and bounded-memory semantic indexes (visit
  and membership checks currently hold source subsets in memory).
- PostgreSQL adapter and integration tests require agreed schema/database availability.
- Existing fixtures/intg_v1 remain unchanged; review migration before replacing tracked large CSVs.
