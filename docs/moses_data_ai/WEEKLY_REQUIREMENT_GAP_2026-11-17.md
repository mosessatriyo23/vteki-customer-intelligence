# Moses — Weekly Requirement Gap Audit (Minggu 1–16)

**Tanggal:** 17 November 2026
**Sumber:** `requirements/extracted_text/` (lokal, tidak di-commit) dan bukti repository di `main` commit `6f1c3db`.
**Status:** `training_ready=false`, `experiment_ready=false`, `final_model=false`.

> Pemetaan peran: SRS mencantumkan nama anggota tanpa memetakan Moses ke "Mhs 2".
> Dokumen ini memakai deliverable Data/AI "Mhs 2" (Minggu 1). Pemetaan itu perlu
> dikonfirmasi tim sebelum audit dianggap resmi.

## 1. Status deliverable

| Minggu | Deliverable Data/AI | Status repo | Kekurangan |
|---|---|---|---|
| 2 | Definisi churn dan inactivity window | Parsial | Dokumen sumber bertentangan (lihat bagian 3); menunggu keputusan Christ (Gate A) |
| 3 | `data_quality` (null, duplikat, range, regex) | Parsial | Validator ingestion ada, tetapi tidak ada modul data quality tersendiri, rule regex per field, atau duplikat non-primary-key |
| 5 | Isi `action_catalogue` | Di luar jalur Moses di repo | Dua versi katalog di dokumen (11 aksi vs 5 sampel); keputusan Christ |
| 6 | Feature pipeline PIT + RFM/lifecycle | Parsial | Event-time saja; tidak aman terhadap `available_at`; bukan tabel `feature_value`; aturan lifecycle masih proposal |
| 7 | Model churn, CLV, propensity, scoring | Parsial/stub | Churn masih aturan recency; tidak ada model fit, scoring service, atau propensity; CLV butuh retention method |
| 9 | Evaluator, SHAP, `/models/metrics`, `/explainability/shap` | Parsial | Evaluator baseline ada; SHAP dan kedua endpoint belum ada; lift decile null untuk skor biner |
| 11 | Attribution dan drift (PSI/CSI, AUC drop) | Attribution selesai; drift **ditutup sebagian di PR ini** | Modul PSI/CSI/AUC-drop murni tersedia; belum ada API, tabel scheduler, atau binning dari baseline training |
| 12 | `test_data_leakage` | Parsial | Cakupan tersebar di tes lain; tidak ada tes per-nama dan tidak ada tes pengetahuan-lampau (`known_at`) |
| 14 | Fixture `intg_v1` | Parsial | Tidak memiliki `customer_visits.csv` dan `membership_events.csv`; kepatuhan validator belum diverifikasi |
| 15 | Model cards | Parsial | Hanya satu card untuk baseline sintetis; belum ada tiap model, SHAP, atau kalibrasi |
| 16 | Revisi laporan dan card final | Belum | Bergantung pada seluruh model dan gate |

## 2. Yang dikerjakan di PR ini

`services/data/monitoring/drift.py` (stdlib saja, tanpa I/O, DB, atau training):

- PSI dan CSI memakai bin dengan batas tetap yang sama untuk baseline dan current, ditambah bin missing terpisah.
- Smoothing aditif dengan epsilon positif, dijelaskan di docstring.
- Ambang: `<0.10` STABLE, `0.10 ≤ x < 0.25` WARNING, `≥0.25` RETRAIN_RECOMMENDED (Minggu 11).
- Penurunan ROC-AUC dianggap drift hanya jika **lebih besar dari** 0.05; perbandingan memakai `Decimal` agar tidak bergantung pada pembulatan float. AUC yang tidak tersedia menghasilkan `UNAVAILABLE`, bukan nilai karangan.
- Setiap laporan memuat `training_ready=false`, `experiment_ready=false`, `final_model=false`.

Batasan:
- Ini hanya perhitungan; tidak ada pemicu retraining otomatis.
- Bin edge harus berasal dari baseline training yang disetujui. Belum ada baseline seperti itu.
- Modul belum terhubung ke `POST /monitoring/drift`, `GET /governance/model-drift`, atau scheduler. Ambang di UI (0.2) berbeda dari requirement (0.10/0.25) dan perlu diselaraskan oleh pemilik API dan dashboard.

## 3. Konflik dokumen yang menghalangi pekerjaan model

| Topik | Sumber A | Sumber B | Pemilik keputusan |
|---|---|---|---|
| Definisi churn | Minggu 2: 90 hari tanpa transaksi | Requirement_Capstone: horizon 90 hari, tanpa perpanjangan membership; Minggu 7: 90 hari setelah prediction date | Christ |
| Lifecycle | Requirement_Capstone: New ≤30 hari, Active ≥3 transaksi/60 hari | Minggu 6: NEW <90 hari, ACTIVE transaksi dalam 90 hari, AT_RISK 91–180, LAPSED >180 | Christ |
| Nomor kontrak K-06..K-12 | Minggu 4 | Minggu 9 dan 11 | Semua tim |
| Band RFM | Minggu 6 hanya menyebut sebagian band | FRD 9.1 tidak ada di folder lokal | Christ |

Parameter yang tidak memiliki nilai di dokumen lokal dan tidak boleh diisi dengan asumsi: retention factor, action weight, `min_ev_threshold`, incentive cost.

## 4. Urutan pekerjaan berikutnya

Dapat dikerjakan sekarang (tanpa training dan tanpa aturan bisnis baru):

1. Modul drift murni (PR ini).
2. `test_data_leakage`: injeksi transaksi T+1/H+2 tidak boleh mengubah fitur atau skor di T, ditambah kasus `available_at` setelah `known_at` bila didukung kontrak James.
3. Penyelarasan ambang drift di API/UI dengan 0.10/0.25 (koordinasi dengan pemilik API).
4. Lift/decile evaluator untuk skor kontinu, diuji dengan prediksi sintetis, bukan model baru.
5. Reason-code translator berbasis dictionary dengan allowlist fitur (larangan atribut sensitif).
6. Skeleton model card per model yang tetap menandai BLOCKED.

Menunggu gate:

- Label churn versi baru, model churn/propensity, SHAP final: Gate A–C ditutup, lalu review Gate D.
- Parameter CLV, EV, dan katalog aksi: keputusan Christ.
- Fitur berbasis `known_at` dari ledger: perbaikan James (replacement recording, Customer360 dari ledger) dan feed refund/status.

## 5. Yang dibutuhkan dari tim lain

| Pemilik | Kebutuhan |
|---|---|
| Christ | Satu definisi churn dan lifecycle; retention method; parameter EV dan katalog aksi; persetujuan resmi dengan nama dan tanggal |
| James | Tutup temuan kontrak historis (lihat `READINESS_REVIEW_PACKET_2026-11-16.md`); selaraskan ambang drift di API dan UI; sediakan endpoint metrik dan drift bila dipakai dashboard |
| Semua | Konfirmasi pemetaan Moses = peran Data/AI "Mhs 2"; satu penomoran kontrak K-xx |
