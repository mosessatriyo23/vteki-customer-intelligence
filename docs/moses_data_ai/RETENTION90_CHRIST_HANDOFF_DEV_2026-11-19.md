# Moses → Christ: ringkasan retensi sintetis 90 hari

**Status:** evidence deskriptif development untuk review, bukan approval atau `Retention_Factor` CLV 12 bulan. Versi label `christ-churn90-three-events-dev-1.2`; cohort minimal satu POS `COMPLETED`/`PARTIAL_REFUND`, visit `COMPLETED`, atau membership `RENEWAL` dalam `(cutoff-365d, cutoff]`. Outcome aktivitas salah satu tiga event dalam `(cutoff, cutoff+90d]`; `retained=1-churn90` untuk eligible dan complete saja. Lifecycle berasal dari segmentasi cutoff yang sama.

Sumber di checkout lokal: `artifacts/models/christ_v12_20261119/retention90.json`, SHA-256 `a724f646e28944232d71ef14fa42289c8affd384f8c25302be54333117072065`. `model_manifest.json` mencatat checksum input/output; artefak lokal ignored sehingga tabel berikut disalin secara portable. Reproduksi dan keterbatasan historis: [progress Moses](MOSES_DEVELOPMENT_PROGRESS_2026-11-19.md).

| Lifecycle | 1 Maret: retained / eligible-complete | 1 Juni: retained / eligible-complete |
|---|---:|---:|
| ACTIVE | 2.151 / 2.159 (99,63%) | 2.319 / 2.348 (98,76%) |
| AT_RISK | 1.223 / 2.072 (59,03%) | 1.245 / 2.430 (51,23%) |
| DORMANT | 88 / 436 (20,18%) | 202 / 1.160 (17,41%) |
| LOYAL | 6.125 / 6.129 (99,93%) | 9.132 / 9.148 (99,83%) |
| NEW | 307 / 383 (80,16%) | 340 / 429 (79,25%) |
| OCCASIONAL | 10.455 / 12.811 (81,61%) | 14.695 / 18.156 (80,94%) |
| REACTIVATED | 53 / 76 (69,74%) | 52 / 108 (48,15%) |
| NEVER_TRANSACTED | null: 0 eligible; 6.669 excluded | null: 0 eligible; 5.397 excluded |
| CHURNED | no rows | null: 0 eligible; 46 excluded |
| UNCLASSIFIED | no rows | null: 0 eligible; 18 excluded |

Tambahan excluded: NEW 2.508 (Maret), 2.515 (Juni); DORMANT 4 (Juni). Total label 75.002; eligible-complete 57.845 (24.066 Maret + 33.779 Juni); excluded ineligible 17.157, incomplete 0. **Null karena denominator nol ≠ retensi 0; no rows ≠ null.** Orang yang sama bisa muncul di dua cutoff; jangan jumlahkan sebagai pelanggan unik. REACTIVATED kecil dan tidak stabil. Angka ACTIVE/LOYAL tinggi mencerminkan pola generator sintetis, bukan evidence umum.

**Mohon keputusan Christ, tanpa menandai approved atas nama Christ:** (1) apakah `NEVER_TRANSACTED` berarti nol POS atau nol semua event qualifying sehingga pelanggan visit-only/renewal-only dapat eligible; (2) apa estimand, periode, pembobotan dan metode validasi `Retention_Factor` **12 bulan** CLV; (3) apakah 90-day descriptive table ini hanya referensi atau relevan sebagai salah satu input estimasi lebih lanjut. Moses **tidak** akan otomatis memakai angka ini, `1-churn_score` atau konstanta 0,7 untuk formula CLV. James masih perlu menyediakan historical known-at, status/refund correction dan identity-as-of sebelum klaim PIT/final.
