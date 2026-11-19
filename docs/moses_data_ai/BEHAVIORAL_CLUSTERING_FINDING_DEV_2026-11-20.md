# Behavioral clustering — proposal development, bukan persona bisnis

Modul `services/data/segmentation/behavioral.py` melengkapi perhitungan awal FRD §9.1/TRD §9.2: StandardScaler + K-means (`random_state=42`, `n_init=10`), pencarian k=3..8, silhouette pada sampel deterministik ≤1.500, profil ukuran cluster + lima deviasi fitur terstandar terbesar.

## Hasil Juni (run ulang main agent)

| Parameter | Hasil |
|---|---:|
| Cutoff | 1 Juni 2026 |
| Baris (unik customer) | 41.759 |
| k dipilih | 3 |
| Silhouette | 0,403484 |
| Ukuran cluster 0 / 1 / 2 | 7.912 / 11.406 / 22.441 |

Sumber adalah fitur 3-cutoff, tetapi **hanya Juni** yang di-fit. Tidak ada label/outcome/ground truth yang dibaca. Standardisasi di-fit pada populasi cutoff yang sama. Fit cluster di bawah 1% populasi (minimum 2) ditolak; jika tidak ada solusi nondegenerat, proses gagal, bukan memaksa persona.

## Batas penting

Fitur hanya tujuh kolom purchase/recency/tenure ditambah indikator recency missing. Tidak tersedia category/channel mix, visit regularity, basket size, promotion response, app activity, complaints/service intensity atau exposure. Jadi ini **proposal mekanis spend/frequency**, bukan bukti persona behavioral kaya atau pemenuhan lengkap seluruh keluarga fitur FRD.

Semua membership, profil dan manifest membawa `name=null`, `description=null`, `approved=false`, `targeting_allowed=false`, `serving_ready=false`. Tidak ada setter untuk membuka targeting. Identitas diterapkan retrospektif; bukan historical PIT-safe. Cluster ID numerik hanya lokal pada run ini, bukan identitas segmen stabil lintas cutoff. Penamaan, deskripsi, versi consumer dan penerimaan bisnis tetap perlu Christ/James.

## Reproduksi

```powershell
.venv\Scripts\python.exe -m services.data.segmentation.behavioral --feature-dir artifacts/features/propensity_3cut_20261119 --output-dir artifacts/segments/behavioral_june_dev_20261120_verified --cutoff-at 2026-06-01T00:00:00+07:00
```

Gunakan output baru saat mengulang. Run main agent pada kode terakhir selesai, checksum input tidak berubah. Artefak awal `behavioral_june_dev_20261120` tidak ditimpa.

## Verifikasi sementara

Review independen memverifikasi checksum, gates, 41.759 customer unik dan aritmetika profil; menemukan satu defect wajib: surplus CSV fields lolos meskipun header benar. Dua regresi checksum-valid (kolom berlebih/kurang) gagal sebelum perbaikan; loader kini menolak keduanya sebelum compute. Behavioral tests kini **12 passed**; bersama segmentation/PIT **20 passed**; Ruff/Black bersih. Reviewer juga mengonfirmasi tie-break k kecil dan input-order invariance lewat probe, belum berupa regression tests repo.

Run `_verified` dilakukan sebelum perbaikan validasi jumlah field; outputnya tetap konsisten untuk input valid ini, tetapi bukan bukti eksekusi guard terakhir. Tidak ada bukti acceptance targeting, persistensi segment membership berinterval atau serving. Reproducibility bersifat dalam lingkungan numerik yang sama; versi NumPy/sklearn belum tercatat dalam manifest.
