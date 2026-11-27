# Hasil uji coba UAT (dry run) — sandbox lokal

**Dijalankan:** 2026-11-27 06:30 oleh `uat_dry_run.py` (dapat diulang).
**Data:** SINTETIS (fixture uji), bukan data atau model riil. Tidak ada model riil yang direview atau diberi izin pakai.

> **Ini BUKAN UAT resmi.** Dijalankan di DB sqlite memori, lewat API/worker, tanpa UI, tanpa lingkungan bersama, dan tanpa penguji independen. Gunakan sebagai pemeriksaan awal; UAT resmi tetap harus dijalankan dan dicatat di `UAT_PLAN.md` setelah alur impor→review→izin→NBA→simulator→audit berjalan di lingkungan bersama.

Verdict: `PASS` = sesuai harapan pada level yang dijalankan; `FAIL` = berbeda dari harapan; `TERHALANG` = prasyarat belum ada (bukan kegagalan logika); `TIDAK DIJALANKAN` = butuh lingkungan/UI.

Ringkasan: PASS 11, TERHALANG 3

| ID | Skenario | Level | Verdict |
|---|---|---|---|
| UAT-01 | Hasil valid | API sandbox + service murni | **TERHALANG** |
| UAT-02 | Belum ada skor (keadaan 1) | API sandbox | **PASS** |
| UAT-03 | Run menunggu review (keadaan 2) | API sandbox | **PASS** |
| UAT-04 | Run ditolak (keadaan 2) | API sandbox | **PASS** |
| UAT-05 | Review oleh pengunggah / pembuat model | API sandbox + service murni | **PASS** |
| UAT-06 | Sudah direview, belum ada izin pakai / izin dicabut | API sandbox | **PASS** |
| UAT-07 | Skor kedaluwarsa | API sandbox + service murni (batas 30/31 hari) | **PASS** |
| UAT-08 | ID tidak cocok / tanpa pemetaan pasti | API sandbox + service murni | **PASS** |
| UAT-09 | Data sebagian hilang | API sandbox | **PASS** |
| UAT-10 | NO_ACTION karena kebijakan | service murni (sumber sintetis); API terhalang | **TERHALANG** |
| UAT-11 | Worker gagal / retry impor skor | API sandbox + test worker Moses | **PASS** |
| UAT-12 | Campaign tanpa persetujuan | API sandbox + worker | **PASS** |
| UAT-13 | Campaign berjalan dan pengukuran | API sandbox + worker + test service | **TERHALANG** |
| UAT-14 | Data tersimpan, audit trail, UI kosong | API sandbox | **PASS** |

## UAT-01 · Hasil valid — TERHALANG

Level: API sandbox + service murni

- ✅ evaluate mengembalikan 201
- ✅ skor: SCORE_READY (alur impor→review→izin sah)
- ✅ service murni (sumber sintetis lengkap): serving_ready=true
- ✅ service murni: aksi dipilih dan EV berupa angka dari sistem
- Catatan: API: score_state=SCORE_READY, serving_ready=False, selected_action=NO_ACTION, expected_value=None, unavailable_sources=['consent', 'complaint_history', 'eligibility', 'product_suitability']
- Catatan: service murni: aksi=RETENTION_OUTREACH, EV=2158000.0 (SINTETIS (fixture uji), bukan data atau model riil)
- ⛔ TERHALANG: Keputusan valid belum bisa dihasilkan lewat API: sumber ['consent', 'complaint_history', 'eligibility', 'product_suitability'] belum tersambung (loader mengirim None). Hasil diharapkan (serving_ready=true, aksi + EV angka) tidak tercapai.

## UAT-02 · Belum ada skor (keadaan 1) — PASS

Level: API sandbox

- ✅ score_state = SCORE_MISSING
- ✅ alasan = SCORE_ROW_MISSING
- ✅ aksi = NO_ACTION
- ✅ expected_value = null (UI harus menulis Kosong)
- ✅ model_review_status = null
- ⏸ Tidak diperiksa di sandbox: Tampilan UI (lencana 'Belum ada skor', kolom Kosong) tidak dapat diperiksa dari sandbox.

## UAT-03 · Run menunggu review (keadaan 2) — PASS

Level: API sandbox

