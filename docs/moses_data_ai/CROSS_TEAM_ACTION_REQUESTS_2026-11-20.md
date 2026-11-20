# Permintaan tindak lanjut antar tim (Moses → Christ, James)

Tanggal 20 November 2026. Status kerja, bukan persetujuan. Semua artefak Moses saat ini development-only (`serving_ready=false`). **Catatan historis v1.3:** butir C1/C3/C5 dan daftar pekerjaan mandiri di bawah ditulis sebelum audit Christ v1.4 dan sebelum PR #48–#53; jangan dipakai sebagai status/keputusan terkini. Rekonsiliasi v1.4 P1–P8 dan acceptance yang lebih tepat ada di [pesan untuk Christ](CHRIST_V14_RECONCILIATION_MESSAGE_2026-11-20.md); status implementasi kini di [ledger mandiri](MOSES_INDEPENDENT_WORK_LEDGER_2026-11-20.md). Requirement_Capstone menyebut definisi churn 180 hari ke depan dan horizon prediksi 90 hari ke depan sebagai dua konsep berbeda; C1 di bawah bukan resolusinya. `actual_revenue` aggregate/projection dev sudah ada, tetapi retensi 365 hari belum disepakati. Lifecycle v1.4 masih menunggu keputusan fallback/REACTIVATED/ACTIVE. Bagian tabel tetap disimpan sebagai catatan permintaan pada saat ditulis, bukan sebagai approval.

## Untuk Christ (keputusan bisnis)

| # | Keputusan yang dibutuhkan | Mengapa memblokir | Bukti/artefak Moses | Acceptance |
|---|---|---|---|---|
| C1 | **Sign-off mentor** atas window churn 90 hari, bukan memilih angkanya lagi. Christ v1.3 dan FRD §9.2 sama-sama menyebut 90 hari; rujukan 180 hari di FRD terkait reprocessing late data, bukan label churn. | Label/band/`outcome_window_end` sudah memakai 90 hari, tetapi kontraknya belum berstatus approved. | `christ-churn90-three-events-dev-1.2` | Versi target_definitions yang di-approve mentor; Moses hanya menerbitkan label baru bila angkanya berubah. |
| C2 | Apakah "≥3 alasan" berarti tiga **konsep bisnis berbeda**, plus kebijakan untuk baris berpenjelasan kurang. | FRD §9.2 meminta ≥3 alasan ranked, terbaca manusia, terkait fitur; FRD **tidak** menyebut "tiga konsep berbeda" — itu interpretasi yang perlu diputuskan. 50.141 dari 50.640 punya ≥3 kode matematis; 499 tidak. Dengan peta konsep usulan, 41.830 memenuhi tiga konsep berbeda. | `churn_contract_dev_20260906_reviewed_v2` (manifest), `REASON_CODE_LIMITATION_DEV_2026-11-19.md` | Daftar kode final, aturan pengelompokan konsep, teks tampilan, dan kebijakan untuk 499 baris tersebut. |
| C3 | Satu konvensi revenue field-level (gross vs net) dan estimand retention **12 bulan**. | Christ v1.3 sudah mengusulkan metode retensi lifecycle historis, tetapi konvensinya saling bertentangan: target_definitions menyebut gross namun mengizinkan net, sementara FRD §9.3/TRD §9.4 menetapkan net. Tabel Moses baru 90 hari deskriptif, belum faktor CLV 12 bulan. | `RETENTION90_CHRIST_HANDOFF_DEV_2026-11-19.md` | Konvensi field yang disetujui + definisi estimand 12 bulan; Moses mengimplementasikan dan menguji. |
| C4 | Semantik renewal: renewal = upgrade atau bukan; apakah renewal60 tetap target. | Label PROPOSED; model POS-only AUC lemah. | `PROPENSITY_EXPERIMENT_FINDING…`, `RENEWAL_ABLATION_FINDING…` | Definisi target final dan kebijakan eligibility. |
| C5 | Lifecycle: DORMANT recency-saja atau butuh expiry overdue; fallback recency >365 dengan expiry unknown/aktif; durasi/bukti prior state REACTIVATED; bukti ACTIVE via membership; NEVER_TRANSACTED pada visit-only/renewal-only; apakah renewal dihitung untuk frequency/revenue tanpa double-count POS; pemetaan LAPSED/RECLAIMED (FRD). | Kode saat ini mengeluarkan `UNCLASSIFIED` dan memakai aturan reactivation sendiri. | `SEGMENTATION_GAP_AUDIT_2026-11-19.md` | Tabel keputusan; Moses menerbitkan rule version baru + test. |
| C6 | RFM: populasi aktif, recency/frequency/monetary hanya purchase **positive-net** sesuai FRD §9.1, pemetaan kuintil ke nama segmen, dan field monetary otoritatif. | Implementasi sekarang memakai activity recency termasuk visit/renewal dan `actual_revenue`; mapping tidak boleh dikarang. | Audit segmentasi | Definisi populasi, field revenue dan named mapping tertulis untuk `segment_version_config`. |
| C7 | Trade-off threshold churn (precision vs recall). Kalibrasi isotonic tidak membantu secara teknis; threshold kalibrasi ~0,25 menaikkan recall 0,513→0,884 dengan precision 0,594→0,465. | Ini keputusan biaya bisnis. | `CALIBRATION_FINDING_DEV_2026-11-19.md` | Threshold/band operasional yang disetujui. |
| C8 | Approval operasional band risiko. Cutoff <0,30 / 0,30–<0,60 / 0,60–<0,80 / ≥0,80 dan validitas 30 hari sudah tertulis di Christ v1.3; yang terbuka adalah baseline review/approval mentor dan versi operasional. | Manifest masih menandai band tidak approved. | `band_cutoffs_version` di manifest | Approval/revisi tertulis dan nomor versi. |

