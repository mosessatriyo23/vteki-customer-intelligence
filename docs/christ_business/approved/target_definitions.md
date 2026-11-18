# Kontrak Definisi Bisnis: Target & Standar Sistem
**Dokumen:** `target_definitions.md`
**Status:** v1.3 — REVISI (menunggu persetujuan Dosen/Mentor + review tim). v1.0 berstatus APPROVED.
**Penyusun:** Christ (Decisioning, Activation & Measurement Engineer)
**Disetujui oleh:** [PENDING — tidak akan diisi sendiri; menunggu tanda tangan Dosen Pembimbing / Mentor V-TEKI]
**Versi:** v1.3
**Tanggal:** v1.0 = 2026-10-28; v1.1 = 2026-11-07; v1.2 = 2026-11-09; v1.3 = 2026-11-18
**Klasifikasi:** 100% Data Sintetis — Hanya untuk keperluan akademik Capstone Project UKDW

---

> **TUJUAN DOKUMEN**
> Dokumen ini menetapkan definisi formal target bisnis yang dibutuhkan sebagai kontrak antar modul.
> Modul Machine Learning (Moses) **wajib** mengacu pada standar ini saat membuat label training data,
> dan modul Decisioning (Christ) akan menerapkan aturan-aturan ini dalam NBA Engine & Policy Services.

---

## 1. Definisi Churn

> **Referensi:** `Requirement_Capstone.md` Bab 2 (FRD §6.6, TRD §9.3)

### 1.1 Definisi Churn yang Disepakati (label target ML)

Label churn adalah **hasil yang diamati SETELAH `prediction_date`** (bukan keadaan sebelumnya).

| Komponen | Nilai / Aturan |
|---|---|
| **Cohort (eligible)** | Pelanggan yang sudah terdaftar dan aktif pada `prediction_date`. **[DISETUJUI v1.3 — Item 1]**: minimal **1 churn negation event** (transaksi POS, kunjungan, atau perpanjangan) dalam 365 hari sebelum `prediction_date`. |
| **Jendela outcome** | **90 hari ke depan**: (`prediction_date`, `prediction_date` + 90 hari]. Batas kanan tertutup, `prediction_date` sendiri tidak termasuk. |
| **Churn = 1** | Tidak ada satu pun *churn negation event* di dalam jendela outcome. |
| **Churn = 0** | Ada minimal satu *churn negation event* di dalam jendela outcome. |
| **Label tidak lengkap** | Jika data belum mencakup `prediction_date` + 90 hari, label dikosongkan (null), **bukan** diisi 0. |

**Churn negation events** (salah satu cukup untuk membatalkan label churn):

1. Minimal **1 transaksi POS** berstatus `COMPLETED` atau `PARTIAL_REFUND`;
2. **Kunjungan fisik terverifikasi** (`customer_visits.csv`, status `COMPLETED`);
3. **Perpanjangan keanggotaan** (`membership_events.csv`, `event_type = RENEWAL`). Perpanjangan dihitung sebagai transaksi resmi sesuai `Requirement_Capstone.md` Bab 1.

> **Resolusi ketidakkonsistenan Requirement (Item 1 — v1.3):**
> `Requirement_Capstone.md` Bab 2.1 memuat dua angka berbeda: (a) "jendela outcome 180 hari ke depan" dan (b) "prediction horizon = 90 hari".
> **Resolusi:** Angka **90 hari** yang berlaku sebagai jendela label ML. Alasan: (1) implementasi Moses (`labels.py`, `horizon_days = 90`) sudah menggunakan 90 hari; (2) Panduan Kerja Christ Minggu 1 menetapkan 90 hari; (3) `business_events.md` bagian *Model labels* menggunakan 90 hari; (4) angka 180 hari di Requirement Bab 2.1 kemungkinan typo atau merujuk pada jendela monitoring lifecycle, bukan label ML. **Konfirmasi ke Dosen/Mentor WAJIB sebelum Gate A ditutup** — kolom approver tetap PENDING sampai dosen menandatangani.
>
> **Contoh positif (churn=1):** Pelanggan A belanja terakhir 2026-08-01; `prediction_date` = 2026-10-01; tidak ada transaksi/kunjungan hingga 2026-12-30 (> 90 hari). Label = 1.
> **Contoh negatif (churn=0):** Pelanggan B belanja terakhir 2026-08-01; `prediction_date` = 2026-10-01; memperpanjang membership pada 2026-10-15 (14 hari ke depan). Label = 0.
> **Contoh boundary:** Pelanggan C transaksi terakhir tepat pada `prediction_date` + 90 hari (hari ke-90 batas kanan tertutup). Label = 0 (satu negation event dalam jendela).

> **Sumber v1.1:** `Panduan_Kerja_Christ.md` Minggu 1 (window 90 hari pasca `prediction_date` + 3 negation events);
> `contracts/business_events.md` bagian *Model labels*; implementasi `services/data/models/labels.py` (`horizon_days = 90`).
>
> **Catatan cohort (v1.3):** Definisi cohort dikonfirmasi ≥ 1 qualifying event dalam 365 hari sebelum `prediction_date` (sinkron dengan implementasi `labels.py`). Pelanggan `NEVER_TRANSACTED` (tenure > 30 hari, 0 transaksi) **dikecualikan dari cohort ML** — tidak masuk training set.

### 1.1a Permintaan keputusan Moses — 2026-11-18 (belum disetujui)