- ✅ impor artefak sintetis berhasil (201)
- ✅ score_state = SCORE_PRESENT_NOT_APPROVED
- ✅ alasan = MODEL_RUN_NOT_REVIEWED
- ✅ model_review_status = pending_review
- ✅ tanpa EV, aksi NO_ACTION
- ⏸ Tidak diperiksa di sandbox: Tampilan UI (amber 'menunggu pemeriksaan', skor Kosong) tidak dapat diperiksa dari sandbox.

## UAT-04 · Run ditolak (keadaan 2) — PASS

Level: API sandbox

- ✅ reviewer independen dapat menolak run
- ✅ model_review_status = rejected
- ✅ alasan = MODEL_RUN_NOT_REVIEWED
- ✅ keadaan 2, tanpa EV
- ✅ izin pakai pada run yang ditolak = 409
- ⏸ Tidak diperiksa di sandbox: UI harus memilih teks 'ditolak' (bukan 'menunggu') dari model_review_status; tidak diperiksa di sini.

## UAT-05 · Review oleh pengunggah / pembuat model — PASS

Level: API sandbox + service murni

- ✅ pengunggah mereview run sendiri ditolak (409)
- ✅ izin pakai ditolak bila pembuat model = reviewer (409)
- ✅ skor tetap tidak dipakai
- ✅ pertahanan berlapis di gerbang skor: reviewer = pengunggah ditolak
- Catatan: di API, pelanggaran ini sudah dicegah saat review (409), jadi kode MODEL_RUN_REVIEWED_BY_SUBMITTER hanya muncul bila data DB rusak.

## UAT-06 · Sudah direview, belum ada izin pakai / izin dicabut — PASS

Level: API sandbox

- ✅ reviewed tanpa izin → MODEL_USAGE_NOT_APPROVED
- ✅ keadaan 2, tanpa EV
- ✅ setelah izin pakai: SCORE_READY
- ✅ pencabutan izin berhasil (200)
- ✅ setelah dicabut: skor diblokir pada evaluasi berikutnya

## UAT-07 · Skor kedaluwarsa — PASS

Level: API sandbox + service murni (batas 30/31 hari)

- ✅ umur 29 hari: SCORE_READY
- ✅ umur 31 hari: SCORE_EXPIRED
- ✅ kedaluwarsa: serving_ready=false, degraded_input=true, EV null
- ✅ aksi = NO_ACTION
- Catatan: Batas tepat 30 hari (masih sah) dan 31 hari dikunci test service `TestExpiredScoreIsNotReady`; di API waktu berjalan sehingga batas tepat tidak dapat diuji stabil.

## UAT-08 · ID tidak cocok / tanpa pemetaan pasti — PASS

Level: API sandbox + service murni

- ✅ pelanggan tanpa pemetaan Golden pasti: 409, tidak dievaluasi
- ✅ skor milik ID lain ditolak (SCORE_CUSTOMER_MISMATCH)
- Catatan: detail API: Customer requires an exact, approved Golden Customer mapping.
- ⏸ Tidak diperiksa di sandbox: Penghapusan fallback customer_code di LINGKUNGAN BERSAMA (data nyata) perlu diperiksa oleh James/Moses.

## UAT-09 · Data sebagian hilang — PASS

Level: API sandbox

- ✅ kontrak SCHEMA_PARTIAL (walau sudah direview + diberi izin): SCORE_CONTRACT_NOT_SERVING
- ✅ keadaan 2 (ada, tidak dipakai), bukan 'belum ada'
- ✅ serving_ready = false
- ✅ field wajib (clv_amount) hilang, walau sudah direview + diberi izin: skor TIDAK dipakai dan tanpa EV
- ✅ sumber non-skor yang belum tersambung dilaporkan di unavailable_sources (bukan data palsu)
- Catatan: impor tanpa field clv_amount: HTTP 201
- Catatan: alasan = SCORE_FIELDS_INCOMPLETE; score_state = SCORE_PRESENT_NOT_APPROVED
- Catatan: unavailable_sources = ['complaint_history', 'consent', 'eligibility', 'product_suitability']

## UAT-10 · NO_ACTION karena kebijakan — TERHALANG

Level: service murni (sumber sintetis); API terhalang

