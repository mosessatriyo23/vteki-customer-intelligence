# Kontrak Definisi Bisnis: Target & Standar Sistem
**Dokumen:** `target_definitions.md`
**Status:** v1.4 — REVISI / PENDING APPROVAL. **Belum APPROVED.** (v1.0 pernah berstatus APPROVED; sudah digantikan.)
**Penyusun:** Christ (Decisioning, Activation & Measurement Engineer)
**Disetujui oleh:** [PENDING — diisi hanya setelah Dosen Pembimbing / Mentor V-TEKI benar-benar menyetujui; tidak boleh diisi sendiri]
**Tanggal persetujuan:** [PENDING]
**Versi:** v1.4
**Tanggal:** v1.0 = 2026-10-28; v1.1 = 2026-11-07; v1.2 = 2026-11-09; v1.3 = 2026-11-18 (draf); v1.4 = 2026-11-19
**Klasifikasi:** 100% Data Sintetis — Hanya untuk keperluan akademik Capstone Project UKDW

---

> **TUJUAN DOKUMEN**
> Dokumen ini menetapkan definisi formal target bisnis sebagai kontrak antar modul.
> Modul ML (Moses) **wajib** mengacu ke sini saat membuat label; modul Decisioning (Christ) menerapkannya di NBA Engine & Policy.

> **ATURAN STATUS KEPUTUSAN (v1.4)**
> Draf v1.3 memuat tag "DISETUJUI v1.3" yang ditulis oleh penyusun sendiri. Itu **dicabut**: self-declared approval tidak menutup Gate A.
> Semua keputusan di bawah berstatus salah satu dari:
> - **USULAN** — keputusan penyusun, menunggu tanda tangan dosen/mentor + review Moses/James;
> - **PROVISIONAL** — angka/aturan placeholder kebijakan yang belum dikalibrasi dari data;
> - **PENDING** — butuh data atau konfirmasi pihak lain; tidak diisi dengan angka karangan.
> Tidak ada bagian dokumen ini yang APPROVED sampai kolom "Disetujui oleh" terisi.

---

## 1. Definisi Churn

> **Referensi:** `Requirement_Capstone.md` Bab 2 (FRD §6.6, TRD §9.3)

### 1.1 Definisi Churn (label target ML) — USULAN

Label churn adalah **outcome yang diamati SETELAH `prediction_date`**, bukan prediksi model.
Semua batas hari memakai kalender **WIB (UTC+7)**: sebuah event masuk ke hari berdasarkan tanggal WIB-nya.

| Komponen | Aturan |
|---|---|
| **Cohort aktif (eligible)** | Pelanggan dengan **minimal 1 churn negation event** dalam jendela (`prediction_date` − 365 hari, `prediction_date`] (batas kiri terbuka, batas kanan tertutup). Event yang tepat 365 hari sebelum `prediction_date` **tidak** dihitung. |
| **Jendela outcome** | (`prediction_date`, `prediction_date` + 90 hari]. `prediction_date` tidak termasuk; hari ke-90 termasuk. |
| **Churn = 1** | Cohort aktif DAN tidak ada churn negation event di jendela outcome. |
| **Churn = 0** | Cohort aktif DAN ada ≥ 1 churn negation event di jendela outcome. |
| **Label tidak lengkap** | Data belum mencakup `prediction_date` + 90 hari → label **null** (bukan 0). |
| **Bukan cohort** | Tidak punya negation event dalam 365 hari terakhir → tidak diberi label (bukan churn=1). Termasuk `NEVER_TRANSACTED`. |

**Churn negation events** (salah satu cukup):
1. Minimal 1 transaksi POS berstatus `COMPLETED` atau `PARTIAL_REFUND` (`CANCELLED`/`REFUNDED` tidak dihitung);
2. Kunjungan fisik terverifikasi (`customer_visits.csv`, status `COMPLETED`);
3. Perpanjangan keanggotaan (`membership_events.csv`, `event_type = RENEWAL`; dihitung transaksi resmi sesuai Requirement Bab 1).

> **Ketidaksesuaian yang ditemukan (v1.4) — kode ≠ dokumen v1.3:** v1.3 menulis bahwa definisi cohort "sinkron dengan implementasi `labels.py`". **Tidak benar.** `labels.py` menghitung `eligible` dari **transaksi saja** (`history = events`), sedangkan jendela outcome memakai ketiga jenis event. Akibatnya pelanggan yang dalam 365 hari terakhir hanya berkunjung/memperpanjang membership dikeluarkan dari cohort, padahal event yang sama dianggap membatalkan churn di jendela outcome.
> **Keputusan (USULAN):** cohort memakai **ketiga jenis event** (simetris dengan jendela outcome). Ini **berubah dari implementasi saat ini** → permintaan ke Moses: terbitkan versi label baru (`label_version` baru; `churn90` development lama tidak ditimpa). Sampai Moses mengimplementasikan dan Gate A disetujui, `training_ready=false` tetap berlaku.

> **Resolusi kontradiksi Requirement (180 vs 90 hari) — USULAN, BELUM DIKONFIRMASI DOSEN:**
> `Requirement_Capstone.md` Bab 2.1 menulis "180 hari ke depan" (Definisi Churn) dan "Jendela prediksi = 90 hari ke depan" (Prediction Horizon) dalam bab yang sama; panduan Bab 2 juga menyebut 90 hari.
> **Pembacaan yang diusulkan:** **90 hari** menentukan label ML. Alasan: (1) jendela prediksi dan jendela outcome label harus sama agar skor "risiko churn 90 hari" dapat dievaluasi terhadap label; (2) `labels.py` (`horizon_days=90`), `contracts/business_events.md`, dan Panduan Kerja memakai 90; (3) 180 hari tidak muncul di tempat lain pada Requirement; (4) angka 180 paling mungkin salah ketik/sisa draf lama (v1.0 memakai 180 hari arah mundur dari tanggal prediksi).
> **Status: PENDING konfirmasi tertulis dosen/mentor.** Draf permintaan konfirmasi ada di `docs/christ_business/approved/GATE_A_REVIEW_REQUEST_2026-11-19.md`. Jika dosen menetapkan 180: `horizon_days` di `labels.py` (saat ini menolak ≠ 90), konstanta `PREDICTION_HORIZON_DAYS`, `valid_until`, dan seluruh contoh di bawah harus direvisi sebagai versi baru; jangan ubah diam-diam.

