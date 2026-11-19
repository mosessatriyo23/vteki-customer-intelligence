# Global importance dan evaluasi subkelompok — development

Modul: `services/data/models/model_importance.py`. Laporan awal memakai holdout dari eksperimen masing-masing, seed 42, 10 repeat. Tidak refit: permutation kolom fitur mentah melewati preprocessing model yang sudah dilatih. Angka berikut hasil run subagent dan run ulang main agent; focused test diverifikasi main agent (10 passed). Review independen selesai tanpa temuan wajib. Reviewer merekonstruksi ketiga holdout dan memastikan probabilitas hasil reload cocok dengan prediksi tersimpan (selisih maksimum 4,45e-16), termasuk imputer/scaler artefak.

## Ringkasan

| Model | Holdout | ROC-AUC | Brier | Mean AUC drop permutasi bersama tiga frequency |
|---|---:|---:|---:|---:|
| Churn | 33.779 | 0,903389 | 0,092640 | 0,36242 ± 0,00242 |
| Retail30 | 27.647 | 0,679816 | 0,267696 | 0,15060 ± 0,00348 |
| Renewal60 POS-only | 8.465 | 0,465716 | 0,251365 | −0,03419 ± 0,00668 |

Kolom terkuat churn adalah purchase_count_90d (AUC drop 0,29561 ± 0,00354), juga retail (0,22304 ± 0,00365). Renewal POS-only tidak menunjukkan sinyal berguna: largest single drop hanya 0,00127 ± 0,00155, dan permutasi frequency group justru memperbaiki ranking. Nilai negatif tidak dipotong.

## Performa agregat menyembunyikan kelemahan

- **Churn recency 91–180:** n=2.430, AUC **0,428**, Brier 0,255 meskipun AUC keseluruhan 0,903. Model tidak boleh disajikan sama kuat pada semua kelompok.
- **Retail recency 31–90:** n=8.585, AUC **0,516**, Brier 0,323; discrimination dalam kelompok ini hampir acak.
- **Renewal recency >180:** n=95, seluruh outcome negatif. AUC null dengan alasan `n_below_min_n_and_single_class`.
- **Renewal tenure >365:** n=395, seluruh outcome negatif. AUC null dengan alasan `single_class`.

Pengelompokan recency/tenure/frequency adalah subkelompok fitur deterministik, **bukan lifecycle atau tier CLV final**. Evaluasi per nilai CLV belum digantikan oleh laporan ini. Perbandingan subgroup bersifat deskriptif, bukan tuning atau pemilihan target dari holdout.

## Batas interpretasi

Permutation importance mengukur ketergantungan model, bukan efek kausal. Kolom frequency 60/90/365 hari berkorelasi, sehingga permutasi satu kolom dapat memberi kombinasi tidak wajar dan tidak mengukur dampak menghapus fitur/retrain. Permutasi bersama memakai satu urutan baris acak yang sama untuk ketiga kolom guna mempertahankan hubungan internalnya. Std repeat adalah variasi permutasi, **bukan confidence interval generalisasi**.

Cakupan saat ini churn fitted dua-cutoff dan propensity POS-only. Tidak termasuk model churn tiga-fold atau renewal membership eksploratif. Tidak ada klaim semua model sudah memiliki laporan explainability lengkap. Tidak ada taxonomy bisnis/approval/serving readiness yang diberikan oleh laporan ini.

Artefak awal: `artifacts/models/importance_{churn,retail,renewal}_verified_20261119/`. Main agent telah menjalankan ulang kode dengan guard checksum terbaru ke `artifacts/models/importance_{churn,retail,renewal}_reviewed_20261119/`; ketiganya selesai dengan holdout masing-masing 33.779 / 27.647 / 8.465. Review independen kode selesai tanpa temuan wajib; ini bukan persetujuan model oleh validator atau izin serving. Data sintetis, retrospective identity, bukan historical PIT certification.