## Untuk James (data/platform/integrasi)

| # | Kebutuhan | Mengapa memblokir | Acceptance |
|---|---|---|---|
| J1 | Sumber event booking **dan** definisi conversion/outcome (FRD D-07 prasyarat label propensity). | Target `service_booking30` berstatus `UNSUPPORTED_SOURCE`; visit/pembelian SERVICE bukan pengganti. Feed saja tidak cukup tanpa definisi outcome. | Tabel/feed event booking dengan timestamp event dan `known_at`, plus definisi conversion tertulis (Christ). |
| J2 | `known_at`/`recorded_at`, koreksi, refund, perubahan status, identity-as-of, serta histori exposure/response (D-08/I-11) bila fitur contact-fatigue diperlukan. | Fitur saat ini retrospective, bukan point-in-time historis. | Query as-of yang mengembalikan data seperti yang diketahui pada cutoff; test replay. |
| J3 | `prediction_id` dan penyimpanan prediksi. TRD I-04 mewajibkan `prediction_id`; skema FRD K-04 tidak mencantumkannya — rekonsiliasi kedua dokumen. | Producer Moses tidak membuat `prediction_id`; semua record `SCHEMA_PARTIAL`. | Tabel prediksi + idempotency key; keputusan siapa yang menerbitkan ID. |
| J4 | Timestamp/expiry otoritatif dari producer dan penolakan skor kedaluwarsa oleh consumer. Validitas 30 hari sudah tertulis di Christ v1.3. | Sumber memiliki `valid_until` null; `proposed_valid_until` bukan otorisasi. | Aturan platform + test penolakan skor kedaluwarsa. |
| J5 | Adapter ke NBA/decision engine. | Adapter dev menolak secara default dan sengaja tidak kompatibel dengan `AIScores`. | Kontrak dua sisi: fixture bersama + contract test di kedua modul. |
| J6 | Kesepakatan consumer segmen/audience berversi, persistensi `valid_from`/`valid_to` + transisi, ekspos `segmentation rule_version` di Customer360. | Snapshot immutable ada, tetapi bukan membership berinterval. | Skema + migrasi + test. |
| J7 | Integrasi platform registry/validator. **Pemisahan peran:** TRD menempatkan model registry di Group A (Moses: metadata, versi, inventaris); validator independen (bukan pembuat) mengotorisasi promosi; James: integrasi platform. | TRD §9.6. Promosi tidak dapat dilakukan Moses sendiri. | State machine registry dan bukti satu promosi uji oleh validator berbeda dari pembuat. |

## Yang masih bisa dikerjakan Moses tanpa menunggu

- Behavioral clustering (K-means k=3..8, silhouette, profil lima fitur) sebagai proposal; penamaan dan izin targeting tetap manusia.
- RFM kuintil populasi dengan konfigurasi tersimpan, **setelah C6**; pemisahan recency pembelian dari recency aktivitas dapat dimulai sekarang dengan rule version baru.
- Importance/evaluasi untuk model churn tiga-fold dan membership eksploratif (belum tercakup).
- Reason codes untuk propensity.
- Validasi independen renewal pada cutoff baru, bila data memungkinkan.

## Batas klaim

Tidak ada butir di atas yang menyatakan data/AI selesai 100%. Hasil renewal membership bersifat eksploratif pada holdout yang sudah diperiksa. Kalibrasi propensity memakai cohort test Juni yang sudah pernah diperiksa, jadi bukan konfirmasi independen.