**Contoh (cutoff `prediction_date` = 2026-10-01 WIB; jendela outcome berakhir 2026-12-30, karena 1 Okt + 90 hari = 30 Des):**

| Kasus | Data | Cohort? | Label |
|---|---|---|---|
| Positif (churn=1) | A: transaksi terakhir 2026-08-01; tidak ada transaksi/kunjungan/renewal pada 2026-10-02 s.d. 2026-12-30 **inklusif** | Ya | **1** |
| Negatif (churn=0) | B: transaksi terakhir 2026-08-01; renewal membership 2026-10-15 | Ya | **0** |
| Boundary kanan | C: satu-satunya event di jendela jatuh tepat 2026-12-30 (hari ke-90) | Ya | **0** |
| Boundary kanan +1 | D: event pertama di jendela baru 2026-12-31 (hari ke-91) | Ya | **1** |
| Boundary cohort | E: event terakhir sebelum cutoff tepat 2025-10-01 (365 hari sebelum) | **Tidak** (di luar jendela) | null |
| Boundary cohort dalam | F: event terakhir 2025-10-02 (364 hari sebelum) | Ya | tergantung outcome |
| Event di hari cutoff | G: event 2026-10-01 | masuk jendela cohort (≤ cutoff), **bukan** jendela outcome | — |
| Label tidak lengkap | H: data baru tersedia sampai 2026-12-15 | Ya | **null** |
| Hanya kunjungan | I: tak ada transaksi 365 hari, tetapi 1 kunjungan COMPLETED 2026-09-10 | Ya (usulan) — **Tidak** (implementasi lama) | beda antar versi |

Kasus tambahan dari pertanyaan C2 tim (`TEAM_FOLLOW_UP_ACTIONS` C2): pelanggan tanpa riwayat membership tetap masuk cohort bila punya transaksi/kunjungan; pelanggan identitas `PROVISIONAL`/`REVIEW_REQUIRED` **tidak dipakai** untuk label produksi sampai ada policy tertulis (lihat catatan ke James, §8).

### 1.2 Parameter Prediksi

| Parameter | Nilai |
|---|---|
| **Prediction Horizon** | 90 hari ke depan (PENDING konfirmasi dosen, §1.1) |
| **Masa Berlaku Skor (`valid_until`)** | 30 hari sejak skor diterbitkan |
| **Risk Band Cut-offs** | LOW (< 0.30) / MEDIUM (0.30–0.60) / HIGH (0.60–0.80) / VERY_HIGH (≥ 0.80) |

### 1.3 Persyaratan Reason Codes

Setiap prediksi churn **wajib** minimal **3 Reason Codes** berbahasa bisnis: `RECENCY_LONG`, `SPEND_DECLINE`, `FREQUENCY_DROP`, `MEMBERSHIP_EXPIRING` (≤ 30 hari), `UNRESOLVED_COMPLAINT`, `NO_CROSS_CATEGORY`.

---

## 2. Definisi Customer Lifetime Value (CLV)

> **Referensi:** `Requirement_Capstone.md` Bab 2 (FRD §6.7, TRD §9.4); implementasi referensi `services/data/models/business_clv.py`.

### 2.1 Formula

```
CLV = Historical_Spend_12m + (Avg_Txn_Value x Freq_Per_Month x 12 x Retention_Factor)
```

CLV adalah **pendapatan (revenue) yang diterima bisnis, bukan profit/margin** (Requirement Bab 2). "Kotor" di sini berarti sebelum biaya/margin; **bukan** berarti sebelum diskon (lihat 2.2).

### 2.2 Pemetaan field sumber → formula — USULAN

| Variabel | Definisi | Field sumber |
|---|---|---|
| Jendela | **Rolling 365 hari**: (`prediction_date` − 365 hari, `prediction_date`], tanggal WIB. Bukan tahun kalender (menghindari bias musiman; `prediction_date` bisa kapan saja). | `transactions.transaction_datetime` |
| Transaksi dihitung | Status `COMPLETED` dan `PARTIAL_REFUND` saja. `CANCELLED`, `REFUNDED`, `PENDING`, `FAILED` tidak dihitung (nilainya 0 / bukan transaksi). | `transactions.status` |
| Nilai per transaksi | `actual_revenue = net_amount − refund_amount`, dengan `net_amount = gross_amount − discount_amount` (diskon/voucher **sudah mengurangi** nilai; yang dihitung adalah uang yang benar-benar diterima). | `gross_amount`, `discount_amount`, `net_amount`, `refund_amount`, `actual_revenue` |
| `Historical_Spend_12m` | Σ `actual_revenue` transaksi dalam jendela | — |
| `Avg_Txn_Value` | `Historical_Spend_12m` ÷ jumlah transaksi dalam jendela | — |
| `Freq_Per_Month` | jumlah transaksi dalam jendela ÷ 12 (bukan ÷ jumlah bulan aktif) | — |
| Perpanjangan membership | Dihitung sebagai transaksi **hanya jika** nilainya tercatat di `transactions` (jangan dobel hitung dari `membership_events`). Jika tidak tercatat di `transactions`, tidak masuk CLV (PENDING konfirmasi James/Moses di data sumber). | `membership_events` (event saja, tanpa nilai) |
| Refund | Refund yang **sudah diketahui pada `prediction_date`** (`known_at ≤ prediction_date`) mengurangi nilai. Refund/koreksi yang baru tersedia setelahnya **tidak** mengubah CLV historis yang sudah diterbitkan (mengikuti kontrak James: late event tidak dihitung ulang di cutoff lama). | event `REFUND_RECORDED`/`CORRECTION` (James) |
| Pajak | Tidak ada field pajak di data sintetis; diasumsikan **tidak ada** (nilai = harga yang dibayar). PENDING bila data nyata punya pajak: pajak harus dikeluarkan. | — |
| Mata uang & pembulatan | IDR, bilangan bulat; CLV dihitung tanpa pembulatan perantara lalu dibulatkan ke rupiah terdekat di akhir. Nilai negatif tidak diperbolehkan (`business_clv.py` menolak). | — |
| Riwayat minimum | < 2 transaksi dalam jendela **atau** CLV < Rp 200.000 → `INSUFFICIENT_HISTORY` (pelanggan 1 transaksi diberi tier ini, tetap punya angka CLV). | — |

> Catatan perbaikan v1.4: teks v1.3 ("gunakan `gross_amount`; jika ada `net_amount` gunakan `net_amount`") ambigu dan bertentangan dengan dirinya sendiri; diganti definisi `actual_revenue` di atas yang sama dengan basis `clv90` development dan `labels.py`.

