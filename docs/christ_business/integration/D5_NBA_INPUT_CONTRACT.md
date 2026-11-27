# D5 — Input minimum NBA (jawaban Christ)

**Tanggal:** 21 November 2026
**Menjawab:** `docs/moses_data_ai/TEAM_ALIGNMENT_MVP_2026-11-21.md` §5 D5
**Status:** **USULAN Christ — belum ada persetujuan mentor.** Butir yang butuh keputusan mentor ditandai ⚠️.

Setiap klaim "terverifikasi" di bawah dikunci oleh test terhadap engine asli di
`tests/decision/test_nba_input_contract.py` dan `tests/decision/test_nba_serving.py`.
Bila engine berubah dan klaim jadi salah, test gagal. Dokumen ini tidak bergantung pada ingatan.

---

## 1. Jawaban ringkas

| Pertanyaan D5 | Jawaban |
|---|---|
| Apakah NBA butuh **reason codes** untuk logika? | **Tidak.** Reason code tidak mempengaruhi aksi, nilai EV, maupun status degraded. Hanya disimpan di snapshot K-07 untuk audit. Skor **tidak boleh ditolak** karena reason code kurang dari 3. |
| Apakah NBA butuh **band**? | **Ya, wajib.** Dipakai kelayakan RELATIONSHIP_MANAGER_CONTACT, RETENTION_OUTREACH, EDUCATION. Band harus konsisten dengan `churn_score`; engine **tidak** mendeteksi inkonsistensi (terverifikasi), jadi band harus berasal dari satu fungsi pemotong milik Moses, bukan dihitung ulang NBA. |
| Apakah NBA butuh **tier CLV**? | **Ya, wajib** untuk RM_CONTACT, RETENTION_OUTREACH, LOYALTY_REWARD, WIN_BACK_OFFER. Nilai yang dikenali kelayakan: `GOLD`, `PLATINUM` (SILVER terverifikasi memblokir RETENTION). |
| Apakah NBA butuh **CLV (angka)**? | **Ya, untuk SEMUA aksi promosi.** EV = peluang × estimasi pendapatan (CLV × faktor aksi) × bobot aksi − biaya insentif, dengan ambang minimum Rp 1.000. Tanpa CLV positif tidak ada promosi yang bisa direkomendasikan (terverifikasi pada 60 kombinasi lifecycle × tier × band). |
| Apa yang terjadi saat skor **kosong / expired / sebagian**? | **Tolak seluruh skor** (bukan mode terbatas): NBA tidak merekomendasikan promosi dan menulis alasan jelas. Satu-satunya jalur yang tetap hidup adalah `COMPLAINT_RESOLUTION` (jalur suppression, bukan jalur skor). Terverifikasi. |
| Masa berlaku skor | **30 hari**, batas tepat 30 hari masih sah, lewat 1 detik expired. Dihitung dari waktu cutoff/generasi skor, **bukan** waktu impor. |

## 2. Field skor yang dibutuhkan, per aksi

`✔` = dipakai logika. Semua aksi promosi juga memakai `clv_amount` (EV).

| Aksi | `churn_score` | `churn_risk_band` | `propensity_purchase` | `propensity_renew` | `clv_tier` | `lifecycle_stage` | Syarat non-skor |
|---|:-:|:-:|:-:|:-:|:-:|:-:|---|
| RETENTION_OUTREACH | ✔ | ✔ HIGH/VERY_HIGH | | | ✔ GOLD/PLATINUM | ✔ AT_RISK/DORMANT | |
| RELATIONSHIP_MANAGER_CONTACT | ✔ | ✔ HIGH/VERY_HIGH | | | ✔ PLATINUM | | |
| WIN_BACK_OFFER | ✔ | | | | ✔ GOLD/PLATINUM | ✔ DORMANT | tidak ada win-back aktif |
| CROSS_SELL | | | ✔ ≥ 0,6 | | | ✔ ACTIVE/LOYAL | |
| UPSELL | | | | ✔ ≥ 0,6 | | ✔ ACTIVE/LOYAL | tenure ≥ 60 hari |
| RENEWAL_REMINDER | | | | ✔ (EV) | | | membership sisa ≤ 15 hari |
| LOYALTY_REWARD | | | ✔ (EV) | | ✔ GOLD/PLATINUM | ✔ LOYAL | |
| EDUCATION | ✔ (EV) | ✔ LOW | | | | ✔ NEW/OCCASIONAL | |
| SERVICE_REMINDER | | | | | | ✔ ACTIVE/LOYAL | jadwal habis pakai −14..+7 hari |
| COMPLAINT_RESOLUTION | | | | | | | keluhan berat terbuka (bukan jalur skor) |

