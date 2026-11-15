# Historical Data Contract v1.0

**Owner:** James - Platform & Historical Data
**Status:** DRAFT - menunggu review lintas tim
**Tanggal:** 15 November 2026

## 1. Tujuan

Dokumen ini menjelaskan pencatatan histori transaksi agar sistem dapat
membedakan waktu kejadian bisnis dan waktu informasi diterima platform.

## 2. Definisi waktu

| Field | Makna |
|---|---|
| occurred_at | Waktu kejadian menurut waktu bisnis/sumber |
| available_at | Waktu event diterima dan tersedia di platform |
| recorded_at | Waktu event dicatat oleh database |

Semua timestamp harus timezone-aware. Event baru memperoleh available_at
dan recorded_at dari waktu database, bukan waktu yang dapat di-backdate
oleh pemanggil.

## 3. Event history

Tabel yang digunakan adalah source.transaction_event_history.

Jenis event yang didukung:
- TRANSACTION_RECORDED
- REFUND_RECORDED
- STATUS_CHANGED
- CORRECTION

Setiap event memiliki idempotency_key, source_batch_id, payload, dan
referensi lineage yang tersedia. Actor dan source provenance dicatat
melalui actor_type, actor_id, source_event_id, serta source_version.

Event bersifat append-only. Correction harus dibuat sebagai event baru
yang merujuk event sebelumnya melalui corrects_event_id.

## 4. Late-arriving event

Event hanya boleh masuk snapshot as-known jika:

    occurred_at <= effective_at
    available_at <= known_at

Contoh: transaksi terjadi tanggal 10 Oktober, tetapi baru diterima
tanggal 12 Oktober. Snapshot yang mengetahui data sampai tanggal 11
Oktober tidak boleh menggunakan event tersebut.

## 5. Idempotency

Replay dengan idempotency key dan isi yang sama tidak boleh membuat
event duplikat. Penggunaan key yang sama dengan isi berbeda harus ditolak.

## 6. Refund, status, dan correction

Loader saat ini membuat baseline TRANSACTION_RECORDED dari transaksi
yang tersedia. Baseline tersebut tidak membuktikan histori refund atau
status sebelum ingestion.

Service mendukung pencatatan event refund, status, dan correction.
Namun, feed historis refund/status dari sumber belum terintegrasi penuh.
Final-state projection setelah correction juga belum tersedia.

Karena itu, event log belum boleh diklaim sebagai rekonstruksi final
kondisi transaksi yang lengkap.

## 7. Aturan snapshot dan training

- Gunakan effective_at dan known_at secara eksplisit.
- Jangan gunakan event yang available_at-nya melewati known_at.
- Jangan mengubah snapshot historis yang telah diterbitkan.
- Perubahan kontrak harus menghasilkan versi/output baru.
- Jangan mengarang timestamp historis yang tidak tersedia dari sumber.

## 8. Bukti pengujian lokal

Validasi lanjutan pada 15 November 2026:
- Migration PostgreSQL testing: 0018_identity_mapping_batch_fk (head).
- PostgreSQL integration test: 9 passed.
- Test suite: 725 passed.
- Ruff: All checks passed.
- Black: 162 files unchanged.
- Foreign key identity mapping history ke ingestion batches:
  berhasil diverifikasi pada database testing.

Pengujian dilakukan pada database testing lokal, bukan database produksi.
Hasil ini bukan bukti CI GitHub terbaru atau production readiness.

## 9. Pekerjaan yang masih diperlukan

1. Integrasikan feed historis refund dan status dari sumber.
2. Implementasikan final-state projection untuk correction.
3. Tambahkan tes correction chain, refund berulang, status change,
   replay konflik, dan concurrency.
4. Buktikan snapshot lama tidak berubah setelah event terlambat.
5. Minta review dan persetujuan lintas tim.

## 10. Persetujuan

| Reviewer | Status |
|---|---|
| James - Platform | Draft disiapkan |
| Data owner / Moses | Pending |
| Business owner / Christ | Pending bila terkait definisi bisnis |
| Cross-team Gate C | Pending |

Kesimpulan: fondasi event availability dan provenance telah diuji
secara lokal. J-PLAT-01 masih in progress sampai integrasi histori
sumber, rekonstruksi final state, acceptance tests, dan persetujuan
lintas tim terpenuhi.
