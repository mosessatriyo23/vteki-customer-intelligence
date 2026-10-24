# Penyelesaian Scope James — Evidence & Integrasi (`main` 32d89a0 + James 3167ec4)

**Owner:** James, Platform Architect / Security / Full-Stack Interface Lead
**Status:** Paket integrasi tahap 1 untuk diverifikasi dan direview tim. **Bukan** jaminan semua NFR selesai.

## Keputusan arsitektur yang dapat dilaksanakan tanpa mengubah kontrak Moses

### Skema dan ERD ringkas

```text
stg.ingestion_batches (batch_id PK, checksum manifest, status PUBLISHED)
  ├── stg.ingestion_raw_rows (PK batch_id, table_name, source_id)
  └── source.{crm_customers,transactions,...} (typed validated input)

identity.registry_versions (version_tag PK)
  ├── identity.golden_customers (golden_customer_id PK)
  │     └── identity.source_identity_mapping (source_customer_id PK, golden_customer_id FK)
  ├── identity.match_decisions (batch, version, reason, match score)
  └── identity.review_queue → identity.review_audit_log (append-only)

customer360.profile_snapshots
  UNIQUE (golden_customer_id, cutoff_at, identity_registry_version, rule_version)
  FK golden_customer_id → identity.golden_customers
  FK identity_registry_version → identity.registry_versions

segmentation.rfm_lifecycle_snapshots
  UNIQUE (golden_customer_id, cutoff_at, identity_registry_version, rule_version)
  FK golden_customer_id → identity.golden_customers
  FK identity_registry_version → identity.registry_versions

gov.audit_event (request_id, correlation_id, occurred_at) -- immutable trigger
```

Alembic revisions `0009` dan `0010` sudah berisi tabel registry, typed input, snapshot, constraint IDR nonnegative, append-only trigger, dan index timeline. Jangan menjalankan SQL manual dan Alembic dua kali. Semua transaksi uang pada snapshot memakai INTEGER/BIGINT IDR, bukan float. Datetime `cutoff_at` diwajibkan timezone-aware; input source v2 memerlukan offset `+07:00`. Pastikan `timestamptz` diterapkan di PostgreSQL.

**Partisi fisik PostgreSQL:** schema `core/stg/feat/ml/dec/act/msr/gov` tidak sama dengan *table partitioning*. Fisik partisi `gov.audit_event` atau tabel fakta belum ada; migrasi fisik memerlukan desain primary/unique key yang melibatkan partition key, backfill, rencana cutover, dan persetujuan DBA. Jangan otomatis mengganti tabel audit yang sudah dipakai transaksi.

### Publish & rollback serving (tahap 1)

- `services.data.customer360.publish.publish_serving_snapshots` memeriksa bahwa `batch_id` sudah PUBLISHED dan `registry_version` ada.
- Profil dan RFM harus memiliki pasangan Golden ID/cutoff yang sama. Normalisasi cutoff ke UTC dipakai untuk validasi pasangan, bukan untuk mengganti timestamp historis.
- Kedua adapter memakai **satu transaksi DB** (`session_factory.begin()`); kegagalan integer IDR, unique constraint, FK, atau output RFM akan rollback penulisan C360 juga. Replay natural key identik no-op, konflik replay ditolak tanpa rewrite.
- **Batas transaksi tetap dua tahap:** ingestion source `PUBLISHED` dalam transaksi loader sendiri, lalu serving C360+RFM dalam transaksi terpisah. JANGAN menyebut ingestion+identity+serving 100% atomik. Perlu state/manifest tersendiri untuk kesiapan serving lintas tahap, serta retry/recovery saat identity gagal.
- Berkas ground truth sintetis tidak boleh masuk resolver atau serving.

### API & frontend

`GET /customers/golden` (maks 200) dan `GET /customers/golden/{golden_id}` memuat snapshot terbaru per Golden ID beserta status dan lifecycle jika cocok `cutoff`, `registry_version`, **dan `source_batch_id`**; tidak bergabung ke `core.customers` demo. `GET /customers/golden/{golden_id}/provenance` menyediakan mapping sumber serta riwayat review untuk admin/analyst saja. JWT/RBAC diwajibkan; response tidak membocorkan email/nomor telepon. Endpoint `/customers` lama sengaja dipertahankan agar campaign dan NBA yang masih memakai `core.customers.id` tetap berjalan. **Tidak ada pemetaan otomatis** dari Golden ID ke demo Customer ID karena keduanya belum memiliki kontrak join resmi.

UI Customer 360 memiliki panel terpisah **Golden Customer — Snapshot PostgreSQL**, dengan label PROVISIONAL/REVIEW_REQUIRED yang eksplisit dan tautan ringkas provenance bagi admin/analyst. Frontend preview hanya dapat dinyalakan secara eksplisit saat Vite development dengan `VITE_ENABLE_LOCAL_PREVIEW=true`; production build selalu mewajibkan login. Jangan mengaktifkan pengiriman campaign sungguhan.