**Akibat langsung:** satu-satunya hal yang Moses hasilkan hari ini sebagai skor tersimpan
adalah skor churn + band (tipe `CHURN`, band FRD 0,30 / 0,60 / 0,80). Itu **belum cukup** untuk aksi
apa pun, karena semua aksi juga butuh `clv_amount`, dan sebagian butuh `clv_tier`,
`lifecycle_stage`, atau propensity.

## 3. Perilaku saat data tidak lengkap

**Keputusan yang diusulkan: tolak penuh (fail-closed), bukan nol-isi.**

- Nol adalah **nilai prediksi**, bukan tanda "kosong". `clv_amount=0` dianggap skor sah dan menghasilkan
  `BELOW_MIN_EV` dengan `degraded_input=False` (terverifikasi). Mengisi nol agar kontrak lolos akan
  menyamarkan data hilang menjadi keputusan "tidak layak" yang tampak sah. Dilarang.
- Satu field kosong, di luar rentang, NaN/inf, atau tidak valid membuat **seluruh skor** tidak dipakai
  (terverifikasi). Tidak ada nilai pengganti.
- Alasan "skor tidak dipakai" dicatat spesifik: `SCORE_ROW_MISSING`, `MODEL_RUN_NOT_REVIEWED`,
  `MODEL_RUN_REVIEWED_BY_SUBMITTER`, `MODEL_USAGE_NOT_APPROVED`, `SCORE_FIELDS_INCOMPLETE`,
  `SCORE_VALUES_INVALID`, dan, sejak 26 Nov 2026, `SCORE_CONTRACT_NOT_SERVING` (baris ada tetapi kontrak producer `SCHEMA_PARTIAL`/`INVALID_SCORE`), `SCORE_EXPIRED` (lebih dari 30 hari sejak cutoff; `serving_ready=false`), dan `SCORE_CUSTOMER_MISMATCH` (skor milik ID lain). Setiap alasan dipetakan ke tiga keadaan tampilan `SCORE_MISSING` / `SCORE_PRESENT_NOT_APPROVED` / `SCORE_READY` (`UI_SCORE_STATES_SPEC.md`).
- Alasan churn kurang dari 3 **bukan** alasan menolak skor (P7, final dari sisi Christ; taxonomy: `approved/reason_taxonomy.md`).
- **"Mode terbatas per aksi"** (mis. tetap jalankan RETENTION walau propensity kosong) secara teknis
  mungkin, tetapi `AIScores` saat ini mewajibkan semua field float sehingga butuh perubahan engine
  (field opsional + tabel syarat per aksi di §2). **Usulan: tunda ke tahap 2**, setelah CLV dan
  lifecycle benar-benar tersedia. Menambahkannya sekarang berarti mengubah engine untuk data yang
  belum ada. ⚠️ Mentor/Moses boleh meminta sebaliknya.

## 4. Kontrak yang harus disediakan loader (`api/` atau orchestration)

`services/decision/nba/serving.py::lookup_scores` menerima **satu dict per pelanggan**.
Dict ini adalah gabungan beberapa sumber; **tabel review existing tidak memuatnya sekaligus** (lihat §6).

| Kunci | Sumber yang diharapkan | Aturan |
|---|---|---|
| `churn_score`, `churn_risk_band`, `reason_codes` | `ml.prediction_review_records` tipe CHURN | Cutoff terbaru yang sah, status record valid (bukan `SCHEMA_PARTIAL`/`INVALID_SCORE`) |
| `propensity_purchase`, `propensity_renew` | prediksi propensity (Moses) | Skor yang sama-sama sah dan belum expired |
| `clv_amount`, `clv_tier` | CLV (Moses) | Hanya dari sumber yang disetujui. Dev-only tidak boleh |
| `lifecycle_stage` | segmentasi lifecycle | Hanya versi aturan yang disetujui |
| `score_generated_at` | turunan `cutoff_at` | **Bukan** waktu impor (publikasi tidak boleh memperpanjang masa berlaku) |
| `model_version` | run prediksi | Dicatat ke `rationale` keputusan |
| `review_status`, `reviewed_by`, `submitted_by` | run prediksi | `reviewed` **dan** reviewer ≠ pengirim |
| `model_author` (opsional) | catatan pelatih model | Bila ada, reviewer ≠ pembuat model |
| `usage_approved` | **belum ada sumbernya** | Harus `True` boolean. `reviewed` saja bukan izin pakai |

