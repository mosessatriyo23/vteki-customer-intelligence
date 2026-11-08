# Kontrak Definisi Bisnis: Target & Standar Sistem
**Dokumen:** `target_definitions.md`
**Status:** v1.1 — REVISI (v1.0 berstatus APPROVED). Perubahan v1.1 menunggu persetujuan ulang.
**Penyusun:** Christ (Decisioning, Activation & Measurement Engineer)
**Disetujui oleh:** [ISI_SENDIRI: nama penyetuju (Dosen Pembimbing / Mentor V-TEKI) dan tanggal persetujuan v1.1]
**Versi:** v1.1
**Tanggal:** v1.0 = 2026-10-28; v1.1 = 2026-11-07
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
| **Cohort (eligible)** | Pelanggan yang sudah terdaftar dan aktif pada `prediction_date`. Implementasi saat ini (`services/data/models/labels.py`): minimal 1 transaksi dalam 365 hari sebelum `prediction_date`. |
| **Jendela outcome** | **90 hari ke depan**: (`prediction_date`, `prediction_date` + 90 hari]. Batas kanan tertutup, `prediction_date` sendiri tidak termasuk. |
| **Churn = 1** | Tidak ada satu pun *churn negation event* di dalam jendela outcome. |
| **Churn = 0** | Ada minimal satu *churn negation event* di dalam jendela outcome. |
| **Label tidak lengkap** | Jika data belum mencakup `prediction_date` + 90 hari, label dikosongkan (null), **bukan** diisi 0. |

**Churn negation events** (salah satu cukup untuk membatalkan label churn):

1. Minimal **1 transaksi POS** berstatus `COMPLETED` atau `PARTIAL_REFUND`;
2. **Kunjungan fisik terverifikasi** (`customer_visits.csv`, status `COMPLETED`);
3. **Perpanjangan keanggotaan** (`membership_events.csv`, `event_type = RENEWAL`). Perpanjangan dihitung sebagai transaksi resmi sesuai `Requirement_Capstone.md` Bab 1.

> **Sumber v1.1:** `Panduan_Kerja_Christ.md` Minggu 1 (window 90 hari pasca `prediction_date` + 3 negation events);
> `contracts/business_events.md` bagian *Model labels*; implementasi `services/data/models/labels.py` (`horizon_days = 90`).
>
> **Koreksi dari v1.0:** v1.0 menulis definisi 180 hari ke **belakang** dan memuat syarat "tidak diprediksi aktif dalam 90 hari ke depan".
> Itu keliru karena (a) membuat label bergantung pada keadaan masa lalu sehingga tidak bisa menjadi target prediksi, (b) bersifat sirkular
> (memakai hasil prediksi untuk mendefinisikan label), dan (c) bertentangan dengan Panduan serta pipeline label Moses yang sudah memakai jendela 90 hari ke depan.
>
> **Catatan ketidakkonsistenan sumber:** `Requirement_Capstone.md` Bab 2.1 menulis "180 hari ke depan" sementara Prediction Horizon di bab yang sama = 90 hari.
> v1.1 mengikuti 90 hari (Panduan + implementasi). **Konfirmasi ke Dosen/Mentor diperlukan.**
> Angka 180 hari hanya tetap dipakai pada lifecycle `CHURNED` (membership kadaluarsa > 180 hari, §3), yang merupakan status berbasis aturan, bukan label ML.

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
| `Historical_Spend_12m` | Total pendapatan kotor (Gross Revenue) pelanggan dalam **12 bulan terakhir** |
| `Avg_Txn_Value` | Rata-rata nilai transaksi dalam 12 bulan terakhir |
| `Freq_Per_Month` | Rata-rata frekuensi transaksi per bulan dalam 12 bulan terakhir |
| `Retention_Factor` | Estimasi probabilitas pelanggan tetap aktif (0.0-1.0). Requirement_Capstone hanya menyebut nama variabel ini **tanpa nilai**; nilai default 0.7 pada v1.0 adalah **asumsi tanpa sumber** dan dicabut. Nilai/cara estimasi ditetapkan oleh model ML (Moses) dan wajib didokumentasikan. |

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
| **Occasional (Sesekali)** — *usulan implementasi* | `OCCASIONAL` | Tidak ada pada Requirement. Implementasi: recency <= 90 hari dan transaksi 60 hari terakhir < 3 | Belum ada perlakuan (lihat §3.1) |
| **Never Transacted (Belum Pernah Bertransaksi)** — *usulan implementasi* | `NEVER_TRANSACTED` | Tidak ada pada Requirement. Implementasi: tenure > 30 hari dan belum pernah ada transaksi | Belum ada perlakuan (lihat §3.1) |

