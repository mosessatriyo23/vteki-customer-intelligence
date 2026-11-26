# Rencana UAT — Decisioning (NBA + Campaign)

**Versi:** 26 November 2026 (menggantikan versi 21 November). **Pemilik:** Christ. **Status:** rencana. Semua kolom **Hasil aktual** sengaja `BELUM DIJALANKAN`. Isi hanya setelah benar-benar diuji, dengan bukti (screenshot, ID keputusan, atau `correlation_id`). Penguji bukan pembuat kode. Tidak ada persetujuan mentor atas dokumen ini.

UAT dijalankan **setelah** gate izin pakai, loader skor, dan UI tersambung (urutan C di update Moses). Dokumen ini menulis 14 skenario beserta **hasil yang diharapkan** sekarang, tanpa menunggu skor asli.

## Aturan yang berlaku di semua skenario
- Data kosong ditulis `Kosong`. Tidak ada angka contoh, tidak ada label "AI" atau persentase yang tidak berasal dari respons API.
- Jangan mengisi `usage_approved = True`, band, atau angka bisnis sendiri demi lolos. Skenario yang butuh izin pakai ditunda sampai keputusan D2/D3/D5 tertulis.
- Pengiriman memakai simulator (`*_sim`); tidak ada pengiriman nyata.
- Setiap keputusan dan eksekusi punya `correlation_id` yang sama di audit trail.

## Keselarasan dengan 12 skenario wajib (TEAM_ALIGNMENT §7)

| Skenario wajib | UAT |
|---|---|
| hasil valid | UAT-01 |
| belum ada skor | UAT-02 |
| run pending | UAT-03 |
| run ditolak | UAT-04 |
| self-review | UAT-05 (+ izin pakai belum ada: UAT-06) |
| skor expired | UAT-07 |
| ID tidak cocok | UAT-08 |
| data sebagian hilang | UAT-09 |
| `NO_ACTION` | UAT-10 |
| worker gagal/retry | UAT-11 |
| campaign tanpa approval | UAT-12 |
| data kosong pada UI | UAT-02, 03, 06 (tiga keadaan skor) dan UAT-14 |

## Ringkasan

| ID | Skenario | Bisa dijalankan sekarang? | Dijaga test otomatis |
|---|---|---|---|
| UAT-01 | Hasil valid | Menunggu D2/D3/D5 + loader (butuh `usage_approved` sah) | `test_nba_serving.py` |
| UAT-02 | Belum ada skor (keadaan 1) | Ya, setelah UI memakai `score_state` | `test_score_states.py` |
| UAT-03 | Run `pending_review` (keadaan 2) | Ya (impor Moses menghasilkan status ini) | `test_score_states.py` |
| UAT-04 | Run `rejected` (keadaan 2) | Ya, bila ada run yang ditolak | `test_score_states.py` |
| UAT-05 | Review oleh pengunggah / pembuat model | Ya | `test_nba_serving.py` |
| UAT-06 | Sudah direview tetapi belum ada izin pakai | Ya (`usage_approved` memang belum ada) | `test_score_states.py`, `test_nba_serving.py` |
| UAT-07 | Skor kedaluwarsa | Ya, dengan skor uji ber-label | `test_score_states.py` |
| UAT-08 | ID tidak cocok / tanpa pemetaan pasti | Sebagian (loader); menunggu D4 | `test_score_states.py` |
| UAT-09 | Data sebagian hilang | Ya | `test_nba_serving.py`, `test_nba_input_contract.py` |
| UAT-10 | `NO_ACTION` karena kebijakan | Menunggu consent/komplain/kontak tersambung | `test_nba_serving.py`, `test_policy.py`, `test_cross_segment_matrix.py` |
| UAT-11 | Worker gagal / retry impor | Ya | `tests/worker/test_prediction_import_job.py` (milik Moses) |
| UAT-12 | Campaign tanpa persetujuan | Ya | `test_campaign_pipeline.py` |
| UAT-13 | Campaign berjalan dan pengukuran | Menunggu UAT-01 dan campaign tersambung | `test_campaign_pipeline.py`, `test_uplift_measurement.py` |
| UAT-14 | Data tersimpan, audit trail, UI kosong | Menunggu `api/`/`worker/` menyimpan hasil | `test_e2e_decision_flow.py` |

