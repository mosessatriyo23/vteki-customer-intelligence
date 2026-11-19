# Moses — titik masuk handoff data/AI terbaru

Tanggal: 2026-11-19. **Churn synthetic-development sudah runnable; seluruh cakupan AI FRD belum selesai.** Jangan memakai status COMPLETE di handoff Oktober sebagai tanda semua model final telah selesai. Acuan yang tersedia FRD/TRD v0.9 draft + Requirement_Capstone + keputusan Christ v1.3; bukan bukti v1.0 final approved.

## Yang dapat dicoba tim sekarang

1. Jalur sumber tervalidasi → identity → fitur/label churn tiga event → temporal fit/evaluation → JSON model → inference fitur tanpa label. Perintah reproducible dan hasil ada di [progress](MOSES_DEVELOPMENT_PROGRESS_2026-11-19.md).
2. [Model card fitted](MODEL_CARD_FITTED_CHURN_DEV_1_0.md) berisi versi, cohort, tujuh fitur, metrik dan checksum. Model baseline lama tetap terpisah.
3. Diagnostik evaluasi: customer-bootstrap CI, reliability bins dan fixed-threshold metrics. Diagnostik feature drift: train-only bins, missingness dan PSI. Offline saja, tidak menjadwalkan retraining atau campaign.
4. [Tabel retensi untuk Christ](RETENTION90_CHRIST_HANDOFF_DEV_2026-11-19.md) portable, bukan retention factor CLV otomatis.
5. `clv_projection.project_clv` membungkus formula existing: retention factor wajib eksplisit beserta versi, tanpa faktor hasil forward/total/tier unavailable. Ini kalkulator, bukan fitted model CLV.

## Evaluasi lanjutan — termasuk temuan yang tidak bagus

- [Kalibrasi tiga fold](CALIBRATION_FINDING_DEV_2026-11-19.md): isotonic calibration pada fold terpisah **memperburuk** ECE dan Brier pada test (tidak tergeneralisasi), dan threshold 0,5 menjadi tidak berguna setelah kalibrasi (TP=0). Threshold yang dipilih dari fold kalibrasi (≈0,25) menaikkan recall 0,513→0,884 dengan trade-off precision 0,594→0,465 — keputusan bisnis untuk Christ.
- [Reason codes](REASON_CODE_LIMITATION_DEV_2026-11-19.md): 50.141/50.640 prediksi punya ≥3 alasan matematis yang lolos cek faithfulness, tetapi mayoritas tiga alasan teratas adalah tiga jendela waktu dari satu konsep (frekuensi pembelian 365/90/60 hari). **Ini belum memenuhi niat "tiga alasan bisnis berbeda".**
- [Renewal dengan fitur membership](RENEWAL_MEMBERSHIP_EXPLORATORY_DEV_2026-11-19.md): fitur membership baru (`days_to_expiry`, tier, tenure, riwayat renewal) menaikkan AUC renewal60 dari 0,4657 (POS-only) menjadi **0,6492** pada holdout Juni. Status **eksploratif**, bukan konfirmasi independen, karena holdout itu sudah dilihat lewat probe. Sinyalnya kemungkinan berasal dari struktur window eligibility, belum diuji dengan ablasi.
- [Eksperimen propensity](PROPENSITY_EXPERIMENT_FINDING_DEV_2026-11-19.md): retail logistic (AUC 0,680) sedikit di bawah aturan sederhana `recency<=30` (AUC 0,684). **Renewal POS-only AUC 0,4657**, di bawah referensi acak pada holdout ini; semua keputusan pada threshold 0,5 positif, bukan berarti skor konstan. Ketiadaan fitur membership merupakan hipotesis keterbatasan, bukan akar sebab yang terbukti. Eksperimen membership-only terbaru dijelaskan di atas.

## Belum selesai — dibedakan supaya tim tidak menerima klaim palsu

| Area | Status sekarang | Pemicu tindak lanjut |
|---|---|---|
| Governed churn prediction I-04 | Belum tersedia: skor mentah offline; belum calibration, risk bands/expiry dan reason codes bisnis sah | Christ/James menyepakati kontrak; Moses menambah producer + acceptance fixtures setelah artinya jelas |
| Historical PIT | Belum terbukti: current mapping/final status retrospektif | James menyediakan known-at/refund correction/identity-as-of dengan coverage; Moses menguji consumer |
| CLV 12 bulan | Formula ada, faktor empiris final belum ada; mismatch nama Gross vs net/retained belum diputuskan | [Rekonsiliasi](CLV_REVENUE_RECONCILIATION_DEV.md), Christ memilih convention/estimand, James memastikan as-of source |
| Propensity retail/renewal | Sudah fitted & dievaluasi; renewal POS-only tidak berguna; membership-only eksploratif AUC 0,649 (belum ablasi/konfirmasi); booking source tidak ada | Ablasi fitur membership, cutoff evaluasi baru, dan definisi booking source dengan James |
| Reason codes | Matematis faithful tersedia; taxonomy bisnis "distinct" belum disepakati | Christ memutuskan apakah 3 fitur frekuensi = 1 atau 3 alasan |
| Kalibrasi | Dicoba dan **tidak membantu** pada data ini; threshold dari fold kalibrasi terbukti berguna | Christ memilih trade-off precision/recall; jangan pakai isotonic ini sebagai kalibrasi final |
| API/worker/persisted NBA/campaign | Tidak disentuh oleh slice Moses ini | Integrasi James/Christ, tidak menggunakan integer customer demo sebagai Golden ID |

`training_ready=false`, `experiment_ready=false`, `final_model=false`, `serving_ready=false`. Tidak ada Gate A/C/D ditutup oleh dokumen ini. Snapshot September mencakup semua pelanggan, tidak membuktikan eligible campaign audience. Revisi target/fitur harus versi baru dan retrain; [aturan revisi](CHURN_MODEL_REVISION_POLICY_DEV.md).

## Verifikasi lokal

`.venv\Scripts\python.exe -m pytest -q` pasca-review: **1080 passed, 19 skipped, 3 xfailed**, warning Starlette/httpx. Test targeted pasca-review: **68 passed**. Tiga test regresi tambahan membuktikan empty population sudah ditolak ValueError oleh shared PSI helper, bukan ZeroDivisionError. Docstring CLV diperbaiki agar tidak mengklaim net/retained source yang belum digunakan. PostgreSQL acceptance yang skipped tidak dianggap lulus. Ruff dan Black file baru lulus. Output besar berada di `artifacts/` ignored; jangan commit data/PII/ground_truth/.env. Gunakan output dir baru, jangan timpa artefak. Perubahan belum di-commit dan belum di-push.
