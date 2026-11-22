# Bukti lokal monitoring propensity terkalibrasi — 2026-11-22

Status: **development-only**, bukan acceptance produksi, bukan persetujuan model. Model POS-only tersimpan yang sama dipakai menghitung skor pada snapshot fitur dua-cutoff; artefak baru ditulis ke direktori baru di `artifacts/models/` (di-ignore git). Tidak ada artefak historis ditimpa.

## Cara mengulang

Jalankan dari root repo dengan `.venv\Scripts\python.exe` dan input lokal yang tersedia:

1. `python -m services.data.models.calibrated_propensity_inference --model-dir artifacts/models/propensity_retail_calibration_20261120 --features-dir artifacts/features/propensity_20260301_20260601_dev --target retail_purchase30 --output-dir artifacts/models/propensity_retail_calibrated_twocut_20261122_moses`
2. `python -m services.data.models.prediction_monitoring --predictions-dir artifacts/models/propensity_retail_calibrated_twocut_20261122_moses --baseline-cutoff 2026-03-01T00:00:00+07:00 --current-cutoff 2026-06-01T00:00:00+07:00 --score-field calibrated_probability --output-dir artifacts/models/propensity_retail_calibrated_monitoring_20261122_moses`
3. Ulangi dua perintah itu dengan `propensity_renewal_calibration_20261120`, target `renewal60`, serta nama output `propensity_renewal_calibrated_twocut_20261122_moses` dan `propensity_renewal_calibrated_monitoring_20261122_moses`.

Gunakan **nama direktori output baru** untuk pengulangan. Perintah memakai `python` sebagai singkatan dalam contoh; panggil lewat `.venv\Scripts\python.exe` pada Windows. Input ini adalah artefak development lokal, bukan data produksi.

## Hasil yang benar-benar diamati

| Target | Baris yang diskor | Baseline (Maret) | Current (Juni) | PSI `calibrated_probability` | Status aturan PSI |
| --- | ---: | ---: | ---: | ---: | --- |
| `retail_purchase30` | 75.002 | 33.243 | 41.759 | 0,08072469872327787 | `STABLE` |
| `renewal60` | 75.002 | 33.243 | 41.759 | 1,4546002150068804 | `RETRAIN_RECOMMENDED` |

Kedua CLI menjawab `serving_ready=false`; monitoring membaca bundle dengan manifest dan checksum yang diverifikasi. `RETRAIN_RECOMMENDED` adalah nama status **alert advisory** dari PSI, bukan instruksi retraining otomatis atau bukti kualitas prediksi memburuk. Tidak ada outcome-performance, band mix, eligibility, atau pemeriksaan PIT di sini. Skor berasal dari cohort sintetis yang pernah dipakai; ini bukan evaluasi prospektif atau konfirmasi independen.

Percobaan awal dengan snapshot tiga-cutoff (100.008 baris per target) **ditolak** oleh monitoring (`Prediction cutoff is outside baseline/current periods`) karena alat mengharuskan tepat dua periode. Tidak ada baris yang dibuang dari artefak tersebut. Snapshot dua-cutoff menghasilkan bundle baru 75.002 baris per target untuk pengukuran di atas.