## Kasus uji

### UAT-01 · Hasil valid
- **Prasyarat:** run model `reviewed` oleh orang berbeda dari pengunggah dan pembuat model; izin pakai sah; skor lengkap (churn, band, propensity, CLV, tier, lifecycle); consent, komplain, riwayat kontak, kelayakan, produk tersambung; skor ≤ 30 hari dari cutoff.
- **Langkah:** evaluasi satu pelanggan melalui `POST /decisions/next-best-actions/evaluate`.
- **Hasil yang diharapkan:** `score_state = SCORE_READY`, `serving_ready = true`; aksi sesuai matriks `target_definitions.md` §3.1 untuk segmen itu; `expected_value` berupa angka dari sistem (Rp format titik); `reason` kalimat Indonesia sederhana; `model_version` tercatat; baris `dec.nba_decisions` dan `gov.decision_traces` tersimpan.
- **Hasil aktual:** BELUM DIJALANKAN

### UAT-02 · Belum ada skor (keadaan 1)
- **Prasyarat:** pelanggan nyata tanpa baris skor.
- **Langkah:** evaluasi pelanggan itu; buka kartu keputusan.
- **Hasil yang diharapkan:** `score_state = SCORE_MISSING`, `score_unavailable_reason = SCORE_ROW_MISSING`; lencana "Belum ada skor"; aksi `NO_ACTION`; skor, band, CLV, EV tampil `Kosong`; `expected_value = null`.
- **Hasil aktual:** BELUM DIJALANKAN

### UAT-03 · Run menunggu review (keadaan 2)
- **Prasyarat:** run hasil `prediction_import` berstatus `pending_review`.
- **Langkah:** evaluasi pelanggan yang skornya ada di run itu.
- **Hasil yang diharapkan:** `score_state = SCORE_PRESENT_NOT_APPROVED`, alasan `MODEL_RUN_NOT_REVIEWED`, `model_review_status = pending_review`; lencana "Skor ada, belum dipakai" (bukan hijau); teks "menunggu pemeriksaan reviewer"; `model_version` tampil; skor/band/CLV/EV `Kosong`; `NO_ACTION`.
- **Catatan:** bila baris itu berstatus kontrak `SCHEMA_PARTIAL`, hasil ini hanya benar setelah loader memperbaiki pengembalian `None` (lihat `integration/UI_SCORE_STATES_SPEC.md` §5). Sebelum itu hasil aktualnya "keadaan 1": catat sebagai temuan, bukan lulus.
- **Hasil aktual:** BELUM DIJALANKAN

### UAT-04 · Run ditolak (keadaan 2)
- **Prasyarat:** run berstatus `rejected` (reviewer memilih tolak).
- **Hasil yang diharapkan:** alasan `MODEL_RUN_NOT_REVIEWED` dengan `model_review_status = rejected`; teks "ditolak reviewer, jadi tidak dipakai" (**bukan** "menunggu"); tidak ada angka; `NO_ACTION`.
- **Hasil aktual:** BELUM DIJALANKAN

### UAT-05 · Review oleh pengunggah atau pembuat model
- **Prasyarat:** run `reviewed` dengan `reviewed_by` = `submitted_by` (atau = `model_author` bila diketahui).
- **Hasil yang diharapkan:** skor ditolak, alasan `MODEL_RUN_REVIEWED_BY_SUBMITTER`, teks "reviewer harus berbeda dari pengirim model"; tidak ada angka; `NO_ACTION`.
- **Hasil aktual:** BELUM DIJALANKAN

### UAT-06 · Sudah direview, belum ada izin pakai (keadaan 2)
- **Prasyarat:** run `reviewed` oleh orang lain; `usage_approved` tidak `True` (belum ada sumbernya, atau `False` setelah dicabut).
- **Hasil yang diharapkan:** alasan `MODEL_USAGE_NOT_APPROVED`; teks "sudah diperiksa, tetapi belum disetujui untuk dipakai"; tidak ada angka; `NO_ACTION`. Hanya nilai boolean `True` yang membuka skor; `1`, `"true"`, `None` tidak.
- **Hasil aktual:** BELUM DIJALANKAN

