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
