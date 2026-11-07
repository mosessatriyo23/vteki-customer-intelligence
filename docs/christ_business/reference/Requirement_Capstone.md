TEMPLATE DOKUMEN KEBUTUHAN (REQUIREMENTS) | CP AI CUSTOMER INTELLIGENCE 

# **TEMPLATE DOKUMEN KEBUTUHAN (REQUIREMENTS)** 

_Platform AI Customer & Revenue Intelligence | Spesifikasi Bisnis, Lifecycle, Model AI, & Action Catalogue_ 

#### **PANDUAN PENGGUNAAN TEMPLATE:** 

1. Dokumen ini dirancang khusus berdasarkan draf requirment.docx tim serta diselaraskan secara presisi dengan spesifikasi standar FRD v1.0 (Functional Requirements Document) dan TRD v1.0 (Technical Requirements Document). 

_2. Bagian berpola [ISI_SENDIRI: ...] adalah kolom yang wajib Anda dan tim Anda isi/sesuaikan sesuai dengan keputusan bisnis kelompok._ 

3. Kotak Penjelasan & Panduan (Callout Box) di setiap bab memberikan instruksi langkah-demi-langkah dan contoh konkret untuk membimbing pengisian tim Anda. 

## **LEMBAR KONTROL & IDENTITAS BASELINE DOKUMEN** 

|**Nama Proyek / Topik**|Platform AI Customer & Revenue Intelligence|
|---|---|
|**Perusahaan Acuan**|PT Nusantara Beauty & Wellness (Bisnis Omnichannel<br>Sintetis, 20 Cabang)|
|**Versi Dokumen**|[ISI_SENDIRI: v0.5 (Draf Minggu 2) / v1.0 (Baseline<br>Dibekukan Minggu 4)]|
|**Tim Penyusun**|[ISI_SENDIRI: Nama Mahasiswa 1 (NIM), Nama<br>Mahasiswa 2 (NIM), Nama Mahasiswa 3 (NIM)]|
|**Dosen Pembimbing & Mentor**|[ISI_SENDIRI: Nama Dosen Pembimbing / Nama Mentor<br>V-TEKI]|
|**Klasifikasi Data & Batasan**|100% Data Sintetis (Hanya untuk keperluan akademik<br>Capstone Project UKDW)|



## **BAB 1: DEFINISI & KRITERIA CUSTOMER LIFECYCLE** 

#### **PANDUAN & PETUNJUK PENGISIAN BAB 1:** 

- Konteks FRD & TRD: Customer Lifecycle merupakan aturan bisnis berbasis aturan deklaratif (bukan hasil prediksi ML) yang mengelompokkan pelanggan ke dalam tahap perjalanan hubungan bisnis (FRD §6.5, TRD §9.1). 

- Cara Mengisi Tabel: Tentukan ambang transaksi (Recency/Frequency), akumulasi belanja (Monetary), dan status keanggotaan (Membership) untuk setiap tahap. 

Dokumen Capstone Project - Hanya Data Sintetis | UKDW & V-TEKI 

TEMPLATE DOKUMEN KEBUTUHAN (REQUIREMENTS) | CP AI CUSTOMER INTELLIGENCE 

_• Catatan Penting dari requirment.docx: Perpanjangan membership dihitung sebagai transaksi resmi dan pemasukan klinik. Pelanggan yang memperpanjang membership TIDAK BOLEH dikategorikan sebagai Churned!_ 

