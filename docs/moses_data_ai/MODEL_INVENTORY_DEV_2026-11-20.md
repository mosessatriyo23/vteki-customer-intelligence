# Inventaris model development (bukan registry/promosi)

`services/data/models/model_inventory.py` membaca direktori eksperimen yang sudah ada, memverifikasi checksum keluaran terhadap manifest masing-masing, lalu melaporkan versi, hasil evaluasi yang tersedia, keterbatasan, dan field tata kelola yang belum ada. Ini **bukan** tabel `model_version` TRD §9.6, bukan validator, dan tidak menyediakan transisi TRAINED→ACTIVE. Semua entri berstatus `UNREGISTERED_DEV_ONLY` dan `promotable=false`; `registry_authoritative=false`, `serving_ready=false`.

Contoh run (memerlukan artefak lokal yang **tidak di-track Git**; selalu gunakan output baru):

```powershell
.venv\Scripts\python.exe -m services.data.models.model_inventory `
  --model-dir artifacts/models/churn_fitted_dev_20261119_verified `
  --model-dir artifacts/models/propensity_retail_20261119 `
  --model-dir artifacts/models/propensity_renewal_20261119 `
  --output artifacts/models/inventory_dev_20261120_v2/inventory.json
```

Run lokal ini mencatat **3 model, seluruh checksum keluaran terverifikasi**. Ketiganya masih kekurangan `trained_by`, `validated_by`, `calibration_ref`, `explainability_ref`, dan `leakage_check_result` dalam manifest eksperimennya. `evaluation` yang disertakan berasal dari `evaluation.json` yang checksum-nya cocok; `artifact_sha256` berasal dari manifest dan harus dibaca bersama `checksums_verified`. Tidak ada hasil run atau approval yang dikarang; metrik berasal dari artefak sintetis, bukan bukti performa pelanggan nyata.

**Lanjutan lintas tim:** Moses mengumpulkan metadata dan bukti yang sah per versi model tanpa mengubah artefak lama. James mengintegrasikan registri dan penyimpanan platform, sedangkan validator **berbeda dari penulis** memeriksa bukti, memutuskan promosi/penangguhan, serta menegakkan satu ACTIVE per tipe prediksi. Sampai workflow dan kontrak itu diuji bersama, hasil inventaris tidak boleh diubah menjadi skor serving atau persetujuan model.
