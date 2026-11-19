# Moses — perkembangan development 19 November 2026

## Cakupan

Moses meminta pengerjaan bagian data/AI terlebih dahulu, termasuk jalur development sintetis tanpa menunggu proses persetujuan formal tambahan. Catatan ini tidak mengatasnamakan persetujuan Christ, James, atau dosen; tidak menutup Gate A/C/D dan tidak menyatakan production-ready.

## Perubahan yang sudah diimplementasikan

- `services/data/models/labels.py`: label Christ menjadi `christ-churn90-three-events-dev-1.2`. Eligibility menggunakan minimal satu POS `COMPLETED`/`PARTIAL_REFUND`, visit `COMPLETED`, atau membership `RENEWAL` dalam `(cutoff - 365 hari, cutoff]`. Outcome tetap `(cutoff, cutoff + 90 hari]`.
- Versi sebelumnya v1.1 mempunyai eligibility POS-only meskipun outcome memakai tiga jenis event. Artefak lama tidak diubah; jangan membandingkan metrik kedua versi sebagai peningkatan model pada cohort yang sama.
- Mode default tetap `future-outcomes-proposed-dev-1.0` dengan eligibility transaksi saja.
- `retention_diagnostics.py`: menerima v1.1 atau v1.2 secara terpisah; menolak pencampuran versi. Output menyebut scope cohort yang sesuai. Denominator nol menghasilkan null.
- CLI model development dengan `--christ-churn-events` menghasilkan `retention90.json` per lifecycle/cutoff/rule version. Checksum-nya dicatat di `model_manifest.json`; manifest tetap menjadi penanda penyelesaian terakhir. Mode default tidak menghasilkan file retensi.
- Retensi tetap statistik deskriptif 90 hari, bukan faktor CLV 12 bulan, prediksi terkalibrasi, atau bukti dampak bisnis. `clv_factor_ready=false`, `experiment_ready=false`, dan `final_model=false` tetap dipertahankan.

## Menjalankan jalur development

Gunakan direktori output baru setiap run (artefak existing ditolak):

```powershell
python -m services.data.models.cli --inbound inbound/2026-09-06 --resolution artifacts/identity/v11 --cutoff-at 2026-03-01T00:00:00+07:00 --cutoff-at 2026-06-01T00:00:00+07:00 --christ-churn-events --output-dir artifacts/models/christ_v12_20261119
```

Input tersebut harus tersedia di checkout lokal. Perintah menghasilkan labels, complete eligible training rows, metrik baseline deterministik, tabel retensi, dan manifest checksum. Ini **bukan fitting model ML**. Jangan menjadikan file hasil parsial sebagai hasil sah tanpa completion manifest.

## Verifikasi yang dieksekusi

- Bug direproduksi dengan test visit-only/renewal-only: FAIL sebelum perbaikan, PASS setelahnya.
- `python -m unittest tests.data.test_model_baseline tests.data.test_retention_diagnostics tests.data.test_model_evaluator`: **20 tests PASS** setelah melengkapi review.
- Regression mencakup batas -365 hari/cutoff, cancelled visit, outcome, masuknya customer event-only ke training rows dan denominator retensi, CLV90 nol tanpa POS, penolakan mixed-version, checksum output, dan publikasi mode default.
- Ruff/Black pada file perubahan: lulus.
- Percobaan suite `tests/data`: 100 tests ditemukan, 4 import error karena `sqlalchemy` belum tersedia pada Python lokal 3.10.11. Ini batas verifikasi lingkungan, bukan bukti bahwa suite penuh lulus. PostgreSQL acceptance belum dijalankan.
- Run data sintetis penuh selesai: **75.002 label**, **57.845 complete eligible training rows** (24.066 train / 33.779 test), **17.157 excluded ineligible**, 0 incomplete berdasarkan akhir periode generator. Terdapat 18 baris agregat retensi. Checksum seluruh input dan empat output diverifikasi cocok dengan completion manifest. Ini kematangan event-time sintetis, bukan bukti kelengkapan historis `known_at`.

## Hasil retensi sintetis yang sudah tersedia

Sumber lokal: `artifacts/models/christ_v12_20261119/retention90.json` (artefak ignored, tidak otomatis tersedia di checkout lain). SHA-256: `a724f646e28944232d71ef14fa42289c8affd384f8c25302be54333117072065`.

