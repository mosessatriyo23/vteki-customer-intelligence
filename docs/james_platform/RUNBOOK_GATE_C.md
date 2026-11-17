# Runbook deploy, rollback, backup, dan recovery

**Status:** Operasional draft; belum disahkan untuk production
**Owner:** James — Platform
**Scope:** PostgreSQL, API, worker, historical event ledger, dan batch recovery

Runbook ini adalah prosedur teknis, bukan bukti bahwa production deployment,
restore drill, worker load test, atau audit SLA telah diverifikasi. Jalankan
semua prosedur pada lingkungan non-production terlebih dahulu. Jangan
menjalankan restore atau migration downgrade pada database production tanpa
change approval dan backup yang tervalidasi.

## 1. Prasyarat dan pemisahan role

- Simpan kredensial dalam secret manager, bukan repository atau image.
- `MIGRATION_DATABASE_URL` menggunakan akun migrator/admin untuk DDL.
- `API_DATABASE_URL` memakai login `vteki_api`.
- `WORKER_DATABASE_URL` memakai login `vteki_worker`.
- API dan worker tidak boleh memakai kredensial superuser atau login migrator.
- Terapkan `scripts/db_permissions.sql`, lalu `scripts/runtime_roles.sql`
  sebagai administrator PostgreSQL. Atur password role login secara terpisah.
- Verifikasi bahwa tiap URL tersambung sebagai role yang tepat dan bahwa role
  runtime tidak dapat membuat schema, mengubah audit, atau menjalankan DDL.
- Pada Compose, API menjalankan migration sebelum Uvicorn menggunakan
  `MIGRATION_DATABASE_URL`; koneksi request tetap memakai `API_DATABASE_URL`.
  Worker hanya memakai `WORKER_DATABASE_URL`.

Contoh bentuk konfigurasi (gunakan nilai dari secret manager):

```text
MIGRATION_DATABASE_URL=postgresql+psycopg://<migrator>:<secret>@<host>/<db>
API_DATABASE_URL=postgresql+psycopg://vteki_api:<secret>@<host>/<db>
WORKER_DATABASE_URL=postgresql+psycopg://vteki_worker:<secret>@<host>/<db>
```

Jangan mencetak URL lengkap atau password ke log/terminal rekaman.

## 2. Deploy

1. Pastikan PR sudah direview, seluruh CI wajib hijau, dan approval rilis
   tercatat. Historical contract tetap DRAFT sampai review lintas tim dicatat.
2. Pastikan backup terakhir berhasil dan restore drill masih valid.
3. Hentikan worker sementara agar tidak memproses pipeline saat schema berubah.
4. Jalankan `alembic upgrade head` dengan `MIGRATION_DATABASE_URL`.
   Alembic head pada branch ini adalah `0023_identity_history_coverage_marker`;
   selalu cek `alembic heads` pada commit yang akan dirilis sebelum deploy.
5. Verifikasi satu Alembic head dan jalankan acceptance tests PostgreSQL pada
   database rilis/lingkungan verifikasi.
6. Deploy API dengan `API_DATABASE_URL`; cek `/health`, login, RBAC, pembacaan
   audit, dan alur approval tanpa mengirim campaign ke provider eksternal.
7. Deploy worker dengan `WORKER_DATABASE_URL`; cek job claim, retry, timeout,
   cancellation, advisory lock, dan hasil audit pada canary.
8. Lanjutkan traffic hanya setelah pemeriksaan operasional di bawah selesai.

Jangan menandai refund/status history tersedia bila connector sumber belum
memberikan event ID, revision, waktu kejadian, dan contract feed yang disetujui.

## 3. Monitoring

Pantau sekurangnya:

- `/health` API, konektivitas PostgreSQL, pool exhaustion, error rate, dan latensi.
- Jumlah job `queued`, `running`, `cancel_requested`, `cancelled`, dan `failed`;
  umur job tertua, `attempts`, `lease_until`, serta frekuensi recovery.
- Status batch `STAGED`/`PUBLISHED`, duplikasi checksum, kegagalan ingestion,
  konflik ID sumber, dan event yang terlambat.
- Kegagalan penulisan audit serta trace yang menunjukkan marker truncation.
- Advisory lock yang tertahan dan durasi setiap pipeline/handler.

Audit trace saat ini membatasi hasil dan mengembalikan
`audit_events_truncated` / `decision_traces_truncated`. Jika marker bernilai
`true`, trace belum lengkap; jangan mengklaim rekonstruksi penuh atau SLA
produksi. Benchmark ≤300 detik pada dataset representatif masih harus dijalankan.

Contoh pemeriksaan antrean job:

```sql
SELECT status, count(*), min(created_at) AS oldest_created_at
FROM act.batch_jobs
GROUP BY status
ORDER BY status;
```

Contoh pemeriksaan batch yang belum publish:

```sql
SELECT batch_id, status, loaded_at, rejection_reasons
FROM stg.ingestion_batches
WHERE status <> 'PUBLISHED'
ORDER BY loaded_at;
```