### 2.3 Retention Factor — USULAN (angka PENDING dari Moses)

- Nilai `0.7` (v1.0) **dicabut**, tidak boleh dipakai kembali.
- `1 − churn_score` / `1 − churn90` **dilarang** (memakai target prediksi sebagai input = leakage; `business_clv.py` mewajibkan retensi diberikan eksplisit).
- **Makna bisnis yang disetujui (USULAN):** `Retention_Factor` = proporsi **empiris** pelanggan di segmen lifecycle yang sama pada cutoff historis yang memiliki ≥ 1 churn negation event dalam **12 bulan ke depan**, yaitu (cutoff, cutoff + 365 hari].
- **Perubahan dari v1.3:** v1.3 menyebut "retensi 90-hari per segmen". Itu **tidak cocok**: proyeksi CLV adalah 12 bulan, sehingga retensi 90 hari yang dipakai pada proyeksi 12 bulan melebihkan nilai. Jika data sintetis tidak cukup panjang untuk jendela 365 hari, Moses harus melapor — **bukan** mengompound 90 hari secara diam-diam.
- Aturan estimasi (semantik; teknik oleh Moses): hanya cutoff dengan jendela outcome lengkap; per segmen lifecycle; sel dengan < 30 pelanggan → laporkan "tidak cukup data" dan CLV = null (bukan default); tidak memakai skor churn pelanggan itu sendiri; tabel diberi versi dan tanggal.
- **Status: PENDING Moses menyerahkan tabel.** CLV scoring tidak final sebelum tabel ada.

**Contoh numerik.** Pelanggan ACTIVE, 8 transaksi dalam 365 hari, Σ `actual_revenue` = Rp 1.200.000:
`Historical_Spend_12m` = 1.200.000; `Avg_Txn_Value` = 150.000; `Freq_Per_Month` = 8/12 = 0,6667. Karena `Avg × Freq × 12` = 1.200.000, bagian proyeksi = `Historical_Spend_12m × RF`, yaitu **CLV = 1.200.000 × (1 + RF)**.
- *Ilustrasi aritmetika saja (RF = 0,50 BUKAN nilai kebijakan):* CLV = 1.800.000 → `PLATINUM`.
- *Negatif:* 1 transaksi Rp 600.000 → `INSUFFICIENT_HISTORY` (txn < 2) walau CLV ≥ 200.000.
- *Boundary tier:* CLV tepat 1.000.000 → `PLATINUM`; 999.999 → `GOLD`; tepat 500.000 → `GOLD`; 499.999 → `SILVER`; tepat 200.000 → `SILVER`; 199.999 → `INSUFFICIENT_HISTORY`.
- *Boundary refund:* transaksi Rp 300.000 dengan refund parsial Rp 100.000 yang diketahui sebelum cutoff → kontribusi 200.000. Refund yang baru tercatat setelah cutoff → kontribusi tetap 300.000 pada skor cutoff itu.
- *Boundary jendela:* transaksi tepat 365 hari sebelum cutoff **tidak** dihitung; 364 hari dihitung.

### 2.4 Tiering CLV

| Tier | Ambang (IDR) | Label | Implikasi |
|---|---|---|---|
| Sangat Tinggi | CLV ≥ 1.000.000 | `PLATINUM` | Eligible `RELATIONSHIP_MANAGER_CONTACT`, insentif tertinggi |
| Tinggi | 500.000 ≤ CLV < 1.000.000 | `GOLD` | Retensi proaktif, insentif menengah |
| Sedang | 200.000 ≤ CLV < 500.000 | `SILVER` | Penawaran standar |
| Rendah / Riwayat Tidak Cukup | CLV < 200.000 atau transaksi < 2 | `INSUFFICIENT_HISTORY` | Dikecualikan dari filter tier |

> Requirement Bab 2.2 menulis nama tier ganda ("Platinum / Gold", "Gold / Silver", "Silver / Bronze"); pemetaan satu-label di atas adalah pembacaan penyusun dan ikut diminta konfirmasi dosen.

### 2.5 Peran nilai CLV

CLV adalah **skor input decisioning dan dasar tiering**, bukan target prediksi ML. `clv90` development tetap ada sebagai target teknis terpisah (tidak menggantikan CLV bisnis).

---

## 3. Matriks Siklus Pelanggan (Customer Lifecycle)

> **Referensi:** `Requirement_Capstone.md` Bab 1; implementasi `services/data/segmentation/snapshot.py::lifecycle()` (milik Moses, status PROPOSED).

Lifecycle bersifat **rule-based declarative**, bukan hasil ML. Perpanjangan membership dihitung sebagai transaksi resmi — pelanggan yang memperpanjang **tidak boleh** menjadi Churned.

| Tahap | Label | Syarat Requirement (Bab 1) |
|---|---|---|
| New | `NEW` | Akun/transaksi pertama ≤ 30 hari lalu DAN total transaksi ≤ 2 |
| Active | `ACTIVE` | Transaksi ≥ 3x dalam 60 hari ATAU membership aktif digunakan dalam 60 hari |
| Loyal | `LOYAL` | Transaksi ≥ 5x DAN belanja ≥ Rp 500.000 dalam 90 hari DAN tenure ≥ 60 hari |
| At Risk | `AT_RISK` | Tanpa transaksi/kunjungan 91–180 hari DAN sisa membership ≤ 30 hari |
| Dormant | `DORMANT` | Tanpa transaksi/kunjungan 181–365 hari DAN membership terlewat 1–60 hari |
| Churned | `CHURNED` | Tanpa transaksi/kunjungan > 365 hari DAN membership kedaluwarsa > 180 hari |
| Reactivated | `REACTIVATED` | Sebelumnya Dormant/Churned, kembali belanja ≥ 2x ATAU memperpanjang membership |
| Occasional | `OCCASIONAL` | Tidak ada di Requirement. Usulan implementasi: recency ≤ 90 hari dan transaksi 60 hari < 3 |
| Never Transacted | `NEVER_TRANSACTED` | Tidak ada di Requirement. Usulan implementasi: tenure > 30 hari dan belum pernah ada aktivitas |

### 3.1 Matriks Alokasi Perlakuan per Segmen — USULAN

Sumber: Requirement Bab 4 + keputusan v1.4. Tabel ini **dibaca langsung oleh `tests/decision/test_lifecycle_matrix.py`** dan harus sama dengan perilaku `evaluator.py`. Tidak ada lagi sel "Belum ditetapkan".