Setiap sel menunjukkan **retained / eligible-complete (persentase)**. Cohort per cutoff dilaporkan terpisah; customer dapat muncul di kedua cutoff sehingga bukan customer unik gabungan.

| Lifecycle | 1 Maret 2026 | 1 Juni 2026 |
|---|---:|---:|
| ACTIVE | 2.151 / 2.159 (99,63%) | 2.319 / 2.348 (98,76%) |
| AT_RISK | 1.223 / 2.072 (59,03%) | 1.245 / 2.430 (51,23%) |
| DORMANT | 88 / 436 (20,18%) | 202 / 1.160 (17,41%) |
| LOYAL | 6.125 / 6.129 (99,93%) | 9.132 / 9.148 (99,83%) |
| NEW | 307 / 383 (80,16%) | 340 / 429 (79,25%) |
| OCCASIONAL | 10.455 / 12.811 (81,61%) | 14.695 / 18.156 (80,94%) |
| REACTIVATED | 53 / 76 (69,74%) | 52 / 108 (48,15%) |
| NEVER_TRANSACTED | null (eligible 0; excluded 6.669) | null (eligible 0; excluded 5.397) |
| CHURNED | Tidak ada baris | null (eligible 0; excluded 46) |
| UNCLASSIFIED | Tidak ada baris | null (eligible 0; excluded 18) |

Exclusion tambahan: NEW 2.508 (Maret) / 2.515 (Juni), DORMANT 4 (Juni). Semua exclusion incomplete = 0. Perbedaan DORMANT di batas 365 hari dapat terjadi karena lifecycle memakai selisih tanggal, sementara label memakai timestamp interval terbuka di sisi kiri. Jangan menyamakan null atau tidak ada baris dengan retensi 0%.

Angka tinggi pada ACTIVE/LOYAL mencerminkan pola generator sintetis, bukan validasi model atau performa bisnis. Sampel REACTIVATED kecil dan berubah antarcutoff; jangan langsung menjadikannya parameter scoring. Tabel ini memenuhi pengiriman **diagnostik deskriptif development** kepada Christ, bukan finalisasi faktor CLV.

## Batas kontrak yang masih perlu dicatat

Definisi Christ v1.3 menyebut any-event cohort, tetapi juga menyebut pengecualian `NEVER_TRANSACTED` berdasarkan nol transaksi. Jalur development v1.2 mengikuti definisi cohort eksplisit tiga event; customer visit-only/renewal-only dapat eligible. Jangan menambahkan filter lifecycle tersembunyi. Untuk kontrak final, Christ perlu memperjelas apakah never-transacted berarti tanpa POS atau tanpa semua qualifying event.

James masih menyediakan bukti historical availability (`known_at`), correction/refund/status history, dan identity-as-of. CSV development menggunakan current mapping secara retrospektif dan final source status; elapsed outcome horizon tidak membuktikan kelengkapan observasi historis. Retensi deskriptif tidak menyelesaikan keterbatasan ini.

## Eksperimen churn fitted tambahan — development only