Batasi akses hasil query ke operator yang berwenang; jangan menaruh data
pelanggan mentah dalam tiket atau log.

## 4. Retry, cancellation, dan recovery worker

- Retry job menggunakan `idempotency_key` yang stabil. Payload berbeda dengan
  key yang sama harus ditolak; replay identik mengembalikan job yang sama.
- Job queued dapat dibatalkan langsung. Job running berubah ke
  `cancel_requested`; worker menghentikan proses handler dan menulis status
  `cancelled`.
- Cancellation menghentikan proses handler, tetapi tidak dapat membatalkan
  side effect eksternal yang telah terjadi. Handler wajib idempotent dan
  melakukan side effect melalui pola yang aman untuk retry.
- Jika lease habis, worker mengembalikan job ke antrean dengan backoff, atau
  menandainya `failed` setelah batas attempt. Job yang berstatus
  `cancel_requested` dipulihkan sebagai `cancelled`.
- Periksa audit event `batch.retry_scheduled`, `batch.recovered`,
  `batch.cancel_requested`, `batch.cancelled`, dan `batch.failed` sebelum retry
  manual.
- Jangan mengubah status job langsung di database untuk membuatnya tampak
  berhasil. Retry melalui API/worker dengan key dan payload yang sama.

## 5. Ingestion dan event recovery

- Ingestion batch menulis raw rows, typed rows, event history, dan status
  publikasi dalam satu transaksi. Partial failure semestinya rollback seluruh
  batch.
- Exact retry dari batch yang sudah `PUBLISHED` menghasilkan
  `ALREADY_LOADED` tanpa mengganti metadata publikasi.
- Batch yang tersimpan non-PUBLISHED, checksum berbeda pada batch ID sama,
  atau konflik primary key lintas batch adalah kondisi investigasi; jangan
  mengubah statusnya manual menjadi `PUBLISHED`.
- Event refund/status harus mempertahankan transaction-origin batch dan
  receiving batch yang benar. `occurred_at` wajib berasal dari feed sumber;
  availability/recording adalah waktu penerimaan database.
- Event as-of hanya terlihat bila waktu efektif/knowledge memenuhi cutoff dan
  batch terkait `PUBLISHED`.
- Snapshot yang sudah diterbitkan tidak diperbaiki dengan UPDATE. Terbitkan
  versi rule/registry baru; composite key sama dengan payload berbeda harus
  ditolak.
- Jika feed historis tidak tersedia, tandai coverage `MISSING`/blocked.
  Jangan mengisi event, timestamp, atau refund dengan tebakan.

## 6. Backup dan restore

Backup sebelum migration dan sesuai jadwal retensi organisasi. Simpan backup
terenkripsi di lokasi terpisah dari database dan batasi aksesnya.

```bash
pg_dump --format=custom --no-owner --file=vteki-predeploy.dump "$BACKUP_DATABASE_URL"
pg_restore --list vteki-predeploy.dump
```

Untuk restore drill, gunakan database kosong yang terisolasi dan kredensial
restore admin:

```bash
createdb "$RESTORE_DATABASE"
pg_restore --no-owner --dbname="$RESTORE_DATABASE" vteki-predeploy.dump
```

Setelah restore, verifikasi Alembic version, jumlah batch/event/snapshot,
foreign key, trigger append-only, role privileges, `/health`, dan acceptance
tests. Catat waktu backup, durasi, hasil, serta recovery point/time yang
tercapai. Jangan mengarahkan restore drill ke database production aktif.

## 7. Rollback

- Prefer rollback aplikasi ke image sebelumnya bila schema bersifat
  backward-compatible.
- Migration yang menambah tabel/kolom tidak otomatis dibatalkan saat aplikasi
  di-rollback. Pastikan versi aplikasi sebelumnya tetap dapat berjalan dengan
  schema baru.
- Hentikan worker sebelum rollback aplikasi untuk mencegah handler baru
  memakai schema/kontrak berbeda.
- Jangan gunakan `alembic downgrade` sebagai respons otomatis. Downgrade
  dapat menghapus ledger/provenance; evaluasi migration dan backup bersama
  database owner sebelum menjalankannya.
- Jika data rusak, hentikan writer, pertahankan bukti/log, tentukan recovery
  point, dan restore ke database terisolasi terlebih dahulu. Cutover hanya
  setelah validasi serta persetujuan incident commander.

## 8. Batasan dan keputusan terbuka

- Migration 0013 mencatat identity baseline saat migrasi; tidak merekonstruksi
  identity sebelum cakupan tersebut.
- Feed historis refund/status/cancellation belum tersedia di repository.
- Benchmark SLA audit, restore drill production-like, dan uji worker multi-host
  masih menunggu bukti operasional.
- Physical table partitioning belum diputuskan; jangan menambahkannya tanpa
  volume, retensi, key, FK/unique, serta rencana migrasi yang disetujui.
- Sampai feed, test coverage, review lintas tim, dan approval rilis selesai,
  `training_ready=false`, `experiment_ready=false`, dan `final_model=false`.