Aturan baca: **satu baris per pelanggan, cutoff terbaru yang sah, tanpa menggabungkan skor dari cutoff
berbeda.** Bila komponen berasal dari cutoff berbeda, jadikan skor tidak lengkap, jangan ditambal.

## 5. Input non-skor (butir Christ #2 di TEAM_ALIGNMENT §6)

Aturan: **tidak ada izin otomatis dari data kosong.**

| Sumber | Belum tersambung | Tersambung tapi kosong |
|---|---|---|
| Consent | `None` → "belum ada keputusan promosi" | `UNKNOWN`/expired → diblokir (kebijakan K-10 `BLOCKED`) |
| Komplain | `None` → belum ada keputusan | `[]` → tidak ada komplain |
| Riwayat kontak | `None` → belum ada keputusan | `[]` → belum ada kontak |
| Kelayakan (tenure, membership) | `None` → belum ada keputusan | tidak ada keadaan "kosong" |
| Ketersediaan produk | `None` → belum ada keputusan | daftar kosong = tidak ada pembatasan |

⚠️ **Temuan untuk `api/decisions.py`:** endpoint evaluate sekarang membuat `EligibilityProfile` dengan
`tenure_days=0` dan `has_active_membership=False`. Itu menyatakan "pelanggan ini bukan anggota",
padahal sumbernya belum ada. Padahal P4 di pesan Moses menegaskan *"tidak ada baris ≠ non-member"*.
Disarankan mengirim `None` sampai sumber kelayakan tersambung.

## 6. Dampak ke keputusan lain (D1–D4)

- **D1 (tabel review cukup?):** untuk **menyimpan** skor, ya. Untuk **dikonsumsi NBA**, kurang pada tiga hal:
  (1) tidak ada kolom izin pakai, (2) hanya satu skor per tipe sehingga CLV dan lifecycle harus
  datang dari sumber lain, (3) `cutoff_at` berupa string. Usulan perubahan **minimal**: tambah status
  izin pakai + penyetuju + waktu pada run, **tanpa tabel baru**; penggabungan komponen dilakukan loader.
- **D2 (siapa reviewer):** dari sisi bisnis, `reviewed` ≠ `disetujui`. NBA hanya memakai skor bila
  `usage_approved is True`. Sampai sumbernya ada, NBA menjawab "belum disetujui untuk dipakai".
  Itu perilaku yang benar, bukan bug.
- **D3 (pemilihan skor):** cutoff terbaru yang sah, kedaluwarsa 30 hari dari cutoff, sebagian = ditolak.
- **D4 (Golden ID → ID aplikasi):** NBA memakai `golden_customer_id or customer_code` sebagai
  `customer_ref`. Pelanggan tanpa pemetaan pasti atau pelanggan demo **tidak boleh dievaluasi**
  (tanpa tebakan).

## 7. Alasan: kenapa dua jenis kalimat dipisah

| Pertanyaan | Sumber tunggal |
|---|---|
| "Kenapa **skor** ini tinggi/rendah?" | Formatter Moses `score_explanations.explain_contributions` (`score-explanation-id-1.0`) |
| "Kenapa **keputusan** ini (aksi atau tidak ada aksi)?" | `services/decision/nba/explain.py` (`plain-id-1.1`) |

`explain.py` **tidak menerjemahkan reason code sendiri** (versi sebelumnya melakukannya; sudah dihapus).
Ia menyisipkan kalimat Moses **apa adanya** hanya bila skor benar-benar dipakai, dan membuang bentuk
yang tidak valid tanpa memperbaikinya. Versi penjelasan dicatat di `rationale.score_explanation_version`.

## 8. Yang belum diputuskan (⚠️)

1. **Band:** memakai cut-off FRD (0,30 / 0,60 / 0,80, `frd-requirement-capstone-2.1-dev`) yang Moses
   tandai "menunggu keputusan baseline-review". Usulan Christ: pakai itu, tetapi butuh persetujuan.
2. **Pemetaan tier CLV** (Gate A D2) dan **faktor retensi CLV** masih terbuka; selama itu CLV tidak
   boleh dianggap siap serving.
3. **Mode terbatas per aksi** (§3): ditunda, butuh persetujuan.
4. **Sumber `usage_approved`**: butuh keputusan D1/D2 (Moses + reviewer + Christ).

## 9. Cara memverifikasi

```
python -m pytest tests/decision/test_nba_input_contract.py tests/decision/test_nba_serving.py -v
```
