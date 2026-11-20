# VTEKI Customer Intelligence

Platform starter untuk arsitektur data pelanggan dengan PostgreSQL, JWT/RBAC, audit trace, batch orchestration, dan React/Vite.

## Menjalankan stack

1. Dari root repo, jalankan `Copy-Item .env.example .env` di PowerShell (atau `cp .env.example .env` di macOS/Linux). Ganti `POSTGRES_PASSWORD`, password admin, dan `JWT_SECRET` dengan nilai unik. Gunakan karakter alfanumerik untuk password PostgreSQL karena Compose menyusunnya ke URL koneksi. Jangan commit `.env`.
2. Jalankan `docker compose --env-file .env up --build -d` dari root repo. Compose membangun API, web, dan worker, menunggu PostgreSQL sehat, lalu menjalankan migrasi otomatis.
3. Buat administrator pertama satu kali dengan `docker compose exec api python -m api.bootstrap`.
4. Buka `http://localhost` untuk web app atau `http://localhost:8000/docs` untuk OpenAPI. Port host dapat diubah lewat `WEB_PORT`, `API_PORT`, dan `POSTGRES_PORT`.

Bootstrap ditolak jika tabel user sudah berisi akun. User berikutnya dibuat admin lewat `POST /auth/users`.

## PostgreSQL dan keamanan

Migration `0005_governance_schemas_and_traceability` dan `0006_governance_workflows` menyatukan tabel ke delapan schema domain:

- `core`: user, role, customer, identity review.
- `stg`: ingestion dan pipeline run.
- `feat`: customer features.
- `ml`: model drift metrics.
- `dec`: NBA decision dan human override.
- `act`: campaign dan batch job.
- `msr`: hasil observed vs incremental.
- `gov`: `audit_event` dan decision trace.

Password di-hash dengan bcrypt (rounds 12) setelah pre-hash SHA-256 agar passphrase panjang tidak terpotong oleh batas input bcrypt. JWT HS256 memerlukan `JWT_SECRET`. Role awal: `admin`, `analyst`, `campaign_manager`, `operator`.

`AuditMiddleware` mencatat request dan menerima atau membuat `X-Correlation-ID`; respons membawa `X-Request-ID` dan `X-Correlation-ID`. Event bisnis campaign, identity review, NBA override, dan worker memakai correlation ID yang sama. Trigger PostgreSQL menolak UPDATE/DELETE pada `gov.audit_event`.

Endpoint utama:

- `POST /auth/login`, `GET /auth/me`, `POST /auth/users`.
- `GET /audit/events`, `GET /audit/trace/{correlation_id}`, `GET /audit/decision-trace/{correlation_id}`.
- `GET /governance/reconstruct/{correlation_id}` untuk menyusun decision trace dan waktu rekonstruksi.
- `GET /customers`, `GET /customers/{id}/provenance`, `GET/POST /identity-reviews`.
- Campaign dibuat sebagai draft, dikirim untuk approval, `admin` atau `campaign_manager` dapat approve/reject, dan hanya campaign approved yang dapat diluncurkan.
- `GET/POST /decisions/next-best-actions` dan endpoint `/override` untuk human override beralasan.
- `GET /monitoring/dashboard`, `POST /monitoring/drift`, `POST /monitoring/measurements`.
- `POST /jobs`, `GET /jobs`, `GET /jobs/{id}`.

## Worker dan pipeline

Worker memproses job PostgreSQL dengan row locking, retry/backoff, dan hasil persisten. Campaign hanya menggunakan channel simulator; tidak ada pengiriman pesan keluar.

APScheduler menjalankan urutan pipeline setiap `PIPELINE_INTERVAL_MINUTES` (default 15). PostgreSQL advisory lock mencegah overlap lintas worker. Setiap pipeline memiliki budget 60 menit, mencatat run/hasil tiap tahap, dan menandai kegagalan bila budget terlewati. Runner memeriksa budget di antara tahap; task yang sedang berjalan harus kooperatif dan memiliki timeout internal jika kelak ditambahkan.

