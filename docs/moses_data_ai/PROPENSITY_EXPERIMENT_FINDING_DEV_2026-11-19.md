# Eksperimen propensity retail dan renewal — hasil nyata, development only

Modul `services/data/models/propensity_experiment.py`, model `moses-fitted-propensity-dev-1.0`. Dua target dilatih **independen**, tidak berbagi model/skor/alasan. Booking tetap `UNSUPPORTED_SOURCE`. `training_ready/experiment_ready/final_model/serving_ready` tetap false pada kedua target.

## Reproduksi

```powershell
.venv\Scripts\python.exe -m services.data.models.propensity_labels --inbound inbound/2026-09-06 --resolution artifacts/identity/v11 --cutoff-at 2026-03-01T00:00:00+07:00 --cutoff-at 2026-06-01T00:00:00+07:00 --output-dir artifacts/models/propensity_labels_20261119
.venv\Scripts\python.exe -m services.data.features.cli --inbound inbound/2026-09-06 --resolution artifacts/identity/v11 --cutoff-at 2026-03-01T00:00:00+07:00 --cutoff-at 2026-06-01T00:00:00+07:00 --output-dir artifacts/features/propensity_20260301_20260601_dev
.venv\Scripts\python.exe -m services.data.models.propensity_experiment --labels-dir artifacts/models/propensity_labels_20261119 --features-dir artifacts/features/propensity_20260301_20260601_dev --target retail_purchase30 --output-dir artifacts/models/propensity_retail_20261119
.venv\Scripts\python.exe -m services.data.models.propensity_experiment --labels-dir artifacts/models/propensity_labels_20261119 --features-dir artifacts/features/propensity_20260301_20260601_dev --target renewal60 --output-dir artifacts/models/propensity_renewal_20261119
```

Label cutoff Maret/Juni: `propensity_labels.csv` 75.002 baris; retail eligible 46.325 (positif 21.232), renewal eligible 16.552 (positif 9.298). `retail_purchase30`: train 18.678 / test 27.647, 0 purged. `renewal60`: train 8.087 / test 8.465, 0 purged.

## Hasil pada fold test (threshold 0,5, belum dituning pada test)

| Target | Model | ROC-AUC | AP | Brier | Precision | Recall | F1 |
|---|---|---:|---:|---:|---:|---:|---:|
| retail_purchase30 | base rate | 0,5000 | 0,3626 | 0,2875 | 0,3626 | 1,0000 | 0,5322 |
| retail_purchase30 | fixed rule (`recency<=30`) | 0,6842 | 0,4797 | 0,3642 | 0,4987 | 0,8604 | 0,6314 |
| retail_purchase30 | logistic | 0,6798 | 0,4995 | 0,2677 | 0,4479 | 0,7855 | 0,5705 |
| renewal60 | base rate | 0,5000 | 0,5429 | 0,2496 | 0,5429 | 1,0000 | 0,7038 |
| renewal60 | fixed rule (`purchase_count_90d>=1`) | 0,4989 | 0,5424 | 0,4797 | 0,5422 | 0,7478 | 0,6286 |
| renewal60 | logistic | **0,4657** | 0,5161 | 0,2514 | 0,5429 | 1,0000 | 0,7038 |

## Temuan jujur yang wajib diketahui tim

1. **Retail:** logistic punya Brier lebih baik dari base rate dan fixed rule, tetapi ranking (AUC 0,680) sedikit **di bawah** aturan sederhana `recency<=30` (AUC 0,684). Model fitted belum terbukti lebih baik dari heuristik murah di sini; jangan mengklaim keunggulan tanpa menyebut angka ini. Fitur juga tumpang-tindih dengan label (outcome adalah event pembelian, sebagian fitur mengukur pembelian historis), sehingga performa sebagian mencerminkan kebiasaan beli, bukan niat baru.
2. **Renewal:** logistic AUC **0,4657**, di bawah referensi ranking acak 0,5 pada holdout ini, dan **semua keputusan pada threshold 0,5** menjadi positif (TP 4.596, FP 3.869, FN 0, TN 0). Ini tidak berarti koefisien atau skor probabilitas konstan; AUC non-0,5 menunjukkan ranking masih bervariasi. Model belum menunjukkan manfaat prediktif dibanding base rate dan tidak dipromosikan. Tujuh fitur yang tersedia tidak memuat atribut membership (`expires_at`, `membership_tier`, durasi keanggotaan). Menambahnya adalah hipotesis perbaikan yang harus diuji, bukan akar sebab atau jaminan kenaikan AUC yang sudah terbukti. Generator renewal juga memakai probabilitas acak, sehingga sinyal prediktif bisa memang terbatas. Data `membership_events.csv` tersedia, tetapi fitur `event-time-dev-1.0` belum memakainya.
3. **Probe data langsung (read-only, bukan model) pada cohort eligible renewal60 cutoff Juni:** tingkat renewal hampir rata di sekitar 0,64 pada setiap rentang 15 hari `days_to_expiry` di dalam window eligible (0,6426 / 0,6407 / 0,6421 / 0,6579), lalu turun ke 0 secara mekanis di luar window karena definisi eligibility, bukan karena sinyal prediktif. Angka ~0,64 ini konsisten dengan probabilitas 0,65 yang dipakai generator untuk memutuskan apakah membership chain berlanjut (`generator/business_events.py`). Artinya proses renewal pada data sintetis ini **mendekati acak per periode** dan hampir tidak bergantung pada jarak kalender ke expiry di dalam window eligible. Ini kemungkinan penjelasan utama AUC rendah, **bukan semata-mata ketiadaan fitur membership** — menambah `days_to_expiry` sebagai fitur adalah hipotesis yang perlu diuji, bukan perbaikan yang terjamin, karena sinyalnya sendiri tampak mendekati flat pada probe ini.
4. **Keputusan yang diperlukan sebelum melanjutkan renewal:** Christ/Moses perlu menyepakati apakah menambah fitur membership (tier, riwayat renewal, tenure) tetap dicoba meski probe di atas menunjukkan sinyal `days_to_expiry` sendiri lemah, atau apakah target renewal pada data sintetis generator saat ini memang mendekati batas tak terhindarkan karena randomness generator.
5. Target keduanya tetap **PROPOSED**, bukan approved oleh Christ. Renewal bukan upgrade; tidak ada label upgrade yang dibuat.

## Batas

Probe expiry memakai holdout Juni yang sudah dilihat. Eksperimen fitur membership sesudah probe ini bersifat eksploratif/adaptif, bukan konfirmasi pada holdout yang belum pernah disentuh. Diperlukan cutoff evaluasi baru yang mature untuk klaim generalisasi independen. Bucket negatif dan tepat +60 hari masih berada dalam cohort eligibility yang diusulkan, tetapi renewal generator terjadi sehari setelah expiry: perbedaan rate nol versus ~0,65 ini bisa memberikan sinyal antar-subkelompok. Rate yang hampir datar di bucket 0–59 hari tidak membuktikan bahwa seluruh fitur membership tidak berguna; probe agregat juga bukan uji kausal atas penyebab AUC rendah.

Data sintetis, retrospektif, tanpa jaminan PIT. Tidak ada kalibrasi atau klaim kausal. Fixed rule adalah konvensi development yang ditetapkan sebelum melihat holdout, bukan hasil tuning. Artefak lokal ignored: `artifacts/models/propensity_retail_20261119/`, `artifacts/models/propensity_renewal_20261119/` (masing-masing `evaluation.json`, `holdout_predictions.json`, `model_parameters.json` JSON-only, `experiment_manifest.json` dengan checksum).