### UAT-07 · Skor kedaluwarsa
- **Prasyarat:** skor ber-label uji dengan `score_generated_at` tepat 30 hari lalu, lalu 31 hari lalu.
- **Hasil yang diharapkan:** 30 hari masih sah (`SCORE_READY`). 31 hari: `SCORE_EXPIRED`, `serving_ready = false`, `degraded_input = true`, `expected_value = null`, `NO_ACTION`. Umur dihitung dari cutoff/generasi skor, bukan waktu impor.
- **Hasil aktual:** BELUM DIJALANKAN

### UAT-08 · ID tidak cocok / tanpa pemetaan pasti
- **Prasyarat:** (a) pelanggan aplikasi tanpa Golden ID terpetakan; (b) baris skor milik ID lain.
- **Hasil yang diharapkan:** (a) pelanggan tidak dievaluasi atau hasilnya "belum ada skor"; tidak ada tebakan ID (keputusan D4 menentukan apakah fallback `customer_code` dihapus). (b) alasan `SCORE_CUSTOMER_MISMATCH`, tanpa menampilkan ID pelanggan lain; `NO_ACTION`.
- **Hasil aktual:** BELUM DIJALANKAN

### UAT-09 · Data sebagian hilang
- **Prasyarat:** (a) skor kehilangan satu field wajib (mis. `clv_amount`); (b) salah satu sumber non-skor (consent/komplain/kontak/kelayakan/produk) belum tersambung (`None`).
- **Hasil yang diharapkan:** (a) `SCORE_FIELDS_INCOMPLETE` dengan `score_missing_fields` terisi; seluruh skor ditolak, tidak ada nilai pengganti (nol bukan "kosong"). (b) `unavailable_sources` memuat sumbernya; "Belum ada keputusan promosi karena sumber berikut belum tersambung: …"; `serving_ready = false`; tidak ada rekaman K-07 palsu. `[]` (tersambung dan kosong) berbeda dari `None` (belum tersambung).
- **Hasil aktual:** BELUM DIJALANKAN

### UAT-10 · `NO_ACTION` karena kebijakan (skor tinggi tidak melangkahi aturan)
- **Prasyarat:** pelanggan dengan skor siap dan risiko tinggi, dalam tiga kondisi: (a) global opt-out; (b) sudah menerima 2 pesan komersial dalam 14 hari; (c) komplain berat terbuka.
- **Hasil yang diharapkan:** (a) `NO_ACTION`, alasan `OPT_OUT_SUPPRESSED` (juga mengalahkan `COMPLAINT_RESOLUTION`). (b) `NO_ACTION`, alasan menyebut batas 2 pesan / 14 hari (`FREQ_CAP_SUPPRESSED`); `COMPLAINT_RESOLUTION` dan `SERVICE_REMINDER` tidak dihitung. (c) `COMPLAINT_RESOLUTION`, tidak ada promosi (`EXCL_OPEN_SEVERE_COMPLAINT`). Untuk segmen CHURNED/REACTIVATED/NEVER_TRANSACTED: perilaku sesuai jawaban P2 (saat ini Opsi A: RM_CONTACT/RENEWAL_REMINDER/COMPLAINT_RESOLUTION lintas segmen tetap berlaku).
- **Hasil aktual:** BELUM DIJALANKAN

### UAT-11 · Worker gagal / retry impor skor
- **Prasyarat:** `PREDICTION_IMPORT_ROOT` terkonfigurasi; (a) impor manifest yang sama dua kali; (b) artefak rusak/dimanipulasi; (c) folder tidak diizinkan (`ground_truth`, path keluar root).
- **Hasil yang diharapkan:** (a) tidak ada baris ganda (`already_imported = true`). (b) tidak ada hasil parsial yang tampak lengkap (tidak ada record yang masuk). (c) ditolak. Hasil impor berstatus `pending_review`, plus audit event. Pengujian ini memakai kode Moses; Christ hanya menerima hasilnya.
- **Hasil aktual:** BELUM DIJALANKAN

