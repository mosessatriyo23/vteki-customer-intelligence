# Renewal60 dengan fitur membership — eksploratif, development only

Modul: `membership_features.py` (versi `moses-membership-features-proposed-dev-1.0`) dan `renewal_membership_experiment.py` (`moses-renewal-membership-exploratory-dev-1.0`). Semua flag readiness false. Eksploratif setelah holdout Juni sudah dilihat; **bukan konfirmasi independen**.

## Reproduksi

```powershell
.venv\Scripts\python.exe -m services.data.models.membership_features --inbound inbound/2026-09-06 --resolution artifacts/identity/v11 --cutoff-at 2026-03-01T00:00:00+07:00 --cutoff-at 2026-06-01T00:00:00+07:00 --output-dir artifacts/features/membership_20260301_20260601_dev
.venv\Scripts\python.exe -m services.data.models.renewal_membership_experiment --labels-dir artifacts/models/propensity_labels_20261119 --membership-dir artifacts/features/membership_20260301_20260601_dev --output-dir artifacts/models/renewal_membership_exploratory_20261119
```

## Hasil (train Maret 8.087 / test Juni 8.465, 0 purged, threshold 0,5)

| Model | ROC-AUC | AP | Brier | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| base rate | 0,5000 | 0,5429 | 0,2496 | 0,5429 | 1,0000 | 0,7038 |
| logistic membership-only | 0,6492 | 0,6162 | 0,2284 | 0,6372 | 0,8640 | 0,7335 |

Pembanding POS-only sebelumnya: AUC 0,4657 (cohort sama, laporan terpisah).

## Cara membaca

- Fitur membership menaikkan AUC dari di bawah acak menjadi 0,649 pada holdout ini.
- Kemungkinan besar sinyal ini berasal dari struktur cohort, misalnya `days_to_expiry` di dekat batas window eligibility. Dari probe sebelumnya, rate renewal di dalam window hampir datar (~0,64). Ini belum diuji dengan ablasi per fitur.
- Karena generator memakai probabilitas renewal acak, ini tidak boleh dibaca sebagai perilaku pelanggan nyata.
- Tidak ada klaim kalibrasi, kausal, atau kesiapan serving. Untuk klaim generalisasi diperlukan cutoff baru yang belum pernah dilihat.