Eksperimen Moses terpisah di `services/data/models/churn_experiment.py` memakai `requirements-models.txt` (scikit-learn opsional, bukan dependency runtime). Perintah:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt -r requirements-models.txt
.venv\Scripts\python.exe -m services.data.models.churn_experiment --source artifacts/models/christ_v12_20261119 --output-dir artifacts/models/churn_fitted_dev_20261119_verified
```

Ia memakai train cutoff 1 Maret (24.066 rows), holdout cutoff 1 Juni (33.779 rows) dengan purged split yang sama; 0 rows purged untuk dua cutoff ini. Baseline recency>90, logistic regression dengan train-only imputer/scaler, dan decision tree dangkal dilaporkan pada **holdout yang sama**. Seed estimator 42, threshold confusion 0,5 ditetapkan sebelum melihat holdout; tidak ada fitting atau tuning pada test. Hasil lokal:

| Kandidat | ROC-AUC | Average precision | Brier | TP / FN / FP / TN |
|---|---:|---:|---:|---:|
| Recency baseline | 0,6591 | 0,3289 | 0,1509 | 2.143 / 3.651 / 1.447 / 26.538 |
| Logistic regression | 0,9034 | 0,5911 | 0,0926 | 1.987 / 3.807 / 1.521 / 26.464 |
| Shallow tree | 0,8998 | 0,5506 | 0,0873 | 975 / 4.819 / 211 / 27.774 |

Brier yang lebih kecil di atas adalah metrik error probabilitas pada data sintetis, **bukan bukti kalibrasi**. Kedua model fitted mengungguli baseline dalam ranking, tetapi threshold 0,5 tree menghasilkan recall lebih rendah; tidak ada kandidat dipilih untuk produksi. Artefak ignored berada di `artifacts/models/churn_fitted_dev_20261119_verified/`: `evaluation.json`, `holdout_predictions.json`, `model_parameters.json` (JSON inspeksi, bukan model serving), dan `experiment_manifest.json`. Checksum seluruh input/output terverifikasi cocok. Prediksi holdout memuat outcome untuk evaluasi; **jangan kirim file ini ke API/decision engine**. Tidak ada reason codes sah, calibration artifact, valid_until, atau historical known_at; tidak memenuhi kontrak I-04 di `PREDICTION_CONTRACT_I04_DRAFT_2026-11-18.md`.

Verifikasi final `.venv\Scripts\python.exe -m pytest -q`: **1002 passed, 19 skipped, 3 xfailed**; warning Starlette/httpx tercatat. Ruff file terkait lulus. Tiga test regresi pasca-review menjaga normalisasi recency dan UTC offset serta checksum keluaran. Test PostgreSQL yang skipped belum dibuktikan pada server lokal.

## Model churn yang bisa dimuat ulang dan dipakai prediksi offline

`services/data/models/churn_inference.py` memuat model logistic dari `experiment_manifest.json` tanpa pickle (hanya JSON), memverifikasi checksum ketiga output eksperimen sebelum mempercayai isinya, dan menolak bila versi model/fitur/label atau bentuk parameter tidak sesuai. `predict_rows` menolak baris yang membawa `churn90` (ground truth), cutoff di masa depan relatif `generated_at`, cutoff sebelum batas ketersediaan outcome training (`max(train_cutoffs) + 90 hari`), dan duplikasi customer/cutoff. Skor memakai sigmoid stabil dari kontribusi log-odds per fitur; penjelasan yang disimpan adalah dekomposisi matematis model (bukan reason codes bisnis yang disetujui).

Snapshot fitur uji (tanpa label) dibuat untuk cutoff baru:

```powershell
.venv\Scripts\python.exe -m services.data.features.cli --inbound inbound/2026-09-06 --resolution artifacts/identity/v11 --cutoff-at 2026-09-06T00:00:00+07:00 --output-dir artifacts/features/churn_inference_20260906_dev
```

Lalu scoring offline:

```powershell
.venv\Scripts\python.exe -m services.data.models.churn_inference --model-dir artifacts/models/churn_fitted_dev_20261119_verified --features-dir artifacts/features/churn_inference_20260906_dev --generated-at 2026-09-06T12:00:00+07:00 --output-dir artifacts/predictions/churn_offline_dev_20260906
```

Hasil: **50.640 prediksi**, checksum output cocok dengan `prediction_manifest.json`, probabilitas churn berkisar dari sangat kecil hingga 0,80 (median ≈ 0,042). `serving_ready/training_ready/experiment_ready = false` pada setiap baris. **Ini skor untuk seluruh snapshot, belum difilter menjadi cohort eligible atau audiens campaign** — jangan dikirim langsung ke decision engine.

Verifikasi: 10 test baru di `tests/data/test_churn_inference.py` (parity probabilitas vs `evaluate()`, penolakan model yang dirusak/bentuk salah, penolakan baris cutoff masa depan/sebelum boundary/duplikat, kelengkapan manifest CLI). Ruff/Black bersih. `pytest -q` seluruh repo: **1012 passed, 19 skipped, 3 xfailed** — tidak ada regresi.

## Revisi aturan bisnis oleh Christ

Lihat `docs/moses_data_ai/CHURN_MODEL_REVISION_POLICY_DEV.md`: perubahan definisi target (event churn, cohort, horizon) memerlukan `label_version` baru dan retrain; perubahan treatment/threshold campaign cukup versi kebijakan baru tanpa retrain otomatis. Model dan label lama tidak ditimpa.

## Bukti evaluasi dan monitoring offline tambahan

- `churn_diagnostics.py`: memverifikasi manifest eksperimen dan prediksi holdout, lalu menghitung CI bootstrap 200 replikasi **cluster pelanggan** (seed 42), reliability 10 bin, ECE deskriptif, precision/recall/F1/specificity pada threshold tetap 0,5. Run lokal `artifacts/models/churn_diagnostics_20261119/` berisi `diagnostics.json` dan manifest checksum. CI95 ROC-AUC: baseline 0,6525–0,6644, logistic 0,9002–0,9063, tree 0,8961–0,9028. Logistic precision 0,5664 dan recall 0,3429 di threshold 0,5. ECE logistic 0,0375 **bukan** kalibrasi approved; interval bootstrap tidak mengukur bias sumber atau ketidakpastian retraining. Jalankan: `.venv\Scripts\python.exe -m services.data.models.churn_diagnostics --source artifacts/models/churn_fitted_dev_20261119_verified --output-dir artifacts/models/churn_diagnostics_20261119` (gunakan output baru untuk pengulangan).
- `feature_drift.py`: membandingkan distribusi 7 fitur antara *purged train* Maret dan snapshot September, memakai fungsi PSI yang sudah ada di `services/data/monitoring/drift.py`; bin decile dibekukan dari train, missing tercatat. Run lokal `artifacts/models/feature_drift_20260906/` (JSON + manifest). PSI recency 1,590 dan tenure 0,618, sementara fitur lain 0,014–0,036. **Snapshot September mencakup seluruh 50.640 pelanggan, train hanya eligible cohort**: perbedaan populasi dan waktu membatasi interpretasi. Tidak ada alarm otomatis, retraining otomatis, atau performance drift yang bisa dihitung tanpa outcome September matang. Perintah: `.venv\Scripts\python.exe -m services.data.models.feature_drift --reference artifacts/models/christ_v12_20261119 --current artifacts/features/churn_inference_20260906_dev --output-dir artifacts/models/feature_drift_20260906`.
- Model card baru: [fitted churn dev 1.0](MODEL_CARD_FITTED_CHURN_DEV_1_0.md). Retensi 90d sudah disiapkan sebagai [handoff Christ](RETENTION90_CHRIST_HANDOFF_DEV_2026-11-19.md). Inventaris [tiga propensity](PROPENSITY_TARGET_INVENTORY_DEV.md) memblokir penyamaan pembelian layanan `service30` dengan booking. [Rekonsiliasi pendapatan CLV](CLV_REVENUE_RECONCILIATION_DEV.md) mencatat gross/net/retained mismatch tanpa mengubah kode ambigu.
- `clv_projection.py` membungkus formula/tier existing `business_clv.py`, menghitung komponen history/frequency, dan **menahan** projection/tier bila tidak ada retention factor berprovenance. Ini kalkulator terpisah, bukan fitted CLV. Definisi jumlah revenue input masih harus diputuskan Christ; nama `gross` pada input bukan bukti bahwa net-after-refund sudah tersedia.

Verifikasi pasca-review `.venv\Scripts\python.exe -m pytest -q`: **1080 passed, 19 skipped, 3 xfailed**, 1 warning Starlette/httpx; PostgreSQL skipped belum dibuktikan. Ruff/Black pada file baru lulus. Tiga test regresi tambahan menjaga penolakan dataset kosong oleh PSI helper. Docstring CLV dikoreksi supaya tidak mengklaim upstream memakai net/retained; nilai sekarang masih gross_amount-only.

## Handoff yang masih membutuhkan tim

1. Christ: putuskan cohort `NEVER_TRANSACTED` vs any-event, estimand/faktor retensi CLV 12 bulan, gross/net/retained revenue, definisi tiga propensity dan taxonomy reason codes. Dokumen handoff di atas mengandung contoh dan pertanyaan spesifik, bukan persetujuan buatan.
2. James: historical `known_at`, koreksi refund/status dan identity-as-of; sumber booking terpisah dari pembelian/visit, serta consumer I-04 yang tidak mencampur tiga target. Sampai ada feed tersebut, training/experiment/serving readiness tetap false.
3. Moses setelah revisi tim: versi label/fitur baru bila artinya berubah, regenerasi dan retrain, evaluasi ulang pada target baru. Tidak membandingkan AUC antar-cohort seolah target sama; tidak mengirim skor offline ke NBA.