Pembacaan FRD v0.9 §9.2 dan TRD v0.9 §9.3 dari ZIP terbaru mendukung **default 90 hari**, tetapi tidak menghapus konflik 180 hari di Requirement_Capstone Bab 2.1. Weekly guide dan kode yang sudah ada bukan dasar persetujuan bisnis baru. Bagian ini tidak mengubah definisi v1.2 maupun approver di header.

| Sumbu keputusan | Pilihan yang perlu dikonfirmasi | Status |
|---|---|---|
| Outcome horizon | 90 hari (default FRD/TRD) atau 180 hari (teks literal Capstone); jika berbeda dari horizon skor, jelaskan makna keduanya | PENDING |
| Negation events | Konfirmasi POS completed/partial refund, completed visits dan renewal **masing-masing**, termasuk refund/correction | PENDING |
| Eligible cohort | Definisikan registered/active, membership-only/visit-only, identity unresolved; prior purchase 365 hari adalah pilihan development | PENDING |
| Boundary/observability | Inclusion endpoint, timezone, maturity/adjustment dan coverage yang cukup untuk non-null label | PENDING |

Memilih 90 hari tidak sekaligus menyetujui ketiga event atau cohort 365 hari. Renewal dan lifecycle CHURNED bukan label ML yang sama. Label development `christ-churn90-three-events-dev-1.1` tetap tidak berubah. Keputusan harus direview Christ dan penyetuju berwenang; nama/tanggal tidak diisi oleh Moses. Detail siap-review: [Moses unblock handoff](../../moses_data_ai/MOSES_UNBLOCK_HANDOFF_2026-11-18.md) dan [draft I-04](../../moses_data_ai/PREDICTION_CONTRACT_I04_DRAFT_2026-11-18.md).

### 1.2 Parameter Prediksi

| Parameter | Nilai |
|---|---|
| **Prediction Horizon** | 90 hari ke depan dari `prediction_date` |
| **Masa Berlaku Skor (`valid_until`)** | 30 hari sejak skor diterbitkan |
| **Risk Band Cut-offs** | LOW (< 0.30) / MEDIUM (0.30-0.60) / HIGH (0.60-0.80) / VERY_HIGH (>= 0.80) |

### 1.3 Persyaratan Reason Codes

Setiap prediksi churn **wajib** menghasilkan **minimal 3 Reason Codes** dalam format bahasa bisnis:

| Kode | Deskripsi |
|---|---|
| `RECENCY_LONG` | Tidak berkunjung / bertransaksi dalam N hari |
| `SPEND_DECLINE` | Penurunan nilai transaksi rata-rata dibanding 3 bulan sebelumnya |
| `FREQUENCY_DROP` | Penurunan frekuensi kunjungan signifikan |
| `MEMBERSHIP_EXPIRING` | Membership akan kadaluarsa dalam <= 30 hari |
| `UNRESOLVED_COMPLAINT` | Memiliki keluhan aktif yang belum diselesaikan |
| `NO_CROSS_CATEGORY` | Tidak pernah melakukan pembelian lintas kategori produk |

---

## 2. Definisi Customer Lifetime Value (CLV)

> **Referensi:** `Requirement_Capstone.md` Bab 2 (FRD §6.7, TRD §9.4)

### 2.1 Formula CLV

```
CLV = Historical_Spend_12m + (Avg_Txn_Value x Freq_Per_Month x 12 x Retention_Factor)
```

**Keterangan variabel:**

| Variabel | Penjelasan |
|---|---|
| `Historical_Spend_12m` | Total pendapatan kotor (Gross Revenue) pelanggan dalam **rolling 365 hari** mundur dari `prediction_date` |
| `Avg_Txn_Value` | Rata-rata nilai transaksi dalam rolling 365 hari terakhir |
| `Freq_Per_Month` | Rata-rata frekuensi transaksi per bulan dalam rolling 365 hari terakhir |
| `Retention_Factor` | Estimasi probabilitas pelanggan tetap aktif (0.0-1.0). Requirement_Capstone hanya menyebut nama variabel ini **tanpa nilai**; nilai default 0.7 pada v1.0 adalah **asumsi tanpa sumber** dan dicabut. Nilai/cara estimasi ditetapkan oleh model ML (Moses) dan wajib didokumentasikan. |

> **[KEPUTUSAN v1.3 — Item 3] Sumber gross revenue:**
> - **Jendela waktu:** rolling **365 hari** mundur dari `prediction_date` (bukan tahun kalender).
> - **Status transaksi yang dihitung:** `COMPLETED` dan `PARTIAL_REFUND`. Transaksi berstatus `CANCELLED`, `PENDING`, `FAILED` **tidak dihitung**.
> - **Perlakuan refund/diskon:** Gunakan `gross_amount` (sebelum diskon di laporan internal). Jika tersedia `net_amount` (setelah diskon POS), gunakan `net_amount`. Refund penuh (`CANCELLED`/`REFUNDED`) dikecualikan dari perhitungan. Refund parsial (`PARTIAL_REFUND`) dihitung dengan nilai bersih yang diterima bisnis.
> - **Alasan rolling vs kalender:** Menghindari bias musiman akhir tahun dan konsisten dengan `prediction_date` yang dapat jatuh kapan saja.
>
> **[KEPUTUSAN v1.3 — Item 3] Retention Factor:**
> - Nilai `0.7` TIDAK BOLEH dipakai — dicabut karena tanpa sumber bisnis.
> - `1 - churn_score` TIDAK BOLEH dipakai — data leakage (memakai target prediksi sebagai input).
> - **Metode yang disetujui:** Estimasi empiris berbasis segmen lifecycle historis. Moses menyediakan rata-rata probabilitas retensi 90-hari per segmen lifecycle dari data historis (`services/data/`). Christ menyetujui nilai bisnis dan contoh numerik setelah Moses menyerahkan angka tersebut.
> - **Status:** PENDING Moses menyerahkan tabel retensi per segmen. `SERVICE_REMINDER` dan CLV scoring tidak dapat di-finalize sampai nilai ini tersedia.
>
> **Contoh numerik (placeholder sampai Moses menyerahkan angka):**
> Pelanggan ACTIVE, rolling 365 hari: 8 transaksi, total gross Rp 1.200.000 → `Historical_Spend_12m = 1.200.000`, `Avg_Txn_Value = 150.000`, `Freq_Per_Month = 0.67`. `Retention_Factor = [Moses akan isi]`. CLV = 1.200.000 + (150.000 × 0.67 × 12 × RF).

