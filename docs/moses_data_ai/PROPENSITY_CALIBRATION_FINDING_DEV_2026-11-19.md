# Kalibrasi propensity tiga fold — development

Sumber label dan fitur tiga cutoff selesai (100.008 baris masing-masing). Model terpisah retail30/renewal60 dilatih Desember 2025, isotonic dan threshold di-fit/dipilih hanya pada Maret 2026, lalu dievaluasi Juni 2026. Semua artefak non-serving dan calibration_final=false.

| Target / skor | Train / calibration / test | ROC-AUC | AP | Brier | ECE |
|---|---|---:|---:|---:|---:|
| Retail raw | 11.405 / 18.678 / 27.647 | 0,708751 | 0,579663 | 0,218642 | 0,132578 |
| Retail isotonic | sama | 0,706523 | 0,568258 | 0,249749 | 0,206819 |
| Renewal POS-only raw | 5.181 / 8.087 / 8.465 | 0,578672 | 0,593391 | 0,346026 | 0,280704 |
| Renewal POS-only isotonic | sama | 0,614736 | 0,609830 | 0,231207 | 0,014579 |

Retail memburuk setelah isotonic pada test; renewal POS-only membaik pada run ini. Tidak mempromosikan model berdasarkan hasil test. Perubahan AUC sesudah transformasi monoton dapat terjadi karena ties; jangan mengklaim ranking metric pasti identik. Model dasar di sini dilatih Desember, **bukan** model POS-only dua-cutoff yang dilatih Maret dan bukan model membership eksploratif. Perbandingan lintas eksperimen tidak mengisolasi efek kalibrasi: bandingkan raw/isotonic dalam baris eksperimen yang sama.

Walau fitting/threshold dipisahkan dengan benar, cohort test Juni sudah diperiksa dalam eksperimen sebelumnya. Ini follow-up development pada reused test cohort, bukan independent fresh-holdout confirmation. Output JSON inspection belum loader calibrated serving; reloadable inference POS-only yang terpisah tetap memakai model dua-cutoff raw.

## Reproduksi

```powershell
.venv\Scripts\python.exe -m services.data.models.propensity_calibration --labels-dir artifacts/models/propensity_labels_3cut_20261119 --features-dir artifacts/features/propensity_3cut_20261119 --target retail_purchase30 --output-dir artifacts/models/propensity_retail_calibration_20261119
.venv\Scripts\python.exe -m services.data.models.propensity_calibration --labels-dir artifacts/models/propensity_labels_3cut_20261119 --features-dir artifacts/features/propensity_3cut_20261119 --target renewal60 --output-dir artifacts/models/propensity_renewal_calibration_20261119
```

Run penuh main agent berhasil untuk keduanya. Setelah review 20 November, run diulang tanpa menimpa artefak lama ke `artifacts/models/propensity_retail_calibration_20261120/` dan `artifacts/models/propensity_renewal_calibration_20261120/`; gunakan kedua direktori baru untuk limitations yang ikut tersimpan di calibration artifact. Review independen (20 Nov) selesai tanpa temuan wajib dan mereproduksi artefak kedua target. Atas catatannya, peringatan "reused cohort, bukan holdout independen" dan "kalibrasi lebih baik bukan bukti model berguna" kini juga ada di limitations/interpretasi artefak, bukan hanya di dokumen ini. Target masih proposed, renewal bukan upgrade, booking unsupported, identitas retrospektif, bukan historical PIT certification.
