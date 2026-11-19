# Evaluasi churn tiga fold dan temuan kalibrasi — development

Modul `services/data/models/churn_calibration.py`, model `moses-calibrated-churn-dev-1.0`, label `christ-churn90-three-events-dev-1.2`, fitur `event-time-dev-1.0`. Semua flag `training_ready/experiment_ready/final_model/serving_ready` tetap false.

## Desain yang menghilangkan satu kelemahan sebelumnya

Eksperimen pertama hanya punya dua cutoff, sehingga threshold 0,5 dipakai tanpa dasar dan tidak ada data untuk kalibrasi. Sekarang ada tiga cutoff kronologis: **train 1 Des 2025 (14.855 baris) → kalibrasi 1 Mar 2026 (24.066 baris) → test 1 Jun 2026 (33.779 baris)**, 0 baris purged. Logistic dilatih hanya pada train. Isotonic regression dan pemilihan threshold **hanya memakai fold kalibrasi**; fold test di-skor sekali dan tidak pernah dipakai untuk fitting atau pencarian threshold. Aturan threshold (maksimalkan F1 pada fold kalibrasi, tie ke threshold tertinggi) ditetapkan di kode sebelum test di-skor dan ikut dicatat di report.

Reproduksi:

```powershell
.venv\Scripts\python.exe -m services.data.models.cli --inbound inbound/2026-09-06 --resolution artifacts/identity/v11 --cutoff-at 2025-12-01T00:00:00+07:00 --cutoff-at 2026-03-01T00:00:00+07:00 --cutoff-at 2026-06-01T00:00:00+07:00 --christ-churn-events --output-dir artifacts/models/christ_v12_3cut_20261119
.venv\Scripts\python.exe -m services.data.models.churn_calibration --source artifacts/models/christ_v12_3cut_20261119 --output-dir artifacts/models/churn_calibration_20261119
```

## Hasil pada fold test

| Skor | ROC-AUC | Brier | ECE deskriptif |
|---|---:|---:|---:|
| Tanpa kalibrasi | 0,89649 | 0,09535 | 0,02744 |
| Isotonic terkalibrasi | 0,89447 | 0,09905 | 0,04512 |

| Skor dan threshold | Precision | Recall | F1 | TP / FP / FN / TN |
|---|---:|---:|---:|---|
| Tanpa kalibrasi, 0,5 | 0,59444 | 0,51277 | 0,55059 | 2.971 / 2.027 / 2.823 / 25.958 |
| Tanpa kalibrasi, threshold kalibrasi 0,23321 | 0,46541 | 0,88350 | 0,60966 | 5.119 / 5.880 / 675 / 22.105 |
| Terkalibrasi, threshold kalibrasi 0,25343 | 0,46541 | 0,88350 | 0,60966 | 5.119 / 5.880 / 675 / 22.105 |
| Terkalibrasi, 0,5 | null | 0,00000 | 0,00000 | 0 / 0 / 5.794 / 27.985 |

Lift top-10% 3,559 (tanpa kalibrasi) dan 3,355 (terkalibrasi); capture rate top-20% 0,672 dan 0,671.

## Temuan jujur: kalibrasi ini tidak membantu

1. **Kalibrasi memperburuk ECE pada test** (0,0274 → 0,0451) dan Brier (0,0953 → 0,0991). Isotonic yang di-fit pada cohort Maret tidak tergeneralisasi ke cohort Juni. Jadi **tidak ada bukti bahwa model ini terkalibrasi**, dan klaim kalibrasi tidak boleh dibuat.
2. **Setelah kalibrasi, threshold 0,5 menjadi tidak berguna**: tidak satu pun baris test mencapai 0,5, sehingga TP=0 dan precision undefined. Ini menunjukkan bahaya memakai 0,5 sebagai angka default pada skor terkalibrasi. Threshold harus berasal dari aturan eksplisit, bukan kebiasaan.
3. **Threshold dari fold kalibrasi memperbaiki recall secara nyata**: 0,513 → 0,884 dengan F1 naik 0,551 → 0,610, tetapi precision turun 0,594 → 0,465 (FP naik dari 2.027 ke 5.880). Ini trade-off bisnis, bukan keputusan teknis Moses. Christ yang menentukan apakah menjangkau lebih banyak pelanggan berisiko sebanding dengan lebih banyak false positive.
4. Ranking tetap konsisten (AUC turun tipis 0,8965 → 0,8945; isotonic monoton), sehingga nilai utama model ini adalah **pengurutan risiko**, bukan probabilitas absolut.

## Batas

Data sintetis, identitas retrospektif, tanpa jaminan point-in-time; tidak ada klaim kausal atau efek kampanye. Satu fold kalibrasi tunggal pada satu cutoff bukan validasi kalibrasi produksi. Angka precision/recall di atas adalah trade-off pada cohort sintetis, bukan proyeksi hasil kampanye. Artefak lokal (ignored) berada di `artifacts/models/churn_calibration_20261119/`: `calibration_evaluation.json`, `test_predictions.json`, `calibration_artifact.json` (JSON, bukan pickle, bukan model serving), dan `calibration_manifest.json` dengan checksum. Jangan mengirim file ini ke decision engine.
