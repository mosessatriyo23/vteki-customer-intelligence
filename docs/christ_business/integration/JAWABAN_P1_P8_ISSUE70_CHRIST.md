# Jawaban Christ untuk issue #70 (P1–P8 dan status D1–D7)

**Tanggal:** 26 November 2026 (diperbarui 26 November 2026, setelah pesan Moses "sisa pekerjaan sebelum pengumpulan")
**Menjawab:** `docs/moses_data_ai/CHRIST_V14_RECONCILIATION_MESSAGE_2026-11-20.md` (P1–P8) dan update Moses 26 Nov (to-do Christ #1)
**Status per poin diperbarui (lihat tabel di bawah).** P2, P6, P7, dan P8 **final dari sisi Christ** (ditetapkan 26 Nov atas instruksi Christ, mengikuti keputusan percepatan Moses di #70/#71). P1, P3, P4, P5 tetap **USULAN** sampai Christ menyatakan final. **Tidak ada persetujuan mentor atas satu pun poin**; poin yang menyimpang dari Requirement/FRD ditandai ⚠️. Tidak ada angka bisnis yang dikarang.

Dasar: `docs/christ_business/approved/target_definitions.md` v1.4 (masih **PENDING approval**, approver/tanggal belum diisi), `D5_NBA_INPUT_CONTRACT.md`, dan perilaku engine yang diuji.

---

## Pernyataan status per poin (untuk issue #70)

Moses menutup #70 dan meminta pernyataan per poin agar penutupan issue tidak disalahartikan sebagai persetujuan.

| Poin | Status | Catatan |
|---|---|---|
| P1 cutoff WIB | **USULAN** (rekomendasi: nyatakan final) | Hanya menegaskan teks v1.4 §1.1 ("tanggal WIB"); tabel boundary siap dipakai Moses |
| P2 lintas segmen | **FINAL: Opsi A** | Dikunci `test_cross_segment_matrix.py`; ditegaskan di `target_definitions.md` §3.2.A |
| P3 REACTIVATED | USULAN | Butuh konfirmasi "cool-off tidak di-reset" dan coverage as-of dari James |
| P4 ACTIVE / membership | USULAN | Butuh James (penanda kelengkapan feed) dan revisi §3.2.G.1 |
| P5 retensi 365 hari | USULAN | Teknik pooling milik Moses; semantik di bawah |
| P6 pembulatan IDR | **FINAL: half-up `Decimal`** | `target_definitions.md` §2.4; Moses menambah boundary test |
| P7 reason codes | **FINAL: kurang dari 3 tetap tampil tanpa alasan palsu**, ⚠️ menunggu mentor | Taxonomy dan teks di `reason_taxonomy.md`; menyimpang dari FRD "minimal 3" |
| P8 RFM | **FINAL: di luar MVP** | `target_definitions.md` §3.3 |

Teks yang disarankan untuk issue #70: "Status per poin: P2 final (Opsi A), P6 final (half-up Decimal), P7 final dari sisi Christ (alasan < 3 tetap tampil tanpa alasan palsu; **menunggu penerimaan mentor** karena menyimpang dari FRD), P8 final (RFM di luar MVP). P1/P3/P4/P5 masih usulan. Tidak ada poin yang disetujui mentor. Dokumen: `docs/christ_business/integration/JAWABAN_P1_P8_ISSUE70_CHRIST.md`, `docs/christ_business/approved/reason_taxonomy.md`, `target_definitions.md` v1.5 (draf)."

---

## Bagian 1 — Status D1–D7 (`JAWABAN_TIM_D1_D7_CHRIST.md`)

Pertanyaannya: apakah usulan di file itu sudah final? Jawaban jujur: **sebagian bagian sisi NBA sudah bisa disebut final dari sisi Christ** karena terkunci test, sedangkan nilai kebijakan, nama orang, dan keputusan lintas tim **belum final**.

| Keputusan | Bagian yang bisa ditulis "final (sisi Christ/NBA)" | Bagian yang tetap terbuka |
|---|---|---|
| D1 | NBA memakai `ml.prediction_review_runs/records` tanpa tabel baru; penggabungan CHURN+propensity+CLV+lifecycle dilakukan di loader | Kolom tambahan (izin pakai + penyetuju + waktu) dan keputusan skema: Moses + Marvin (+ James) |
| D2 | "Reviewed" bukan izin pakai; NBA memakai skor hanya bila `usage_approved is True`; reviewer berbeda dari pengunggah dan pembuat model; dicabut = `False` dan berlaku pada evaluasi berikutnya | Nama pembuat model, reviewer independen, siapa yang boleh memberi/mencabut izin: **[ISI]**, putuskan di meeting. Penerima bisnis: Christ |
| D3 | Satu cutoff terbaru yang sah per pelanggan, tanpa menggabung komponen dari cutoff berbeda; skor parsial/kosong/di luar rentang ditolak seluruhnya; 30 hari dari cutoff, tepat 30 hari masih sah (31 hari kedaluwarsa, sudah dikunci test) | ⚠️ Angka 30 hari adalah usulan; konfirmasi di meeting dan mentor |
| D4 | NBA tidak menebak: pelanggan tanpa pemetaan pasti atau berstatus demo tidak dievaluasi; skor milik ID lain ditolak (`SCORE_CUSTOMER_MISMATCH`, baru, dikunci test) | Penghapusan fallback `customer_code`: Moses + Marvin + James |
| D5 | Reason code tidak dipakai logika (tidak menolak skor bila < 3); band wajib dan berasal dari satu fungsi pemotong Moses; CLV (angka) wajib untuk semua aksi promosi; skor kosong/kedaluwarsa/parsial ditolak seluruhnya (fail-closed, nol adalah nilai bukan "kosong") | ⚠️ Band 0,30 / 0,60 / 0,80 (dari FRD, tertulis di v1.4 §1.2 tetapi v1.4 belum disetujui); pemetaan tier CLV (v1.4 §2.4); penundaan "mode terbatas per aksi" ke tahap 2 |
| D6 | Batch scoring idempoten per (pelanggan, cutoff, jenis prediksi, run); retry tidak menggandakan; hasil parsial tidak tampak lengkap | Manual atau terjadwal, dan PIC operasi: Moses + Marvin + James. PIC: **[ISI]** |
| D7 | Simulator ber-label cukup untuk demo MVP; tidak ada pengiriman nyata; `NO_ACTION` yang benar ikut didemokan; skenario UAT: `docs/christ_business/demo/UAT_PLAN.md` (14 skenario, hasil diharapkan sudah ditulis) | ⚠️ Arti "campaign jalan beneran" menurut mentor; penandatangan UAT: **[ISI]** |

> **Pembaruan 26 Nov:** Moses sudah mengimplementasikan penyimpanan izin pakai (migrasi 0027, endpoint izin/pencabutan, audit) dan loader yang membedakan tiga keadaan skor; keputusan D1–D7 dicatat Moses mewakili tim. Isi tabel di atas tetap menjadi posisi sisi NBA; nama reviewer/pemberi izin, PIC, dan penandatangan UAT tetap perlu ditunjuk manusia.

**Teks yang disarankan untuk issue #70:** "Sisi NBA untuk D1–D7: bagian yang tertulis di kolom kiri (rule fail-closed, izin pakai, kedaluwarsa, ID, input minimum) **final dari sisi Christ** dan dikunci test di `tests/decision`. Nilai kebijakan dan nama PIC/reviewer **belum final**; dibawa ke meeting D2/D3/D5."

---

## Bagian 2 — Jawaban P1–P8

### P1 — cutoff WIB ⚠️ (usulan; penegasan teks v1.4 §1.1)
**Jawaban:** `prediction_date` adalah **tanggal kalender WIB**, bukan titik waktu. Seluruh hari itu (00:00:00 sampai 23:59:59,999 WIB) termasuk **riwayat/cohort/fitur**. Jendela outcome mulai **00:00:00 WIB hari berikutnya**. Sebuah event dimasukkan ke hari berdasarkan `occurred_at` yang dikonversi ke WIB, lalu diambil tanggalnya.
**`known_at`/`available_at` berbeda dari cutoff event:** event dipakai di riwayat hanya bila tanggal WIB `occurred_at` ≤ cutoff **dan** `known_at` ≤ akhir hari cutoff (23:59:59,999 WIB). Event atau refund yang baru diketahui sesudahnya tidak mengubah skor cutoff lama (sesuai kontrak James dan v1.4 §2.2). Satu definisi ini berlaku untuk label, fitur, dan proyeksi.

Contoh, cutoff = **2026-10-01 WIB**:

| Waktu event | Dalam WIB | Masuk |
|---|---|---|
| 2025-10-01T16:59:59Z | 2025-10-01 23:59:59 | **Tidak** (tepat cutoff−365 hari; batas kiri terbuka) |
| 2025-10-01T17:00:00Z | 2025-10-02 00:00:00 | Ya, jendela cohort (sesaat sesudah batas kiri) |
| 2026-09-30T17:00:00Z | 2026-10-01 00:00:00 | Ya, riwayat (tanggal UTC 30 Sep, tanggal WIB 1 Okt) |
| 2026-10-01T16:59:59Z | 2026-10-01 23:59:59 | Ya, riwayat; **bukan** outcome (tepat cutoff) |
| 2026-10-01T17:00:00Z | 2026-10-02 00:00:00 | Outcome (sesaat sesudah cutoff) |
| 2026-10-01T20:00:00Z | 2026-10-02 03:00:00 | Outcome (tanggal UTC 1 Okt, tanggal WIB 2 Okt) |
| 2026-12-30T16:59:59Z | 2026-12-30 23:59:59 | Outcome, hari ke-90 (masuk) |
| 2026-12-30T17:00:00Z | 2026-12-31 00:00:00 | **Tidak**, hari ke-91 |

Moses dapat menulis boundary tests dari tabel ini setelah Christ menyatakan "final".

### P2 — lintas segmen vs NO_ACTION — **FINAL: Opsi A** (sisi Christ; mentor belum)
**Perilaku engine saat ini ("Opsi A"):** untuk CHURNED, REACTIVATED, dan NEVER_TRANSACTED, tiga aksi lintas segmen **tidak** dikalahkan oleh NO_ACTION/cool-off. Dikunci di `tests/decision/test_cross_segment_matrix.py` (15 test).

| Segmen | RELATIONSHIP_MANAGER_CONTACT (PLATINUM + risiko HIGH/VERY_HIGH) | RENEWAL_REMINDER (sisa membership ≤ 15 hari) | COMPLAINT_RESOLUTION (komplain berat terbuka) | Aksi promosi lain |
|---|---|---|---|---|
| CHURNED | Boleh | Boleh | Boleh (prioritas #1) | NO_ACTION |
| REACTIVATED | Boleh | Boleh | Boleh (prioritas #1) | NO_ACTION |
| NEVER_TRANSACTED | Boleh | Boleh | Boleh (prioritas #1) | NO_ACTION |

**Prioritas (tertinggi dulu):** global opt-out dan suppression mutlak (hasil `NO_ACTION`, alasan `OPT_OUT_SUPPRESSED`, juga mengalahkan `COMPLAINT_RESOLUTION`) → `COMPLAINT_RESOLUTION` → aksi lintas segmen lain → aksi berbasis segmen. Opt-out tidak boleh di-override pada opsi mana pun.

**Pengamatan yang membantu keputusan:** secara definisi, konflik ini hampir teoritis untuk CHURNED dan NEVER_TRANSACTED. CHURNED berarti tanpa transaksi/kunjungan > 365 hari **dan** membership kedaluwarsa > 180 hari atau tidak ada (v1.4 §3.2.G.1), jadi `Historical_Spend_12m` hampir pasti 0 (tier `INSUFFICIENT_HISTORY`, bukan PLATINUM) dan "sisa membership ≤ 15 hari" tidak terpenuhi. Yang nyata hanya **REACTIVATED**, karena pelanggannya baru belanja lagi dan bisa punya CLV tinggi.

**Dua opsi untuk REACTIVATED (Christ memilih):**
- **Opsi A (saat ini):** RM_CONTACT dan RENEWAL_REMINDER tetap boleh. Dasarnya: keduanya tidak memberi insentif promosi, jadi tidak mencemari ukuran win-back; pelanggan PLATINUM berisiko tinggi layak ditangani.
- **Opsi B:** NO_ACTION/cool-off menang untuk RM_CONTACT dan RENEWAL_REMINDER di REACTIVATED (kecuali COMPLAINT_RESOLUTION). Dasarnya: cool-off melindungi pengukuran 30 hari. Konsekuensi: ubah `evaluator.py`, terbitkan v1.5 `target_definitions.md`, ubah test matriks secara sadar.
**Keputusan (26 Nov): Opsi A.** Alasan: yang terdampak hanya REACTIVATED dan aksinya non-insentif. Bila mentor menginginkan cool-off ketat, ubah `evaluator.py`, terbitkan versi baru, dan ubah test matriks secara sadar. Batas cool-off (hari ke-30 masih REACTIVATED, hari ke-31 diklasifikasi ulang) adalah perilaku `snapshot.py` (milik Moses) menurut v1.4 §3.1; boundary test-nya dari sisi Moses.

### P3 — REACTIVATED (usulan; sebagian PENDING)
- **Trigger (usulan):** dalam 30 hari terakhir WIB (cutoff−30, cutoff]: **≥ 2 transaksi** berstatus `COMPLETED`/`PARTIAL_REFUND` **atau ≥ 1 `RENEWAL`**, setelah sebelumnya DORMANT/CHURNED. Sesuai Requirement Bab 1 ("≥ 2x ATAU memperpanjang"). Renewal saja (tanpa POS) **cukup** memicu. Kunjungan saja **tidak** memicu REACTIVATED.
- **Interval dan sumber pembelian:** 30 hari, sama dengan jendela atribusi win-back, supaya definisi satu angka.
- **Bukti "sebelumnya Dormant/Churned":** diutamakan snapshot historis yang tersimpan. Rekonstruksi as-of dari event dengan `known_at` ≤ cutoff hanya boleh bila aturan lifecycle versi yang sama dipakai. **PENDING James:** coverage feed as-of yang benar-benar ada; tanpa itu bukti ini tidak bisa dijamin.
- **Cool-off:** 30 hari dihitung dari event yang melengkapi trigger (pembelian ke-2 atau renewal) dan **tidak di-reset** oleh event berikutnya (agar segmen tidak menyala tanpa batas). Setelah itu klasifikasi ulang ke ACTIVE/OCCASIONAL. **PENDING Christ:** konfirmasi "tidak di-reset".
- **Prioritas:** tetap §3.2.G.4 (`REACTIVATED` > `LOYAL` > `NEW` > …). Moses menerbitkan rule version baru, tidak menimpa snapshot lama.
- **Visit-only / renewal-only vs NEVER_TRANSACTED:** usulan: `NEVER_TRANSACTED` = **tidak ada satu pun churn negation event (transaksi, kunjungan, renewal)**, sehingga pelanggan visit-only atau renewal-only **bukan** NEVER_TRANSACTED. Alasan: dengan cohort tiga event (v1.4 §1.1) mereka punya skor churn, sedangkan NEVER_TRANSACTED diasumsikan tidak punya skor (§3.2.B). ⚠️ Nama segmen ("never transacted") tidak persis sama dengan definisi ini; konfirmasi mentor bila dianggap mengganggu.

### P4 — ACTIVE dan kelengkapan membership (usulan; PENDING James)
- **Makna "membership aktif digunakan dalam 60 hari":** di data yang ada, `membership_events` hanya memuat `JOIN` dan `RENEWAL`; **tidak ada event "penggunaan membership"** (kunjungan diturunkan dari transaksi POS). Maka usulan: *digunakan* = ≥ 1 transaksi POS `COMPLETED`/`PARTIAL_REFUND` atau 1 kunjungan terverifikasi dalam 60 hari **saat membership berstatus aktif** (belum kedaluwarsa pada tanggal itu). `RENEWAL` saja bukan penggunaan. Ini proksi, bukan pengukuran penggunaan benefit; dicatat sebagai keterbatasan.
- **Unknown vs non-member:** setuju dengan Moses: tidak ada baris atau feed tidak lengkap ≠ non-member. Usulan: "tidak punya riwayat membership" hanya boleh dinyatakan bila ada **penanda kelengkapan feed membership** untuk periode itu. Tanpa penanda: status riwayat = `UNKNOWN`, dan pelanggan **tidak dipaksa** menjadi CHURNED; NBA memperlakukannya fail-closed (tidak ada aksi promosi).
- **Konsekuensi dokumen:** §3.2.G.1 v1.4 menulis "tidak ada segmen `UNCLASSIFIED` yang boleh keluar". Usulan ini membutuhkan revisi aturan tersebut (v1.5): ganti dengan status eksplisit "riwayat membership tidak diketahui" yang tidak masuk cohort promosi. Butuh keputusan Christ + konfirmasi James soal sumber, timestamp, coverage. Tidak boleh memaksa missing → CHURNED demi menghilangkan UNCLASSIFIED.

### P5 — retensi 365 hari (usulan; teknik estimasi milik Moses)
- **Segmentasi:** memakai **segmen pada cutoff historis**, bukan segmen sesudah outcome. Ditegaskan.
- **Makna faktor:** proporsi observasi di segmen itu yang punya ≥ 1 churn negation event (transaksi / kunjungan / renewal) dalam (cutoff, cutoff + 365 hari], seperti v1.4 §2.3.
- **Denominator:** observasi (pelanggan, cutoff) yang berada di segmen itu pada cutoff tersebut **dan** punya jendela outcome 365 hari lengkap. Cutoff yang jendela outcome-nya belum lengkap tidak dihitung.
- **Ambang ≥ 30:** diukur pada **pelanggan unik** dengan outcome lengkap per segmen. Bila beberapa cutoff dipooling, cutoff harus berjarak ≥ 365 hari agar jendela outcome tidak tumpang tindih; satu pelanggan dihitung sekali untuk ambang. Sel < 30 → "tidak cukup data", **CLV = null** (tanpa default, tanpa `1−churn_score`, tanpa 0,7, tanpa diagnostik 90 hari).
- **PENDING:** teknik pooling/varians diserahkan ke Moses; yang diminta hanya laporan versi, tanggal, denominator, dan coverage.

### P6 — pembulatan IDR — **FINAL: half-up dengan `Decimal`** (contoh yang diminta tidak membedakan aturan)
- **Aturan:** **half-up** ke rupiah terdekat (x,5 naik) dengan aritmetika `Decimal` (`ROUND_HALF_UP`), bukan `round()` bawaan Python yang half-even pada float. Pembulatan hanya di **akhir**; **tier ditentukan setelah pembulatan**; aturan minimal 2 transaksi tetap.
- **Catatan penting:** tiga contoh yang diminta (`199999,5`, `499999,5`, `999999,5`) menghasilkan nilai sama di half-up dan half-even (200.000 / 500.000 / 1.000.000, karena tetangga atasnya genap), jadi tidak membedakan aturan dan tier tidak pernah berbeda di batas tier. Aturan baru berpengaruh pada nilai tersimpan. Contoh pembeda yang disarankan:

| Nilai sebelum pembulatan | Half-up | Half-even | Tier (≥ 2 transaksi) |
|---|---|---|---|
| 199.999,5 | 200.000 | 200.000 | `SILVER` |
| 199.999,4 | 199.999 | 199.999 | `INSUFFICIENT_HISTORY` |
| 200.000,5 | 200.001 | 200.000 | `SILVER` |
| 499.999,5 | 500.000 | 500.000 | `GOLD` |
| 999.999,5 | 1.000.000 | 1.000.000 | `PLATINUM` |
| 1.000.000,5 | 1.000.001 | 1.000.000 | `PLATINUM` |

### P7 — reason codes dan versi — **FINAL dari sisi Christ** ⚠️ (penyimpangan "minimal 3" menunggu mentor)
- **Satu konsep = satu alasan:** tiga jendela waktu dari konsep yang sama (frekuensi 365/90/60 hari) dihitung **satu** alasan (`FREQUENCY_DROP`). "Tiga alasan bisnis berbeda" berarti tiga konsep berbeda dari taxonomy v1.4 §1.3: `RECENCY_LONG`, `SPEND_DECLINE`, `FREQUENCY_DROP`, `MEMBERSHIP_EXPIRING`, `UNRESOLVED_COMPLAINT`, `NO_CROSS_CATEGORY`.
- **Bila dukungan faithful < 3 konsep:** tampilkan yang ada (1 atau 2), **jangan tambah alasan palsu**, dan tandai bahwa alasan di bawah minimum FRD. NBA **tidak menolak skor** karena ini (D5): reason code tidak dipakai logika. ⚠️ Ini menyimpang dari FRD "wajib minimal 3"; butuh penerimaan mentor tertulis.
- **Taxonomy dan teks (final dari sisi Christ):** `docs/christ_business/approved/reason_taxonomy.md`: empat konsep aktif (`RECENCY`, `FREQUENCY`, `SPEND`, `TENURE`), tiga konsep v1.4 tidak aktif karena tidak ada fitur, penggabungan konsep dengan menjumlahkan kontribusi log-odds, teks netral per arah. Penggabungan belum diimplementasi di producer (pekerjaan Moses).
- **Versi terpisah (usulan penamaan):** `reason_taxonomy_version`, `label_version`, `lifecycle_rule_version`, `revenue_definition_version` (dan `target_definitions` v1.x sebagai dokumen payung). Setiap perubahan semantik menaikkan versi terkait; tidak ada penimpaan diam-diam. Hubungan dengan kontrak dan approval: kontrak mengutip versi-versi itu; persetujuan (D2) melekat pada kombinasi versi model + versi definisi.

### P8 — RFM — **FINAL: di luar MVP**
Requirement hanya menyebut RFM kuintil sebagai penjelasan segmen (mis. "dikecualikan dari audiens berbasis RFM kuintil"); **tidak ada definisi populasi, jendela, field monetary, atau pemetaan nama**. Engine NBA dan campaign **tidak memakai RFM**. Jawaban: **di luar cakupan MVP** (`target_definitions.md` §3.3). Moses diminta tidak mengarang nama (Champions dll.) dan tidak menyamakan RFM dengan lifecycle. Bila RFM mau dipakai, Christ dan mentor perlu menetapkan: populasi aktif, jendela, field monetary otoritatif (`actual_revenue`?), recency pembelian vs aktivitas, dan pemetaan kuintil → nama untuk `segment_version_config`.

---

## Bagian 3 — Konfirmasi mentor yang masih terbuka

1. **D1 horizon churn:** 90 vs 180 hari (usulan Christ 90; alasan di v1.4 §1.1). Butuh jawaban tertulis. Bila 180, Moses menerbitkan label/model versi baru.
2. Penyimpangan dari Requirement Bab 4 yang sudah dicatat di v1.4 §3.2: RM_CONTACT tanpa batas lifecycle, RETENTION_OUTREACH untuk HIGH dan VERY_HIGH, WIN_BACK hanya DORMANT, RENEWAL_REMINDER tanpa ambang propensity.
3. Pemetaan satu-label tier CLV (v1.4 §2.4) dan band risiko 0,30 / 0,60 / 0,80.
4. Arti "campaign jalan beneran" dan penandatangan UAT (D7).
5. Penerimaan alasan di bawah 3 konsep (P7).

## Bagian 4 — Yang Christ bawa ke meeting 30–45 menit (bagian B update Moses)

| Topik | Posisi Christ |
|---|---|
| D2 izin pakai | Aturan di Bagian 1 sudah final dari sisi NBA. Perlu: nama pembuat model, reviewer independen (orang lain), pemberi/pencabut izin |
| D3 skor dan masa berlaku | 30 hari dari cutoff; satu cutoff per pelanggan; skor parsial ditolak seluruhnya |
| D5 band, tier, alasan < 3 | Band dan tier dari v1.4 (belum disetujui); alasan < 3 tidak menolak skor (P7) |
| D1 tabel review | Cukup bila ditambah status izin pakai + penyetuju + waktu pada level run; keputusan skema bukan di Christ |
| D4 pemetaan ID | NBA tidak menebak; setuju hapus fallback bila pemetaan pasti tersedia |
| D6 job import | Kebutuhan NBA saja: idempoten, retry aman, hasil parsial tidak tampak lengkap |
| D7 simulator dan UAT | Simulator ber-label cukup; 14 skenario UAT siap; penandatangan perlu ditunjuk |

**Hasil meeting langsung ditulis di issue #70/#71.** Jangan mengisi `usage_approved = True`, band, atau angka bisnis sebelum ada keputusan tertulis.
