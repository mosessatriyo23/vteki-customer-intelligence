# Status penyelesaian tugas James — Orang 3

Tanggal audit: 24 Oktober 2026. Basis kode yang diperiksa: branch `71230971-James-Marvin-3` terhadap `main` di repository VTEKI Customer Intelligence.

## Ringkasan

Fondasi platform sudah cukup banyak tersedia. Paket penyelesaian ini menutup tiga celah implementasi yang bisa ditangani di kode tanpa mengubah algoritma Data Engineering: timeout worker yang benar-benar membatalkan handler macet, validasi/immutability snapshot, dan regresi pengamanan yang dijalankan melalui CI. Paket ini juga menambahkan tes integrasi PostgreSQL untuk append-only audit dan privilege role.

**Tugas belum boleh diberi status 100%** sampai workflow GitHub Actions berhasil pada commit hasil perubahan, migrasi diuji terhadap PostgreSQL, dan blocker operasional di bagian terakhir mendapat keputusan. Tidak ada benchmark produksi yang bisa digantikan oleh tes unit kecil.

## Matriks tanggung jawab

| Area | Kondisi saat audit | Perubahan / bukti dalam paket | Status realistis |
|---|---|---|---|
| Delapan schema domain + Alembic | Schema `core, stg, feat, ml, dec, act, msr, gov` dan migrasi tersedia; migrasi identity/snapshot juga ada | Tes PostgreSQL memeriksa schema, indeks trace, panjang CRM ID, dan unique key snapshot | Implementasi tersedia; migrasi nyata wajib lulus CI/DB |
| PostgreSQL table partitioning fisik | Tidak ada strategi partition key, retensi, batas data, atau kebutuhan FK yang disetujui di kontrak saat ini | Tidak mengubah tabel besar secara destruktif tanpa keputusan desain | Blocker keputusan arsitektur jika yang dimaksud adalah `PARTITION BY` fisik; schema/domain terpisah bukan partisi tabel |
| JWT, bcrypt, RBAC endpoint | JWT/bcrypt dan `require_roles` ada; route sudah punya dependensi auth | Tes statis gagal jika endpoint bisnis baru ditambahkan tanpa dependensi `get_current_user` | Menambah regresi otomatis; CI harus lulus |
| Audit append-only + correlation ID | `gov.audit_event`, audit review, trigger append-only, correlation ID dan trace endpoint tersedia | Tes PostgreSQL mencoba UPDATE/DELETE dan memastikan ditolak; indeks timeline diverifikasi | Implementasi tersedia; tes PostgreSQL perlu lulus |
| SLA audit trace ≤ 5 menit | Query sudah memiliki indeks; endpoint rekonstruksi membatasi hasil menjadi 2.000 audit event dan 100 decision trace | Belum ada data volume produksi yang disepakati untuk load test | **Belum terbukti**. Batas hasil juga berarti trace tidak lengkap jika satu correlation ID melebihi limit tersebut |
| Worker APScheduler + run lock + NFR 60 menit | Advisory lock dan budget ada, tetapi sebelumnya handler yang macet hanya terdeteksi setelah kembali | Handler produksi sekarang harus pickleable/importable dan dijalankan sebagai child process; watchdog terminate/kill saat deadline habis; tes regresi ditambah | Implementasi code ditambahkan; tetap perlu lulus CI dan uji beban di worker/DB nyata |
| CI/CD dan allowlist dependensi | Workflow lint, mypy, pytest, T-SEC-03, Schemathesis, migration PostgreSQL, dan Vite build tersedia | CI kini juga menyiapkan role groups dan menjalankan tes governance PostgreSQL setelah migrasi | Belum terverifikasi sampai workflow selesai hijau |
| Customer 360 & RFM snapshots | Adapter dan unique key sudah ada; adapter sebelumnya mengubah snapshot yang telah terbit pada key/version sama | Validasi semua row dilakukan sebelum menulis; replay identik menjadi no-op dan mempertahankan `generated_at/source_batch_id`; payload berbeda pada key yang sama ditolak; tes ditambah | Implementasi code ditambahkan; cek regresi wajib lulus |
| Ingestion CSV → PostgreSQL | Validator source-only, checksum, raw/staging, typed tables, advisory transaction lock, rollback, dan idempotency batch sudah ada | Tetap memakai kontrak 10 CSV; tidak mengganti data contract tim | Fondasi tersedia; tes PostgreSQL nyata tetap diperlukan |
| Persistent identity registry | Golden ID, mapping, match decisions, review queue, registry versions, anti-silent-merge/split dan review audit sudah ada | Tetap memakai resolver source-only; tidak memasukkan synthetic ground truth | Fondasi tersedia; kebijakan rekonsiliasi downstream masih perlu keputusan |
| Role database writer/reviewer/reader | `scripts/db_permissions.sql` sudah mendefinisikan role group least privilege | CI menjalankan SQL dan memeriksa privilege baca/tulis per role | Memvalidasi grants, bukan membuktikan runtime sudah memakai login yang terisolasi |
| React/Vite lintas persona | Menu/halaman utama dan endpoint backend sudah ada; pipeline CI mem-build Vite | Tidak membuat ulang UI karena baseline telah tersedia | Build CI perlu lulus; tes browser end-to-end per persona belum tersedia |

