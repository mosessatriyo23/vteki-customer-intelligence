# PostgreSQL integration smoke — 2026-10-15

Executed against PostgreSQL 15 in Docker, after synchronizing origin/main at 541bdd1.
A disposable database was created, migrated to revision
0009_data_contracts_and_persistent_identity and removed after testing. Main development
DB was not populated. No API, worker or campaigns were started.

## Executed checks

- Generated a 20-customer fixture (not the full dataset).
- Ingested 1080 raw rows; checked total against validated manifest row counts.
- Replayed ingestion: ALREADY_LOADED.
- Injected a post-load checksum failure on a second batch: transaction rolled back,
  zero raw rows remained for that batch, and a REJECTED batch record was logged.
- Applied resolver mapping for 24 source identities and replayed registry assignment.
- Saved 20 Customer360 and 20 segmentation snapshots twice; checked row counts stable.
- All checks passed after the sequential decision-replay fix below.

## Defect found and minimal fix

Registry used session.merge() on MatchDecision without its generated primary key.
It attempted INSERT rather than matching the natural unique key
(source_batch_id, left_source_id, right_source_id). Replaying a batch failed with
PostgreSQL UniqueViolation. Registry now looks up existing decisions by that key,
keeps identical published decisions, and rejects changed version/evidence rather
than overwriting provenance. Added regression coverage in test_persistence.py.

After fix: pytest tests/data tests/security tests/worker -q => 72 passed, one library
deprecation warning. These tests predominantly use SQLite; the PostgreSQL smoke above
is a separate manual integration check, not a permanent PostgreSQL CI test.

## Remaining limits

- Sequential replay only: concurrent writer locking/idempotency is not proven.
- Registry review approval/merge semantics and permission isolation not verified here.
- Registry mapping updates are not an immutable historical identity registry.
- Ingestion currently publishes JSON raw rows in stg.ingestion_raw_rows; existence of
  source schema tables does not mean they are populated by this loader.
- No full-scale ingestion, API/dashboard integration or predictive training claimed.
- Snapshot replay may update generated_at; stable count is not immutable publication.
- Compose currently exposes PostgreSQL on host interfaces; bind localhost for local-only
  deployment or apply suitable firewall controls. Do not expose development DB publicly.
