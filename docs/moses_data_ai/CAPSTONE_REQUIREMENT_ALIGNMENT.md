# Moses — Alignment to Requirement_Capstone

**Acuan bisnis:** `requirements/extracted_text/Requirement_Capstone.txt` (file lokal, tidak di-commit). Panduan Minggu 1–16 hanya konteks pelaksanaan, bukan sumber aturan bisnis yang menimpa dokumen ini. **Review:** 17 November 2026; kode yang ditinjau: `main` `6f1c3db`.

**Status:** `training_ready=false`, `experiment_ready=false`, `final_model=false`. Seluruh pekerjaan hanya menggunakan data development sintetis. Tidak ada campaign/pesan nyata atau seleksi pelanggan.

## Pemetaan requirement → bukti / gap

| Bagian acuan | Kebutuhan | Bukti saat ini | Gap / tindak lanjut |
|---|---|---|---|
| Bab 1 | Lifecycle rule-based: NEW ≤30 hari dan ≤2 transaksi; ACTIVE ≥3 transaksi/60 hari **atau** membership aktif dipakai; LOYAL ≥5 transaksi, ≥Rp500.000/90 hari, tenure ≥60 hari; AT_RISK 91–180 hari **dan** expiry ≤30 hari; DORMANT 181–365 hari **dan** expiry terlewat 1–60 hari; CHURNED >365 hari tanpa transaksi/kunjungan **dan** expiry >180 hari; REACTIVATED mantan DORMANT/CHURNED dengan ≥2 pembelian atau renewal | `services/data/segmentation/snapshot.py` menghitung recency dari transaksi, completed visit, renewal dan hanya memberi CHURNED jika expiry terbukti >180 hari; memiliki versi rule development | ACTIVE belum memeriksa penggunaan membership, AT_RISK/DORMANT belum memeriksa syarat membership masing-masing; NEW belum membatasi transaksi ≤2; REACTIVATED memakai jeda pembelian >180 hari dan satu pembelian baru, bukan status terdahulu + ≥2 atau renewal. Prioritas saat syarat overlap/gap tidak ditentukan Bab 1: pertahankan label usulan `OCCASIONAL`/`UNCLASSIFIED`, jangan mengklaim approved. Versikan perubahan bila Christ menyepakati prioritas/fallback. |
| Bab 2.1 | Model churn aktif, outcome transaksi **dan** kunjungan **dan** renewal; validity 30 hari; risk band `<.30`, `.30–<.60`, `.60–<.80`, `≥.80`; ≥3 reason codes | `services/data/models/labels.py` menyediakan label **development** tiga event, horizon 90 hari; `models/evaluator.py` mengevaluasi recency baseline | **Konflik di satu dokumen:** kalimat "180 hari ke depan" sementara prediction horizon ditulis 90 hari; jangan diam-diam mengganti label. Cohort aktif tidak didefinisikan terukur. Model terlatih, skor/valid_until dan reason codes ≥3 belum ada. Pertahankan label/baseline lama; minta keputusan tertulis Christ tentang outcome 180 vs 90 dan cohort aktif sebelum versi label/model berikutnya. |
| Bab 2.2 | CLV gross revenue historis 12m + proyeksi 12m dengan `Retention_Factor`; tier 200k/500k/1jt, riwayat <2 transaksi insufficient | `services/data/models/business_clv.py` punya formula/tier dengan retention wajib; `clv_features.py` membuat agregat development | Tidak ada nilai/metode retention di Requirement; sumber gross dan 12 kalender bulan vs 365 hari perlu disepakati. Jangan isi default atau pakai `1-churn90`; belum ada pipeline CLV bitemporal yang disetujui. |
| Bab 3 | 5 masukan keputusan independen, fail-closed pada consent, keluhan, cap, suitability, score expired | `services/decision/nba/` punya engine dan guardrails development | Audit kontrak terpisah dengan Christ; Moses tidak mengubah kebijakan atau mengirim pesan. Contoh cap `2/14 hari` ditulis sebagai **misal**, bukan parameter resmi dalam dokumen ini. |
| Bab 4 | 11 aksi termasuk NO_ACTION; syarat kanal/band insentif | `services/decision/` punya katalog aksi development | Contoh WIN_BACK menyebut dormant/lapsed 91–180 hari, bertentangan dengan Bab 1 (181–365). SERVICE_REMINDER mensyaratkan jadwal tanpa siklus replenishment eksplisit; jangan mengarang datanya. Pilihan prioritas dan kanal tetap keputusan Christ. |
| Bab 5 | `EV = Propensity × Expected_Revenue_Contribution × Action_Weight − Incentive_Cost_Estimate`; jika EV < min threshold pilih NO_ACTION | `services/decision/nba/ev_calculator.py` menerapkan kalkulasi development | Requirement tidak menetapkan nilai action weight, biaya insentif, maupun min EV. Jangan menganggap nilai dalam dokumen lain telah menggantikan baseline Capstone tanpa persetujuan. |

## Prioritas Moses sekarang

1. **Tanpa mengubah aturan bisnis:** uji non-leakage untuk fitur dan baseline yang sudah ada; bedakan cutoff kejadian dari cutoff ketersediaan. Jika input CSV tidak memiliki availability, nyatakan hanya event-time test, bukan bitemporal certification.
2. Tambah tes kontrak negatif terhadap komponen development agar tidak secara diam-diam melanggar Bab 1/2; jangan ubah label lama atau menyebut rule usulan sebagai approved.
3. Modul drift PSI/CSI di PR #38 boleh dipertahankan sebagai utilitas development opsional, tetapi bukan bukti kepatuhan Requirement_Capstone atau dasar retraining. CI harus hijau sebelum merge.
4. Selaraskan review James tentang event history/identity dan historical feed sebelum membuat snapshot feature baru; model baru menunggu definisi bisnis yang tidak ambigu serta Gates A–C dan review Gate D.

## Pertanyaan minimum untuk Christ / tim

- Bab 2.1: outcome churn **180 hari ke depan atau 90 hari**? Apa kriteria terukur untuk "pelanggan aktif" pada prediction_date? Perhatikan lifecycle CHURNED di Bab 1 (>365 hari + expiry >180) adalah status berbeda dari label ML.
- Bab 1: urutan prioritas dan fallback bila syarat membership tidak diketahui/tidak terpenuhi atau beberapa tahap sekaligus cocok; bagaimana membuktikan membership "digunakan" dan status lifecycle sebelumnya untuk REACTIVATED?
- Bab 2.2: sumber gross revenue; 12 bulan kalender atau rolling 365 hari; metode estimasi retention factor (tanpa nilai default).
- Bab 4/5: definisi window WIN_BACK, ketersediaan jadwal SERVICE_REMINDER, nilai parameter EV, serta daftar aksi/insentif final.
- Dokumen Requirement_Capstone yang tersedia masih memuat `[ISI_SENDIRI]` pada versi, tim, dan penyetuju. Mohon catat versi dan persetujuan final bila baseline ini dipakai untuk menutup Gate A. Klarifikasi user bahwa Christ telah menentukan proses bisnis mengizinkan audit dan pengembangan teknis, tetapi bukan bukti tanda tangan formal pada field tersebut.