|**Tahap Lifecycle**|**Kriteria & Syarat Transaksi /**<br>**Membership**|**Panduan Logika Sistem (FRD/TRD**<br>**Alignment)**|
|---|---|---|
|**New (Pelanggan Baru)**|Akun / transaksi pertama dibuat <= 30<br>hari yang lalu DAN total riwayat<br>transaksi <= 2 kali.|Pelanggan baru tanpa riwayat transaksi<br>sebelumnya. Dikecualikan dari audiens<br>berbasis RFM kuintil.|
|**Active (Pelanggan Aktif)**|Transaksi >= 3  kali dalam 60 hari<br>terakhir ATAU memiliki membership<br>aktif yang digunakan dalam 60 hari<br>terakhir.|Pelanggan yang rutin belanja atau<br>menggunakan membership. Recency<br>sangat baru.|
|**Loyal (Pelanggan Setia)**|Transaksi >= 5 kali DAN akumulasi<br>belanja >= Rp 500..000 dalam 90 hari<br>terakhir (serta tenure >= 60 hari).|Pelanggan bernilai tinggi dengan<br>frekuensi dan monetary di atas kuintil<br>teratas.|
|**At Risk (Mulai Pasif)**|Tidak ada transaksi/kunjungan selama<br>91-180 hari terakhir DAN sisa<br>perpanjangan membership <= 30 hari.|Indikasi awal penurunan aktivitas.<br>Menjadi target prioritas tindakan<br>intervensi retensi.|
|**Dormant / Lapsed (Pasif)**|Tidak ada transaksi/kunjungan dalam<br>181-365 hari DAN perpanjangan<br>membership terlewat (1-60 hari).|Pelanggan telah melewati jendela aktif.<br>Memerlukan penawaran reaktivasi<br>khusus.|
|**Churned (Berpaling)**|Tidak ada transaksi/kunjungan > 365<br>hari DAN membership kadaluarsa > 180<br>hari.|Pelanggan dianggap hilang secara<br>bisnis. Pengubahan status dicatat di<br>histori lifecycle.|
|**Reactivated / Reclaimed**|Pelanggan sebelumnya berstatus<br>Dormant/Churned yang kembali<br>melakukan belanja >= 2x ATAU<br>memperpanjang membership.|Pelanggan berhasil ditarik kembali<br>melalui kampanye win-back atau<br>perpanjangan membership.|



## **BAB 2: DEFINISI CHURN, CLV, & MODEL PREDICTIVE AI** 

#### **PANDUAN PENGISIAN BAB 2 (PREDICTIVE AI MODELS):** 

1. Definisi Churn (FRD §6.6, TRD §9.3): Wajib disepakati di awal (misal: 90 hari tanpa transaksi & tanpa perpanjangan keanggotaan). Prediction horizon ditetapkan 90 hari ke depan, dengan masa berlaku skor (valid_until) selama 30 hari. 

2. Reason Codes (Keterjelasan AI): Setiap prediksi Churn/Propensity WAJIB menghasilkan minimal 3 kode alasan berbasis bahasa bisnis (misal: RECENCY_LONG = 'Tidak berkunjung selama 138 hari'). 

_3. Customer Lifetime Value / CLV (FRD §6.7, TRD §9.4): Dihitung dari Nilai Historis + Proyeksi Ke Depan 12 Bulan. CLV WAJIB dinyatakan sebagai PENDAPATAN KOTOR (Revenue), BUKAN PROFIT/MARGIN._ 

Dokumen Capstone Project - Hanya Data Sintetis | UKDW & V-TEKI 

TEMPLATE DOKUMEN KEBUTUHAN (REQUIREMENTS) | CP AI CUSTOMER INTELLIGENCE 

### **2.1 Spesifikasi Model Churn Prediction** 

- **Definisi Churn Disepakati:** Pelanggan aktif yang tidak melakukan transaksi DAN kunjungan selama 180 hari ke depan sejak prediction_date DAN tidak memperpanjang membership. 

- **Prediction Horizon & Validitas:** Jendela prediksi = 90 hari ke depan; Masa berlaku skor (valid_until) = 30 hari. 

- **Risk Band Cut-offs:** LOW (< 0.30), MEDIUM (0.30 - 0.60), HIGH (0.60 - 0.80), VERY_HIGH (>= 0.80). 

- **Persyaratan Reason Codes:** Minimal 3 kode alasan (contoh: RECENCY_LONG, SPEND_DECLINE, UNRESOLVED_COMPLAINT). 

### **2.2 Spesifikasi Perhitungan Customer Lifetime Value (CLV)** 

|**Kategori / Tier CLV**|**Ambang Batas Nilai CLV (IDR)**|**Aturan & Formula Perhitungan**<br>**(FRD/TRD)**|
|---|---|---|
|**Sangat Tinggi (Platinum / Gold)**|CLV >= Rp 1.000.000|Formula: CLV = Historical Spend (12m)<br>+ (Avg Txn Value * Freq/Mo * 12 *<br>Retention_Factor).|
|**Tinggi (Gold / Silver)**|Rp 500.000 <= CLV < Rp 1.000.000|Diprioritaskan untuk program retensi<br>proaktif dan insentif tingkat menengah.|
|**Sedang (Silver / Bronze)**|Rp 200.000 <= CLV < Rp 500.000|Mendapatkan penawaran standar<br>tanpa eskalasi insentif khusus.|
|**Rendah / Insufficient History**|CLV < Rp 200.000 atau Txn < 2x|Pelanggan baru/transaksi minim diberi<br>label INSUFFICIENT_HISTORY dan<br>dikecualikan dari filter tier.|



## **BAB 3: MATRIKS 5 MASUKAN KEPUTUSAN INDEPENDEN** 

#### **PRINSIP UTAMA DECISION INTELLIGENCE (FRD §9.6 / TRD §10.1):** 

'Skor tinggi bukan izin!' Sistem Keputusan (Next-Best-Action Engine) WAJIB mengevaluasi 5 masukan independen sebelum mengeksekusi penawaran. Jika salah satu masukan protektif gagal, sistem WAJIB memilih NO_ACTION. 

|**Masukan Keputusan**|**Pertanyaan Yang Dijawab**|**Aturan Penegakan Sesuai FRD/TRD**|
|---|---|---|
|**1. Predictive AI Scores**|Seberapa besar kemungkinan perilaku<br>ini terjadi?|Mengosongkan skor atau menggunakan<br>default jika skor kedaluwarsa<br>(valid_until terlewati).|
|**2. Business Eligibility Rules**|Apakah pelanggan memenuhi syarat<br>produk/program ini?|Memeriksa syarat tenure, status<br>keluhan aktif<br>(OPEN_SEVERE_COMPLAINT<br>memblokir promosi), dll.|
|**3. Customer Consent & Permission**|Apakah pelanggan mengizinkan kontak<br>pada kanal ini?|Mengevaluasi Opt-In/Opt-Out. Jika Opt-<br>Out = TRUE, sistem WAJIB memilih<br>NO_ACTION.|
|**4. Contact Policy / Frequency Cap**|Apakah kontak melampaui batas<br>frekuensi pemasaran?|Mengevaluasi batas kontak (misal max<br>2 kontak per 14 hari). Jika melampaui =|



Dokumen Capstone Project - Hanya Data Sintetis | UKDW & V-TEKI 

TEMPLATE DOKUMEN KEBUTUHAN (REQUIREMENTS) | CP AI CUSTOMER INTELLIGENCE 

|||FREQ_CAP_SUPPRESSED.|
|---|---|---|
|**5. Product Suitability & Availability**|Apakah produk tepat & tersedia untuk|Memeriksa ketersediaan stok<br>l|
||pelanggan ini?|produk/layanan serta flag kesesuaian<br>i|
|||non-sensitif (tanpa klaim medis).|



## **BAB 4: KATALOG AKSI (ACTION CATALOGUE) & ATURAN EKSEKUSI** 

#### **PANDUAN KATALOG AKSI (FRD §10.1, TRD §10.1):** 

Berikut adalah template Action Catalogue lengkap yang memuat 11 aksi utama dari draf requirment.docx dan dokumen FRD. Setiap aksi harus memiliki ID unik, Kategori, Syarat Pemicu, Kanal Terizin, dan Band Insentif. 

|**ID Aksi & Nama**|**Kategori**|**Syarat Pemicu & Aturan**<br>**Kelayakan (Eligibility)**|**Kanal & Band Insentif**|
|---|---|---|---|
|**1. NO_ACTION**|Proteksi / System|Diambil jika Consent = Opt-<br>Out, Frequency Cap tercapai,<br>atau<br>ALL_CANDIDATES_BLOCKED.|Tanpa Kanal / Tanpa Insentif|
|**2. COMPLAINT_RESOLUTION**|Layanan (Prioritas #1)|Keluhan aktif (status<br>OPEN_SEVERE). Menghentikan<br>seluruh pesan promosi<br>komersial sampai keluhan<br>tuntas.|Task RM / Branch / Tanpa<br>Insentif|
|**3.**<br>**RELATIONSHIP_MANAGER_CO**<br>**NTACT**|Retensi Khusus|Pelanggan CLV Sangat Tinggi<br>(>= Rp 1 Juta) dengan Churn<br>Risk HIGH/VERY_HIGH atau<br>keluhan aktif.|Task RM Cabang / Band<br>Rendah-Sedang|
|**4. RETENTION_OUTREACH**|Retensi|Pelanggan Churn Risk HIGH,<br>CLV Tinggi/Sangat Tinggi,<br>Segment At_Risk/Lapsed,<br>Consent Opt-In.|Email, Push / Diskon Berbatas<br>Waktu|
|**5. CROSS_SELL (Cross Category**<br>**Intro)**|Pertumbuhan|Segment Active/Loyal,<br>Propensity Purchase Tinggi,<br>Belum memiliki produk di<br>kategori bersebelahan.|Email, Push / Band Rendah<br>(Sample/Diskon)|
|**6. UPSELL (Membership**<br>**Upgrade)**|Pertumbuhan|Segment Active/Loyal, Tenure<br>>= 60 hari, Propensity<br>Renew/Upgrade Tinggi.|Email, Push / Band Sedang<br>(Voucher)|
|**7. RENEWAL_REMINDER**|Retensi / Keanggotaan|Sisa keanggotaan <= 15 hari,<br>belum diperpanjang,<br>Propensity Renew Tinggi.|Email, Push / Tanpa Insentif<br>atau Rendah|
|**8. SERVICE_REMINDER**|Layanan / Pengingat|Jadwal kunjungan/pembelian<br>produk habis pakai mendekati,<br>tanpa keluhan aktif.|Push, Email / Tanpa Insentif|
|**9. EDUCATION**|Edukasi Pelanggan|Pelanggan Baru (New), Churn<br>Risk Low, memberikan<br>panduan pemakaian|Email, Push / Tanpa Insentif|



Dokumen Capstone Project - Hanya Data Sintetis | UKDW & V-TEKI 

TEMPLATE DOKUMEN KEBUTUHAN (REQUIREMENTS) | CP AI CUSTOMER INTELLIGENCE 

|||produk/layanan.||
|---|---|---|---|
|**10. LOYALTY_REWARD**|Apresiasi|Segment Loyal, CLV<br>Tinggi/Sangat Tinggi, Freq<br>kontak belum tercapai.|Email, Push / Hadiah / Poin<br>Loyalitas|
|**11. WIN_BACK_OFFER**|Reaktivasi|Pelanggan Dormant/Lapsed<br>(91-180 hari pasif), CLV historis<br>Tinggi, belum ada tawaran<br>aktif.|Email, Push / Band Sedang<br>(Voucher Khusus)|



## **BAB 5: FORMULA EXPECTED VALUE & PEMERINGKATAN NBA** 

**FORMULA EXPECTED VALUE (EV) (FRD §10.3, TRD §10.2): Expected Value = Propensity * Expected_Revenue_Contribution * Action_Weight - Incentive_Cost_Estimate** 

- Propensity: Skor kecenderungan AI (0.0 - 1.0) untuk aksi tersebut. 

- Expected Revenue Contribution: Estimasi nilai transaksi pendapatan kotor dari penawaran. 

- Action Weight: Bobot prioritas strategi bisnis (misal: Retensi Churn diberi bobot lebih tinggi). 

- Incentive Cost Estimate: Estimasi nilai biaya insentif/diskon. 

_Aturan Ambang EV: Jika Expected Value kandidat aksi < min_ev_threshold, sistem memilih NO_ACTION._ 

Dokumen Capstone Project - Hanya Data Sintetis | UKDW & V-TEKI 

