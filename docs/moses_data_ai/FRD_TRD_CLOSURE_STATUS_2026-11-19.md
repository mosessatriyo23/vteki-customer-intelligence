# Status penutupan data/AI terhadap FRD/TRD

Tanggal 19 November 2026. Status kerja, bukan sertifikasi selesai atau persetujuan model. Acuan lokal: FRD/TRD dalam `requirements/extracted_20261118/`, Requirement_Capstone, dan keputusan bisnis Christ. Perbedaan antaracuan harus direkonsiliasi; dokumen lama tidak otomatis menimpa keputusan baru.

## Kriteria selesai

Sebuah requirement ditutup dengan implementasi, bukti pengujian, hasil run yang dapat direproduksi, dan acceptance yang relevan. Dokumentasi keterbatasan tidak menutup requirement yang belum diimplementasikan. Hasil model buruk tidak otomatis menggagalkan pekerjaan eksperimen: FRD tidak menjanjikan target AUC sebelum baseline. Sebaliknya, test unit lulus tidak membuktikan integrasi atau penerimaan bisnis.

## Daftar pekerjaan

| Acuan | Bukti tersedia | Yang masih harus ditutup | Pemilik tindak lanjut |
|---|---|---|---|
| FRD §6.4; TRD §9.1 fitur | Snapshot event-time berversi, pengujian future-event, fitur membership terpisah | Registry/persistence/refresh terintegrasi; bukti historical availability dan identity-as-of; cakupan keluarga fitur terhadap scope disepakati | Moses: definisi/consumer/tests; James: feed dan platform |
| FRD §6.5; TRD §9.2 segmentasi | Implementasi segmentasi development | Audit ulang RFM, lifecycle, behavioral segmentation dan histori terhadap keputusan Christ terbaru; jangan menganggap alignment 17 Nov masih final | Moses + Christ, persistence James |
| FRD §6.6; TRD §9.3 churn | Logistic temporal, comparator, JSON inference, bootstrap, lift, three-fold isotonic experiment | Evaluasi per segmen/nilai, importance global, kontrak band/expiry/reason, validasi model; perbedaan challenger shallow tree vs rancangan gradient boosting perlu keputusan scope atau eksperimen | Moses; validator terpisah untuk promosi |
| FRD §6.7; TRD §9.4 CLV | Formula/tier dan wrapper retention eksplisit | Convention revenue dan estimand retention 12 bulan, lineage serta output terintegrasi | Christ menetapkan makna; Moses implementasi/uji; James sumber |
| FRD §6.8/§9.4; TRD §9.5 propensity | Retail30 dan renewal60 fitted independen; membership-only eksploratif | Reloadable offline inference, kalibrasi terpisah, reason codes, importance/per-segmen; semantik renewal vs upgrade; booking source tidak tersedia | Moses untuk teknis; Christ target; James sumber booking |
| FRD FR-MON-001; TRD §9.3/§9.6 | Kontribusi lokal churn faithful | Importance global; alasan bisnis distinct dan berbasis fakta; explanation tiap propensity | Moses + Christ taxonomy |
| FRD FR-MON-002 | PSI/missingness dan drift offline | Distribusi skor/band, metrik per segmen, alert dan suspend/fallback integration | Moses metrik; James/validator integrasi |
| FRD K-04/OBJ-02; TRD kontrak prediksi | Offline JSON dan validator kontrak terkait | Producer lengkap dan acceptance dua sisi; validitas waktu; lineage; tidak ada adapter yang memberi otorisasi serving hanya karena schema lengkap | Moses + James + Christ |
| TRD §9.6 governance | Artefak, versi, checksum, laporan | Inventaris konsisten semua model, promosi oleh validator bukan pembuat, state machine dan proof integrasi | Moses metadata; platform/validator workflow |
| FRD T-17/T-18 | Pengujian lokal komponen | Rekonstruksi end-to-end dan fixture bersama terhadap kontrak | Bersama; bukan tanggung jawab Moses sendiri |

## Slice yang sedang berjalan

Belum dianggap selesai sebelum review dan verifikasi:

1. **Selesai untuk churn dua-cutoff dan propensity POS-only:** global permutation importance dan evaluasi subkelompok recency/tenure/frequency; 10 test lulus, run penuh diulang main agent, review independen tanpa temuan wajib. [Hasil](GLOBAL_IMPORTANCE_SEGMENT_FINDING_DEV_2026-11-19.md). Subkelompok ini bukan pengganti lifecycle atau tier CLV final; model membership dan churn tiga-fold belum tercakup.
2. **Selesai sebagai analisis eksploratif:** ablasi membership renewal pada holdout Juni yang sudah diperiksa. Aturan pembanding adalah post-hoc, bukan pre-registered; 6 test lulus. [Hasil](RENEWAL_ABLATION_FINDING_DEV_2026-11-19.md).
3. **Perbaikan berjalan:** envelope prediksi churn development. Versi awal memiliki status compliance menyesatkan, adapter tidak aman untuk development, masalah tanggal referensi dan lineage; [peringatan artefak](PREDICTION_CONTRACT_REVIEW_NOTICE_2026-11-19.md). Kelengkapan struktur bukan kepatuhan bisnis atau izin serving.
4. **Implementasi berjalan:** reloadable offline propensity inference tanpa label; tidak mengisi eligibility, CLV atau alasan yang belum tersedia.

## Batas yang tetap berlaku

- Tidak mengubah generator supaya AUC terlihat bagus; tidak memakai ground truth generator sebagai predictor.
- Tidak menambah cutoff yang outcome-nya belum mature atau menyebut reused holdout sebagai konfirmasi independen.
- Booking tidak diganti dengan service purchase; renewal tidak otomatis upgrade.
- Tidak mengisi retention factor, persetujuan, CLV atau alasan bisnis yang tidak tersedia.
- `training_ready`, `experiment_ready`, `final_model`, `serving_ready` tetap false untuk artefak development saat ini.
- Full suite terakhir sebelum slice berjalan: 1180 passed, 19 skipped, 3 xfailed. Skipped PostgreSQL bukan bukti acceptance lulus.

## Sesudah slice berjalan

Lanjutkan gap teknis Moses: inference/kalibrasi/explanation propensity, audit segmentasi terhadap baseline terbaru, inventaris/model card dan uji kontrak. Sisa dependensi eksternal harus diserahkan dengan input yang dibutuhkan serta acceptance konkret, bukan dinyatakan selesai. Tidak ada klaim 100% pada dokumen ini.