> **ATURAN PENTING:**
> CLV **WAJIB** dinyatakan sebagai **PENDAPATAN KOTOR (Gross Revenue)**, bukan profit atau margin.

### 2.2 Tiering CLV

| Tier | Ambang Nilai CLV (IDR) | Label Sistem | Implikasi Aksi |
|---|---|---|---|
| **Sangat Tinggi** | CLV >= Rp 1.000.000 | `PLATINUM` | Eligible untuk `RELATIONSHIP_MANAGER_CONTACT`, insentif tertinggi |
| **Tinggi** | Rp 500.000 <= CLV < Rp 1.000.000 | `GOLD` | Diprioritaskan untuk program retensi proaktif & insentif menengah |
| **Sedang** | Rp 200.000 <= CLV < Rp 500.000 | `SILVER` | Penawaran standar tanpa eskalasi insentif khusus |
| **Rendah / Riwayat Tidak Cukup** | CLV < Rp 200.000 atau total transaksi < 2x | `INSUFFICIENT_HISTORY` | Dikecualikan dari filter tier CLV; label khusus diterapkan |

---

## 3. Matriks Siklus Pelanggan (Customer Lifecycle)

> **Referensi:** `Requirement_Capstone.md` Bab 1 (FRD §6.5, TRD §9.1)

> **CATATAN KRITIS:**
> Lifecycle bersifat **rule-based declarative** (bukan hasil prediksi ML).
> Perpanjangan membership **dihitung sebagai transaksi resmi** — pelanggan yang memperpanjang
> membership **TIDAK BOLEH** dikategorikan Churned.

| Tahap Lifecycle | Label Sistem | Syarat RFM & Membership | Logika Prioritas |
|---|---|---|---|
| **New (Pelanggan Baru)** | `NEW` | Akun/transaksi pertama <= 30 hari lalu DAN total transaksi <= 2x | Dikecualikan dari audiens berbasis RFM kuintil |
| **Active (Pelanggan Aktif)** | `ACTIVE` | Transaksi >= 3x dalam 60 hari terakhir ATAU membership aktif digunakan dalam 60 hari terakhir | Target kampanye cross-sell & upsell |
| **Loyal (Pelanggan Setia)** | `LOYAL` | Transaksi >= 5x DAN akumulasi belanja >= Rp 500.000 dalam 90 hari terakhir DAN tenure >= 60 hari | Target loyalty reward & upsell premium |
| **At Risk (Mulai Pasif)** | `AT_RISK` | Tidak ada transaksi/kunjungan selama 91-180 hari DAN sisa perpanjangan membership <= 30 hari | Target prioritas intervensi retensi |
| **Dormant / Lapsed (Pasif)** | `DORMANT` | Tidak ada transaksi/kunjungan dalam 181-365 hari DAN perpanjangan membership terlewat 1-60 hari | Memerlukan penawaran reaktivasi khusus |
| **Churned (Berpaling)** | `CHURNED` | Tidak ada transaksi/kunjungan > 365 hari DAN membership kadaluarsa > 180 hari | Status dicatat di histori lifecycle |
| **Reactivated / Reclaimed** | `REACTIVATED` | Sebelumnya `DORMANT`/`CHURNED`, kembali transaksi >= 2x ATAU memperpanjang membership | Hasil kampanye win-back yang berhasil |
| **Occasional (Sesekali)** — *[DISETUJUI v1.3 — Item 2]* | `OCCASIONAL` | Tidak ada pada Requirement. Implementasi: recency <= 90 hari dan transaksi 60 hari terakhir < 3 | **DISETUJUI** sebagai segmen pelengkap untuk kelengkapan coverage. Perlakuan: lihat §3.1 |
| **Never Transacted (Belum Pernah Bertransaksi)** — *[DISETUJUI v1.3 — Item 2]* | `NEVER_TRANSACTED` | Tidak ada pada Requirement. Implementasi: tenure > 30 hari dan belum pernah ada transaksi | **DISETUJUI** untuk consent/edukasi saja. Perlakuan: lihat §3.1 |