Untuk pengembangan, instal `requirements-dev.txt`. `python -m worker --once` memproses paling banyak satu job; `python -m worker` menjalankan polling worker dan scheduler.

## Frontend

Web app memakai `POST /auth/login` dan menyimpan JWT di local storage. Dashboard, Customer 360/provenance, campaign draft/approval/launch, identity review, NBA override, model drift, measurements, audit events, dan reconstruction memakai endpoint backend; setelah mutasi halaman memuat ulang data dari server. Role yang tampil berasal dari `/auth/me`, sedangkan setiap aksi tetap diperiksa RBAC oleh API. Tidak ada mode preview berisi data contoh di web app; data yang belum tersedia ditampilkan sebagai kosong.

Data telepon, riwayat kunjungan, consent per channel, dan segmentasi membership belum ada pada response customer saat ini. UI tidak mengarang field tersebut. Campaign tetap memakai simulator; setelah worker berjalan, daftar campaign menampilkan status job, jumlah audiens, dan pembagian varian A/B dari hasil tersimpan.

Jalankan API/database dengan Docker Compose, lalu masuk ke `web/`, jalankan `npm ci` dan `npm run dev`. Proxy `/api` Vite meneruskan request ke API pada port 8000; web dev server tersedia di `http://localhost:5173`.

Endpoint demo `POST /customers/seed` dinonaktifkan dan mengembalikan `410 Gone`. Pelanggan hanya muncul setelah dimasukkan melalui sumber resmi atau didaftarkan admin lewat `POST /customers`; nilai LTV dan churn yang belum ada tetap kosong. Record demo lama ditandai dan disembunyikan dari alur pelanggan/NBA/kampanye.

## Handoff Moses dan pemeriksaan model

Halaman **Review model Moses** menerima `contract_manifest.json` dan `records.jsonl` keluaran `services.data.models.prediction_contract`, memeriksa checksum/versi, dan menyimpan run serta baris skor ke `ml.prediction_review_runs` dan `ml.prediction_review_records`. Role admin/analis dapat mengimpor artefak; run hanya dapat ditinjau oleh pengguna lain. Catatan import dan review masuk ke audit trail.

Artefak di halaman review tetap diberi status **development/non-serving**. Kontrak I-04 masih draft, tidak ada output Moses di repo yang disetujui untuk serving, dan teks alasan/band bisnis belum disetujui. Review teknis mencatat pemeriksaan orang kedua; itu tidak mengaktifkan serving dan tidak menghubungkan skor ke NBA. Identitas kandidat hanya ditautkan lewat Golden Customer yang approved dan kecocokan source ID yang tepat. Proposal NBA tetap manual sampai kontrak bisnis dan handoff serving disetujui. Jangan gunakan skor halaman review untuk memilih pelanggan atau campaign sebelum prasyarat itu terpenuhi.

Untuk menjalankan handoff dari direktori artefak Moses yang sudah tersedia:

```powershell
python -m services.data.models.prediction_contract `
  --predictions-dir artifacts/predictions/prediction-run `
  --reasons-dir artifacts/predictions/reason-run `
  --output-dir artifacts/predictions/contract-run
```

Ganti tiga nama direktori dengan output Moses yang memang tersedia di checkout. Impor `contract_manifest.json` dan `records.jsonl` dari folder output itu di halaman Review model Moses. Artefak model dan input datanya tidak disertakan di repo ini; halaman akan tetap kosong sampai run nyata diimpor.

## CI/CD

`.github/workflows/ci.yml` menjalankan Ruff, Black, mypy, test suite, allowlist T-SEC-03, migrasi PostgreSQL, Schemathesis terhadap OpenAPI, dan production build web.

## Pemisahan branch yang disarankan

- `feat/platform-auth-rbac`
- `feat/audit-trail-traceability`
- `feat/worker-batch-orchestration`
- `feat/frontend-dashboard-c360`

Branch aktif tidak diubah otomatis.
