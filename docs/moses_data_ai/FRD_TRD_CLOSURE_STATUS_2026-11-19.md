# Status penutupan data/AI terhadap FRD/TRD

Tanggal 19 November 2026. Status kerja, bukan sertifikasi selesai atau persetujuan model. Acuan lokal: FRD/TRD dalam `requirements/extracted_20261118/`, Requirement_Capstone, dan keputusan bisnis Christ. Perbedaan antaracuan harus direkonsiliasi; dokumen lama tidak otomatis menimpa keputusan baru.

## Pembaruan 2026-11-20 (setelah PR #48–#54; baca sebelum tabel)

Tabel di bawah ditulis 19 Nov. Butir yang sudah berubah (development-only, bukan acceptance):

- **Importance tiga-fold churn dan membership renewal:** ada (PR #53, #54). Reload/importance membership dan kalibrasi churn tersedia; reason code propensity berbasis taxonomy tetap terbuka.
- **FR-MON-002:** PSI skor, volume, dan alert advisory offline ada (PR #51). Band mix, metrik per segmen, delivery alert, suspend/fallback tetap terbuka.
- **Governance TRD §9.6:** inventaris read-only dengan metadata terverifikasi (PR #49, #53); estimator algorithm/hyperparameter dicatat untuk artefak BARU di empat generator. Promosi model, author != validator, dan persistence tetap terbuka.
- **Feature definition K-03:** skeleton in-memory (PR #52); belum persisten, daftar restricted berasal dari caller.
- **TRD 9.7:** disclaimer sintetis pada tujuh generator evaluasi (PR #52).
- Suite terakhir terverifikasi: 1429 passed, 19 skipped, 3 xfailed. Rujukan: [ledger mandiri](MOSES_INDEPENDENT_WORK_LEDGER_2026-11-20.md).
- Observasi 500 intermiten pada `POST /monitoring/drift` (CI #50) milik backend James; dibaca statis, tidak tereproduksi dari validasi payload, belum ada root cause.

## Kriteria selesai

Sebuah requirement ditutup dengan implementasi, bukti pengujian, hasil run yang dapat direproduksi, dan acceptance yang relevan. Dokumentasi keterbatasan tidak menutup requirement yang belum diimplementasikan. Hasil model buruk tidak otomatis menggagalkan pekerjaan eksperimen: FRD tidak menjanjikan target AUC sebelum baseline. Sebaliknya, test unit lulus tidak membuktikan integrasi atau penerimaan bisnis.

## Daftar pekerjaan

| Acuan | Bukti tersedia | Yang masih harus ditutup | Pemilik tindak lanjut |
|---|---|---|---|
| FRD §6.4; TRD §9.1 fitur | Snapshot event-time berversi, pengujian future-event, fitur membership terpisah | Registry/persistence/refresh terintegrasi; bukti historical availability dan identity-as-of; cakupan keluarga fitur terhadap scope disepakati | Moses: definisi/consumer/tests; James: feed dan platform |
| FRD §6.5; TRD §9.2 segmentasi | Implementasi segmentasi development; NEW lifetime-count gate sudah diperbaiki (`586088b`, rule version 1.2) | [Audit terbaru](SEGMENTATION_GAP_AUDIT_2026-11-19.md): quintile/named RFM belum tersedia; RFM recency/monetary belum positive-net purchase-only; [behavioral clustering development tersedia](BEHAVIORAL_CLUSTERING_FINDING_DEV_2026-11-20.md), nama/deskripsi dan targeting tetap belum disetujui; snapshot immutable ada tetapi bukan effective-dated membership. Policy DORMANT/REACTIVATED, NEVER_TRANSACTED dan akuntansi renewal perlu Christ | Moses + Christ, persistence James |
| FRD §6.6; TRD §9.3 churn | Logistic temporal, comparator, JSON inference, bootstrap, lift, three-fold isotonic experiment, importance global + evaluasi subkelompok untuk model dua-cutoff | Importance/evaluasi untuk model tiga-fold belum ada; evaluasi per nilai/tier CLV belum ada; kontrak band/expiry/reason dan validasi model belum ditutup; challenger shallow tree vs rancangan gradient boosting perlu keputusan scope | Moses; validator terpisah untuk promosi |
| FRD §6.7; TRD §9.4 CLV | Formula/tier dan wrapper retention eksplisit | Convention revenue dan estimand retention 12 bulan, lineage serta output terintegrasi | Christ menetapkan makna; Moses implementasi/uji; James sumber |
| FRD §6.8/§9.4; TRD §9.5 propensity | Retail30 dan renewal60 POS-only fitted independen; reloadable offline inference; kalibrasi tiga-fold per target diuji; importance/per-segmen untuk dua-cutoff; membership-only eksploratif | Reason codes propensity; importance/evaluasi model tiga-fold dan membership belum ada; reload membership/calibrated artifacts belum ada; semantik renewal vs upgrade; booking source + outcome definition belum tersedia | Moses teknis; Christ target; James sumber booking |
| FRD FR-MON-001; TRD §9.3/§9.6 | Kontribusi lokal churn faithful; importance global dua-cutoff churn dan POS-only propensity selesai | Cakupan model tiga-fold/membership belum ada; alasan human-readable berbasis fitur dan penerimaan taxonomy/konsep masih terbuka; explanation tiap propensity belum ada | Moses + Christ taxonomy |
| FRD FR-MON-002 | PSI/missingness dan drift offline | Distribusi skor/band, metrik per segmen, alert dan suspend/fallback integration | Moses metrik; James/validator integrasi |
| FRD K-04/OBJ-02; TRD kontrak prediksi | Offline JSON dan validator kontrak terkait | Producer lengkap dan acceptance dua sisi; validitas waktu; lineage; tidak ada adapter yang memberi otorisasi serving hanya karena schema lengkap | Moses + James + Christ |
| TRD §9.6 governance | Artefak, versi, checksum, laporan | Inventaris konsisten semua model, promosi oleh validator bukan pembuat, state machine dan proof integrasi | Moses metadata; platform/validator workflow |
| FRD T-17/T-18 | Pengujian lokal komponen | Rekonstruksi end-to-end dan fixture bersama terhadap kontrak | Bersama; bukan tanggung jawab Moses sendiri |

## Slice yang sedang berjalan

Belum dianggap selesai sebelum review dan verifikasi:

1. **Selesai untuk churn dua-cutoff dan propensity POS-only:** global permutation importance dan evaluasi subkelompok recency/tenure/frequency; 10 test lulus, run penuh diulang main agent, review independen tanpa temuan wajib. [Hasil](GLOBAL_IMPORTANCE_SEGMENT_FINDING_DEV_2026-11-19.md). Subkelompok ini bukan pengganti lifecycle atau tier CLV final; model membership dan churn tiga-fold belum tercakup.
2. **Selesai sebagai analisis eksploratif:** ablasi membership renewal pada holdout Juni yang sudah diperiksa. Aturan pembanding adalah post-hoc, bukan pre-registered; 6 test lulus. [Hasil](RENEWAL_ABLATION_FINDING_DEV_2026-11-19.md).
3. **Envelope prediksi churn development diperbaiki dan direview ulang** (`4049e7a`, artefak `churn_contract_dev_20260906_reviewed_v2`): seluruh 50.640 record tetap `SCHEMA_PARTIAL`; integrasi I-04 yang diatur (prediction_id, expiry otoritatif, taxonomy, kalibrasi) masih terbuka. [Peringatan artefak lama](PREDICTION_CONTRACT_REVIEW_NOTICE_2026-11-19.md). Kelengkapan struktur bukan kepatuhan bisnis atau izin serving.
4. **Implemented/tested; review independen selesai tanpa temuan wajib (20 Nov):** reloadable offline propensity inference tanpa label dan kalibrasi tiga-fold per target (`ccb68bb`). [Reload parity](PROPENSITY_RELOAD_FINDING_DEV_2026-11-19.md), [hasil kalibrasi](PROPENSITY_CALIBRATION_FINDING_DEV_2026-11-19.md). Retail isotonic memburuk; renewal POS-only membaik pada model Dec-train ini, bukan model membership. Tidak mengisi eligibility, CLV atau alasan yang belum tersedia.
5. **NEW lifetime-count gate diperbaiki:** `586088b`, versi lifecycle 1.2. Other segmentation gaps remain; [audit](SEGMENTATION_GAP_AUDIT_2026-11-19.md).
6. Verifikasi pasca-restart: 1293 passed, 19 skipped, 3 xfailed; focused regression terakhir 47 passed; Ruff/Black 151 files clean. Review independen kedua modul propensity (37 test) tanpa temuan wajib; dua catatan opsional (peringatan reused-cohort di artefak) sudah ditindaklanjuti. Ini bukan acceptance final. Lihat [permintaan antar tim](CROSS_TEAM_ACTION_REQUESTS_2026-11-20.md).

## Batas yang tetap berlaku

- Tidak mengubah generator supaya AUC terlihat bagus; tidak memakai ground truth generator sebagai predictor.
- Tidak menambah cutoff yang outcome-nya belum mature atau menyebut reused holdout sebagai konfirmasi independen.
- Booking tidak diganti dengan service purchase; renewal tidak otomatis upgrade.
- Tidak mengisi retention factor, persetujuan, CLV atau alasan bisnis yang tidak tersedia.
- `training_ready`, `experiment_ready`, `final_model`, `serving_ready` tetap false untuk artefak development saat ini.
- Full suite terakhir terverifikasi: 1293 passed, 19 skipped, 3 xfailed (angka 1180 lama adalah arsip). Skipped PostgreSQL bukan bukti acceptance lulus.

## Sesudah slice berjalan

Lanjutkan gap teknis Moses: inference/kalibrasi/explanation propensity, audit segmentasi terhadap baseline terbaru, inventaris/model card dan uji kontrak. Sisa dependensi eksternal harus diserahkan dengan input yang dibutuhkan serta acceptance konkret, bukan dinyatakan selesai. Tidak ada klaim 100% pada dokumen ini.
