# Moses — ledger penutupan pekerjaan mandiri, 2026-11-20

Dokumen ini membedakan implementasi development dari acceptance requirement. Tidak ada persentase completion atau approval model yang diasumsikan.

## Ter-merge

| Paket | Bukti kode/PR | Batas closure |
| --- | --- | --- |
| CLV actual_revenue | #47 aggregate, #48 projection | Formula wrapper saja; retensi empiris 365 hari, rounding/tier dan PIT tetap terbuka |
| Inventaris model development | #49 | Read-only; bukan registry persisten/promosi |
| Kontribusi propensity lokal | #50 | Dekomposisi log-odds exact; bukan taxonomy alasan bisnis |
| Monitoring distribusi skor | #51 | PSI, volume, alert JSON advisory; band mix/segment-outcome dan alert delivery belum ada |
| Definisi fitur K-03 | #52 | Skeleton in-memory; DRAFT/ACTIVE/DEPRECATED, immutability, penolakan restricted fields dari daftar eksplisit caller; belum integrasi gov.restricted_attribute/persistence |
| Disclaimer sintetis TRD 9.7 | #52 | Tujuh generator evaluasi utama; tidak memperbarui artefak historis, tidak mengklaim seluruh jenis laporan sudah tercakup |

## Implementasi mandiri terbaru — cek status PR sebelum menganggap masuk main

- PR #53: metadata inventaris terverifikasi (28 focused tests, review independen bersih), importance renewal-membership (8.465 holdout rows, review bersih), metadata algoritma/hyperparameter aktual pada empat generator eksperimen (56 tests bersama suite existing, review bersih). Artefak lama tetap tidak lengkap, bukan ditambal di tempat.
- Churn calibrated tiga-fold importance: implementasi/run lokal 33.779 holdout rows, baseline AUC 0,8944692343 dan Brier 0,0990527914 cocok dengan evaluation serta saved test predictions; review independen bersih (5 focused tests passed). Output `artifacts/models/calibrated_churn_importance_20261120_subagent` tidak menimpa artefak lama.
- Handoff terbaru sudah ditambah status terkini; C1/C3/C5 di permintaan lintas tim ditandai historis dengan pointer ke rekonsiliasi v1.4.
- Gate gabungan lokal terbaru: 1429 passed, 19 skipped, 3 xfailed; Ruff/Black/Mypy bersih. Ini bukan acceptance PostgreSQL atau bukti approval model.

## Batas finish mandiri

Enam paket mandiri yang direncanakan sudah memiliki implementasi development atau bukti eksplisit: inventaris metadata, importance coverage, monitoring skor, skeleton registry fitur, disclaimer evaluasi, serta dokumen status. Penyelesaian PR/review tidak sama dengan seluruh jobdesc FRD/TRD selesai. Registry fitur masih in-memory dan daftar restricted berasal dari caller; model registry masih inventaris tanpa workflow promosi; monitoring belum mencakup band mix/segment outcomes/alert delivery. Fresh production-grade training, acceptance lintas tim, dan kebijakan bisnis tetap membutuhkan pekerjaan di bawah. Tidak ada klaim 100%.

## Tidak dapat ditutup Moses seorang diri

| Dependency | Owner | Acceptance yang diperlukan |
| --- | --- | --- |
| Lifecycle, cutoff WIB, NO_ACTION, retensi 365 hari, CLV rounding/tier, alasan, RFM | Christ | Jawaban tertulis P1–P8 dan versioned contract; mentor approval bila diwajibkan |
| Churn-definition 180 hari vs prediction horizon 90 hari | Mentor via Christ | Konfirmasi kedua konsep, bukan menyamakan angka atau menganggap late-data-only |
| PIT known_at, koreksi/refund, identity-as-of | James | Sumber ber-versi dan coverage teruji, lalu Moses menguji consumer |
| Prediction ID/storage/expiry, NBA adapter, segment membership versions | James + Christ | Kontrak integrasi dan acceptance lintas tim; default fail-closed |
| Booking propensity | James + Christ | Source event dan outcome definition yang dapat ditelusuri |
| Registry promosi model | James + validator independen | Persistence, author != validator, satu ACTIVE per tipe, bukti promosi; tidak boleh dibuat oleh penulis sendiri |

Semua artifact baru tetap dev-only. Test PostgreSQL yang skipped bukan acceptance. HTTP 500 intermittent pada POST /monitoring/drift pernah teramati di CI #50 dan belum terbukti diperbaiki; rerun hijau bukan root-cause fix.