> **[KEPUTUSAN v1.3 — Item 2] Kelengkapan aturan lifecycle:**
>
> **A. OCCASIONAL — DISETUJUI:**
> Segmen ini diperlukan agar setiap pelanggan masuk tepat satu segmen (total coverage = 100%). Tanpa `OCCASIONAL`, pelanggan dengan recency ≤ 90 hari tetapi frekuensi < 3 tidak masuk ACTIVE/LOYAL/NEW — jatuh ke celah. Perlakuan ditetapkan di §3.1.
>
> **B. NEVER_TRANSACTED — DISETUJUI dengan batasan:**
> Diperlukan agar pelanggan terdaftar tanpa transaksi (periode orientasi > 30 hari) tidak ghost. HANYA eligible untuk `EDUCATION` (konten orientasi produk, bukan penawaran komersial). Tidak masuk cohort ML (dikecualikan dari training set churn).
>
> **C. AT_RISK/DORMANT gap — KEPUTUSAN:**
> Pelanggan yang memenuhi syarat recency (91-180 hari) tetapi TIDAK memenuhi syarat membership (sisa > 30 hari, bukan ≤ 30 hari) → **dikategorikan `AT_RISK` berdasarkan recency saja**. Recency adalah kriteria primer; membership adalah reinforcement sekunder. Ini sesuai implementasi `snapshot.py` dan lebih mudah dipahami operasional.
>
> **Contoh gap resolution:**
> - Pelanggan X: recency 120 hari, membership sisa 45 hari → AT_RISK (recency primer; membership tidak memblokir)
> - Pelanggan Y: recency 120 hari, membership sisa 10 hari → AT_RISK (memenuhi kedua kriteria)
>
> **D. WIN_BACK window contradiction — KEPUTUSAN:**
> Bab 1 Requirement: `DORMANT` = 181-365 hari. Bab 4 katalog `WIN_BACK_OFFER`: "91-180 hari pasif".
> **Definisi Bab 1 yang berlaku** — Bab 1 adalah definisi lifecycle primer; Bab 4 adalah teks aksi yang mengacu pada definisi itu. Teks "91-180 hari" di Bab 4 adalah error copywriting. `catalogue.py` trigger text sudah diperbaiki di v1.3 agar menyebut "181-365 hari".
>
> **Urutan prioritas klasifikasi** (implementasi `snapshot.py`): `REACTIVATED` > `LOYAL` > `NEW` > `NEVER_TRANSACTED` > `CHURNED` > `DORMANT` > `AT_RISK` > `ACTIVE` > `OCCASIONAL`. Urutan ini berlaku sampai ada keputusan berbeda dari Moses+Christ.

### 3.1 Matriks Alokasi Perlakuan per Segmen

Sumber: kolom *Syarat Pemicu* pada Requirement_Capstone Bab 4. Sel **"Belum ditetapkan"** berarti Requirement tidak memberi aturan; default sistem adalah `NO_ACTION` sampai diputuskan.