## Detail kontrak snapshot

Composite key tetap:

- Customer 360: `(golden_customer_id, cutoff_at, identity_registry_version, rule_version)`.
- RFM/lifecycle: `(golden_customer_id, cutoff_at, identity_registry_version, rule_version)`.

Replay dengan payload sama tidak mengganti metadata penerbitan. Jika payload berbeda dengan composite key yang sama, proses menolak publikasi: ubah `rule_version` atau `identity_registry_version` dengan sengaja agar perubahan dapat diaudit. Setiap batch divalidasi seluruhnya terlebih dahulu; nilai uang menerima integer IDR, bukan float/bool, dan timestamp harus offset-aware.

## Cara validasi setelah patch diterapkan

Workflow GitHub Actions akan menjalankan tes unit/security, meng-upgrade migrasi pada PostgreSQL 15, menerapkan `scripts/db_permissions.sql`, memverifikasi append-only trigger, schema/index/unique key, dan privilege, kemudian menjalankan tes API Schemathesis dan build React/Vite.

Untuk validasi lokal PowerShell dari root repo:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m black --check api worker migrations tests/security/test_auth.py tests/security/test_route_rbac_coverage.py tests/worker tests/data/test_snapshot_atomicity.py tests/integration/test_postgres_platform.py
.\.venv\Scripts\python.exe -m mypy services api worker --ignore-missing-imports
Push-Location web
npm ci
npm run build
Pop-Location
```

Tes PostgreSQL lokal memerlukan environment variable `VTEKI_TEST_POSTGRES_URL` yang menunjuk database testing **yang sudah menjalankan `alembic upgrade head` dan `scripts/db_permissions.sql`**. Jangan menjalankan tes ini pada database produksi.

## Blocker yang tetap wajib dituntaskan

1. **SLA audit trace:** tentukan volume/retensi dan ukuran trace yang harus didukung; benchmark `EXPLAIN (ANALYZE, BUFFERS)` + request end-to-end pada dataset representatif untuk bukti ≤300 detik. Tentukan juga apakah endpoint harus menyediakan pagination/truncation marker bila trace lebih besar daripada batas hasilnya.
2. **Worker NFR-01:** jalankan worker pada PostgreSQL nyata untuk menguji advisory lock lintas proses, timeout setiap handler, retry/cancellation, serta total pipeline di bawah 3.600 detik pada input realistis. Handler yang dihentikan paksa harus idempotent dan tidak boleh meninggalkan side effect eksternal yang tidak dapat diulang.
3. **DB runtime role isolation:** role group dan grant sudah disiapkan, tetapi Compose masih menggunakan konfigurasi koneksi `POSTGRES_USER` yang sama bagi service API/worker. Proses runtime dengan least privilege perlu akun login/service terpisah; pemisahan tersebut harus konsisten dengan fakta bahwa API saat ini menyatukan banyak persona dan operasi.
4. **Physical table partitioning:** jangan menambah `PARTITION BY` tanpa menyepakati tabel sasaran, partition key, retensi, uniqueness/PK, foreign key, dan migrasi data historis. Kalau kebutuhan tugas hanya pemisahan domain schema, schema yang ada sudah memenuhi maksud tersebut.
5. **Frontend persona E2E:** perlu browser test untuk login, role admin/analyst/operator/campaign manager, workflow approval, identity review, NBA override, dan audit trace, bukan hanya production build.
6. **GitHub release:** merge perubahan melalui Pull Request setelah semua job CI yang baru dan lama berhasil. Jangan merge otomatis saat CI merah.

## Batas cakupan yang sengaja dipertahankan

- Tidak ada mode bypass login atau penurunan RBAC.
- Tidak ada pengiriman campaign ke provider eksternal; channel tetap simulator.
- Tidak ada perubahan kontrak CSV v2 atau penggunaan synthetic ground truth sebagai input resolver.
- Tidak ada klaim bahwa SLA produksi, keamanan deployment, atau E2E UI sudah lulus sebelum ada hasil pengujian nyata.

## Pembaruan status — 26 Oktober 2026

PR #16 telah berhasil di-merge ke `main`. Workflow CI pada PR (run `40194042823`) dan setelah merge ke `main` (run `40194220485`) berhasil.

Pemeriksaan yang berhasil meliputi Ruff, MyPy, Black, tes Python, migrasi PostgreSQL, tes governance dan hak akses database, pengujian API Schemathesis sesuai konfigurasi saat ini, serta production build frontend.

**Catatan:** Fase Coverage Schemathesis sementara dilewati karena masalah timeout. Keberhasilan CI ini tidak berarti seluruh fase pengujian kontrak API sudah selesai.

Implementasi inti telah melewati pemeriksaan CI yang dikonfigurasi. Namun, penyelesaian keseluruhan masih memerlukan pembuktian SLA audit trace, pengujian operasional worker, isolasi akun database runtime, serta pengujian frontend end-to-end untuk setiap role.

## Pembaruan status - 15 November 2026

Branch yang diperiksa: `fix/schemathesis-coverage-diagnostic`.

### Bukti validasi lokal terbaru

| Pemeriksaan | Hasil |
|---|---|
| Seluruh test suite | 831 passed |
| PostgreSQL integration | 8 passed |
| Ruff | All checks passed |
| Black | 160 files unchanged |
| Alembic heads | Satu head: `0016_transaction_event_provenance` |
| Alembic current pada database scratch | `0016_transaction_event_provenance (head)` |
| Database migrasi scratch | `vteki_migration_scratch` |

Pengujian PostgreSQL menggunakan database scratch, bukan database utama.
Hasil ini merupakan validasi lokal dan bukan bukti CI GitHub terbaru atau
production readiness.

### J-PLAT-01 - Transaction event availability dan lineage

Implementasi yang tersedia:

- Migration `0015_transaction_event_history` membuat tabel event history.
- Migration `0016_transaction_event_provenance` menambahkan actor/source
  provenance dan pengamanan timestamp penerimaan database.
- Loader PostgreSQL membuat baseline `TRANSACTION_RECORDED`.
- Service event mendukung pencatatan event, idempotency, dan referensi
  correction.
- Query as-of menerapkan batas `occurred_at` dan `available_at`.
- Tes PostgreSQL bitemporal correction telah berhasil dijalankan.

Dokumen kontrak telah dibuat di:
`docs/james_platform/approved/historical_data_contract_v1.x.md`.

Status: **IN PROGRESS**.

Pekerjaan yang masih diperlukan:

- Integrasi feed historis refund dan perubahan status dari sumber.
- Final-state projection yang menangani correction secara deterministik.
- Tes correction chain, beberapa refund, status change, replay konflik,
  concurrency, dan stabilitas snapshot historis.
- Review serta persetujuan kontrak oleh pemilik data dan lintas tim.

Event baseline tidak membuktikan histori refund/status sebelum ingestion.
Jangan mengklaim histori transaksi lama telah lengkap.

### J-PLAT-02 - Identity as-of

Implementasi yang tersedia:

- Migration `0013_identity_mapping_history`.
- Migration `0014_identity_batch_assignment_unique`.
- `get_mapping_as_of()` untuk pembacaan identity mapping berdasarkan waktu.
- `build_profiles_as_of()` untuk Customer360 menggunakan mapping historis.
- Pengujian unit dan integrasi PostgreSQL telah dijalankan.

Status: **IMPLEMENTED PARTIALLY - VERIFICATION PENDING**.

Skenario split identity, unresolved identity, dan rekonstruksi dampak
downstream masih perlu diverifikasi.

### J-PLAT-03 - Multi-batch semantics

Status: **PENDING VERIFICATION**.

Masih diperlukan bukti PostgreSQL untuk:

- Semantik data yang berasal dari beberapa batch.
- Concurrency dan duplicate/replay.
- Retry dan recovery.
- Rollback serta partial failure.
- Konsistensi snapshot ketika batch baru diterbitkan.

### J-PLAT-04 - Runtime, security, dan interface evidence

Status: **PENDING VERIFICATION**.

Masih diperlukan:

- Pengujian worker pada PostgreSQL nyata, termasuk timeout, retry,
  cancellation, advisory lock, dan batas waktu pipeline.
- Pembuktian isolasi akun login database untuk API dan worker.
- Benchmark audit trace dengan target SLA maksimal 300 detik serta
  penanganan pagination/truncation.
- Browser E2E untuk persona dan workflow utama.

### Status Gate C

| Area | Status |
|---|---|
| J-PLAT-01 - Event availability dan lineage | IN PROGRESS |
| J-PLAT-02 - Identity as-of | IMPLEMENTED PARTIALLY |
| J-PLAT-03 - Multi-batch semantics | PENDING VERIFICATION |
| J-PLAT-04 - Runtime evidence | PENDING VERIFICATION |
| Gate C keseluruhan | NOT CLOSED |

### Catatan repository

Perubahan implementasi, migration, service, dan tes masih berada pada
branch lokal. File backup lokal tidak termasuk file implementasi yang
perlu dimasukkan ke commit.

Belum ada klaim bahwa perubahan terbaru telah lulus CI GitHub. Jangan
menutup Gate C sebelum acceptance criteria, bukti pengujian, dan review
lintas tim terpenuhi.

**Kesimpulan:** validasi lokal terbaru berhasil dengan 831 tes lulus.
Fondasi transaction event history dan identity as-of telah berkembang,
tetapi masih ada pekerjaan integrasi sumber, rekonstruksi histori,
multi-batch, dan runtime yang harus diselesaikan.

## Pembaruan status - 16 November 2026 (follow-up PR #35 untuk PR #33)

Status di bawah ini menggantikan kesimpulan implementasi sebelumnya untuk
follow-up Gate C. Implementasi ada di commit
`3ccbc666aaaae04e03ac03a150d72981d579e2bd`, branch
`fix/historical-data-gate-c-followup`, pada [PR #35](https://github.com/mosessatriyo23/vteki-customer-intelligence/pull/35).
PR masih draft. Gate C tetap **NOT CLOSED**.

### Perubahan James yang sudah dibuat lokal

- Migration 0019 memisahkan batch transaksi asal dan batch penerimaan event
  pada `source.transaction_event_history`; data lama di-backfill dari
  transaksi asal dan kolom origin memiliki foreign key ke batch.
- `append_transaction_event()` menerima event pada batch penerimaan yang
  berbeda, mensyaratkan batch terkait `PUBLISHED`, mewajibkan
  `source_event_id`/`source_version`, dan menangani replay/conflict
  idempotency secara atomik.
- `project_transaction_as_of()` menambahkan projection status, gross,
  discount, refund kumulatif, net, actual revenue, cancellation, dan
  correction chain. Projection menandai `source_coverage` sebagai
  `OBSERVED_EVENTS_ONLY`; ini bukan bukti feed sumber lengkap.
- Migration 0020 dan loader menyalin completed visit, membership join, dan
  renewal dari input dengan occurrence time, source event ID, feed schema
  version, batch, receipt time DB, dan lineage ke event bisnis asal.
- As-of event query membatasi data ke batch PUBLISHED dan ordering memiliki
  tie-break deterministik.
- Migration 0013 baru merekam baseline pada waktu migrasi. Pembacaan juga
  membatasi baseline lama berdasarkan `recorded_at` dan melaporkan
  `AVAILABLE`, `BLOCKED`, atau `UNKNOWN`.
- `build_profiles_as_of()` didokumentasikan sebagai utility identity-aware
  terbatas, bukan feature/training snapshot resmi.

### Status item dengan format yang diminta

| Item | Status | Bukti / blocker |
|---|---|---|
| Refund/status/cancellation feed historis | **BLOCKED** | Tidak ada feed sumber/connector refund atau status-change di repository. API menerima event dengan provenance eksplisit; timestamp historis tidak dibuat. Perlu feed dan kontrak sumber dari owner. |
| Completed visit/membership renewal history | **DONE — code + PostgreSQL CI** | Ledger/loader dan bitemporal read ditambahkan; CI PostgreSQL integration 11/11 lulus. Moses tetap perlu review sebelum renewal dipakai untuk churn. |
| Final-state projection | **IN PROGRESS** | Kode projection dan tes unit ada; PostgreSQL CI lulus. Refund/status source feed masih hilang, jadi coverage hanya `OBSERVED_EVENTS_ONLY`. |
| Event batch A → B → C | **DONE — code + PostgreSQL CI** | Tes PostgreSQL batch A/B/C, as-of, idempotency/conflict dan status lulus. |
| Identity as-of merge/split/coverage | **IN PROGRESS** | Merge integration test yang ada, tes split/baseline baru, dan coverage status eksplisit. Review-required history/revocation dan stabilitas snapshot belum lengkap. |
| Official historical snapshot | **BLOCKED** | Utility C360 masih memakai inbound dan review queue statis; belum boleh menjadi feature/training source. |
| Multi-batch acceptance | **IN PROGRESS** | PostgreSQL CI membuktikan retry/concurrent duplicate batch, rollback/recovery, katalog per-batch, dan filter PUBLISHED. Overlap/master-data/snapshot immutability masih perlu bukti tambahan. |
| Kontrak dan status | **DONE — DRAFT diperbarui** | Kontrak v1.1 berisi decision table, feed gaps, acceptance status dan approval eksplisit yang masih pending. |
| PR/commit/link CI | **DONE — PR draft + CI hijau** | PR #35 dan commit di atas; seluruh checks CI selesai sukses. Belum merge. |
| Approval Moses/Christ/cross-team | **BLOCKED** | Memerlukan review dan keputusan pihak terkait; James tidak menyatakan approval atas nama mereka. |
| DB runtime role isolation, worker operations, audit benchmark, frontend E2E, runbook | **IN PROGRESS / VERIFICATION PENDING** | Di luar P0 yang sedang dikerjakan; tetap belum boleh dinyatakan VERIFIED tanpa bukti deployment/runtime. |
| Physical table partitioning | **NOT APPLICABLE saat ini** | Belum ada workload, retensi, atau partition key yang disetujui untuk membenarkan migrasi fisik. |

### Acceptance test dan hasil yang benar-benar tersedia

- Tes unit projection: transaksi + refund berulang, correction chain, fork
  correction ditolak, tie ordering, replay-order determinism, dan cutoff
  knowledge untuk correction terlambat.
- Tes identity lokal: baseline migration tidak mengklaim pre-migration
  history; cutoff split mempertahankan mapping lama; unknown source tidak
  diberi Golden ID.
- Tes PostgreSQL di
  `tests/integration/test_postgres_platform.py` untuk batch A/B/C,
  idempotency/conflict, late event, visit/membership availability,
  concurrency duplicate-batch, rollback/recovery, katalog per-batch, dan
  filter batch PUBLISHED.
- Hasil PostgreSQL lokal follow-up: **tidak dijalankan** karena
  `VTEKI_TEST_POSTGRES_URL` tidak dikonfigurasi dan Docker/PostgreSQL tidak
  tersedia. Karena itu tes lokal PG ter-skip.
- Full local Python suite: **831 passed, 11 skipped**.
- Ruff: **All checks passed**; Black: **90 files unchanged**; MyPy:
  **Success, no issues found in 88 source files**; Alembic: satu head,
  `0020_business_event_history`.
- [CI PR #35](https://github.com/mosessatriyo23/vteki-customer-intelligence/actions/runs/43747326104):
  **semua jobs lulus**. Job PostgreSQL menjalankan migration dan
  `test_postgres_platform.py`: **11 passed**. Frontend build dan RBAC E2E
  juga lulus. Unit job melaporkan 724 passed dan 11 PostgreSQL tests skipped;
  kasus PostgreSQL tersebut lulus pada dedicated step setelah migration.

Contoh query/projection as-of:

```python
state = project_transaction_as_of(
    session,
    source_transaction_id="source-tx-id",
    effective_at=effective_cutoff,
    known_at=knowledge_cutoff,
)
# state.source_coverage == "OBSERVED_EVENTS_ONLY"
```

Replay event menggunakan idempotency key dan payload sumber yang sama.
Payload berbeda dengan key yang sama ditolak. Contoh tersebut bukan bukti
feed historis lengkap.

### Batasan dan keputusan Moses

- Migration 0013 baseline adalah awal cakupan identity; identity sebelum
  migrasi tidak direkonstruksi. Cutoff yang lebih awal harus menghasilkan
  `BLOCKED`, bukan mapping seolah-olah historis.
- Event transaction baseline tidak membuktikan histori refund/status lama.
- Ground truth tidak boleh menjadi input matching, feature, label, atau
  training.
- Sampai P0 selesai, seluruh feed dan acceptance coverage tersedia, dan
  review lintas tim dicatat:
  `training_ready=false`, `experiment_ready=false`, `final_model=false`.

## Pembaruan status - 16 November 2026 (platform/runtime follow-up)

Metadata GitHub yang diperiksa ulang melaporkan PR #35 **CLOSED / MERGED**
ke `main` pada merge commit `30bb4a68794f6551a184e2f0cf7e9902477c6511`.
Kesimpulan lama OPEN / DRAFT di bawah ini sudah tidak mencerminkan metadata
tersebut; status approval Gate C tetap pending. James-owned follow-up pada
riwayat PR mencapai implementation commit `db189b0b7ee15db69cb1ad33175d0c12865c7451`; dokumentasi
status juga diperbarui setelahnya. CI terbaru yang dicatat pada perubahan itu
[run 43756508746](https://github.com/mosessatriyo23/vteki-customer-intelligence/actions/runs/43756508746)
lulus untuk backend/security, PostgreSQL, frontend build, dan E2E.

### Perubahan James yang ditambahkan

- Migration 0021 menambahkan `idempotency_key` nullable dengan unique
  constraint pada `act.batch_jobs`, kompatibel dengan row lama.
- API job mendukung replay idempotent, menolak pemakaian key dengan payload,
  jenis job, atau batas attempt yang berbeda, dan menyediakan cancellation
  untuk job queued/running.
- Worker memeriksa cancellation saat handler berjalan, menghentikan proses
  handler, mencatat status/audit cancellation, dan memulihkan permintaan
  cancellation yang lease-nya kedaluwarsa.
- CI menyiapkan kredensial login khusus API/worker dan memverifikasi koneksi
  runtime non-superuser; E2E API menggunakan role API, bukan administrator.
- E2E browser menambah alur persetujuan campaign → audit trace dan pembuatan
  serta keputusan identity review.
- PostgreSQL test definitions menambah overlap source ID, konflik update
  master data, replay snapshot immutable, dan uniqueness idempotency job.
- Script CI memulai dari database populated pada revision 0014, meng-upgrade
  ke head, lalu memeriksa transaction/visit/membership event lineage dan
  occurrence time.
- Runbook deploy, rollback, backup/restore, monitoring, dan recovery tersedia
  sebagai draft di [RUNBOOK_GATE_C.md](./RUNBOOK_GATE_C.md).

### Bukti validasi

| Pemeriksaan | Hasil |
|---|---|
| `pytest -q` lokal | 852 passed, 0 skipped; semua 15 PostgreSQL integration tests ikut berjalan pada database PostgreSQL 15 disposable yang baru |
| PostgreSQL acceptance CI | [15 passed](https://github.com/mosessatriyo23/vteki-customer-intelligence/actions/runs/43756508746/job/132941666619) |
| Populated migration upgrade | CI meng-upgrade database berisi data dari revision 0014 sampai Alembic head dan memverifikasi transaction/visit/membership lineage |
| Runtime DB role | CI memverifikasi login non-superuser API/worker dan grant; E2E memakai login API runtime |
| Frontend E2E | [CI job lulus](https://github.com/mosessatriyo23/vteki-customer-intelligence/actions/runs/43756508746/job/132941666351), termasuk campaign approval/audit trace dan identity review |
| Ruff | Lulus |
| Black | Lulus; 168 file unchanged setelah format script migrasi |
| MyPy | Lulus; 88 source files |
| Frontend production build | Lulus (`tsc -b` dan `vite build`) |
| Alembic | Satu head: `0021_batch_job_idempotency` |
| CI workflow YAML | Parse lokal berhasil |

Workflow sebelumnya menemukan lalu memperbaiki blocker append-only pada
migration 0019, query review E2E yang meminta status filter kosong, dan
selector audit trace yang tidak unik. Hasil CI hijau di atas adalah setelah
perbaikan tersebut.

### Status terbaru per butir

| Butir | Status |
|---|---|
| Worker job idempotency dan cancellation | **DONE — code + unit tests lokal/CI**; penggunaan multi-host dan efek samping eksternal tetap butuh uji operasional |
| DB runtime login isolation API/worker | **DONE — CI role grants dan login non-superuser terverifikasi**; deployment production belum diverifikasi |
| Populated-database migration upgrade | **DONE — populated PostgreSQL CI fixture lulus** dari 0014 ke head |
| PostgreSQL overlap/master-data/snapshot acceptance | **DONE — 15 PostgreSQL tests lulus di CI**; tidak mencakup seluruh skenario Gate C atau equal-availability database stress |
| Frontend approval, identity review, audit trace E2E | **DONE — 7 Playwright tests lulus di CI** |
| Deploy/rollback/backup/restore/recovery runbook | **DONE — draft terdokumentasi**; restore drill produksi belum dilakukan |
| Refund/status/cancellation source feeds | **BLOCKED** — sumber dan kontrak feed eksternal belum tersedia |
| Historical identity review/revocation dan official feature snapshot | **BLOCKED / INCOMPLETE** — membutuhkan keputusan dan histori input bitemporal |
| Moses/Christ/cross-team approval | **BLOCKED** — menunggu review pihak terkait; tidak dapat disetujui oleh James |
| Gate C, training, experiment, final model | **NOT CLOSED** — `training_ready=false`, `experiment_ready=false`, `final_model=false` |

PR #35 masih draft dan belum memiliki approval Moses, Christ, atau lintas
tim. Runbook dan kontrak tetap berstatus draft. CI hijau membuktikan kode
dan acceptance tests yang terpasang, bukan source-feed completeness,
production readiness, atau persetujuan Gate C. Jangan menyimpulkan bahwa
Gate C telah ditutup.

## Pembaruan identity-as-of — 16 November 2026

Perbaikan lokal terbaru memastikan `build_profiles_as_of()` tidak membaca
`review_queue.csv` untuk menetapkan status historis. Karena belum ada ledger
review-decision yang bitemporal, profil as-of kini menyatakan
`identity_status=UNKNOWN` alih-alih menganggap status review terkini berlaku
secara retroaktif. `UNKNOWN` juga dapat disimpan oleh adapter snapshot tanpa
mengklaim status yang tidak diketahui.

| Butir | Status | Bukti / blocker |
|---|---|---|
| Static review queue tidak memengaruhi status profil as-of | **DONE — lokal** | Regression test membuktikan queue yang menandai `REVIEW` menghasilkan `UNKNOWN` pada profile as-of; `build_profiles()` non-as-of tetap mempertahankan perilaku saat ini. |
| Persistensi status historis yang tidak diketahui | **DONE — lokal** | Persistence test menerima serta menyimpan status `UNKNOWN`. |
| Review-decision history bitemporal, correction/revocation | **BLOCKED / INCOMPLETE** | Perlu ledger append-only, aturan koreksi/revokasi identity, migration, dan acceptance test PostgreSQL; belum ada pada patch ini. |
| Hasil validasi patch terbaru | **DONE — CI + lokal** | Full `pytest -q`: 852 passed, 0 skipped, termasuk 15 PostgreSQL acceptance tests pada database baru; CI pada head PR terverifikasi melalui run 43756508746. |

Perubahan itu memperjelas batas identity-as-of, tetapi belum menutup Gate C.
Pembaruan James berikutnya dicatat di bawah.

## Pembaruan James — identity review history follow-up, 16 November 2026

Branch kerja: `fix/gate-c-bitemporal-identity-review` dari `main` commit
`30bb4a68794f6551a184e2f0cf7e9902477c6511`.

### Implementasi yang ditambahkan

- Migration `0022_identity_review_decision_history` menambah ledger append-only
  bitemporal untuk review decision. Keputusan legacy dari `review_audit_log`
  dibackfill memakai `performed_at` asli dan `available_at` saat migration;
  ketersediaan sebelum backfill tidak direka.
- `get_review_decision_as_of()` memproyeksikan keputusan sesuai effective dan
  knowledge cutoff. Correction/revocation linear append-only; fork, koreksi
  yang mendahului event induk, dan konflik retry ditolak.
- Keputusan baru mencatat source event ID/version, batch asal, idempotency key,
  reviewer, correlation ID, rationale, serta waktu receipt database.
- `build_profiles_as_of()` membaca status review dari ledger bitemporal dan
  tidak memakai status `review_queue` terkini atau `review_queue.csv`. Status
  merge/reject hanya diakui bila cocok dengan identity mapping pada cutoff;
  konflik tetap `UNKNOWN`.
- Migration `0023_identity_history_coverage_marker` mencatat batas coverage
  tanpa bergantung pada ada/tidaknya baseline mapping. Database kosong saat
  baseline mendapat coverage mulai waktu migration marker, bukan timestamp
  historis rekaan.
- Tes PostgreSQL ditambah untuk append-only dan pencegahan backdate `available_at`
  pada review ledger serta tie ordering event transaksi pada `available_at`
  identik. Role `vteki_identity_reviewer` mendapat SELECT/INSERT ledger.

### Validasi lokal pada branch

| Pemeriksaan | Hasil |
|---|---|
| Full local `pytest -q` | 839 passed, 16 skipped; skipped tests require PostgreSQL |
| `pytest tests/data/test_persistence.py tests/data/test_customer360.py tests/integration/test_postgres_platform.py` | 15 passed, 16 skipped |
| Ruff pada file yang berubah | Lulus |
| MyPy untuk identity/customer360 dan `api/models.py` | Lulus, 10 source files |
| Black pada file yang berubah | Lulus setelah format |
| PostgreSQL lokal | Tidak tersedia; 16 tes integrasi PostgreSQL ter-skip |
| CI branch follow-up | Belum dijalankan |

Tes lokal membuktikan chain projection, status cutoff, correction/revocation,
idempotent replay, serta BLOCKED saat identity coverage marker ada walau tabel
baseline kosong. Hasil itu belum membuktikan migrasi PostgreSQL 0022/0023 atau
tes PostgreSQL baru; CI harus menjalankannya.

### Status setelah follow-up ini

| Butir James | Status | Batas |
|---|---|---|
| Bitemporal identity decision history + as-of read | **IMPLEMENTED — LOCAL TESTED** | Butuh CI PostgreSQL untuk migration dan trigger. |
| Correction / revocation ledger | **IMPLEMENTED — LOCAL TESTED** | Tidak otomatis mengubah identity mapping; perubahan merge/split tetap perlu event mapping yang sesuai. |
| Identity coverage saat baseline kosong | **IMPLEMENTED — LOCAL TESTED** | Migration 0023 menetapkan awal coverage pada waktunya bila tidak ada baseline yang dapat dibuktikan. |
| Equal-availability PostgreSQL ordering | **TEST ADDED — CI PENDING** | Butuh dedicated PostgreSQL CI. |
| Refund/status/cancellation feed historis | **BLOCKED** | Source feed/contract belum tersedia. Timestamp tidak disintesis. |
| Official historical feature snapshot | **NOT IMPLEMENTED / OUT OF CURRENT UTILITY SCOPE** | Profile builder tetap bukan training source. Immutable `known_at`/checksum/version registry perlu desain bila disetujui. |
| Review identity merge/split lintas tim | **PENDING** | Moses/Christ/cross-team perlu meninjau semantik dan approval. |
| Gate C dan Moses training readiness | **NOT CLOSED** | Tetap `training_ready=false`, `experiment_ready=false`, `final_model=false`. |

PR #35 sudah berstatus merged menurut metadata GitHub. Perubahan branch follow-up
ini belum dipush/di-PR dan belum memiliki hasil CI. Approval Gate C tetap belum
ada; jangan menandai kontrak APPROVED.

## Status otoritatif Gate C — 17 November 2026

Bagian ini menggantikan status historis yang lebih lama di atas. Branch
`james/gate-c-p0-finalize` dibuat dari `origin/main` commit `5da8c02` setelah
fetch. Commit dokumen awal `06aeaf1` dan acceptance commit `c12c4f9` belum
di-push atau mendapat CI. Seluruh commit lokal pada branch ini masih menunggu
push dan CI.

| Item | Status | Bukti / blocker |
|---|---|---|
| Refund, partial refund, perubahan status, cancellation, correction dari feed sumber | **BLOCKED** | Event API dan projection tersedia, tetapi repo tidak memiliki konektor/feed historis refund atau status. Data kosong tetap `MISSING`; timestamp tidak boleh dibuat. Owner sumber perlu menyediakan kontrak/feed. |
| Transaction final-state projection pada `effective_at` + `known_at` | **DONE — implementation; source completeness BLOCKED** | `project_transaction_as_of()` mengimplementasikan status/amount/refund/correction chain dari event yang terlihat. Hasil hanya `OBSERVED_EVENTS_ONLY`; acceptance unit dan integrasi di PR #35/36 tidak membuktikan feed sumber lengkap. |
| Koreksi baseline transaksi setelah refund/status | **IMPLEMENTED; unit regression PASSED; PostgreSQL regression ADDED, pending execution** | Koreksi kini menggantikan efek pada posisi root event; event refund/status setelah root diputar ulang di atas baseline terkoreksi. Belum ada CI untuk baseline-correction regression ini. |
| Transaction batch A, event receiving batch B/C | **DONE — code + PostgreSQL CI at PR #35 head** | Origin batch dan receiving batch dipisah, lineage dipertahankan, kedua batch harus PUBLISHED. Bukti PR #35 CI run 43747326104 berlaku pada head PR tersebut. |
| Idempotency, replay, late availability, timezone-aware cutoffs | **DONE — acceptance CI on PR #36 head** | PR #36 head commit `1082182c738283973ff11f9cf2f564b180d4ada2`; run 44051345769 hijau untuk backend/quality, frontend build, E2E. Tidak mengklaim pengujian ulang atas semua migration 0022/0023 di run tersebut. |
| Identity mapping as-of dan migration 0013 boundary | **DONE — implementation; coverage history incomplete before migration 0013** | Merge/split mapping journal dan coverage `AVAILABLE/BLOCKED/UNKNOWN` tersedia. Migration 0013 hanya menangkap baseline saat migrasi dan tidak merekonstruksi identity sebelumnya. |
| Identity review decision as-of, correction/revocation | **IMPLEMENTED; PostgreSQL test ADDED, execution PENDING** | Migration 0022/0023 dan unit test chain tersedia. Test baru memproyeksikan keputusan sebelum/sesudah correction dan revocation dengan `known_at`; tidak dapat dijalankan lokal karena `VTEKI_TEST_POSTGRES_URL` belum dikonfigurasi. Unresolved identity unit test dan old-profile snapshot replay assertion ditambahkan; full PostgreSQL unresolved/split/review-correction consumer coverage masih perlu acceptance. |
| `build_profiles_as_of()` sebagai sumber resmi Moses | **NOT APPLICABLE / OUT OF SCOPE — pilihan (a)** | Utility identity-aware terbatas; input inbound belum seluruhnya bitemporal dan belum ada immutable snapshot manifest/checksum + publication contract. Jangan gunakan untuk training. |
| Batch semantics | **PARTIALLY VERIFIED** | Decision table dan tes mencakup duplicate/retry, overlap, concurrency, rollback, published visibility, catalogue batch reference, snapshot replay. Per-feed recovery/operational failure injection dan snapshot non-mutation untuk keseluruhan integrasi tetap perlu review bukti per CI head. |
| CI terbaru yang relevan untuk acceptance historis | **DONE — PR #36 checks passed** | [Run 44051345769](https://github.com/mosessatriyo23/vteki-customer-intelligence/actions/runs/44051345769) untuk commit PR #36 `1082182c738283973ff11f9cf2f564b180d4ada2`. Bukan CI untuk perubahan dokumen branch ini. |
| Contract approval / Gate C | **BLOCKED** | Contract v1.7 masih **DRAFT**. Moses point-in-time review, Christ review bila definisi nilai memengaruhi target, serta approval lintas tim belum tercatat. Folder `approved/` bukan bukti approval. |
| Moses readiness | **BLOCKED** | `training_ready=false`, `experiment_ready=false`, `final_model=false`; no new labels/features/model, campaign, atau production scoring dari projection ini. Synthetic ground truth tetap dilarang untuk matching, feature, label, dan training. |

### Output dan bukti

- Kontrak terkini: `docs/james_platform/approved/historical_data_contract_v1.x.md` (v1.7 DRAFT).
- Decision table batch/correction ada di bagian 5 kontrak.
- Acceptance test kode ada di `tests/data/test_transaction_events.py`,
  `tests/data/test_persistence.py`, dan `tests/integration/test_postgres_platform.py`.
- Test PostgreSQL correction/revocation as-of, correction baseline setelah
  refund/status, dan immutability replay profil as-of ditambahkan di branch ini;
  eksekusi CI masih pending karena branch belum ter-push.
- Contoh query/replay as-of ada di bagian 3 kontrak; replay harus menggunakan
  source identity, version, batch, idempotency key, dan payload yang sama.
- Bukti CI: [PR #36 workflow](https://github.com/mosessatriyo23/vteki-customer-intelligence/actions/runs/44051345769).
- Batas histori: migration 0013 membuat baseline saat migrasi; histori identity
  sebelumnya tidak direkonstruksi. Backfill event visit/membership hanya
  membuktikan first capture ledger, bukan waktu platform mengetahui event.

**Rekomendasi:** Moses belum boleh memakai data historis ini untuk training
development. Lanjutkan hanya setelah feed historis tersedia atau sumber
ditetapkan missing secara eksplisit, acceptance PostgreSQL untuk identity
review correction/revocation dan merge/split snapshot dilengkapi, lalu
Moses/Christ/cross-team menyetujui kontrak serta feature snapshot resmi.

### Validasi branch revisi lokal

- Tes relevan (`test_persistence.py`, `test_transaction_events.py`,
  `test_customer360.py`, `test_snapshot_atomicity.py`, dan
  `test_postgres_platform.py`): **26 passed, 18 skipped**.
- PostgreSQL integration skipped karena
  `VTEKI_TEST_POSTGRES_URL` tidak tersedia di lingkungan ini.
- Ruff lint dan format checks untuk file Python yang diubah: lulus.
- `git diff --check`: lulus.
- Acceptance PostgreSQL baru dan CI branch ini: **PENDING** sampai branch
  ter-push dan workflow berjalan.
