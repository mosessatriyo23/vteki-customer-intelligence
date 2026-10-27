# Kontrak Definisi Bisnis: Target & Standar Sistem
**Dokumen:** `target_definitions.md`
**Status:** APPROVED — Baseline untuk Modul Machine Learning & Decision Engine
**Penyusun:** Christ (Decisioning, Activation & Measurement Engineer)
**Versi:** v1.0
**Tanggal:** 2026-10-28
**Klasifikasi:** 100% Data Sintetis — Hanya untuk keperluan akademik Capstone Project UKDW

---

> **TUJUAN DOKUMEN**
> Dokumen ini menetapkan definisi formal target bisnis yang dibutuhkan sebagai kontrak antar modul.
> Modul Machine Learning (Moses) **wajib** mengacu pada standar ini saat membuat label training data,
> dan modul Decisioning (Christ) akan menerapkan aturan-aturan ini dalam NBA Engine & Policy Services.

---

## 1. Definisi Churn

> **Referensi:** `Requirement_Capstone.md` Bab 2 (FRD §6.6, TRD §9.3)

### 1.1 Definisi Churn yang Disepakati

Seorang pelanggan dinyatakan **CHURN** apabila memenuhi **seluruh** kondisi berikut:

| Kondisi | Nilai / Aturan |
|---|---|
| Tidak ada transaksi atau kunjungan | Selama **> 180 hari** ke belakang dari `prediction_date` |
| Tidak memperpanjang membership | Membership **kadaluarsa > 180 hari** dari `prediction_date` |
| Tidak ada aktivitas ke depan | Tidak diprediksi aktif dalam **90 hari** ke depan |

> **ATURAN PENGECUALIAN (Wajib Diterapkan oleh Modul ML):**
> Pelanggan **TIDAK BOLEH** dilabeli Churn apabila:
> - Memiliki transaksi atau kunjungan dalam **180 hari terakhir**, ATAU
> - Memperpanjang membership dalam **180 hari terakhir**.
> Perpanjangan membership dihitung sebagai **transaksi resmi** sesuai `Requirement_Capstone.md` Bab 1.

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
| `Retention_Factor` | Estimasi probabilitas pelanggan tetap aktif (0.0-1.0, default: 0.7 untuk Active) |

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
| Pelanggan memiliki status **Opt-Out** pada kanal komunikasi manapun | `OPT_OUT_SUPPRESSED` | `NO_ACTION` wajib dipilih; tidak ada pengecualian |
| Pelanggan memiliki tiket keluhan aktif berstatus **`OPEN_SEVERE_COMPLAINT`** | `COMPLAINT_SUPPRESSED` | Semua pesan promosi komersial diblokir; hanya `COMPLAINT_RESOLUTION` yang boleh dikirim |

> **ATURAN TEGAS:**
> Suppression bersifat **MUTLAK**. Tidak ada skor AI, nilai CLV, atau urgensi bisnis yang dapat
> meng-override kondisi suppression. Jika suppression aktif, sistem **wajib** memilih `NO_ACTION`
> (kecuali `COMPLAINT_RESOLUTION` untuk kasus `OPEN_SEVERE_COMPLAINT`).

---

## Lampiran: Ringkasan Konstanta Sistem

```python
# Konstanta yang harus digunakan konsisten di seluruh modul
CHURN_DEFINITION_DAYS = 180          # Hari tanpa transaksi untuk dianggap Churn
PREDICTION_HORIZON_DAYS = 90         # Jendela prediksi ke depan
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