### UAT-12 · Campaign tanpa persetujuan
- **Prasyarat:** campaign tanpa `approved_by` (manusia); variasi kanal non-simulator.
- **Hasil yang diharapkan:** ditolak (`ValueError`), tidak ada pesan terkirim, tidak ada baris kontak; kanal selain `*_sim` ditolak.
- **Hasil aktual:** BELUM DIJALANKAN

### UAT-13 · Campaign berjalan dan pengukuran
- **Prasyarat:** UAT-01 lulus; campaign disetujui manusia; kanal simulator.
- **Langkah:** jalankan campaign; buka ringkasan; ukur sebelum dan sesudah ada hasil konversi.
- **Hasil yang diharapkan:** ringkasan: audiens, layak, terkirim (simulasi), dilewati beserta alasan (opt-out, komplain, fatigue, tanpa consent kanal); holdout control ≈ 10%; `control_exposure_count = 0`; tanpa panggilan jaringan keluar. Sebelum ada hasil: `AWAITING_OUTCOMES` dan angka lift tidak ditampilkan. Sesudah ada hasil: Observed dan Incremental terpisah, status PROVISIONAL/FINAL sesuai jendela (30 hari konversi, 14 hari penyesuaian refund).
- **Hasil aktual:** BELUM DIJALANKAN

### UAT-14 · Data tersimpan, audit trail, UI kosong
- **Langkah:** (a) muat ulang aplikasi / restart server; (b) buka audit trail keputusan dan campaign; (c) buka layar yang belum punya data.
- **Hasil yang diharapkan:** (a) keputusan, hasil job campaign, dan pengukuran masih ada (bukan hanya di memori/file). (b) ada `nba.engine_evaluated`, `campaign.executed`, `campaign.measured` dengan `correlation_id` sama; rantai keputusan bisa direkonstruksi < 5 menit. (c) tiap kolom tanpa data tampil `Kosong`, tanpa angka contoh.
- **Hasil aktual:** BELUM DIJALANKAN

## Penandatangan dan keputusan yang masih terbuka
- **Penandatangan UAT:** [ISI] (D7, diputuskan di meeting). Penguji bukan pembuat kode.
- **Arti "campaign jalan beneran":** usulan Christ = simulator ber-label cukup untuk demo MVP, tanpa pengiriman nyata; butuh konfirmasi mentor (D7).
- **Skenario yang bergantung keputusan:** UAT-01 (D2/D3/D5), UAT-08 (D4), UAT-10 untuk segmen CHURNED/REACTIVATED/NEVER_TRANSACTED (P2).

## Bukti pra-UAT otomatis (bukan pengganti UAT)
```
python -m pytest tests/decision -q
PYTHONPATH=. python docs/christ_business/demo/run_demo.py   # data sintetis, berlabel
```
Perilaku inti tiap skenario sudah dijaga test pada level fungsi (kolom "Dijaga test otomatis"). UAT-13 dan UAT-14 baru bisa diuji setelah `api/` dan `worker/` menyimpan hasilnya.

## Skrip demo (±5 menit)

1. Tunjukkan 5 profil pelanggan dan alasan tiap keputusan (bagian [1] demo).
2. Jalankan campaign: tunjukkan holdout dan paparan control = 0 (bagian [2]).
3. Tunjukkan bahwa sebelum ada konversi, angka lift tidak ditampilkan (bagian [2]).
4. Masukkan hasil konversi, tunjukkan Observed vs Incremental (bagian [3]).
5. Tutup dengan jejak audit (bagian [4]).

Untuk demo di aplikasi, ulangi langkah 1-5 lewat UI dengan data dari database dan sebutkan apa adanya bagian yang masih kosong. Tambahkan tiga keadaan skor (UAT-02, UAT-03, UAT-06) sebagai bagian demo: tunjukkan bahwa "belum ada", "ada tapi belum disetujui", dan "siap dipakai" tampil berbeda.
