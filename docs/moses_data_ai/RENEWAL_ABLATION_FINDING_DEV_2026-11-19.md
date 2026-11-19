# Ablasi fitur renewal60 — eksploratif, development only

Modul `services/data/models/renewal_ablation.py`, model `moses-renewal-ablation-exploratory-dev-1.0`. Lanjutan dari eksperimen membership eksploratif sebelumnya. **Masih eksploratif dan post-holdout-inspection**, karena cohort Juni sudah diperiksa pada probe sebelumnya — bukan konfirmasi independen.

## Reproduksi

```powershell
.venv\Scripts\python.exe -m services.data.models.renewal_ablation --labels-dir artifacts/models/propensity_labels_20261119 --membership-dir artifacts/features/membership_20260301_20260601_dev --output-dir artifacts/models/renewal_ablation_reviewed_20261119
```

Train Maret 8.087 baris, test Juni 8.465 baris (4.596 positif / 3.869 negatif).

## Temuan utama: sinyal datang dari satu sumber, bukan gabungan enam fitur

| Varian | ROC-AUC | Δ vs full |
|---|---:|---:|
| Full (enam fitur) | 0,649239 | 0 |
| Drop `days_to_expiry` | 0,649239 | 0,000000 |
| Drop `tier_upgraded_last_event` | 0,649029 | −0,000210 |
| Hanya `days_to_expiry` | **0,651154** | +0,001915 |
| Hanya `days_since_last_membership_event` | **0,651154** | +0,001915 |
| Hanya `current_tier_ordinal` | 0,492530 | −0,156709 |
| Hanya `membership_tenure_days` | 0,420748 | −0,228491 |
| Hanya `renewal_count_365d` | 0,500477 | −0,148762 |
| Hanya `tier_upgraded_last_event` | 0,503683 | −0,145556 |
| Aturan tetap `days_to_expiry>=0` (tanpa fitting) | 0,659731 | +0,010492 |

**Menghapus `days_to_expiry` dari model penuh sama sekali tidak mengubah AUC**, dan model satu-fitur menggunakannya sendiri justru menyamai model penuh. `days_since_last_membership_event` memberi angka identik — kedua fitur ini saling redundan secara matematis pada data ini (konsisten dengan keduanya diturunkan dari peristiwa membership terakhir yang sama). Empat fitur lain (tier, tenure, riwayat renewal, upgrade) **sendirian berada di bawah atau mendekati acak** (AUC 0,42–0,50).

**Kesimpulan jujur:** peningkatan AUC renewal dari eksperimen membership sebelumnya (0,4657 POS-only → 0,649 membership) **hampir seluruhnya berasal dari satu sinyal `days_to_expiry`/`days_since_last_membership_event`**, bukan dari gabungan enam fitur membership yang kaya seperti yang tersirat sebelumnya.

## Aturan sederhana mengungguli model fitted — tapi probabilitasnya buruk

Aturan post-hoc tanpa fitting `days_to_expiry>=0 → 1` mencapai AUC 0,6597, lebih tinggi dari varian logistic pada holdout ini. **Bentuk aturan diinformasikan oleh probe holdout sebelumnya, bukan pre-registered**; keunggulan ini bukan perbandingan konfirmatori yang bersih. Tetapi Brier-nya jauh lebih buruk (0,3110 vs 0,2284 model full) karena aturan ini memberi probabilitas 1 ke semua pelanggan non-negatif padahal rate aktualnya ~64%, bukan 100%. Ranking lebih baik, kalibrasi probabilitas jauh lebih buruk.

## Struktur cohort yang menjelaskan semuanya

| Fold | Rentang `days_to_expiry` | Pelanggan | Rate renewal |
|---|---|---:|---:|
| Maret | < 0 | 749 | 0% |
| Maret | 0–60 | 7.338 | 64,08% |
| Juni | < 0 | 1.236 | 0% |
| Juni | 0–60 | 7.229 | 63,58% |

Tidak ada pelanggan dengan `days_to_expiry>60` pada kedua fold — ini **artefak definisi eligibility window renewal60**, bukan temuan model. Di dalam rentang eligible (0–60 hari), rate renewal hampir rata ~64%, sama seperti probe sebelumnya. Jadi AUC yang terlihat sebagian besar berasal dari memisahkan "sudah lewat expiry" (0% pasti) dari "masih eligible" (~64%), bukan dari gradasi jarak hari yang halus.

## Implikasi untuk keputusan selanjutnya

1. **Jangan mempromosikan model renewal enam-fitur** sebagai lebih baik dari model satu-fitur; datanya tidak mendukung klaim itu.
2. **`current_tier_ordinal`, `membership_tenure_days`, `renewal_count_365d`, `tier_upgraded_last_event` belum terbukti berguna** untuk renewal60 pada data sintetis ini sendirian. Ini bisa berarti fiturnya memang tidak informatif di sini, atau perlu kombinasi dengan interaksi yang belum diuji — bukan kegagalan implementasi.
3. **AUC tinggi di sini sebagian adalah artefak struktur eligibility**, bukan pembelajaran perilaku pelanggan. Klaim apa pun atas model renewal harus menyebut ini.
4. Validasi independen (cutoff baru yang belum diperiksa) tetap dibutuhkan sebelum klaim generalisasi apa pun.

## Batas

Enam varian drop-one dan single-only tidak aditif karena fitur berkorelasi. Tidak ada klaim kausal. Data sintetis, retrospektif, tanpa jaminan PIT. Artefak lokal ignored: `artifacts/models/renewal_ablation_reviewed_20261119/evaluation.json`, `experiment_manifest.json`.
