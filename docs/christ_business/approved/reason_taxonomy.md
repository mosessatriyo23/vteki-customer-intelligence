# Taxonomy Alasan Churn (Reason Codes) dan Teks Indonesia

**Dokumen:** `reason_taxonomy.md` · **Versi taxonomy:** `christ-reason-taxonomy-1.5-draft`
**Penyusun:** Christ (Orang 2) · **Tanggal:** 26 November 2026
**Revisi 28 Nov 2026:** alasan churn ditambah dua *faktor konteks bisnis* (§3) atas instruksi Christ; implementasi di `services/decision/nba/context_factors.py`.
**Status:** **FINAL dari sisi Christ** (ditetapkan 26 Nov, direvisi 28 Nov, atas instruksi Christ, mengikuti keputusan percepatan Moses di #70/#71). **Persetujuan mentor/dosen: [PENDING]**; tidak diisi sendiri, mengikuti Gate A `target_definitions.md`.
**Menggantikan:** `target_definitions.md` v1.4 §1.3 (daftar 6 kode bisnis). §1.3 sekarang menunjuk ke dokumen ini. Dari 6 kode v1.4: 3 kode model/bisnis kini aktif sebagai alasan model (`RECENCY`, `FREQUENCY`, `SPEND`), 2 aktif sebagai faktor konteks (`MEMBERSHIP_EXPIRING`, `UNRESOLVED_COMPLAINT`), 1 tidak aktif (`NO_CROSS_CATEGORY`).
**Menjawab:** update Moses, to-do Christ #2 "Finalkan taxonomy alasan beserta teks Indonesianya" dan P7.

---

## 1. Prinsip

1. **Ada dua jenis alasan, selalu ditandai sumbernya.** (a) *Alasan model*: arah pengaruh fitur pada skor model, bukan sebab bisnis atau perilaku pelanggan. (b) *Faktor konteks bisnis*: fakta dari aturan deterministik atas data yang sudah menjadi masukan engine; **bukan kontribusi model** dan tidak pernah dicampur tanpa label. Dasarnya dekomposisi log-odds model logistik yang diverifikasi faithful (`churn_reasons.py`). Teks tidak boleh menyiratkan sebab ("karena pelanggan kecewa") atau menyebut angka kontribusi.
2. **Hanya alasan yang didukung data yang benar-benar ada.** Alasan model hanya dari fitur yang diukur dan diobservasi (fitur yang di-impute tidak pernah tampil, tetap `excluded_imputed`). Faktor konteks hanya dari sumber yang tersambung; sumber `None` tidak menghasilkan faktor.
3. **Satu konsep = satu alasan.** Beberapa jendela waktu dari konsep yang sama digabung (§5).
4. **Tidak ada alasan palsu.** Bila alasan yang tersedia kurang dari tiga, tampilkan yang ada (§7). Tidak ada pengisian, duplikasi, atau alasan cadangan demi memenuhi angka tiga.
5. **Internal, bukan untuk pelanggan.** Kalimat dibaca staf (analis, marketer, RM). Tidak dikirim ke pelanggan dan tidak memuat data pribadi.
6. **Satu sumber taxonomy.** Kode konsep, pemetaan fitur, dan teks di bawah adalah satu-satunya sumber; UI dan formatter tidak membuat teks sendiri.

## 2. Alasan model: konsep aktif (dapat dikeluarkan sekarang)

Model churn saat ini hanya punya 7 fitur (`churn_reasons.REASON_CODES`). Maka hanya empat konsep yang punya dasar data:

| Kode konsep | Makna | Fitur model (kode producer saat ini) | Setara nama v1.4 |
|---|---|---|---|
| `RECENCY` | Jarak waktu sejak aktivitas terakhir (transaksi, kunjungan selesai, atau renewal) | `recency_days` (`PURCHASE_RECENCY`) | `RECENCY_LONG` |
| `FREQUENCY` | Frekuensi pembelian dalam jendela 60/90/365 hari | `purchase_count_60d`, `purchase_count_90d`, `purchase_count_365d` (`PURCHASE_FREQUENCY_60D/90D/365D`) | `FREQUENCY_DROP` |
| `SPEND` | Pendapatan yang dipertahankan dalam jendela 90/365 hari | `retained_revenue_90d`, `retained_revenue_365d` (`RETAINED_REVENUE_90D/365D`) | `SPEND_DECLINE` |
| `TENURE` | Lama pelanggan tercatat | `tenure_days` (`TENURE`) | (baru, tidak ada di v1.4) |

Catatan nama: `recency_days` di data dihitung dari **aktivitas** terakhir (`segmentation/snapshot.py`: transaksi, kunjungan berstatus `COMPLETED`, renewal), bukan hanya pembelian. Kode producer `PURCHASE_RECENCY` karenanya sedikit menyesatkan; di taxonomy ini maknanya "aktivitas". Mohon Moses mengganti namanya pada versi mapping berikutnya (tidak mengubah kode historis diam-diam).

## 3. Faktor konteks bisnis (aktif sejak revisi 28 Nov)

Tambahan alasan yang **punya dasar data dan aturan nyata di proyek ini**, bukan karangan baru. Dihitung oleh `compute_context_factors` (`services/decision/nba/context_factors.py`), dikunci `tests/decision/test_context_factors.py` (26 test).

| Kode | Aturan | Sumber data (masukan engine) | Teks Indonesia |
|---|---|---|---|
| `MEMBERSHIP_EXPIRING` | Membership aktif **dan** sisa masa berlaku ≤ 15 hari. Jendela 15 hari **sama persis** dengan aturan `RENEWAL_REMINDER` di `evaluator.py` (dijaga test: faktor menyala tepat pada sisa 15 hari, tidak pada 16) | `EligibilityProfile` (`has_active_membership`, `membership_days_remaining`) | Masa keanggotaan akan berakhir dalam 15 hari atau kurang. |
| `UNRESOLVED_COMPLAINT` | Ada tiket keluhan **pelanggan ini** berstatus `OPEN_SEVERE`, `OPEN_MILD`, atau `IN_PROGRESS` (`RESOLVED`/`CLOSED` tidak dihitung) | `ComplaintTicket` (status yang sama dengan aturan suppression) | Ada keluhan pelanggan yang belum selesai ditangani. |

Aturan keras: sumber `None` (belum tersambung) tidak menghasilkan faktor; sumber `[]` (tersambung, kosong) juga tidak; data pelanggan lain diabaikan; urutan tetap `MEMBERSHIP_EXPIRING` lalu `UNRESOLVED_COMPLAINT`; faktor **tidak mengubah aksi yang dipilih** (hanya menjelaskan).

**Keluaran:** respons evaluate dan kolom `rationale` memuat `context_factors` = daftar `{code, text, source: "BUSINESS_RULE"}`, terpisah dari alasan model. UI wajib menandai sumbernya (§6). **Status data:** consent/komplain/kelayakan belum tersambung di `api/decisions.py` dan `worker/tasks.py`, jadi hari ini daftar ini kosong sampai James menyambungkan feed (bukan kegagalan).

## 4. Konsep tidak aktif (dilarang dikeluarkan)

| Kode konsep | Alasan tidak aktif | Syarat untuk mengaktifkan |
|---|---|---|
| `NO_CROSS_CATEGORY` | Data kepemilikan kategori belum tersedia (`target_definitions.md` §3.2.C: syarat kategori "tidak ditegakkan"); tidak ada fitur model maupun sumber data | Sumber kepemilikan kategori dari Moses/James + definisi "lintas kategori" + versi taxonomy baru |

Mengeluarkan kode ini sebelum syaratnya terpenuhi melanggar taxonomy. Menambah konsep atau faktor baru berarti menaikkan versi taxonomy dan meminta persetujuan Christ (+ mentor).

## 5. Penggabungan fitur model menjadi konsep

Model logistik bersifat aditif, sehingga kontribusi konsep = **jumlah** kontribusi log-odds fitur anggotanya yang **diobservasi** (bukan di-impute):

- `kontribusi(konsep) = Σ log_odds_contribution(fitur anggota, non-imputed)`.
- **Arah** = tanda jumlah: positif → `INCREASES_RISK`, negatif → `DECREASES_RISK`.
- Konsep model **muncul** bila `|jumlah| ≥ 0,05` log-odds. Ambang 0,05 adalah **konvensi development, PROVISIONAL** (bukan ambang bisnis yang disetujui).
- Bila **semua** fitur anggota di-impute, konsep tidak muncul.
- **Urutan** tampil: `|jumlah|` menurun; bila sama, urutan tetap `RECENCY`, `FREQUENCY`, `SPEND`, `TENURE`.
- Jumlah itu tidak ditampilkan sebagai angka.

**Status implementasi:** producer Moses saat ini mengeluarkan kode tingkat fitur (tiga kode frekuensi terpisah). Penggabungan ke konsep belum diimplementasi; ini pekerjaan Moses setelah dokumen ini diterima.

## 6. Arah dan tempat tampil

| Arah | Tampil sebagai | Dihitung ke "alasan"? |
|---|---|---|
| `INCREASES_RISK` | **Alasan risiko** (daftar utama) | Ya |
| `DECREASES_RISK` | **Faktor penahan** (daftar terpisah, sekunder) | Tidak |
| Faktor konteks (§3) | **Faktor konteks (aturan bisnis)**, ditandai "bukan hasil model" | Ya, lihat §7 |

Alasan risiko menjelaskan "kenapa skor tinggi". Faktor penahan boleh ditampilkan terpisah dengan label yang jelas, tetapi tidak dipakai untuk memenuhi minimum alasan.

## 7. Jumlah alasan (P7)

- **Target:** tiga alasan yang ditampilkan = alasan risiko model (konsep berbeda) **ditambah** faktor konteks yang berlaku. Dengan 4 konsep model + 2 faktor konteks, maksimum 6.
- **Interpretasi yang perlu diketahui mentor:** faktor konteks dihitung ke target tiga karena keduanya fakta nyata tentang pelanggan yang relevan dengan risiko churn, **tetapi bukan penjelasan skor**. Itu sebabnya setiap alasan membawa tanda sumber (`MODEL` / `BUSINESS_RULE`) dan respons memisahkan keduanya; mentor dapat memilih menghitung model saja, dan aturan di bawah tetap berlaku.
- **Kurang dari tiga (setelah ditambah faktor konteks):** skor **tetap dipakai** (alasan bukan syarat penolakan skor; D5) dan alasan yang ada **tetap tampil**. Tidak ada pengisian, duplikasi, atau alasan cadangan demi memenuhi angka tiga. Respons dan UI menandai bahwa jumlah di bawah minimum FRD (mis. `reasons_below_minimum = true`), supaya tidak disalahartikan sebagai kepatuhan.
- **Nol alasan:** tampilkan "Alasan skor belum dapat dijelaskan" (§8); skor tetap dipakai.
- Ini **menyimpang dari** teks FRD "wajib minimal 3 Reason Codes" pada kasus di bawah tiga; penyimpangan dicatat di `target_definitions.md` dan **membutuhkan penerimaan mentor tertulis**. Sampai itu, jangan mengklaim "tiga alasan terpenuhi" (50.141 `OK` di laporan Moses bukan bukti kepatuhan).
- **Realistisnya hari ini:** faktor konteks bergantung feed yang belum tersambung, jadi hampir semua pelanggan masih hanya punya alasan model (maksimum 4).

## 8. Teks Indonesia (final)

Kalimat netral dan faithful. Sengaja tidak memakai kata "rendah/tinggi/lama/baru" karena arah nilai fitur belum diverifikasi per pelanggan; yang dikatakan hanya arah pengaruh pada **skor**.

| Konsep | `INCREASES_RISK` (alasan risiko) | `DECREASES_RISK` (faktor penahan) |
|---|---|---|
| `RECENCY` | Jarak waktu sejak aktivitas terakhir ikut menaikkan skor risiko churn. | Jarak waktu sejak aktivitas terakhir ikut menurunkan skor risiko churn. |
| `FREQUENCY` | Frekuensi pembelian dalam beberapa jendela waktu ikut menaikkan skor risiko churn. | Frekuensi pembelian dalam beberapa jendela waktu ikut menurunkan skor risiko churn. |
| `SPEND` | Pendapatan yang dipertahankan dari pelanggan ini ikut menaikkan skor risiko churn. | Pendapatan yang dipertahankan dari pelanggan ini ikut menurunkan skor risiko churn. |
| `TENURE` | Lama pelanggan tercatat ikut menaikkan skor risiko churn. | Lama pelanggan tercatat ikut menurunkan skor risiko churn. |

Teks faktor konteks (identik dengan kode `context_factors.py`):

| Kode | Teks |
|---|---|
| `MEMBERSHIP_EXPIRING` | Masa keanggotaan akan berakhir dalam 15 hari atau kurang. |
| `UNRESOLVED_COMPLAINT` | Ada keluhan pelanggan yang belum selesai ditangani. |

Teks tambahan:

| Situasi | Teks |
|---|---|
| Alasan (model + konteks) kurang dari 3 | Hanya {n} alasan yang dapat dijelaskan dari data yang tersedia. |
| Tidak ada alasan | Alasan skor belum dapat dijelaskan dari data yang tersedia. |
| Catatan tetap di bawah daftar | Penjelasan ini menunjukkan arah pengaruh pada perhitungan model, bukan penyebab bisnis atau perilaku pelanggan yang sebenarnya. |

`{n}` diisi 1 atau 2. Catatan tetap sama dengan `NOTICE` di `services/data/models/score_explanations.py`; kalimat per fitur milik Moses di sana tetap dapat dipakai untuk tampilan tingkat fitur (mis. mode analis).

## 9. Kontrol yang tidak boleh dilanggar

1. Tidak ada kode di luar §2 (alasan model) dan §3 (faktor konteks) pada daftar keluaran (allowlist tetap).
2. Tidak ada angka kontribusi, nama fitur teknis, atau nama pelanggan lain dalam teks.
3. Tidak ada alasan dari fitur yang di-impute, dan tidak ada faktor konteks dari sumber yang belum tersambung.
4. Perubahan kode, pemetaan, ambang, atau teks = versi taxonomy baru; versi lama tidak ditimpa.
5. Faktor konteks tidak boleh disajikan sebagai kontribusi model, dan tidak boleh mengubah aksi yang dipilih.
6. Versi taxonomy dicatat bersama `model_version`, `label_version`, `lifecycle_rule_version`, dan `revenue_definition_version` pada tiap skor (P7).

## 10. Yang masih terbuka

| Hal | Pemilik | Status |
|---|---|---|
| Penerimaan penyimpangan "kurang dari 3 alasan" + interpretasi faktor konteks dihitung | Mentor | PENDING |
| Persetujuan taxonomy ini (Gate A) | Mentor | PENDING |
| Penggabungan konsep model dan penggantian nama `PURCHASE_RECENCY` | Moses | Belum |
| Penanda `reasons_below_minimum` pada respons/skor | Moses (+ Christ untuk kontrak) | Belum |
| Faktor konteks di engine (`context_factors.py`, di respons dan `rationale`) | Christ | **Selesai** (26 test) |
| Menampilkan `context_factors` di UI dengan label "bukan hasil model", dan "faktor penahan" terpisah | Marvin | Belum |
| Menyambungkan feed kelayakan dan komplain agar faktor konteks terisi | James | Belum |