> **Catatan 9 segmen:** Requirement_Capstone Bab 1 hanya mendefinisikan 7 tahap. `OCCASIONAL` dan `NEVER_TRANSACTED` berasal dari implementasi segmentasi
> (`services/data/segmentation/snapshot.py`) agar setiap pelanggan masuk tepat satu segmen (total 9 segmen). Keduanya **belum disetujui** dan butuh persetujuan.
>
> **Catatan kelengkapan aturan:** kriteria Requirement di atas tidak saling eksklusif dan tidak lengkap. Contoh: `AT_RISK` mensyaratkan recency 91-180 hari **DAN** sisa membership <= 30 hari,
> sehingga pelanggan recency 91-180 hari dengan sisa membership > 30 hari tidak masuk segmen mana pun. Implementasi memakai urutan prioritas usulan berbasis recency:
> `REACTIVATED` > `LOYAL` > `NEW` > `NEVER_TRANSACTED` > `CHURNED` > `DORMANT` > `AT_RISK` > `ACTIVE` > `OCCASIONAL`. Urutan ini dan peran kriteria membership perlu disepakati.

### 3.1 Matriks Alokasi Perlakuan per Segmen

Sumber: kolom *Syarat Pemicu* pada Requirement_Capstone Bab 4. Sel **"Belum ditetapkan"** berarti Requirement tidak memberi aturan; default sistem adalah `NO_ACTION` sampai diputuskan.

| Segmen | Aksi proaktif yang diizinkan menurut Requirement Bab 4 | Catatan |
|---|---|---|
| `NEW` | `EDUCATION` (syarat: Churn Risk LOW) | |
| `ACTIVE` | `CROSS_SELL`, `UPSELL` | |
| `LOYAL` | `CROSS_SELL`, `UPSELL`, `LOYALTY_REWARD` (syarat CLV Tinggi/Sangat Tinggi) | |
| `AT_RISK` | `RETENTION_OUTREACH` (Churn Risk HIGH, CLV Tinggi/Sangat Tinggi) | |
| `DORMANT` | `WIN_BACK_OFFER` (CLV historis Tinggi, belum ada tawaran aktif), `RETENTION_OUTREACH` ("At_Risk/Lapsed") | Bab 4 menulis WIN_BACK untuk "91-180 hari pasif" tetapi Bab 1 menetapkan Dormant = 181-365 hari. Definisi Bab 1 yang dipakai (sesuai §3 dan implementasi). |
| `CHURNED` | **Belum ditetapkan** | |
| `REACTIVATED` | **Belum ditetapkan** | |
| `OCCASIONAL` | **Belum ditetapkan** | |
| `NEVER_TRANSACTED` | **Belum ditetapkan** | |
| *Lintas segmen* | `COMPLAINT_RESOLUTION` (keluhan `OPEN_SEVERE` aktif, prioritas #1); `RENEWAL_REMINDER` (sisa membership <= 15 hari); `SERVICE_REMINDER`; `RELATIONSHIP_MANAGER_CONTACT` (CLV >= Rp 1 juta dengan Churn Risk HIGH/VERY_HIGH) | Tidak dibatasi segmen lifecycle |

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
>
> **[PERLU KONFIRMASI] Cakupan opt-out:** teks di atas (v1.0) menyatakan opt-out pada kanal manapun memblokir penuh. Requirement Bab 3 masukan 3 bertanya
> "mengizinkan kontak pada **kanal ini**?" dan kontrak K-10 membedakan `is_global_opt_out` (hard suppression) dari consent per kanal
> (`UNKNOWN`/`EXPIRED`/`OPT_OUT` = `BLOCKED` pada kanal itu). Implementasi saat ini: opt-out global memblokir semua; opt-out per kanal hanya menutup kanal tersebut.
> Mana yang dimaksud perlu diputuskan.

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
MEMBERSHIP_CHURN_THRESHOLD = 180
```

---

## Riwayat Revisi

| Versi | Tanggal | Perubahan |
|---|---|---|
| v1.0 | 2026-10-28 | Versi awal (APPROVED). |
| v1.1 | 2026-11-07 | (1) §1.1 definisi churn diubah ke jendela 90 hari **ke depan** + 3 churn negation events, menggantikan definisi 180 hari ke belakang; (2) §2.1 nilai default Retention_Factor 0.7 dicabut (tanpa sumber); (3) §3 ditambah label `OCCASIONAL` & `NEVER_TRANSACTED` (usulan) dan catatan kelengkapan aturan; (4) §3.1 matriks alokasi perlakuan per segmen (9 segmen); (5) §4.2 reason code `EXCL_OPEN_SEVERE_COMPLAINT`, penempatan pada 5 masukan, dan butir konfirmasi cakupan opt-out; (6) konstanta `CHURN_DEFINITION_DAYS = 180` dihapus (tidak dipakai di kode mana pun). |
