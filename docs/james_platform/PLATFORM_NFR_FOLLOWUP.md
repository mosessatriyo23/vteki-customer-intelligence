# Platform operational NFR follow-up

**Status:** Separate from Gate C; open operational work
**Owner:** James — Platform
**Updated:** 17 November 2026

These items concern production runtime readiness. They do not establish
historical data correctness and do not block the Gate C evidence review. They
must remain tracked independently and must not be marked complete without the
listed operational evidence.

| Work item | Current status | Required evidence | Gate C dependency |
|---|---|---|---|
| Worker load and failure testing on PostgreSQL | **OPEN** | Multi-process advisory-lock contention, timeout, retry, cancellation, recovery and pipeline duration on representative workload | None; separate operational review |
| Audit trace SLA and pagination/truncation | **OPEN** | `EXPLAIN (ANALYZE, BUFFERS)` and end-to-end benchmark on agreed volume; deterministic pagination or explicit truncation behavior; measured latency ≤300 seconds if that remains the agreed SLA | None; separate operational review |
| Backup/restore drill | **OPEN** | Isolated restore from encrypted backup; measured RPO/RTO; verify schema, ledger counts, append-only triggers, role grants, API health and acceptance tests | None; separate operational review |
| Runtime least-privilege login isolation | **PARTIAL** | CI role grants/login checks exist; prove deployed API/worker use distinct non-superuser login credentials from secret manager and verify privileges against deployed DB | None; separate deployment/security review |
| Physical partitioning decision | **NOT DECIDED** | Table, key, retention, PK/unique/FK requirements, volume evidence and migration plan before any partition DDL | None unless data volume/retention requires it |

Review/update cadence and target dates are **PENDING** an operational owner and
production environment. This file records scope and evidence gates; it does
not imply that a drill or benchmark has been scheduled or performed.
