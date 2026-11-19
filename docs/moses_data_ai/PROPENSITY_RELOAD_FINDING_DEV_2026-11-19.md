# Reloadable offline inference propensity — development

Modul `services/data/models/propensity_inference.py` memuat artefak logistic JSON retail_purchase30 atau renewal60 POS-only, menerapkan median/scaler/coef/intercept hasil training tanpa sklearn pada jalur reload. Bukan model membership eksploratif atau calibrated model. Loader memeriksa target, versi, shape, finite values, duplicate JSON keys dan checksum.

## Hasil run sumber fitur tanpa label

| Target | Snapshot rows | Holdout matched | Missing keys | Selisih >=1e-12 | Maksimum selisih |
|---|---:|---:|---:|---:|---:|
| Retail30 | 75.002 | 27.647 | 0 | 0 | 2,22e-16 |
| Renewal60 POS-only | 75.002 | 8.465 | 0 | 0 | 1,11e-16 |

Angka parity adalah hasil pemeriksaan subagent pada existing fitted holdout predictions; focused tests main agent 28 passed, Ruff/Black bersih. Review independen (20 Nov) selesai tanpa temuan wajib: parity direproduksi dari artefak, tetapi angka parity berasal dari perbandingan sekali jalan, bukan test repo yang meregenerasinya. Commit lokal `ccb68bb`; main-agent focused inference 28 passed dan combined regression 47 passed; full suite terakhir 1293 passed, 19 skipped, 3 xfailed. Parity numerik tidak membuktikan calibration, manfaat model renewal, atau eligibility campaign. Keluaran mencakup seluruh snapshot, termasuk pelanggan yang tidak eligible; tidak ada outcome label yang dibaca jalur inference.

## Reproduksi

```powershell
.venv\Scripts\python.exe -m services.data.models.propensity_inference --model-dir artifacts/models/propensity_retail_20261119 --features-dir artifacts/features/propensity_20260301_20260601_dev --target retail_purchase30 --output-dir artifacts/predictions/propensity_retail_reload_20261119
.venv\Scripts\python.exe -m services.data.models.propensity_inference --model-dir artifacts/models/propensity_renewal_20261119 --features-dir artifacts/features/propensity_20260301_20260601_dev --target renewal60 --output-dir artifacts/predictions/propensity_renewal_reload_20261119
```

Gunakan output baru bila mengulang. Manifest mempertahankan hash input/output dan flag development_only/non-serving. Skor belum dikalibrasi, valid_until null, tanpa alasan bisnis atau approval dan tidak ada adapter NBA. Jangan menggunakan output untuk memilih audiens.
