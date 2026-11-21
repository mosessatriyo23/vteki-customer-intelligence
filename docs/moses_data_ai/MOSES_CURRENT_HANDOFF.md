# Moses — titik masuk handoff data/AI terbaru

## Status terbaru 2026-11-21 — menggantikan seluruh status di bawah

> Untuk pembagian kerja dan keputusan bersama dengan Christ/Marvin menuju MVP, baca [TEAM_ALIGNMENT_MVP_2026-11-21.md](TEAM_ALIGNMENT_MVP_2026-11-21.md). PR #58 menambah formatter kalimat alasan Indonesia; belum tersambung ke API/worker/UI.

- Paket Moses PR #48–#54 dan #56 sudah merged (`bdf74c6` adalah merge #56): wrapper CLV `actual_revenue`, inventaris model development, kontribusi log-odds propensity retail/renewal, monitoring PSI/volume/alert advisory, skeleton registry fitur K-03, disclaimer sintetis TRD 9.7, metadata inventaris/estimator terverifikasi, importance renewal-membership dan churn 3-fold terkalibrasi, laporan kualitas data offline (FR-CDI-004), tes leakage feature→label→fit→inference, serta bukti benchmark dan ingestion. Tidak satupun menutup kontrak serving, approval, atau acceptance lintas tim.
- Monitoring: [bukti dan batasan](PREDICTION_MONITORING_DEV_2026-11-20.md). Retail PSI 0,08423 (STABLE), renewal 0,14147 (WARNING); bukan bukti degradasi performa. `band_mix`/`segment_performance` tetap `None` menunggu kebijakan band/segmen dari Christ. Semua output development-only.
- Gate gabungan lokal terverifikasi terakhir (PR #56): **1458 passed, 19 skipped, 3 xfailed**; Ruff/Black/Mypy bersih. [Ledger penutupan mandiri](MOSES_INDEPENDENT_WORK_LEDGER_2026-11-20.md) membedakan implementasi, PR dan blocker lintas tim.
- Benchmark: identity v1.1 pair recall **0,938893**, di bawah aspirasi 95%; tidak ada model pemenang pada churn/retail/renewal. Lihat [bukti benchmark](BENCHMARK_EVIDENCE_2026-11-20.md).
- Empat dokumen handoff/status Moses yang sudah tergantikan (handoff Oktober, closure scope lama, weekly gap 17 Nov) telah dihapus; rujukan sekarang mengarah ke dokumen ini dan ledger di atas.
- Christ v1.4 tetap PENDING mentor approval. Requirement_Capstone membedakan definisi churn **180 hari ke depan** dari horizon prediksi **90 hari ke depan**; persoalannya perlu konfirmasi mentor, bukan sekadar kontradiksi angka atau late-data reprocessing. Pertanyaan P1–P8 tetap di [pesan rekonsiliasi](CHRIST_V14_RECONCILIATION_MESSAGE_2026-11-20.md), belum ada bukti jawaban/komunikasi eksternal di pekerjaan ini.
- Paragraf dan angka tes di bawah adalah riwayat sebelum PR #48; pernyataan seperti "belum ada projection consumer" dan "belum di-push" tidak berlaku sebagai status terbaru.

> **Update rekonsiliasi 2026-11-20 (baca dahulu):** [Pesan siap kirim Moses → Christ tentang `target_definitions.md` v1.4](CHRIST_V14_RECONCILIATION_MESSAGE_2026-11-20.md). Dokumen v1.4 masih **PENDING approval mentor**; rujukan 180 vs 90 hari adalah kontradiksi dalam Requirement Bab 2.1 yang ditandai di v1.4 §1.1 / Gate A D1, bukan sekadar isu late-data reprocessing. Main sudah memuat PR #47 (`abfcb50`): builder `actual_revenue` tersedia, tetapi pada baseline PR #47 **belum ada projection consumer**; wrapper proyeksi terpisah sedang dikerjakan di slice berikutnya, belum dapat diklaim selesai/teruji di sini. Bukti tes **PR #47 saja**: 1326 passed, 19 skipped, 3 xfailed. NEW dengan batas total transaksi ≤2 sudah diperbaiki (`586088b`). Tabel retensi 90 hari di bawah hanya diagnostik, **bukan** retention factor CLV 365 hari. Output baru tetap development-only (`training_ready=false`, `experiment_ready=false`, `final_model=false`, `serving_ready=false`); tidak ada serving approval. Bagian bertanggal 2026-11-19 di bawah dipertahankan sebagai catatan historis, termasuk angka tes dan rujukan v1.3 yang berlaku saat ditulis; jangan baca sebagai status v1.4 terkini.

Tanggal: 2026-11-19. **Churn synthetic-development sudah runnable; seluruh cakupan AI FRD belum selesai.** Jangan memakai status COMPLETE di handoff Oktober sebagai tanda semua model final telah selesai. Acuan yang tersedia FRD/TRD v0.9 draft + Requirement_Capstone + keputusan Christ v1.3; bukan bukti v1.0 final approved.

## Yang dapat dicoba tim sekarang

1. Jalur sumber tervalidasi → identity → fitur/label churn tiga event → temporal fit/evaluation → JSON model → inference fitur tanpa label. Perintah reproducible dan hasil ada di [progress](MOSES_DEVELOPMENT_PROGRESS_2026-11-19.md).
2. [Model card fitted](MODEL_CARD_FITTED_CHURN_DEV_1_0.md) berisi versi, cohort, tujuh fitur, metrik dan checksum. Model baseline lama tetap terpisah.
3. Diagnostik evaluasi: customer-bootstrap CI, reliability bins dan fixed-threshold metrics. Diagnostik feature drift: train-only bins, missingness dan PSI. Offline saja, tidak menjadwalkan retraining atau campaign.
4. [Tabel retensi untuk Christ](RETENTION90_CHRIST_HANDOFF_DEV_2026-11-19.md) portable, bukan retention factor CLV otomatis.
5. `clv_projection.project_clv` membungkus formula existing: retention factor wajib eksplisit beserta versi, tanpa faktor hasil forward/total/tier unavailable. Ini kalkulator, bukan fitted model CLV.

## Evaluasi lanjutan — termasuk temuan yang tidak bagus

- [Importance global dan evaluasi subkelompok](GLOBAL_IMPORTANCE_SEGMENT_FINDING_DEV_2026-11-19.md) tersedia untuk churn dua-cutoff dan propensity POS-only; review independen tanpa temuan wajib. AUC churn agregat 0,903 menutupi AUC **0,428** pada recency 91–180 hari; retail recency 31–90 AUC **0,516**. Ini bukan evaluasi lifecycle/tier CLV final dan belum mencakup renewal membership.
- [Peringatan producer prediksi pertama](PREDICTION_CONTRACT_REVIEW_NOTICE_2026-11-19.md): artefak `churn_contract_dev_20260906` tidak boleh dipakai untuk acceptance/serving. Pengganti `churn_contract_dev_20260906_reviewed_v2` seluruhnya berstatus SCHEMA_PARTIAL; tanggal cutoff, adapter default-refusal dan hash lineage telah diperbaiki, tanpa mengarang expiry sumber.

- [Kalibrasi tiga fold](CALIBRATION_FINDING_DEV_2026-11-19.md): isotonic calibration pada fold terpisah **memperburuk** ECE dan Brier pada test (tidak tergeneralisasi), dan threshold 0,5 menjadi tidak berguna setelah kalibrasi (TP=0). Threshold yang dipilih dari fold kalibrasi (≈0,25) menaikkan recall 0,513→0,884 dengan trade-off precision 0,594→0,465 — keputusan bisnis untuk Christ.
- [Reason codes](REASON_CODE_LIMITATION_DEV_2026-11-19.md): 50.141/50.640 prediksi punya ≥3 alasan matematis yang lolos cek faithfulness, tetapi mayoritas tiga alasan teratas adalah tiga jendela waktu dari satu konsep (frekuensi pembelian 365/90/60 hari). **Ini belum memenuhi niat "tiga alasan bisnis berbeda".**
- [Renewal dengan fitur membership](RENEWAL_MEMBERSHIP_EXPLORATORY_DEV_2026-11-19.md): fitur membership baru menaikkan AUC renewal60 dari 0,4657 (POS-only) menjadi **0,6492** pada holdout Juni. Status eksploratif.
- [Ablasi fitur renewal](RENEWAL_ABLATION_FINDING_DEV_2026-11-19.md): kenaikan itu **hampir seluruhnya dari satu sinyal** (`days_to_expiry`/`days_since_last_membership_event`, keduanya redundan). Empat fitur lain (tier, tenure, riwayat renewal, upgrade) sendirian **di bawah atau mendekati acak**. Sebagian besar AUC adalah artefak struktur eligibility window, bukan perilaku pelanggan. Jangan mempromosikan model enam-fitur sebagai lebih baik dari model satu-fitur.
- [Eksperimen propensity](PROPENSITY_EXPERIMENT_FINDING_DEV_2026-11-19.md): retail logistic (AUC 0,680) sedikit di bawah aturan sederhana `recency<=30` (AUC 0,684). **Renewal POS-only AUC 0,4657**, di bawah referensi acak pada holdout ini; semua keputusan pada threshold 0,5 positif, bukan berarti skor konstan. Ketiadaan fitur membership merupakan hipotesis keterbatasan, bukan akar sebab yang terbukti. Eksperimen membership-only terbaru dijelaskan di atas.

## Belum selesai — dibedakan supaya tim tidak menerima klaim palsu

| Area | Status sekarang | Pemicu tindak lanjut |
|---|---|---|
| Governed churn prediction I-04 | Belum tersedia: skor mentah offline; belum calibration, risk bands/expiry dan reason codes bisnis sah | Christ/James menyepakati kontrak; Moses menambah producer + acceptance fixtures setelah artinya jelas |
| Historical PIT | Belum terbukti: current mapping/final status retrospektif | James menyediakan known-at/refund correction/identity-as-of dengan coverage; Moses menguji consumer |
| CLV 12 bulan | Formula ada, faktor empiris final belum ada; mismatch nama Gross vs net/retained belum diputuskan | [Rekonsiliasi](CLV_REVENUE_RECONCILIATION_DEV.md), Christ memilih convention/estimand, James memastikan as-of source |
| Propensity retail/renewal | Sudah fitted & dievaluasi; renewal POS-only tidak berguna; membership-only eksploratif AUC 0,649 namun **ablasi eksploratif menunjukkan dominasi sinyal expiry**, bukan enam; booking source tidak ada | Cutoff evaluasi baru yang belum diperiksa, definisi booking source dengan James |
| Reason codes | Matematis faithful tersedia; taxonomy bisnis "distinct" belum disepakati | Christ memutuskan apakah 3 fitur frekuensi = 1 atau 3 alasan |
| Kalibrasi | Dicoba dan **tidak membantu** pada data ini; threshold dari fold kalibrasi terbukti berguna | Christ memilih trade-off precision/recall; jangan pakai isotonic ini sebagai kalibrasi final |
| API/worker/persisted NBA/campaign | Tidak disentuh oleh slice Moses ini | Integrasi James/Christ, tidak menggunakan integer customer demo sebagai Golden ID |

`training_ready=false`, `experiment_ready=false`, `final_model=false`, `serving_ready=false`. Tidak ada Gate A/C/D ditutup oleh dokumen ini. Snapshot September mencakup semua pelanggan, tidak membuktikan eligible campaign audience. Revisi target/fitur harus versi baru dan retrain; [aturan revisi](CHURN_MODEL_REVISION_POLICY_DEV.md).

## Verifikasi lokal

`.venv\Scripts\python.exe -m pytest -q` terakhir: **1293 passed, 19 skipped, 3 xfailed**, satu warning Starlette/httpx (run setelah restart; focused regression berikutnya 47 passed). Ruff dan Black bersih pada 151 file `services`/`tests`. Gunakan `.venv\Scripts\python.exe`, bukan `python` default, karena dependensi model hanya terpasang di venv.

PostgreSQL acceptance yang skipped **tidak** dianggap lulus. Tiga test regresi membuktikan empty population ditolak `ValueError` oleh shared PSI helper, bukan `ZeroDivisionError`. Docstring CLV tidak lagi mengklaim sumber net/retained yang belum dipakai.

Output besar berada di `artifacts/` yang di-ignore; jangan commit data/PII/ground_truth/.env, dan jangan menimpa artefak lama — selalu pakai output dir baru. Pekerjaan ini sudah di-commit lokal di branch `feat/moses-fitted-churn-dev` dan **belum di-push**.

Peta kesesuaian terhadap FRD/TRD beserta sisa pekerjaan ada di [status penutupan](FRD_TRD_CLOSURE_STATUS_2026-11-19.md).