## Checklist verifikasi teknis dan penerimaan

| Area / tujuan | Bukti saat ini | Bukti tambahan sebelum dinyatakan DONE |
|---|---|---|
| JWT/bcrypt/RBAC | Endpoint role-protected, tes unit existing | Matriks semua persona/endpoint, refresh/logout, uji 401/403 & review permission |
| Audit append-only | Alembic 0010 trigger dan correlation middleware | Live PostgreSQL menolak UPDATE/DELETE, termasuk akses role layanan, retensi PII disetujui |
| Trace ≤ 5 menit | Index `ix_gov_audit_trace_timeline`, API decision trace | `scripts/benchmark_james_trace.py` pada data dengan ukuran realistis, `EXPLAIN ANALYZE`, dokumentasikan P95 dan rekonstruksi lengkap, bukan cuma latensi query kosong |
| Worker SLA ≤ 60 menit | Advisory lock dan cooperative budget check | Watchdog/isolasi proses untuk handler hang; timeout saat handler tak kembali; tes dua proses PG dan crash/recovery, hasil pending/RUNNING lama direkonsiliasi |
| CI/CD | Workflow Ruff/Black/MyPy/Schemathesis/allowlist/Vite | GitHub Actions commit final hijau, buktikan di PR; cek coverage 422 email & resource setup |
| PostgreSQL / migrations | 0009/0010, scripts DB role | `alembic upgrade head` di DB test PG15; uji rollback/error, role matrix, dan inspeksi partitioning |
| Serving publish | Adapter baru + tes SQLite | Uji PostgreSQL dengan real transaction/constraint/lock; batch besar; atomic visibility pada transaksi concurrent |
| Frontend persona / UI | React Customer360/approval/NBA/drift/audit | `npm ci && npm run build`; E2E admin/analyst/reviewer/manager/operator pada backend nyata |
| Effective time / multi-batch | Schema v2 + PIT baseline dev | Kontrak `available_at` immutable, master SCD2, idempotency lintas batch/PK, cutover dan migration disetujui Moses |
| Readiness model bisnis | Masih PROPOSED sesuai handoff Moses | Christ menyetujui definisi lifecycle/churn/CLV/consent; training_ready tidak boleh diubah sepihak |

## Jalankan verifikasi (Windows PowerShell)

```powershell
# Terminal pada root repo
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m black --check api worker migrations tests/security/test_auth.py tests/worker
.\.venv\Scripts\python.exe -m mypy services api worker --ignore-missing-imports
.\.venv\Scripts\python.exe -m pytest -q
Push-Location web
npm ci
npm run build
Pop-Location

# Opsional, setelah menyiapkan PostgreSQL test: jalankan hanya terhadap DB non-produksi
.\.venv\Scripts\alembic.exe upgrade head
# Jika sudah memiliki token admin/analyst & correlation dengan event nyata:
$env:VTEKI_TEST_JWT = '<temporary JWT from dev environment>'
.\.venv\Scripts\python.exe scripts/benchmark_james_trace.py --correlation-id '<correlation-id>' --repetitions 5
Remove-Item Env:\VTEKI_TEST_JWT
```

Jangan menaruh JWT, password atau `DATABASE_URL` produksi di repository dan laporan uji. Untuk DB roles, jalankan `scripts/db_permissions.sql` setelah migrasi dengan DBA di database uji lalu konfirmasi setiap service principal tidak mendapat hak UPDATE/DELETE pada `gov.audit_event` dan `identity.review_audit_log`.

## Keputusan yang masih harus disahkan tim

1. **Moses:** sumber `available_at` aktual per transaksi/refund/status dan versioning historis; collision source PK antarbatches: fail sekarang versus upsert/SCD2; satu sumber canonical Golden ID ketika merge/split yang mempengaruhi snapshot lama.
2. **Christ:** taxonomy business persona/campaign eligibility, definisi KPI observed vs incremental, label RFM/lifecycle dan batas penggunaan AI pada data PROVISIONAL; consent/suppression rules.
3. **James + DBA:** masa simpan PII/audit, DB role owner/credential rotation, migrasi partisi PG, rollback setelah serving transaction berhasil, dan definisi recovery job 60 menit dengan isolated subprocess/queue.
4. **Seluruh tim:** definisi DONE untuk pipeline (source published ≠ serving ready), volume benchmark SLA, serta approval sebelum readiness flag berubah dari `false`.

**Kesimpulan teknis:** migrasi, identity registry, loader, audit, worker, dan UI awal telah diimplementasikan pada baseline. Paket tahap 1 menambahkan atomic serving publish dan API/UI Golden snapshot yang belum tersambung. Target SLA produksi, migrasi partisi fisik, semantics effective-time, serta hard worker timeout **belum bisa ditandai DONE** sampai pengujian dan keputusan terkait selesai.