- ✅ (a) global opt-out → NO_ACTION / OPT_OUT_SUPPRESSED
- ✅ (b) 2 pesan komersial dalam 14 hari → NO_ACTION
- ✅ (c) komplain berat terbuka → COMPLAINT_RESOLUTION
- Catatan: (b) alasan = FREQ_CAP_SUPPRESSED
- Catatan: data: SINTETIS (fixture uji), bukan data atau model riil
- ⛔ TERHALANG: Lewat API/UI: consent, komplain, dan kelayakan belum tersambung sehingga skenario kebijakan tidak dapat dipicu dengan data nyata. Diuji di level service dengan sumber sintetis berlabel.

## UAT-11 · Worker gagal / retry impor skor — PASS

Level: API sandbox + test worker Moses

- ✅ impor pertama berhasil
- ✅ impor ulang manifest yang sama ditolak (409), tidak ada baris ganda
- ✅ artefak yang isinya berubah (checksum tidak cocok) ditolak (400)
- ✅ hanya 1 run tersimpan setelah retry + artefak rusak (tidak ada hasil parsial)
- ✅ validasi folder worker: ground_truth, path keluar root, dan folder tak ada ditolak; folder sah diterima
- ✅ test worker impor milik Moses: 21 passed, 1 warning in 24.19s
- Catatan: detail impor ulang: This Moses manifest is already imported as run 1
- Catatan: validasi folder worker: {'ground_truth_dev': 'ditolak (artifact_dir is not an allowed directory name)', '../etc': 'ditolak (artifact_dir is not an allowed directory name)', 'tidak_ada': 'ditolak (artifact_dir does not resolve to an allowed folder)', 'churn_ok_20261126': 'DITERIMA'}
- ⏸ Tidak diperiksa di sandbox: Retry di LINGKUNGAN BERSAMA (PREDICTION_IMPORT_ROOT nyata, PostgreSQL) belum diuji.

## UAT-12 · Campaign tanpa persetujuan — PASS

Level: API sandbox + worker

- ✅ kampanye sintetis (per segmen) dapat dibuat sebagai Draft
- ✅ launch saat Draft ditolak (409)
- ✅ launch saat PendingApproval ditolak (409)
- ✅ eksekusi non-simulator ditolak worker
- Catatan: worker non-simulator → ValueError: Campaign execution must use the channel simulator

## UAT-13 · Campaign berjalan dan pengukuran — TERHALANG

Level: API sandbox + worker + test service

- ✅ kampanye yang disetujui manusia dapat di-launch (200)
- ✅ tanpa pengiriman eksternal (simulator)
- ✅ paparan kelompok holdout = 0 (belum bermakna: tidak ada pelanggan yang ditarget)
- ✅ test pipeline campaign + pengukuran (service murni): 47 passed in 1.86s
- Catatan: hasil job worker: targetable_count=0, sent_count=0, skipped_count=2, control_exposure_count=0, external_delivery=False, identity_mapping_skipped_count=1
- ⛔ TERHALANG: Tidak ada pelanggan yang layak ditarget (targetable = 0) karena consent/komplain/kelayakan belum tersambung: 'campaign berjalan beneran' belum tercapai; tidak ada pesan simulasi terkirim.
- ⏸ Tidak diperiksa di sandbox: Pengukuran setelah hasil konversi nyata (Observed vs Incremental di UI) belum bisa diuji: belum ada hasil.

## UAT-14 · Data tersimpan, audit trail, UI kosong — PASS

Level: API sandbox

- ✅ keputusan tersimpan di database (terbaca dari sesi baru)
- ✅ audit mencatat siklus run model
- ✅ respons evaluate memuat correlation_id
- ✅ keputusan NBA dapat dilacak lewat audit/correlation_id
- Catatan: jenis audit event: ['http.request', 'model.prediction_run.imported_for_review', 'model.prediction_run.reviewed', 'model.prediction_run.usage_approved', 'nba.engine_evaluated']
- Catatan: jejak per correlation_id: ['nba.engine_evaluated', 'http.request']; waktu rekonstruksi 0.02 dtk
- Catatan: Temuan: setiap permintaan API memakai correlation_id sendiri, sehingga import→review→izin→keputusan TIDAK terhubung oleh satu correlation_id; keputusan NBA memuat model_version dan status review tetapi bukan run_id. Rekonstruksi penuh harus menggabungkan jejak lewat model_version/waktu. Dicatat sebagai temuan untuk Moses/James (definisi selesai: audit dari impor sampai NBA).
- ⏸ Tidak diperiksa di sandbox: Penyimpanan hasil CAMPAIGN dan pengukuran di DB bersama, serta tampilan 'Kosong' di UI, belum diperiksa.