| Segmen | Aksi proaktif yang diizinkan | Catatan |
|---|---|---|
| `NEW` | `EDUCATION` (syarat: Churn Risk LOW) | |
| `ACTIVE` | `CROSS_SELL`, `UPSELL`, `SERVICE_REMINDER` (jadwal habis pakai <= 7 hari) | Lihat catatan SERVICE_REMINDER di bawah |
| `LOYAL` | `CROSS_SELL`, `UPSELL`, `LOYALTY_REWARD` (syarat CLV Tinggi/Sangat Tinggi), `SERVICE_REMINDER` (jadwal habis pakai <= 7 hari) | Lihat catatan SERVICE_REMINDER di bawah |
| `AT_RISK` | `RETENTION_OUTREACH` (Churn Risk HIGH atau VERY_HIGH, CLV GOLD/PLATINUM) | **[DISETUJUI v1.3 — Item 5]** Churn Risk HIGH+VERY_HIGH keduanya eligible (kode diperbaiki). |
| `DORMANT` | `WIN_BACK_OFFER` (CLV historis GOLD/PLATINUM, belum ada tawaran aktif), `RETENTION_OUTREACH` (At_Risk/Lapsed) | Jendela DORMANT = 181-365 hari (Bab 1 berlaku). |
| `CHURNED` | **`NO_ACTION`** (tidak ada kontak komersial) | **[DISETUJUI v1.3 — Item 2]** CHURNED tidak di-contact. Jika bisnis ingin winback setelah > 365 hari, harus melalui jalur khusus dengan persetujuan tambahan. |
| `REACTIVATED` | Perlakuan seperti `ACTIVE` | **[DISETUJUI v1.3 — Item 2]** Setelah REACTIVATED, pelanggan diperlakukan sama dengan ACTIVE karena sudah kembali bertransaksi. |
| `OCCASIONAL` | `EDUCATION` (konten awareness, bukan penawaran komersial) | **[DISETUJUI v1.3 — Item 2]** OCCASIONAL eligible untuk konten edukasi/awareness agar menjadi ACTIVE. Tidak eligible untuk CROSS_SELL/UPSELL/insentif besar. |
| `NEVER_TRANSACTED` | `EDUCATION` (orientasi produk, `is_commercial=False`) | **[DISETUJUI v1.3 — Item 2]** Hanya edukasi/onboarding. Tidak ada penawaran komersial sampai ada transaksi pertama. |
| *Lintas segmen* | `COMPLAINT_RESOLUTION` (keluhan `OPEN_SEVERE` aktif, prioritas #1); `RENEWAL_REMINDER` (sisa membership <= 15 hari); `RELATIONSHIP_MANAGER_CONTACT` (CLV >= Rp 1 juta dengan Churn Risk HIGH/VERY_HIGH, lifecycle AT_RISK/DORMANT) | Tidak dibatasi segmen lifecycle |

> **[KEPUTUSAN v1.3 — Item 5] Rekonsiliasi katalog aksi:**
>
> **A. RELATIONSHIP_MANAGER_CONTACT lifecycle restriction:**
> Kode (`evaluator.py`): lifecycle `AT_RISK` atau `DORMANT`. Requirement Bab 4 menyebut "keluhan aktif" juga memicu.
> **Keputusan:** lifecycle restriction AT_RISK/DORMANT di kode **DISETUJUI**. Pelanggan dengan keluhan aktif → `COMPLAINT_RESOLUTION` (bukan RM_CONTACT). Kedua aksi tidak overlap. Trigger text `catalogue.py` sudah diperbaiki v1.3 untuk mencerminkan ini.
>
> **B. RETENTION_OUTREACH risk band:**
> Kode lama: hanya `HIGH`. Target_definitions v1.2: `HIGH+VERY_HIGH`. Requirement Bab 4: `HIGH`.
> **Keputusan:** `HIGH DAN VERY_HIGH` keduanya eligible — **v1.3 memenangkan interpretasi ini** karena pelanggan `VERY_HIGH` jelas lebih urgent untuk diretain. Kode `evaluator.py` sudah diperbaiki.
>
> **C. CROSS_SELL/UPSELL propensity threshold:**
> `catalogue.py` trigger_conditions mencantumkan "Propensity >= 0.6" tetapi `evaluator.py` TIDAK mengecek threshold ini.
> **Keputusan:** Threshold **TIDAK** di-enforce di `evaluator.py` pada v1.3 — EV calculator sudah menggunakan propensity sebagai input formula EV. Aksi dengan propensity rendah (<0.6) akan menghasilkan EV rendah dan akan kalah dari NO_ACTION secara alami. Enforcement di kode (hard threshold) **ditunda** sampai ada data empiris yang membuktikan threshold 0.6 optimal. Trigger text di catalogue.py tetap informational.

> **Catatan `SERVICE_REMINDER` (keputusan tim, v1.2 — dikonfirmasi v1.3):** eligible hanya untuk lifecycle `ACTIVE`/`LOYAL` dengan `days_until_replenishment <= 7`
> (`last_purchase_date + replenishment_cycle_days - hari ini`; nilai negatif = sudah lewat), tanpa keluhan aktif, dengan consent Push/Email.
> `CHURNED`/`DORMANT` dikecualikan. Jika data jadwal tidak tersedia (`None`) aksi **tidak eligible** (fail-closed).
> **Perbedaan dengan Requirement_Capstone Bab 4:** Bab 4 tidak membatasi lifecycle untuk aksi ini. Pembatasan ACTIVE/LOYAL dan ambang 7 hari berasal dari keputusan tim.
> **Ketergantungan data:** field `replenishment_cycle_days` / `last_purchase_date` **belum ada** di data sintetis; Moses perlu menyediakannya.
> Sampai data tersedia, `SERVICE_REMINDER` tidak akan terpilih.

---

## 4. Aturan Kebijakan (Fatigue & Suppression Policy)

> **Referensi:** `Requirement_Capstone.md` Bab 3 (FRD §9.6, TRD §10.1)

### 4.1 Aturan Fatigue (Contact Frequency Cap)

| Parameter | Nilai |
|---|---|
| **Batas Maksimum Kontak Pemasaran** | **2 kontak** per **14 hari** per pelanggan |
| **Jangka Waktu Rolling Window** | 14 hari terakhir dihitung mundur dari tanggal eksekusi |
| **Status Jika Terlampaui** | `FREQ_CAP_SUPPRESSED` |
| **Konsekuensi** | Seluruh aksi komersial diblokir; sistem wajib memilih `NO_ACTION` |
| **Pengecualian** | `COMPLAINT_RESOLUTION` dan `SERVICE_REMINDER` tidak dihitung dalam batas frekuensi |

### 4.2 Aturan Suppression Mutlak

Pelanggan dengan salah satu kondisi berikut akan **diblokir penuh** dari seluruh penawaran komersial:

| Kondisi Suppression | Status Sistem | Konsekuensi |
|---|---|---|
| Pelanggan memiliki status **Opt-Out** pada kanal komunikasi manapun | `OPT_OUT_SUPPRESSED` (reason code: `OPT_OUT_SUPPRESSED`) | `NO_ACTION` wajib dipilih; tidak ada pengecualian |
| Pelanggan memiliki tiket keluhan aktif berstatus **`OPEN_SEVERE_COMPLAINT`** | `COMPLAINT_SUPPRESSED` (reason code: `EXCL_OPEN_SEVERE_COMPLAINT`) | Semua pesan promosi komersial diblokir; hanya `COMPLAINT_RESOLUTION` yang boleh dikirim |

> **Penempatan pada 5 masukan keputusan (Requirement Bab 3):** keluhan aktif termasuk masukan 2 (*Business Eligibility*); opt-out = masukan 3 (*Consent*);
> frequency cap = masukan 4 (*Contact Policy*).

> **[KEPUTUSAN v1.3 — Item 6] Cakupan opt-out — DIPUTUSKAN:**
>
> Sebelum v1.3, teks §4.2 dan implementasi tidak konsisten. Keputusan resmi:
>
> **Model yang berlaku: Campuran (channel-level + global hard stop)**
> - `is_global_opt_out = True` pada K-10 → **blokir SEMUA kanal** (hard suppression global). Alasan: pelanggan yang memilih global opt-out menyatakan tidak ingin dihubungi melalui cara apapun.
> - Opt-out pada **kanal spesifik** (mis. `email_opt_out=True`) → hanya **memblokir kanal itu**. Aksi yang masih punya kanal lain yang diizinkan tetap dapat dikirim.
> - Implementasi `suppression.py` (cek `global_opt_out`) + `evaluator.py::check_channel_availability()` (cek kanal spesifik) sudah mencerminkan model ini dengan benar — TIDAK ada perubahan kode diperlukan.
>
> **Contoh positif (global opt-out):** Pelanggan A, `is_global_opt_out=True`. Engine → `OPT_OUT_SUPPRESSED` → NO_ACTION pada semua aksi.
> **Contoh negatif (channel-level):** Pelanggan B, `email_opt_out=True`, `push_opt_in=True`. RETENTION_OUTREACH (kanal: email, push) → email diblokir, push tersedia → aksi TETAP eligible via push.
> **Contoh boundary:** Pelanggan C, `email_opt_out=True`, `push_opt_out=True`, `is_global_opt_out=False`. RETENTION_OUTREACH hanya punya email+push, kedua-duanya opt-out → `check_channel_availability` mengembalikan alasan blokir → aksi tidak eligible.

> **ATURAN TEGAS:**
> Suppression bersifat **MUTLAK**. Tidak ada skor AI, nilai CLV, atau urgensi bisnis yang dapat
> meng-override kondisi suppression. Jika suppression aktif, sistem **wajib** memilih `NO_ACTION`
> (kecuali `COMPLAINT_RESOLUTION` untuk kasus `OPEN_SEVERE_COMPLAINT`).

---

## Lampiran: Ringkasan Konstanta Sistem

```python
# Konstanta yang harus digunakan konsisten di seluruh modul
PREDICTION_HORIZON_DAYS = 90         # Jendela prediksi & jendela outcome label churn (ke depan)
SCORE_VALIDITY_DAYS = 30             # Masa berlaku skor valid_until
FREQ_CAP_MAX_CONTACTS = 2            # Maksimum kontak per rolling window
FREQ_CAP_WINDOW_DAYS = 14            # Rolling window dalam hari
MIN_REASON_CODES = 3                 # Minimum Reason Codes per prediksi

# CLV Tier Thresholds (IDR)
CLV_TIER_PLATINUM = 1_000_000
CLV_TIER_GOLD = 500_000
CLV_TIER_SILVER = 200_000

# Lifecycle Boundaries (days)
LIFECYCLE_NEW_WINDOW = 30
LIFECYCLE_ACTIVE_WINDOW = 60
LIFECYCLE_AT_RISK_START = 91
LIFECYCLE_AT_RISK_END = 180
LIFECYCLE_DORMANT_START = 181
LIFECYCLE_DORMANT_END = 365
LIFECYCLE_CHURNED_THRESHOLD = 365

# Keputusan tim (v1.2) -- bukan dari Requirement_Capstone
MIN_EV_THRESHOLD_IDR = 1000.0         # EV < nilai ini -> NO_ACTION (alasan BELOW_MIN_EV)
MAX_DISCOUNT_PERCENT = 30.0           # pagu diskon global pada pesan
SERVICE_REMINDER_WINDOW_DAYS = 7      # SERVICE_REMINDER eligible jika habis pakai <= 7 hari
CONTROL_HOLDOUT_RATIO = 0.10          # Holdout Control Group default (K-08)
MEMBERSHIP_CHURN_THRESHOLD = 180
```

---

## §5. Parameter Expected Value (EV) — Keputusan Tim v1.2 Dikonfirmasi v1.3

> **[KEPUTUSAN v1.3 — Item 4]** Parameter-parameter di bawah adalah **kebijakan bisnis** Christ, bukan angka dari Requirement_Capstone. Semua dikonfirmasi berlaku.

### 5.1 Threshold & Caps

| Parameter | Nilai | Alasan Bisnis |
|---|---|---|
| `min_ev_threshold` | **Rp 1.000** | EV di bawah ini tidak bermakna secara bisnis; skor expired/degraded menghasilkan EV ≈ 0, tidak boleh mengalahkan NO_ACTION |
| Pagu diskon global | **30%** | Ceiling agar margin gross tidak tergerus di luar batas dapat diterima |
| Pagu per band: NONE | **0%** | Aksi edukasi/reminder tidak memberi diskon |
| Pagu per band: LOW | **≤ 10%** | Cross-sell/edukasi ringan |
| Pagu per band: MEDIUM | **≤ 20%** | RM Contact, Upsell |
| Pagu per band: HIGH | **≤ 30%** | Retensi prioritas tinggi |

### 5.2 Action Weights (dari `catalogue.py` — DIRATIFIKASI v1.3)

| Aksi | Weight | Alasan |
|---|---|---|
| `COMPLAINT_RESOLUTION` | 2.0 | Prioritas tertinggi — layanan, bukan komersial |
| `RELATIONSHIP_MANAGER_CONTACT` | 1.8 | Pelanggan PLATINUM berisiko tinggi → nilai tertinggi kedua |
| `RETENTION_OUTREACH` | 1.6 | Retensi pelanggan berharga (GOLD/PLATINUM AT_RISK/DORMANT) |
| `WIN_BACK_OFFER` | 1.5 | Reaktivasi pelanggan lapsed berharga |
| `RENEWAL_REMINDER` | 1.5 | Mencegah churn membership berbatas waktu |
| `UPSELL` | 1.4 | Upgrade memberikan nilai jangka panjang |
| `LOYALTY_REWARD` | 1.3 | Apresiasi pelanggan setia → retention |
| `CROSS_SELL` | 1.2 | Pertumbuhan revenue dari pelanggan aktif |
| `SERVICE_REMINDER` | 1.0 | Non-komersial, pengingat rutin |
| `EDUCATION` | 0.8 | Jangka panjang, efek lambat |
| `NO_ACTION` | 0.0 | Fallback; tidak ada EV |

### 5.3 Revenue Factor & Incentive Cost (dari `ev_calculator.py` — DIRATIFIKASI v1.3)

**Faktor kontribusi pendapatan terhadap CLV (proxy):**

| Aksi | Factor | Interpretasi Bisnis |
|---|---|---|
| `RELATIONSHIP_MANAGER_CONTACT` | 0.60 | Mencegah kehilangan 60% CLV pelanggan PLATINUM |
| `RETENTION_OUTREACH` | 0.50 | Mencegah kehilangan 50% CLV |
| `WIN_BACK_OFFER` | 0.40 | Reaktivasi mengambil kembali 40% CLV historis |
| `UPSELL` | 0.35 | Upgrade meningkatkan CLV 35% |
| `CROSS_SELL` | 0.30 | Kategori baru menambah 30% CLV |
| `RENEWAL_REMINDER` | 0.25 | Perpanjangan menjaga 25% CLV tahunan |
| `LOYALTY_REWARD` | 0.20 | Apresiasi meningkatkan retensi; efek pendapatan 20% CLV |
| `EDUCATION` | 0.15 | Edukasi jangka panjang, efek pendapatan 15% CLV |
| `SERVICE_REMINDER` | 0.10 | Reminder ringan, 10% CLV |
| `COMPLAINT_RESOLUTION` | 0.00 | Non-revenue; protektif |

> **Catatan:** Semua angka ini adalah **proxy engineering**. Nilai exat harus dikalibrasi dari data eksperimen setelah deployment. Jika hasil eksperimen mengindikasikan faktor berbeda secara signifikan (> 20% deviasi), tim harus merevisi angka ini.

**Biaya insentif per band (dari `ev_calculator.py`):**

| Band | % CLV | Cap IDR | Contoh (CLV Rp 600.000) |
|---|---|---|---|
| LOW | 5% | Rp 25.000 | 5% × 600.000 = 30.000 → cap → **Rp 25.000** |
| MEDIUM | 10% | Rp 75.000 | 10% × 600.000 = 60.000 (di bawah cap) → **Rp 60.000** |
| HIGH | 15% | Rp 150.000 | 15% × 600.000 = 90.000 (di bawah cap) → **Rp 90.000** |
| DISCOUNT_LIMITED | 8% | Rp 50.000 | 8% × 600.000 = 48.000 (di bawah cap) → **Rp 48.000** |
| LOYALTY_POINTS | 5% | Rp 30.000 | 5% × 600.000 = 30.000 → cap → **Rp 30.000** |

---

## §6. Data Contract SERVICE_REMINDER — Item 7 v1.3

> **[KEPUTUSAN v1.3 — Item 7]**

### 6.1 Definisi Bisnis

`SERVICE_REMINDER` adalah pengingat jadwal kunjungan atau pembelian ulang produk habis pakai. Aksi ini:
- **Non-komersial**: tidak ada diskon/insentif; hanya informasi jadwal
- **Fail-closed**: jika data tidak tersedia → aksi tidak eligible (tidak pernah dipilih)

### 6.2 Field yang Diperlukan

| Field | Makna Bisnis | Sumber |
|---|---|---|
| `last_purchase_date` | Tanggal terakhir pelanggan membeli produk dalam kategori yang memiliki replenishment cycle (mis. skincare, haircare, vitamin). **Bukan** tanggal kunjungan atau perpanjangan membership. | `transactions.csv` — filter berdasarkan `product_category` yang masuk daftar kategori replenishment |
| `replenishment_cycle_days` | Rata-rata durasi pemakaian produk dalam kategori tersebut (dalam hari). Ini adalah rata-rata per kategori, bukan per SKU. Contoh: skincare = 60 hari, haircare = 45 hari. | Moses menyediakan lookup tabel per kategori dari data historis |
| `days_until_replenishment` | `last_purchase_date + replenishment_cycle_days - today`. Nilai ≤ 0 artinya sudah lewat jatuh tempo. | Dihitung di `EligibilityProfile` |

### 6.3 Kategori yang Eligible untuk Replenishment Cycle

Kategori produk/layanan yang umumnya memiliki siklus pemakaian teratur:
- Produk perawatan kulit (skincare)
- Produk perawatan rambut (haircare)
- Suplemen/vitamin
- Layanan salon rutin (potong rambut, perawatan)

> **Routing ke Moses:** Moses perlu menyediakan:
> 1. Daftar `product_category` values yang masuk bucket "replenishment-eligible"
> 2. `replenishment_cycle_days` per kategori (lookup tabel, bukan nilai per pelanggan)
> 3. Cara mengisi `last_purchase_date` jika pelanggan pernah beli beberapa kategori (ambil yang paling baru? atau per kategori?)
>
> **Sampai Moses menyerahkan data ini, `days_until_replenishment` selalu `None` → `SERVICE_REMINDER` selalu `NOT_ELIGIBLE`.**

---

## §7. Kontrak Outcome/KPI — Gate A

> **[KEPUTUSAN v1.3]** Bagian ini memenuhi persyaratan Gate A untuk kontrak outcome/KPI.

### 7.1 Event Konversi per Aksi

| Aksi | Event Konversi yang Valid | Jendela Atribusi |
|---|---|---|
| `RETENTION_OUTREACH` | Transaksi POS COMPLETED atau perpanjangan membership setelah aksi | 30 hari |
| `RELATIONSHIP_MANAGER_CONTACT` | Transaksi POS COMPLETED atau perpanjangan membership setelah aksi | 30 hari |
| `WIN_BACK_OFFER` | Transaksi POS COMPLETED pertama setelah DORMANT | 30 hari |
| `CROSS_SELL` | Transaksi pertama pada kategori yang sebelumnya tidak dimiliki | 30 hari |
| `UPSELL` | Perpanjangan membership pada tier yang lebih tinggi | 30 hari |
| `RENEWAL_REMINDER` | `membership_events.event_type = RENEWAL` | 15 hari (sejak reminder dikirim) |
| `LOYALTY_REWARD` | Transaksi tambahan setelah reward diterima | 30 hari |
| `EDUCATION` | Kunjungan atau transaksi pertama setelah edukasi | 60 hari (efek edukasi lebih lambat) |
| `SERVICE_REMINDER` | Transaksi pada kategori yang diingatkan | 14 hari |
| `COMPLAINT_RESOLUTION` | Penutupan tiket keluhan (`ticket_status = CLOSED`) | 7 hari |

### 7.2 Treatment & Control Group

| Parameter | Nilai | Alasan |
|---|---|---|
| Holdout ratio (control) | **10%** (K-08: `control_holdout_ratio = 0.10`) | Minimum statistis untuk deteksi efek kecil |
| Seed randomisasi | Wajib diisi (`random_seed` di K-08) | Reproducibility |
| Eligibility treatment | Semua pelanggan yang lolos 5 gerbang | |
| Eligibility control | Pelanggan yang lolos 5 gerbang tetapi diassign ke holdout (10%) | |
| Kontaminasi | Pelanggan control yang terkena aksi lewat kanal lain (mis. datang ke toko sendiri) → tetap dihitung sebagai control; tidak ada cara teknis mencegah ini di lingkungan sintetis | |

### 7.3 Atribusi Revenue

| Parameter | Aturan |
|---|---|
| **Jendela atribusi default** | 30 hari sejak aksi dikirim |
| **Jendela refund/penyesuaian** | 14 hari sejak tanggal transaksi (K-09: `adjustment_window_days = 14`) |
| **Revenue yang dihitung** | Gross Revenue dari transaksi COMPLETED; refund dikurangi setelah adjustment window |
| **Revenue terobservasi** | Total gross transaksi treatment group dalam jendela atribusi |
| **Revenue inkremental** | Revenue terobservasi treatment MINUS revenue terobservasi control (normalized per pelanggan) |
| **Uplift sintetis** | **BUKAN** bukti kausalitas bisnis; hanya dipakai untuk validasi teknis pipeline |

### 7.4 Threshold Keberhasilan

> **Catatan:** Threshold ini bersifat sementara dan belum dikalibrasi dari data eksperimen nyata. Harus direvisi setelah deployment pertama.

| Aksi | Threshold Konversi Minimum | Threshold Revenue Inkremental |
|---|---|---|
| `RETENTION_OUTREACH` | ≥ 15% pelanggan treatment bertransaksi dalam 30 hari | Positive (treatment > control) |
| `WIN_BACK_OFFER` | ≥ 10% pelanggan DORMANT kembali aktif | Positive |
| `CROSS_SELL` | ≥ 8% transaksi pada kategori baru | Positive |
| `RENEWAL_REMINDER` | ≥ 20% perpanjangan dalam 15 hari | Positive |
| Lainnya | Belum dikalibrasi — tandai sebagai PENDING empiris | — |

**Contoh positif:** 100 pelanggan AT_RISK treatment RETENTION_OUTREACH; 18 bertransaksi dalam 30 hari = 18% conversion → MELEWATI threshold (≥ 15%).
**Contoh negatif:** 100 pelanggan treatment; hanya 5 bertransaksi = 5% → GAGAL threshold.
**Contoh boundary:** 15 pelanggan bertransaksi = tepat 15% → TEPAT di batas, dianggap LULUS.

### 7.5 Hal yang Belum Dapat Diputuskan (PENDING Data/Eksperimen)

| Item | Status | Routing |
|---|---|---|
| Retensi factor per segmen | PENDING | Moses menyerahkan angka historis per lifecycle segment |
| Threshold konversi per aksi (empiris) | PENDING | Setelah deployment pertama dan data terkumpul |
| Replenishment cycle per kategori | PENDING | Moses menyerahkan lookup table |
| Incremental revenue per aksi (baseline) | PENDING | Eksperimen pertama setelah go-live |

---

## Riwayat Revisi

| Versi | Tanggal | Perubahan |
|---|---|---|
| v1.0 | 2026-10-28 | Versi awal (APPROVED). |
| v1.1 | 2026-11-07 | (1) §1.1 definisi churn diubah ke jendela 90 hari **ke depan** + 3 churn negation events, menggantikan definisi 180 hari ke belakang; (2) §2.1 nilai default Retention_Factor 0.7 dicabut (tanpa sumber); (3) §3 ditambah label `OCCASIONAL` & `NEVER_TRANSACTED` (usulan) dan catatan kelengkapan aturan; (4) §3.1 matriks alokasi perlakuan per segmen (9 segmen); (5) §4.2 reason code `EXCL_OPEN_SEVERE_COMPLAINT`, penempatan pada 5 masukan, dan butir konfirmasi cakupan opt-out; (6) konstanta `CHURN_DEFINITION_DAYS = 180` dihapus (tidak dipakai di kode mana pun). |
| v1.2 | 2026-11-09 | Keputusan tim: (1) `min_ev_threshold` = Rp 1.000 (`BELOW_MIN_EV`); (2) pagu diskon global 30% dan batas per band (Tanpa Insentif 0%, Rendah <= 10%, Sedang <= 20%, Tinggi <= 30%) dengan eskalasi `INCENTIVE_ESCALATED`; (3) daftar kata terlarang; (4) aturan `SERVICE_REMINDER` (ACTIVE/LOYAL, <= 7 hari) dan penyesuaian matriks §3.1; (5) K-08: `control_holdout_ratio` (default 0.10) dan `random_seed`. |
