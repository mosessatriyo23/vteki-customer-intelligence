# Penutupan slice ML mandiri — 22 November 2026

## Selesai dan bukti

| Slice | Bukti | Batas |
| --- | --- | --- |
| Kalimat atribusi propensity retail/renewal | PR #65, formatter memakai kontribusi inference sebenarnya | Bukan taxonomy bisnis atau sebab perilaku |
| Importance/subgroup propensity tiga-fold terkalibrasi | PR #65, parity dengan prediksi tersimpan, checksum dan fold diverifikasi | Cohort sintetis pernah diperiksa; bukan konfirmasi independen |
| Subgroup membership | PR #65, bucket expiry/tier ordinal/tenure/renewal count | Exploratory post-holdout, bukan pre-registered atau lifecycle/CLV tier |
| Reload membership-only JSON | PR #65, parity fit mini-cohort, vektor divalidasi ulang | Library offline, bukan worker/serving |
| Inference propensity terkalibrasi | PR #66, parity kedua target; run lokal 100.008 baris/target | Fitur saja, tidak menentukan eligibility |
| Monitoring bundle terkalibrasi | PR #67, run nyata 75.002 baris/target | PSI/volume advisory, tanpa outcome/band/action otomatis |
| Reload churn terkalibrasi | Slice terakhir, parity mini-cohort dan mutation/checksum guard | Library offline; kalibrasi eksperimen tidak tergeneralisasi, bukan pilihan model final |

Gate lokal slice terakhir: **1752 passed, 19 skipped, 3 xfailed**, satu warning dependensi; Ruff, Black, Mypy bersih. Skipped PostgreSQL bukan acceptance lulus. Review independen per slice sudah dilakukan; temuan wajib ditutup sebelum commit. Hasil monitoring dan cara mengulang ada di [bukti monitoring](CALIBRATED_PROPENSITY_MONITORING_DEV_2026-11-22.md). Artefak lokal tidak di-commit dan artefak lama tidak ditimpa.

## Masih bukan selesai keseluruhan jobdesk

- Worker scoring dan persistensi batch terjadwal belum ada. Jadwal, idempotensi/PIC dan identitas model-author/reviewer serta sumber `usage_approved` masih memerlukan kesepakatan lintas tim.
- Registry fitur persisten, promotion workflow, feed historical `known_at`/identity-as-of, booking source, alert delivery/suspend/fallback adalah integrasi platform atau kontrak lintas tim, bukan gap yang boleh diisi Moses sepihak.
- Band, lifecycle/RFM, retention factor, CLV tier, taxonomy/distinct reasons dan definisi renewal/upgrade masih perlu keputusan Christ/mentor. Tidak ada angka palsu, segmentasi final, atau penggantian model demi klaim selesai.
- Consent, kelayakan dan input non-score NBA memerlukan sumber sah. Skor lengkap secara teknis bukan izin penggunaan.
- Bug API `/monitoring/measurements` (validator cross-field vs OpenAPI) berulang pada CI. Rerun lulus tidak memperbaikinya; bukti tercatat di PR #62–#67. Tidak diselesaikan oleh slice ML.

Karena itu dokumen ini **tidak** menyatakan 100%, tidak menyatakan acceptance produksi, dan tidak menganggap review kode sebagai review independen model atau izin serving. Setelah keputusan tersedia, Moses tetap mengimplementasikan consumer/worker sesuai kontrak yang disetujui dan membuktikan integrasinya.
