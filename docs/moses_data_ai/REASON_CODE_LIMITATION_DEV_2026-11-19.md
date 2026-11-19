# Reason codes churn development — hasil nyata dan satu batas penting

Modul: `services/data/models/churn_reasons.py`, mapping `moses-churn-reason-map-proposed-dev-1.0`, metode `logistic_exact_log_odds_contribution`. Setiap penjelasan diverifikasi faithful: `intercept + Σ kontribusi` harus sama dengan `log_odds` prediksi (toleransi 1e-9), kalau tidak ditolak. Fitur yang di-impute tidak pernah ditampilkan sebagai fakta observasi; ia masuk `excluded_imputed`. `approved_taxonomy=false`, `display_text=null`, `serving_ready=false`.

## Run nyata

```powershell
.venv\Scripts\python.exe -m services.data.models.churn_reasons --predictions-dir artifacts/predictions/churn_offline_dev_20260906 --output-dir artifacts/predictions/churn_reasons_dev_20260906
```

Dari 50.640 prediksi: **50.141 `OK`** (≥3 fitur melewati ambang kontribusi 0,05 log-odds) dan **499 `INSUFFICIENT_EXPLANATION`**. Tidak ada alasan yang diduplikasi atau dikarang untuk memenuhi minimum tiga.

Distribusi kode pada tiga alasan teratas: `PURCHASE_FREQUENCY_365D` 46.970, `PURCHASE_FREQUENCY_60D` 44.614, `PURCHASE_FREQUENCY_90D` 43.790, `RETAINED_REVENUE_90D` 7.483, `TENURE` 4.684, `PURCHASE_RECENCY` 3.857.

## Batas yang tidak boleh diabaikan

Angka di atas memperlihatkan bahwa pada sebagian besar pelanggan, tiga alasan teratas adalah **tiga jendela waktu dari konsep yang sama**: frekuensi pembelian 365/90/60 hari. Secara model itu tiga fitur berbeda dan kontribusinya memang terpisah, tetapi secara bisnis itu kemungkinan besar **satu alasan**, bukan tiga alasan independen.

Karena itu hasil ini **belum memenuhi** `MIN_REASON_CODES = 3` dalam pengertian Christ (tiga alasan bisnis yang berbeda). Pengertian "distinct" pada `Requirement_Capstone` dan `target_definitions.md` adalah keputusan bisnis, bukan keputusan teknis Moses. Jangan mengutip 50.141 `OK` sebagai bukti kepatuhan tiga reason codes.

**Keputusan yang diminta ke Christ:** (1) apakah `PURCHASE_FREQUENCY_365D/90D/60D` dihitung sebagai satu alasan atau tiga; (2) apakah ambang 0,05 log-odds dipertahankan sebagai konvensi development; (3) taxonomy dan template tampilan resmi, termasuk arah `INCREASES_RISK`/`DECREASES_RISK`. Jika ketiga frekuensi digabung menjadi satu kode, **jumlah penjelasan yang lolos minimal tiga akan turun** karena fitur penyumbang yang tersedia hanya tujuh dan sebagian berkorelasi. Itu bukan regresi kode; itu konsekuensi dari himpunan fitur yang sekarang.

Tambahan batas: tidak ada `feature_known_at`/`effective_at` di sini, sehingga syarat provenance pada [desain reason code](REASON_CODE_EVIDENCE_DESIGN_2026-11-17.md) belum terpenuhi — itu menunggu feed James. Kode saat ini hanya menyebut yang benar-benar diukur fitur: recency pembelian, frekuensi pembelian, retained revenue, tenure. Tidak ada kode kunjungan, keluhan, atau kedaluwarsa membership, karena fitur pendukungnya tidak ada.
