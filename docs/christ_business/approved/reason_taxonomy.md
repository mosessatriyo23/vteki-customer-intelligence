# Taxonomy Alasan Churn (Reason Codes) dan Teks Indonesia

**Dokumen:** `reason_taxonomy.md` · **Versi taxonomy:** `christ-reason-taxonomy-1.5-draft`
**Penyusun:** Christ (Orang 2) · **Tanggal:** 26 November 2026
**Status:** **FINAL dari sisi Christ** (ditetapkan 26 Nov atas instruksi Christ, mengikuti keputusan percepatan Moses di #70/#71). **Persetujuan mentor/dosen: [PENDING]**; tidak diisi sendiri, mengikuti Gate A `target_definitions.md`.
**Menggantikan:** `target_definitions.md` v1.4 §1.3 (daftar 6 kode bisnis). §1.3 sekarang menunjuk ke dokumen ini.
**Menjawab:** update Moses, to-do Christ #2 "Finalkan taxonomy alasan beserta teks Indonesianya" dan P7.

---

## 1. Prinsip

1. **Alasan = arah pengaruh fitur pada skor model**, bukan sebab bisnis atau perilaku pelanggan. Dasarnya dekomposisi log-odds model logistik yang diverifikasi faithful (`churn_reasons.py`). Teks tidak boleh menyiratkan sebab ("karena pelanggan kecewa") atau menyebut angka kontribusi.
2. **Hanya alasan yang didukung fitur yang benar-benar diukur dan diobservasi.** Fitur yang di-impute tidak pernah tampil sebagai fakta (tetap diperlakukan sebagai `excluded_imputed`).
3. **Satu konsep = satu alasan.** Beberapa jendela waktu dari konsep yang sama digabung (§4).
4. **Tidak ada alasan palsu.** Bila alasan yang tersedia kurang dari tiga, tampilkan yang ada (§6). Tidak ada pengisian, duplikasi, atau alasan cadangan demi memenuhi angka tiga.
5. **Internal, bukan untuk pelanggan.** Kalimat dibaca staf (analis, marketer, RM). Tidak dikirim ke pelanggan dan tidak memuat data pribadi.
6. **Satu sumber taxonomy.** Kode konsep, pemetaan fitur, dan teks di bawah adalah satu-satunya sumber; UI dan formatter tidak membuat teks sendiri.

## 2. Konsep aktif (dapat dikeluarkan sekarang)

Model churn saat ini hanya punya 7 fitur (`churn_reasons.REASON_CODES`). Maka hanya empat konsep yang punya dasar data:

| Kode konsep | Makna | Fitur model (kode producer saat ini) | Setara nama v1.4 |
|---|---|---|---|
| `RECENCY` | Jarak waktu sejak aktivitas terakhir (transaksi, kunjungan selesai, atau renewal) | `recency_days` (`PURCHASE_RECENCY`) | `RECENCY_LONG` |
| `FREQUENCY` | Frekuensi pembelian dalam jendela 60/90/365 hari | `purchase_count_60d`, `purchase_count_90d`, `purchase_count_365d` (`PURCHASE_FREQUENCY_60D/90D/365D`) | `FREQUENCY_DROP` |
| `SPEND` | Pendapatan yang dipertahankan dalam jendela 90/365 hari | `retained_revenue_90d`, `retained_revenue_365d` (`RETAINED_REVENUE_90D/365D`) | `SPEND_DECLINE` |
| `TENURE` | Lama pelanggan tercatat | `tenure_days` (`TENURE`) | (baru, tidak ada di v1.4) |

Catatan nama: `recency_days` di data dihitung dari **aktivitas** terakhir (`segmentation/snapshot.py`: transaksi, kunjungan berstatus `COMPLETED`, renewal), bukan hanya pembelian. Kode producer `PURCHASE_RECENCY` karenanya sedikit menyesatkan; di taxonomy ini maknanya "aktivitas". Mohon Moses mengganti namanya pada versi mapping berikutnya (tidak mengubah kode historis diam-diam).

## 3. Konsep tidak aktif (dilarang dikeluarkan)

| Kode konsep | Alasan tidak aktif | Syarat untuk mengaktifkan |
|---|---|---|
| `MEMBERSHIP_EXPIRING` | Tidak ada fitur kedaluwarsa membership di model | Fitur ada di model + provenance `known_at/effective_at` dari feed James + review Moses |
| `UNRESOLVED_COMPLAINT` | Tidak ada fitur keluhan | Sama |
| `NO_CROSS_CATEGORY` | Tidak ada fitur lintas kategori | Sama |

Produser yang mengeluarkan kode ini sebelum syaratnya terpenuhi melanggar taxonomy. Menambah konsep baru berarti menaikkan versi taxonomy dan meminta persetujuan Christ (+ mentor).

## 4. Penggabungan fitur menjadi konsep

Model logistik bersifat aditif, sehingga kontribusi konsep = **jumlah** kontribusi log-odds fitur anggotanya yang **diobservasi** (bukan di-impute):

- `kontribusi(konsep) = Σ log_odds_contribution(fitur anggota, non-imputed)`.
- **Arah** = tanda jumlah: positif → `INCREASES_RISK`, negatif → `DECREASES_RISK`.
- Konsep **muncul** bila `|jumlah| ≥ 0,05` log-odds. Ambang 0,05 adalah **konvensi development, PROVISIONAL** (bukan ambang bisnis yang disetujui).
- Bila **semua** fitur anggota di-impute, konsep tidak muncul.
- **Urutan** tampil: `|jumlah|` menurun; bila sama, urutan tetap `RECENCY`, `FREQUENCY`, `SPEND`, `TENURE`.
- Jumlah itu tidak ditampilkan sebagai angka.

**Status implementasi:** producer Moses saat ini mengeluarkan kode tingkat fitur (tiga kode frekuensi terpisah). Penggabungan ke konsep belum diimplementasi; ini pekerjaan Moses setelah dokumen ini diterima.

## 5. Arah dan tempat tampil

| Arah | Tampil sebagai | Dihitung ke "alasan"? |
|---|---|---|
| `INCREASES_RISK` | **Alasan risiko** (daftar utama) | Ya |
| `DECREASES_RISK` | **Faktor penahan** (daftar terpisah, sekunder) | Tidak |

Alasan risiko menjelaskan "kenapa skor tinggi". Faktor penahan boleh ditampilkan terpisah dengan label yang jelas, tetapi tidak dipakai untuk memenuhi minimum alasan.

## 6. Jumlah alasan (P7)

- Target: tiga alasan risiko dari **konsep berbeda**. Dengan empat konsep aktif, banyak pelanggan akan punya kurang dari tiga.
- **Kurang dari tiga:** skor **tetap dipakai** (alasan tidak menjadi syarat penolakan skor; D5) dan alasan yang ada **tetap tampil**. Tidak ada alasan palsu. Respons dan UI menandai bahwa jumlah alasan di bawah minimum FRD (mis. `reasons_below_minimum = true`), supaya tidak disalahartikan sebagai kepatuhan.
- **Nol alasan:** tampilkan "Alasan skor belum dapat dijelaskan" (§7); skor tetap dipakai.
- Ini **menyimpang dari** teks FRD "wajib minimal 3 Reason Codes". Penyimpangan dicatat di `target_definitions.md` dan **membutuhkan penerimaan mentor tertulis**. Sampai itu, jangan mengklaim "tiga alasan terpenuhi" (50.141 `OK` di laporan Moses bukan bukti kepatuhan).

## 7. Teks Indonesia (final)

Kalimat netral dan faithful. Sengaja tidak memakai kata "rendah/tinggi/lama/baru" karena arah nilai fitur belum diverifikasi per pelanggan; yang dikatakan hanya arah pengaruh pada **skor**.

| Konsep | `INCREASES_RISK` (alasan risiko) | `DECREASES_RISK` (faktor penahan) |
|---|---|---|
| `RECENCY` | Jarak waktu sejak aktivitas terakhir ikut menaikkan skor risiko churn. | Jarak waktu sejak aktivitas terakhir ikut menurunkan skor risiko churn. |
| `FREQUENCY` | Frekuensi pembelian dalam beberapa jendela waktu ikut menaikkan skor risiko churn. | Frekuensi pembelian dalam beberapa jendela waktu ikut menurunkan skor risiko churn. |
| `SPEND` | Pendapatan yang dipertahankan dari pelanggan ini ikut menaikkan skor risiko churn. | Pendapatan yang dipertahankan dari pelanggan ini ikut menurunkan skor risiko churn. |
| `TENURE` | Lama pelanggan tercatat ikut menaikkan skor risiko churn. | Lama pelanggan tercatat ikut menurunkan skor risiko churn. |

Teks tambahan:

| Situasi | Teks |
|---|---|
| Alasan risiko kurang dari 3 | Hanya {n} alasan yang dapat dijelaskan dari data yang tersedia. |
| Tidak ada alasan | Alasan skor belum dapat dijelaskan dari data yang tersedia. |
| Catatan tetap di bawah daftar | Penjelasan ini menunjukkan arah pengaruh pada perhitungan model, bukan penyebab bisnis atau perilaku pelanggan yang sebenarnya. |

`{n}` diisi 1 atau 2. Catatan tetap sama dengan `NOTICE` di `services/data/models/score_explanations.py`; kalimat per fitur milik Moses di sana tetap dapat dipakai untuk tampilan tingkat fitur (mis. mode analis).

## 8. Kontrol yang tidak boleh dilanggar

1. Tidak ada kode di luar §2 pada daftar keluaran produser (allowlist tetap).
2. Tidak ada angka kontribusi, nama fitur teknis, atau nama pelanggan lain dalam teks.
3. Tidak ada alasan dari fitur yang di-impute.
4. Perubahan kode, pemetaan, ambang, atau teks = versi taxonomy baru; versi lama tidak ditimpa.
5. Versi taxonomy dicatat bersama `model_version`, `label_version`, `lifecycle_rule_version`, dan `revenue_definition_version` pada tiap skor (P7).

## 9. Yang masih terbuka

| Hal | Pemilik | Status |
|---|---|---|
| Penerimaan penyimpangan "kurang dari 3 alasan" | Mentor | PENDING |
| Persetujuan taxonomy ini (Gate A) | Mentor | PENDING |
| Implementasi penggabungan konsep dan penggantian nama `PURCHASE_RECENCY` | Moses | Belum |
| Penanda `reasons_below_minimum` pada respons/skor | Moses (+ Christ untuk kontrak) | Belum |
| Tampilan "faktor penahan" terpisah di UI | Marvin | Belum |