| Segmen | Aksi proaktif yang diizinkan | Catatan |
|---|---|---|
| `NEW` | `EDUCATION` (Churn Risk LOW) | |
| `ACTIVE` | `CROSS_SELL`, `UPSELL`, `SERVICE_REMINDER` | CROSS_SELL/UPSELL wajib propensity ≥ 0.6 (§3.2.C); SERVICE_REMINDER lihat §6 |
| `LOYAL` | `CROSS_SELL`, `UPSELL`, `LOYALTY_REWARD`, `SERVICE_REMINDER` | LOYALTY_REWARD: CLV GOLD/PLATINUM |
| `AT_RISK` | `RETENTION_OUTREACH` | Churn Risk HIGH atau VERY_HIGH, CLV GOLD/PLATINUM |
| `DORMANT` | `WIN_BACK_OFFER`, `RETENTION_OUTREACH` | WIN_BACK: CLV GOLD/PLATINUM, belum ada tawaran aktif |
| `CHURNED` | `NO_ACTION` | Tidak ada kontak komersial. Jalur win-back > 365 hari butuh keputusan terpisah |
| `REACTIVATED` | `NO_ACTION` | Masa tenang (cool-off): segmen ini hanya bertahan ≤ 30 hari (implementasi), sama dengan jendela atribusi win-back; mengirim aksi lain di jendela itu mencemari pengukuran dan menumpuk insentif. Setelah itu pelanggan diklasifikasi ulang ke ACTIVE/OCCASIONAL dan mengikuti aturan segmen itu |
| `OCCASIONAL` | `EDUCATION` (Churn Risk LOW) | Konten awareness tanpa insentif agar naik ke ACTIVE. Tidak eligible CROSS_SELL/UPSELL/insentif. PROVISIONAL: hentikan bila holdout tidak menunjukkan lift |
| `NEVER_TRANSACTED` | `NO_ACTION` | Lihat §3.2.B |
| *Lintas segmen* | `COMPLAINT_RESOLUTION` (keluhan OPEN_SEVERE aktif, prioritas #1); `RENEWAL_REMINDER` (sisa membership ≤ 15 hari); `RELATIONSHIP_MANAGER_CONTACT` (CLV PLATINUM + Churn Risk HIGH/VERY_HIGH) | **Tanpa** pembatasan lifecycle (§3.2.A) |

---

### 3.2 Keputusan kelengkapan lifecycle & rekonsiliasi katalog — USULAN

**A. `RELATIONSHIP_MANAGER_CONTACT` — pembatasan lifecycle.**
v1.3 dan teks katalog menulis "lifecycle AT_RISK/DORMANT" dan menyebut itu perilaku kode. **Salah**: `evaluator.py` tidak pernah memeriksa lifecycle untuk aksi ini. Requirement Bab 4 juga tidak membatasi lifecycle.
**Keputusan:** perilaku kode **disetujui** (tanpa batas lifecycle: PLATINUM + Churn Risk HIGH/VERY_HIGH). Alasan: pelanggan PLATINUM dengan risiko tinggi layak ditangani apa pun segmennya (mis. ACTIVE yang frekuensinya anjlok). Teks katalog diperbaiki. Pemicu "keluhan aktif" dari Requirement diwujudkan lewat `COMPLAINT_RESOLUTION` (kanal `task_rm`/`branch`, jalur suppression) — penyimpangan dari Bab 4 yang dicatat dan diminta konfirmasi dosen.
*Contoh:* positif — PLATINUM, VERY_HIGH, lifecycle ACTIVE → eligible. Negatif — GOLD, VERY_HIGH → tidak eligible (bukan PLATINUM). Boundary — PLATINUM, MEDIUM (skor 0,59) → tidak eligible.

**B. `OCCASIONAL` dan `NEVER_TRANSACTED`.**
- `OCCASIONAL`: **disetujui** sebagai segmen pelengkap (tanpa ini pelanggan recency ≤ 90 hari dengan < 3 transaksi/60 hari tidak punya segmen). Perlakuan: `EDUCATION` (kode `evaluator.py` diubah: `NEW` atau `OCCASIONAL`, Churn Risk LOW).
- `NEVER_TRANSACTED`: **disetujui sebagai label**, perlakuan NBA = **`NO_ACTION`**. v1.3 menetapkan `EDUCATION`, tetapi pelanggan ini dikeluarkan dari cohort ML sehingga tidak pernah punya skor churn; engine memakai skor default konservatif (propensity 0) dan akan selalu memilih `NO_ACTION`. Menulis EDUCATION di dokumen tidak dapat dipenuhi engine. Onboarding pelanggan tanpa transaksi, jika diinginkan, adalah alur non-skor terpisah yang butuh persetujuan sendiri (PENDING, di luar Gate A).
- *Contoh:* OCCASIONAL, recency 45 hari, 2 transaksi/60 hari, LOW → `EDUCATION` eligible. OCCASIONAL, MEDIUM → tidak. Boundary: 3 transaksi/60 hari → `ACTIVE`, bukan OCCASIONAL.

**C. Ambang propensity CROSS_SELL / UPSELL.**
v1.3: tidak ditegakkan karena "EV rendah akan kalah dari NO_ACTION secara alami". **Alasan itu salah**: CLV Rp 600.000, propensity 0,2 → pendapatan 180.000, EV = 0,2 × 180.000 × 1,2 − 25.000 = **Rp 18.200** (> Rp 1.000), jadi tetap terkirim.
**Keputusan:** Requirement menulis "Propensity Tinggi"; ditegakkan **propensity ≥ 0,6** (CROSS_SELL: `propensity_purchase`; UPSELL: `propensity_renew`). **PROVISIONAL** — 0,6 placeholder kebijakan, kalibrasi setelah ada data eksperimen. `RENEWAL_REMINDER` dan `LOYALTY_REWARD` **tanpa** ambang keras (non-insentif / diurutkan EV); ini penyimpangan dari teks "Propensity Renew tinggi" Bab 4 untuk RENEWAL_REMINDER, diminta konfirmasi dosen.
*Contoh:* 0,60 → eligible; 0,59 → tidak; 0,90 → eligible (boundary tertutup di 0,6).
Syarat CROSS_SELL "belum memiliki produk di kategori itu" **tidak ditegakkan** (tidak ada data kepemilikan kategori); katalog menandainya `[TIDAK DITEGAKKAN]` dan data dirutekan ke Moses.

**D. `RETENTION_OUTREACH` — band risiko.**
Requirement Bab 4: HIGH. **Keputusan:** HIGH **dan** VERY_HIGH (VERY_HIGH ≥ 0,80 jelas risiko lebih besar; mengecualikannya tidak masuk akal). Ini penyimpangan sengaja dari Bab 4; kode dan teks katalog sudah sama (teks katalog sebelumnya masih "HIGH" — diperbaiki). *Contoh:* HIGH → eligible; VERY_HIGH → eligible; MEDIUM (0,59) → tidak.

**E. Celah AT_RISK / DORMANT (syarat membership).**
Requirement menggabungkan recency dan membership; pelanggan yang memenuhi recency tetapi bukan syarat membership jatuh ke celah. **Keputusan:** **recency adalah kriteria utama**; syarat membership tidak memblokir (sesuai `snapshot.py`). *Contoh:* recency 120 hari, sisa membership 45 hari → `AT_RISK`; recency 120, non-member → `AT_RISK`; recency 181 hari → `DORMANT` (boundary: 180 → AT_RISK, 181 → DORMANT; 90 → bukan AT_RISK, 91 → AT_RISK).

**F. Kontradiksi jendela WIN_BACK.**
Bab 1: Dormant = 181–365; Bab 4: WIN_BACK "91–180 hari". **Keputusan:** Bab 1 berlaku (definisi lifecycle primer); "91–180" di Bab 4 dianggap salah ketik. `WIN_BACK_OFFER` hanya untuk `DORMANT`. Ini keputusan penyusun yang **diminta konfirmasi dosen** (bukan sekadar "error copywriting"). *Contoh:* recency 200 hari, GOLD, tanpa tawaran aktif → eligible; recency 150 hari (AT_RISK) → tidak (gunakan RETENTION_OUTREACH); boundary 181 hari → eligible.

**G. Temuan konformansi implementasi `snapshot.py` → diserahkan ke Moses (bukan wewenang Christ mengubah kode):**
1. **Celah `UNCLASSIFIED`:** recency > 365 hari tanpa data kedaluwarsa membership > 180 hari (termasuk **non-member**) menjadi `UNCLASSIFIED`, bukan CHURNED. **Keputusan bisnis:** `CHURNED` = recency > 365 hari DAN (tidak punya riwayat membership ATAU membership kedaluwarsa > 180 hari). Pelanggan recency > 365 yang membership-nya masih berlaku atau kedaluwarsa ≤ 180 hari = `DORMANT` (rentang DORMANT diperluas melewati 365 hari). Tidak ada segmen `UNCLASSIFIED` yang boleh keluar dari snapshot.
2. **NEW:** kode hanya memeriksa tenure ≤ 30 hari; Requirement juga mensyaratkan total transaksi ≤ 2. Tenure 20 hari dengan 4 transaksi → `ACTIVE` (bukan NEW).
3. **REACTIVATED:** kode = 1 pembelian dalam 30 hari terakhir setelah jeda > 180 hari antar-pembelian (hanya transaksi); Requirement = ≥ 2 belanja ATAU renewal setelah Dormant/Churned. **Keputusan:** definisi Requirement berlaku; selisih ini harus diselaraskan Moses atau diterima tertulis oleh dosen.
4. **Prioritas klasifikasi (USULAN):** `REACTIVATED` > `LOYAL` > `NEW` > `NEVER_TRANSACTED` > `CHURNED` > `DORMANT` > `AT_RISK` > `ACTIVE` > `OCCASIONAL`.

---

## 4. Aturan Kebijakan (Fatigue & Suppression)

> **Referensi:** `Requirement_Capstone.md` Bab 3 (FRD §9.6, TRD §10.1)

### 4.1 Fatigue (Contact Frequency Cap)

| Parameter | Nilai |
|---|---|
| Batas | **2 kontak pemasaran / 14 hari / pelanggan** (rolling, mundur dari tanggal eksekusi) |
| Terlampaui | `FREQ_CAP_SUPPRESSED`; seluruh aksi komersial diblokir → `NO_ACTION` |
| Tidak dihitung | `COMPLAINT_RESOLUTION` dan `SERVICE_REMINDER` (non-komersial) |

### 4.2 Suppression mutlak

| Kondisi | Status | Konsekuensi |
|---|---|---|
| **Global opt-out** (`is_global_opt_out = true`, atau status global `OPT_OUT`) | `OPT_OUT_SUPPRESSED` | `NO_ACTION` untuk semua aksi, tanpa pengecualian |
| Tiket keluhan **`OPEN_SEVERE_COMPLAINT`** aktif | `COMPLAINT_SUPPRESSED` (`EXCL_OPEN_SEVERE_COMPLAINT`) | Semua promosi diblokir; hanya `COMPLAINT_RESOLUTION` |

Penempatan pada 5 masukan: keluhan = masukan 2; consent = masukan 3; frequency cap = masukan 4.

### 4.3 Cakupan opt-out — KEPUTUSAN (USULAN)

**Model: channel-level + global hard stop.** Menggantikan teks lama "opt-out pada kanal manapun memblokir penuh" (yang bertentangan dengan keputusan v1.3 dan implementasi K-10).

1. **Global opt-out** → blokir **semua** kontak komersial dan non-komersial ber-kanal pelanggan (`OPT_OUT_SUPPRESSED`). Termasuk saat ada keluhan aktif: kontak ke pelanggan tetap diblokir; penanganan keluhan berjalan sebagai tugas internal oleh tim, bukan pesan ke pelanggan (disimpan di luar NBA).
2. **Opt-out satu kanal** → hanya kanal itu diblokir, untuk **semua** aksi. Aksi tetap eligible bila masih ada ≥ 1 kanalnya yang diizinkan.
3. Status `UNKNOWN`, `EXPIRED`, `BLOCKED`, `valid_until` terlewat, atau kanal tak tercantum = **BLOCKED** (K-10 `from_k10`).
4. Setelah merge identitas: **status paling restriktif menang** (K-10 `most_restrictive_wins`).
5. **Kanal internal** (`task_rm`, `branch`) tidak diatur consent pemasaran, **kecuali** `RELATIONSHIP_MANAGER_CONTACT`: karena itu kontak komersial ke pelanggan, membuat task internal saja tidak cukup — wajib consent kanal `phone`. (Celah ini ditemukan di v1.4: sebelumnya aksi ini lolos untuk pelanggan yang opt-out dari semua kanal non-global.) Kode: `CONSENT_GATED_CHANNELS` di `evaluator.py`, dipakai `engine.py`.

*Contoh:* **Positif:** A `is_global_opt_out=true` → semua aksi `NO_ACTION`. **Negatif:** B `email_opt_out`, `push_opt_in` → `RETENTION_OUTREACH` (email,push) tetap eligible lewat push. **Boundary:** C email & push opt-out, global false → `RETENTION_OUTREACH` tidak eligible; `RELATIONSHIP_MANAGER_CONTACT` eligible **hanya jika** `phone_opt_in = true`; D status email `EXPIRED` → diperlakukan blocked.

Pertanyaan C5 tim yang masih terbuka dan **tidak** diputuskan di sini: sumber/timestamp/expiry/audit perubahan consent dan definisi persis "kontak yang dihitung" (apakah kontak tersimulasi dihitung?) — perlu producer data consent (James) dan dosen.

> **ATURAN TEGAS:** suppression mutlak; tidak ada skor AI, CLV, atau urgensi yang meng-override. Tidak ada outbound nyata selama fase akademik.

---

## Lampiran: Konstanta Sistem

```python
PREDICTION_HORIZON_DAYS = 90         # PENDING konfirmasi dosen (§1.1)
SCORE_VALIDITY_DAYS = 30
FREQ_CAP_MAX_CONTACTS = 2
FREQ_CAP_WINDOW_DAYS = 14
MIN_REASON_CODES = 3
COHORT_LOOKBACK_DAYS = 365           # (cutoff-365d, cutoff]
CLV_WINDOW_DAYS = 365

CLV_TIER_PLATINUM = 1_000_000
CLV_TIER_GOLD = 500_000
CLV_TIER_SILVER = 200_000

LIFECYCLE_NEW_WINDOW = 30
LIFECYCLE_ACTIVE_WINDOW = 60
LIFECYCLE_AT_RISK_START = 91
LIFECYCLE_AT_RISK_END = 180
LIFECYCLE_DORMANT_START = 181
LIFECYCLE_DORMANT_END = 365          # DORMANT melewati 365 hari bila syarat CHURNED membership tidak terpenuhi (§3.2.G.1)
LIFECYCLE_CHURNED_THRESHOLD = 365
MEMBERSHIP_CHURN_THRESHOLD = 180

# Keputusan tim / penyusun -- bukan dari Requirement_Capstone
MIN_EV_THRESHOLD_IDR = 1000.0
MAX_DISCOUNT_PERCENT = 30.0
SERVICE_REMINDER_WINDOW_DAYS = 7
SERVICE_REMINDER_OVERDUE_FLOOR_DAYS = -14   # PROVISIONAL
PROPENSITY_HIGH_THRESHOLD = 0.6             # PROVISIONAL
CONTROL_HOLDOUT_RATIO = 0.10
```

---

## 5. Parameter Expected Value (EV)

> Formula (Requirement Bab 5): `EV = Propensity × Expected_Revenue_Contribution × Action_Weight − Incentive_Cost`. EV < `min_ev_threshold` → `NO_ACTION`.

### 5.1 Threshold & pagu — keputusan tim v1.2, DIRATIFIKASI sebagai USULAN

| Parameter | Nilai |
|---|---|
| `min_ev_threshold` | **Rp 1.000** (`EV < 1.000` → `NO_ACTION`, alasan `BELOW_MIN_EV`; EV tepat 1.000,00 lolos; 999,99 tidak) |
| Pagu diskon global | **30%** pada teks pesan |
| Pagu per band | NONE 0% · LOW ≤ 10% · MEDIUM ≤ 20% · HIGH ≤ 30% (melebihi → `MESSAGE_BLOCKED_BY_GUARDRAIL` + `INCENTIVE_ESCALATED` ke Business Approver); band DISCOUNT_LIMITED & LOYALTY_POINTS memakai pagu global |

### 5.2 Bobot, faktor pendapatan, biaya insentif — status **PROVISIONAL**

Angka berikut adalah **placeholder rekayasa yang mewakili kebijakan**, bukan angka Requirement dan **bukan hasil kalibrasi**. Disetujui hanya sebagai urutan prioritas relatif pada data sintetis; **tidak boleh dipakai sebagai klaim nilai bisnis**.

| Aksi | Weight | Faktor pendapatan | Band insentif |
|---|---|---|---|
| `COMPLAINT_RESOLUTION` | 2.0 | 0.00 | Tanpa |
| `RELATIONSHIP_MANAGER_CONTACT` | 1.8 | 0.60 | MEDIUM |
| `RETENTION_OUTREACH` | 1.6 | 0.50 | DISCOUNT_LIMITED |
| `WIN_BACK_OFFER` | 1.5 | 0.40 | MEDIUM |
| `RENEWAL_REMINDER` | 1.5 | 0.25 | Tanpa |
| `UPSELL` | 1.4 | 0.35 | MEDIUM |
| `LOYALTY_REWARD` | 1.3 | 0.20 | LOYALTY_POINTS |
| `CROSS_SELL` | 1.2 | 0.30 | LOW |
| `SERVICE_REMINDER` | 1.0 | 0.10 | Tanpa |
| `EDUCATION` | 0.8 | 0.15 | Tanpa |

| Band | % CLV | Cap IDR |
|---|---|---|
| LOW | 5% | 25.000 |
| MEDIUM | 10% | 75.000 |
| HIGH | 15% | 150.000 (tidak dipakai aksi katalog mana pun saat ini) |
| DISCOUNT_LIMITED | 8% | 50.000 |
| LOYALTY_POINTS | 5% | 30.000 |

**Contoh kerja (CLV Rp 600.000):** `RETENTION_OUTREACH`, churn 0,7 → pendapatan 0,5 × 600.000 = 300.000; EV = 0,7 × 300.000 × 1,6 − 48.000 = **Rp 288.000** (biaya 8% = 48.000 < cap). `CROSS_SELL`, propensity 0,8 → 180.000; EV = 0,8 × 180.000 × 1,2 − 25.000 (5% = 30.000 → cap) = **Rp 147.800**. Boundary: EV 999,99 → `NO_ACTION`; 1.000,00 → eligible.

**Keterbatasan yang diakui (harus ditinjau dosen):**
1. Untuk aksi retensi, "propensity" = skor churn (peluang pendapatan **terancam**), bukan peluang tawaran dikonversi. Aksi ber-risiko tinggi otomatis mendapat EV tinggi tanpa bukti bahwa aksi itu efektif; hanya eksperimen holdout yang dapat menunjukkan efeknya.
2. Faktor pendapatan dikalikan CLV **total**, yang memuat belanja historis 12 bulan — bukan hanya proyeksi ke depan — sehingga melebihkan kontribusi.
3. Revisi wajib bila hasil eksperimen menyimpang > 20% dari faktor ini.

---

## 6. Data Contract SERVICE_REMINDER

### 6.1 Kebijakan — dikonfirmasi sebagai kebijakan tim (USULAN)

Pengingat jadwal kunjungan/pembelian ulang produk habis pakai; non-komersial, tanpa insentif; **fail-closed** (data tidak ada → tidak eligible). Eligible hanya jika: lifecycle `ACTIVE`/`LOYAL`; `days_until_replenishment` dalam rentang **−14 s.d. +7 hari**; tanpa keluhan aktif; consent push/email. Pembatasan ACTIVE/LOYAL dan ambang 7 hari adalah keputusan tim, **bukan** Requirement Bab 4 (yang tidak membatasi lifecycle).
**Tambahan v1.4:** batas bawah −14 hari (PROVISIONAL). Sebelumnya semua nilai negatif eligible tanpa batas — pelanggan yang terlambat 200 hari tetap dapat "pengingat". *Contoh:* +7 → eligible; +8 → tidak; −14 → eligible; −15 → tidak; `None` → tidak.

### 6.2 Makna bisnis field

| Field | Makna | Sumber |
|---|---|---|
| `last_purchase_date` | Tanggal pembelian **terakhir pada kategori replenishment-eligible** yang sama dengan siklus yang dihitung (per kategori). Bukan tanggal kunjungan/perpanjangan membership/pembelian kategori lain | `transactions` terfilter kategori |
| `replenishment_cycle_days` | Rata-rata hari pemakaian satu pembelian pada kategori itu (**per kategori**, bukan per SKU/pelanggan) | tabel lookup |
| `days_until_replenishment` | `last_purchase_date + replenishment_cycle_days − tanggal eksekusi (WIB)`; ≤ 0 = sudah jatuh tempo | `EligibilityProfile` |

**Kategori:** kandidat awal (perawatan kulit, rambut, suplemen/vitamin, layanan salon rutin). **Daftar final dan nilai siklus belum ada** — penyusun tidak mengarang angka. Jika pelanggan punya beberapa kategori: pakai kategori dengan `days_until_replenishment` terkecil yang masih ≥ −14 (USULAN).

### 6.3 Routing data ke Moses (belum ada di data sintetis)
1. daftar `product_category` replenishment-eligible; 2. tabel `replenishment_cycle_days` per kategori beserta cara menurunkannya dari data; 3. penurunan `last_purchase_date` per kategori. **Sampai ada, `days_until_replenishment = None` dan `SERVICE_REMINDER` selalu tidak eligible.**

---

## 7. Kontrak Outcome / KPI (Gate A)

Implementasi referensi: `services/decision/measurement/uplift.py`, `attribution/touchpoint.py`, `campaign/holdout.py`, kontrak K-08/K-09. **Uplift pada data sintetis hanya memvalidasi pipeline teknis; bukan bukti kausal bisnis dan bukan dasar persetujuan.**

### 7.1 Event konversi per aksi (tipe K-09)

| Aksi | Event konversi | Tipe K-09 |
|---|---|---|
| `RETENTION_OUTREACH`, `RM_CONTACT`, `LOYALTY_REWARD`, `EDUCATION`, `SERVICE_REMINDER` | Transaksi POS `COMPLETED`/`PARTIAL_REFUND` setelah paparan | `PURCHASE` |
| `WIN_BACK_OFFER` | Transaksi pertama setelah paparan pada pelanggan DORMANT | `PURCHASE` |
| `RENEWAL_REMINDER` | `membership_events.event_type = RENEWAL` | `MEMBERSHIP_RENEWAL` |
| `UPSELL` | Perpanjangan/upgrade ke tier lebih tinggi | `UPGRADE` — butuh data tier membership (PENDING) |
| `CROSS_SELL` | Transaksi pertama di kategori yang belum dimiliki | `PURCHASE` — butuh data kategori (PENDING) |
| `COMPLAINT_RESOLUTION` | Tiket ditutup — **hasil layanan, bukan konversi pendapatan** | tidak diukur dengan uplift |
| (`BOOKING`) | **Tidak diaktifkan**: tidak ada event booking nyata | — |

**Jendela konversi:** default implementasi `conversion_window_days = 30` dan `adjustment_window_days = 14` (K-09). Angka per aksi di v1.3 (15/60/14/7 hari) tidak punya sumber bisnis → **ditarik**. Pilihan bisnis per aksi **PENDING** (pemilik: Christ + dosen); usulan logis: RENEWAL_REMINDER ≤ 15 hari agar tidak melewati kedaluwarsa.

### 7.2 Treatment, control, kontaminasi
- Eligible = lolos 5 gerbang + fatigue **sebelum** pengacakan. Holdout (default 10%, `random_seed` wajib, hash SHA-256) diambil dari yang eligible; control = eligible tetapi ditahan.
- **Analisis intent-to-treat:** treatment = semua yang ditugaskan, termasuk yang pesannya tidak terkirim; control tetap control walau tersentuh.
- **Kontaminasi** (control tersentuh kampanye lain; treatment dalam dua kampanye; datang ke toko tanpa pesan): dicatat sebagai flag (konflik atribusi), tetap dianalisis ITT, plus analisis sensitivitas tanpa yang terkontaminasi. Tidak dapat dicegah di lingkungan sintetis.
- **Pengecualian holdout (kebijakan):** `COMPLAINT_RESOLUTION` dan aksi protektif **tidak boleh** ditahan sebagai control. Belum ditegakkan di `holdout.py` → butir kerja Christ berikutnya.
- Jendela observasi sama untuk treatment & control: [mulai paparan, akhir paparan + jendela konversi].

### 7.3 Atribusi, refund, finalisasi, observed vs incremental
| Hal | Aturan |
|---|---|
| Atribusi | Last-touch dalam jendela konversi; konflik multi-kampanye diberi flag. **Atribusi ≠ inkrementalitas** (`is_incremental` individu selalu null) |
| Basis pendapatan | Default `REFUND_ADJUSTED` = `net_amount` dikurangi refund yang terjadi ≤ 14 hari sejak transaksi; refund > 14 hari diabaikan (K-09 `NET_FINALIZED`). **Berbeda dari basis CLV** (§2.2, refund yang diketahui pada cutoff) — disengaja, dan keduanya harus disebut eksplisit di setiap laporan |
| Finalisasi | Hasil `PROVISIONAL` sampai tanggal akhir paparan + jendela konversi + 14 hari; baru `FINAL` setelahnya |
| Observed | Hasil apa adanya pada treatment (termasuk pembelian yang akan terjadi tanpa kampanye) — tidak boleh disajikan sebagai dampak |
| Incremental | `Rev_T − Rev_C × (N_T / N_C)` dan `Conv_T − Conv_C × (N_T / N_C)` — satu-satunya angka yang boleh diklaim sebagai efek kampanye |

(v1.3 menulis "refund dikurangi setelah adjustment window" — ambigu dan salah terhadap kode; diganti di atas.)

### 7.4 Kriteria keberhasilan
Persentase ambang v1.3 (15%/10%/8%/20%) tidak punya sumber bisnis → **ditarik, bukan dipakai ulang**. Aturan keputusan (USULAN), semuanya wajib:
1. hasil berstatus `FINAL`;
2. lift konversi absolut > 0 dan **batas bawah CI 95% > 0** (`uplift.py`);
3. pendapatan inkremental per pelanggan treatment **>** biaya insentif per pelanggan treatment;
4. jumlah minimum pelanggan/konversi per kelompok dan *minimum meaningful lift*: **PENDING pilihan bisnis** (Christ + dosen; tidak diisi angka karangan).

| Contoh (angka ilustrasi) | Treatment | Control | Lift | CI 95% | Hasil |
|---|---|---|---|---|---|
| Positif | 180/900 (20%) | 10/100 (10%) | +10 pp | (+3,6; +16,4) pp | **Lolos** kriteria 2 |
| Negatif | 90/900 (10%) | 11/100 (11%) | −1 pp | (−7,4; +5,4) pp | Gagal |
| Boundary (titik estimasi positif tapi CI memuat 0) | 126/900 (14%) | 9/100 (9%) | +5 pp | (−1,0; +11,0) pp | **Tidak meyakinkan = bukan sukses** |
| Boundary eksak | batas bawah CI tepat 0,0 | | | | **Gagal** (harus > 0 secara ketat) |

Karena holdout 10% kecil, CI lebar; angka di atas menunjukkan alasan ambang minimum harus ditentukan.

### 7.5 Yang belum dapat diputuskan
| Item | Status | Routing |
|---|---|---|
| Tabel Retention Factor 12 bulan per segmen | PENDING | Moses |
| Jendela konversi per aksi, minimum lift, ukuran sampel minimum | PENDING pilihan bisnis | Christ + dosen |
| `replenishment_cycle_days` per kategori | PENDING data | Moses |
| Data kategori dimiliki (CROSS_SELL) dan tier membership (UPSELL) | PENDING data | Moses/James |
| Producer/consumer + acceptance test K-09 | PENDING | Christ (consumer), James (producer) |
| Booking | Tidak diaktifkan | — |

---

## 8. Status Gate A, penerimaan, dan routing

**Belum dapat ditutup.** Syarat yang masih menggantung:
- Konfirmasi dosen: 180 vs 90 hari (§1.1); penyimpangan dari Bab 4 (§3.2.A, C, D, F); pemetaan nama tier (§2.4).
- Persetujuan formal dokumen ini: **Disetujui oleh [PENDING] · Tanggal [PENDING]**.
- Review Moses (cohort, tabel retensi, konformansi `snapshot.py` §3.2.G, data replenishment) dan James (makna bisnis refund/koreksi/ketersediaan).
Rincian permintaan: `GATE_A_REVIEW_REQUEST_2026-11-19.md`.

---

## Riwayat Revisi

| Versi | Tanggal | Perubahan |
|---|---|---|
| v1.0 | 2026-10-28 | Versi awal (APPROVED). |
| v1.1 | 2026-11-07 | Churn → 90 hari ke depan + 3 negation events; Retention_Factor 0.7 dicabut; label `OCCASIONAL`/`NEVER_TRANSACTED` (usulan); matriks §3.1; reason code suppression; konstanta `CHURN_DEFINITION_DAYS = 180` dihapus. |
| v1.2 | 2026-11-09 | Keputusan tim: `min_ev_threshold` Rp 1.000; pagu diskon 30% + per band; kata terlarang; aturan SERVICE_REMINDER; K-08 holdout. |
| v1.3 | 2026-11-18 | **Draf, tidak punya baris changelog saat ditemukan; dicatat di sini.** Menambah Item 1–7 dan §7 KPI dengan tag "DISETUJUI v1.3" (self-declared). Ditemukan v1.4: beberapa klaim tidak sesuai kode (cohort, RM_CONTACT lifecycle, propensity, OCCASIONAL/NEVER_TRANSACTED/REACTIVATED) dan 5 tes `test_lifecycle_matrix` gagal. |
| v1.4 | 2026-11-19 | (1) Tag "DISETUJUI" dicabut → USULAN/PROVISIONAL/PENDING; approver/tanggal tetap PENDING. (2) §1.1 cohort 3 event (berubah dari `labels.py`), contoh boundary, WIB, 180 vs 90 tetap PENDING dosen. (3) §2 pemetaan `actual_revenue`, Retention Factor = retensi empiris 12 bulan per segmen (bukan 90 hari), contoh. (4) §3 matriks lengkap tanpa "belum ditetapkan"; OCCASIONAL→EDUCATION; NEVER_TRANSACTED/CHURNED/REACTIVATED→NO_ACTION; RM_CONTACT tanpa batas lifecycle; ambang propensity 0,6 ditegakkan; temuan `snapshot.py` ke Moses. (5) §4.3 consent channel-level + global; `RELATIONSHIP_MANAGER_CONTACT` wajib consent `phone`. (6) §5 parameter EV = PROVISIONAL + keterbatasan. (7) §6 batas bawah −14 hari. (8) §7 ambang KPI v1.3 ditarik; aturan CI; pengecualian holdout. Kode: `evaluator.py`, `catalogue.py`, `engine.py`; tes diperbarui. Overflow `scores_are_valid()` sudah diperbaiki sebelumnya (diverifikasi). |
