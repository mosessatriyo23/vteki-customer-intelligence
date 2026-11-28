# Rancangan UI: tiga keadaan skor

**Dari:** Christ (Orang 2) · **Untuk:** Marvin (`web/`), James dan Moses (loader skor) · **Tanggal:** 26 November 2026
**Status:** rancangan; diperbarui 26 November 2026 setelah update terbaru James/Marvin/Moses. Christ tidak mengubah `web/` maupun `api/`; dokumen ini spesifikasi, hasil uji, dan usulan.
**Menjawab:** to-do PM "Rancang tampilan UI untuk tiga kondisi: skor belum ada / skor ada tapi belum disetujui / skor siap dipakai. Sekarang ketiganya sama-sama tampil `SCORE_ROW_MISSING`."

---

## 1. Kenapa ketiganya tampil sama

| # | Penyebab | Pemilik | Status |
|---|---|---|---|
| 1 | `load_serving_score_row` (`api/decision_inputs.py`) mengembalikan `None` bila record terbaru berstatus kontrak `SCHEMA_PARTIAL` atau `INVALID_SCORE`. `None` dibaca engine sebagai "baris tidak ada" (`SCORE_ROW_MISSING`). Padahal producer Moses saat ini **hanya** menghasilkan dua status itu, jadi semua skor yang sudah tersimpan tampil "belum tersedia". | James/Moses | **Selesai (zip 26 Nov):** loader kini mengirim `contract_status` dan field izin pakai dari DB; fallback `customer_code` dihapus (D4) |
| 2 | `lookup_scores` tidak punya alasan khusus untuk "ada, tetapi kontrak belum lengkap". | Christ | **Selesai** (alasan baru `SCORE_CONTRACT_NOT_SERVING`) |
| 3 | Respons tidak memuat satu field yang langsung menyatakan keadaan skor. | Christ | **Selesai** (`score_state`) |
| 4 | Kode `MODEL_RUN_NOT_REVIEWED` sama untuk run "menunggu" dan "ditolak". | Christ | **Selesai** (respons memuat `model_review_status`) |
| 5 | `scoreServingStatus` di `web/src/App.tsx` (zip 26 Nov) sudah membedakan kosong / menunggu / ditolak / belum diizinkan / siap, tetapi **belum** membedakan kedaluwarsa, kontrak belum lengkap, dan ID tidak cocok. Hasil uji: §8 | Marvin | **Belum** (7 dari 11 kondisi sesuai) |

Bukti sisi Christ: `tests/decision/test_score_states.py` (43 test). Dua temuan tambahan ikut diperbaiki: (a) skor berumur > 30 hari dulu tampil `serving_ready = true`, kini `SCORE_EXPIRED` + `serving_ready = false`; (b) skor milik pelanggan lain dulu bisa dipakai bila loader salah mengirim, kini ditolak dengan `SCORE_CUSTOMER_MISMATCH`.

## 2. Tiga keadaan

Field baru di respons `POST /decisions/next-best-actions/evaluate` dan di `rationale` tiap baris `dec.nba_decisions` (`score_state`, `score_unavailable_reason`, `model_review_status`). Di `rationale` tersimpan `score_state` dan `score_unavailable_reason`; `model_review_status` sudah ada di sana:

| Keadaan | Nilai `score_state` | Arti | Angka skor/EV tampil? |
|---|---|---|---|
| 1. Belum ada skor | `SCORE_MISSING` | Tidak ada baris skor untuk pelanggan ini | **Tidak** |
| 2. Skor ada, belum bisa dipakai | `SCORE_PRESENT_NOT_APPROVED` | Baris ada, tetapi belum direview / belum disetujui / kontrak belum lengkap / field kosong / nilai tidak valid / kedaluwarsa | **Tidak** |
| 3. Skor siap dipakai | `SCORE_READY` | Lolos semua gerbang | Ya (dari respons API saja) |

Alasan yang tidak dikenal diperlakukan sebagai keadaan 2 (fail-closed), tidak pernah 1 atau 3.

### Keadaan 1: Belum ada skor
- **Lencana:** `Belum ada skor` (abu-abu netral)
- **Pesan utama:** "Skor prediksi untuk pelanggan ini belum ada, jadi tidak ada angka yang dipakai."
- **Kolom skor, band, CLV, EV:** `Kosong`
- **Langkah berikutnya (teks kecil):** "Skor muncul setelah hasil model diimpor dan disetujui."

### Keadaan 2: Skor ada, belum bisa dipakai
- **Lencana:** `Skor ada, belum dipakai` (kuning/amber, **bukan** hijau)
- **Pesan utama:** kalimat menurut alasan (tabel §3)
- **Tampilkan hanya yang nyata dan tidak menyesatkan:** `model_version` dan status review. **Jangan** tampilkan nilai skor, band, CLV, atau EV, karena angka yang belum disetujui bisa terbaca sebagai angka resmi.
- **Langkah berikutnya:** sesuai alasan (tabel §3)

### Keadaan 3: Skor siap dipakai
- **Lencana:** `Skor siap dipakai` (hijau)
- **Tampilkan:** `model_version`, `expected_value` (format Rp titik, mis. `Rp 2.158.000`), kalimat `reason` apa adanya
- **Syarat tambahan:** lencana hijau **tidak sama** dengan "keputusan siap". Bila `unavailable_sources` tidak kosong, tampilkan panel terpisah (§4).

## 3. Alasan dan teks (untuk `scoreAvailabilityLabel`)

| `score_unavailable_reason` | Keadaan | Teks tampil | Langkah berikutnya |
|---|---|---|---|
| `SCORE_ROW_MISSING` | 1 | Skor prediksi belum tersedia. | Menunggu impor hasil model |
| `SCORE_CONTRACT_NOT_SERVING` | 2 | Skor sudah tersimpan, tetapi formatnya belum lengkap menurut kontrak, jadi belum dipakai. | Moses melengkapi kontrak skor |
| `MODEL_RUN_NOT_REVIEWED` + `model_review_status = pending_review` | 2 | Skor menunggu pemeriksaan reviewer. | Reviewer independen memeriksa run |
| `MODEL_RUN_NOT_REVIEWED` + `model_review_status = rejected` | 2 | Hasil model ditolak reviewer, jadi tidak dipakai. | Moses mengirim run baru |
| `MODEL_RUN_REVIEWED_BY_SUBMITTER` | 2 | Reviewer harus berbeda dari pengirim model. | Orang lain memeriksa ulang |
| `MODEL_USAGE_NOT_APPROVED` | 2 | Skor sudah diperiksa, tetapi belum disetujui untuk dipakai dalam keputusan. | Menunggu keputusan izin pakai (D2) |
| `SCORE_FIELDS_INCOMPLETE` | 2 | Data skor belum lengkap; skor tidak digunakan. | Moses melengkapi field yang kosong (`score_missing_fields`) |
| `SCORE_VALUES_INVALID` | 2 | Nilai skor tidak valid; skor tidak digunakan. | Moses memeriksa nilai skor |
| `SCORE_CUSTOMER_MISMATCH` | 2 | Skor yang ditemukan tidak cocok dengan identitas pelanggan ini, jadi tidak dipakai. | Tim data memeriksa pemetaan ID (D4) |
| `SCORE_EXPIRED` | 2 | Skor sudah kedaluwarsa (lebih dari 30 hari sejak cutoff), jadi tidak dipakai. | Moses menerbitkan skor baru |
| *(lainnya / tak dikenal)* | 2 | Skor belum dapat digunakan. | Hubungi tim data |
| *(kosong, `score_state = SCORE_READY`)* | 3 | Skor siap dipakai. | n/a |

Catatan: masa berlaku 30 hari dihitung dari cutoff/generasi skor, bukan waktu impor; tepat 30 hari masih sah, 31 hari kedaluwarsa (usulan D3, dikunci test `TestExpiredScoreIsNotReady`).

## 4. Skor dan sumber data lain

`score_state` hanya menjawab soal **skor**. Keputusan juga butuh consent, komplain, riwayat kontak, kelayakan, dan ketersediaan produk (`unavailable_sources`).

| `score_state` | `unavailable_sources` | Panel keputusan |
|---|---|---|
| `SCORE_READY` | kosong | Rekomendasi + alasan + EV. `serving_ready = true` |
| `SCORE_READY` | tidak kosong | Lencana skor hijau, tetapi panel keputusan: "Belum ada keputusan: sumber data berikut belum tersambung: …" EV `Kosong` |
| `SCORE_PRESENT_NOT_APPROVED` atau `SCORE_MISSING` | apa pun | Rekomendasi `NO_ACTION`, alasan menyebut skor (dan sumber yang belum tersambung bila ada). EV `Kosong`. Jalur layanan (`COMPLAINT_RESOLUTION`) tetap bisa muncul |

Aturan tegas:
1. Tidak ada angka contoh. Data kosong ditulis `Kosong`.
2. Jangan tampilkan label "AI" atau persentase yang tidak berasal dari respons API.
3. `expected_value == null` berarti `Kosong`, bukan `Rp 0`. Nol adalah nilai sah (`BELOW_MIN_EV`), null adalah tidak ada.
4. Selalu tampilkan `model_version` bila ada, dan `serving_ready`.

## 5. Perbaikan loader (James/Moses): sudah dikerjakan

Permintaan di versi 26 Nov pagi (kembalikan baris dengan `contract_status`, bukan `None`) sudah diterapkan di `api/decision_inputs.py` pada zip 26 Nov malam, berikut field izin pakai dari DB. Alurnya diuji Moses (impor → review → izin → NBA memakai skor → izin dicabut → skor diblokir) dan diulang di `docs/christ_business/demo/uat_dry_run.py` (UAT-03 sampai UAT-09: PASS). Tidak ada tindakan lanjutan untuk bagian ini.

## 6. Sketsa tampilan (satu kartu keputusan)

```
Keadaan 1                          Keadaan 2
+---------------------------+      +-------------------------------------+
| Rekomendasi: NO_ACTION    |      | Rekomendasi: NO_ACTION              |
| [Belum ada skor]          |      | [Skor ada, belum dipakai]   (amber) |
| Skor prediksi untuk       |      | Skor menunggu pemeriksaan reviewer. |
| pelanggan ini belum ada,  |      | Versi model: churn-dev-1.0          |
| jadi tidak ada angka      |      | Status review: pending_review       |
| yang dipakai.             |      | Skor / band / CLV / EV: Kosong      |
| Skor / band / CLV / EV:   |      | Berikutnya: reviewer independen     |
| Kosong                    |      | memeriksa run                       |
+---------------------------+      +-------------------------------------+

Keadaan 3 (sumber data lengkap)    Keadaan 3 (sumber belum lengkap)
+---------------------------+      +-------------------------------------+
| Rekomendasi: RETENTION_   |      | Belum ada keputusan                 |
| OUTREACH                  |      | [Skor siap dipakai]         (hijau) |
| [Skor siap dipakai] hijau |      | Sumber belum tersambung: data izin  |
| Perkiraan manfaat bersih  |      | kontak (consent).                   |
| Rp 2.158.000 (hasil hitung|      | EV: Kosong                          |
| sistem, bukan jaminan)    |      +-------------------------------------+
| Versi model: churn-dev-1.0|
+---------------------------+
```

## 7. Cara menerimanya (untuk Marvin dan UAT)

Tiga tangkapan layar dari data nyata di aplikasi yang berjalan dari repo:
1. Pelanggan tanpa baris skor → keadaan 1 (UAT-02).
2. Pelanggan dengan run `pending_review` → keadaan 2 dengan teks "menunggu pemeriksaan" (UAT-03); run `rejected` → teks "ditolak" (UAT-04); run `reviewed` tanpa izin pakai → "belum disetujui untuk dipakai" (UAT-06).
3. Skor siap → keadaan 3 **hanya setelah** D2/D3/D5 diputuskan dan `usage_approved = True` datang dari sumber yang disepakati. Jangan memaksa keadaan 3 dengan data buatan.

Jangan pernah mengisi `usage_approved = True`, band, atau angka bisnis demi memunculkan keadaan 3.

## 8. Hasil uji UI Marvin (zip 26 Nov) dan usulan perbaikan

**Cara uji:** fungsi `scoreServingStatus` dan `scoreAvailabilityLabel` diambil apa adanya dari `web/src/App.tsx` (tanpa mengubah file), lalu dijalankan dengan kondisi yang benar-benar dihasilkan backend (dari `uat_dry_run.py`). Skrip: `docs/christ_business/demo/ui_score_status_check.mjs` (Node 22.13 ke atas; `node docs/christ_business/demo/ui_score_status_check.mjs`).

| # | Kondisi (dari backend) | Teks UI saat ini | Sesuai? |
|---|---|---|---|
| 1 | Skor belum ada | Skor belum tersedia | Ya |
| 2 | Run menunggu review | Skor tersedia, menunggu pemeriksaan reviewer | Ya |
| 3 | Run ditolak | Skor ditolak saat review | Ya |
| 4 | Sudah direview, belum diizinkan | Sudah direview, belum disetujui untuk NBA | Ya |
| 5 | Kontrak belum lengkap + `pending_review` (**kondisi nyata hari ini**) | Skor tersedia, menunggu pemeriksaan reviewer | **Tidak**: menyesatkan, review pun tidak membuat skor bisa dipakai |
| 6 | Kontrak belum lengkap + reviewed | Skor belum dapat digunakan. | **Tidak**: teks umum |
| 7 | **Skor kedaluwarsa** | Skor belum dapat digunakan. | **Tidak**: tidak dibedakan |
| 8 | Skor milik ID lain | Skor belum dapat digunakan. | **Tidak**: teks umum |
| 9 | Field skor tidak lengkap | Data skor belum lengkap; skor tidak digunakan. | Ya |
| 10 | Skor siap, sumber lain belum lengkap | Skor disetujui; sumber NBA lain belum lengkap | Ya |
| 11 | Skor siap dan keputusan siap | Skor siap dipakai NBA | Ya |

**Penyebab:** `scoreServingStatus` memeriksa `modelReviewStatus` **sebelum** alasan skor, sedangkan engine memprioritaskan alasan yang tidak bisa diperbaiki review (ID tidak cocok, kontrak belum lengkap, kedaluwarsa); `scoreAvailabilityLabel` belum memuat tiga kode itu.

**Usulan perbaikan untuk Marvin** (diuji pada salinan sementara: 11 dari 11 sesuai; `web/` tidak diubah). Ganti kedua fungsi dengan:

```ts
function scoreAvailabilityLabel(code: string | null): string | null {
  if (!code) return null
  const labels: Record<string, string> = {
    SCORE_ROW_MISSING: 'Skor prediksi belum tersedia.',
    MODEL_RUN_NOT_REVIEWED: 'Skor menunggu pemeriksaan reviewer.',
    MODEL_RUN_REVIEWED_BY_SUBMITTER: 'Reviewer harus berbeda dari pengirim model.',
    MODEL_USAGE_NOT_APPROVED: 'Skor belum disetujui untuk digunakan.',
    SCORE_CONTRACT_NOT_SERVING: 'Skor sudah tersimpan, tetapi formatnya belum lengkap menurut kontrak, jadi belum dipakai.',
    SCORE_EXPIRED: 'Skor sudah kedaluwarsa (lebih dari 30 hari sejak cutoff), jadi tidak dipakai.',
    SCORE_CUSTOMER_MISMATCH: 'Skor yang ditemukan tidak cocok dengan identitas pelanggan ini, jadi tidak dipakai.',
    SCORE_FIELDS_INCOMPLETE: 'Data skor belum lengkap; skor tidak digunakan.',
    SCORE_VALUES_INVALID: 'Nilai skor tidak valid; skor tidak digunakan.',
  }
  return labels[code] ?? 'Skor belum dapat digunakan.'
}

function scoreServingStatus(
  decision: Pick<Decision, 'servingReady' | 'modelReviewStatus' | 'scoreUnavailableReason'>,
): string {
  if (decision.servingReady === true) return 'Skor siap dipakai NBA'
  const reason = decision.scoreUnavailableReason
  // Urutan mengikuti prioritas engine: alasan yang tidak bisa diperbaiki review didahulukan.
  if (reason === 'SCORE_ROW_MISSING') return 'Skor belum tersedia'
  if (reason === 'SCORE_CUSTOMER_MISMATCH') return 'Skor tidak cocok dengan pelanggan ini; tidak dipakai'
  if (reason === 'SCORE_CONTRACT_NOT_SERVING') return 'Skor ada, tetapi formatnya belum lengkap; belum dipakai'
  if (reason === 'SCORE_EXPIRED') return 'Skor kedaluwarsa; tidak dipakai'
  if (decision.modelReviewStatus === 'pending_review') return 'Skor tersedia, menunggu pemeriksaan reviewer'
  if (decision.modelReviewStatus === 'rejected') return 'Skor ditolak saat review'
  if (reason === 'MODEL_RUN_REVIEWED_BY_SUBMITTER') return 'Review tidak sah; reviewer harus orang berbeda'
  if (reason === 'MODEL_USAGE_NOT_APPROVED') return 'Sudah direview, belum disetujui untuk NBA'
  if (reason) return scoreAvailabilityLabel(reason) ?? 'Skor belum dapat digunakan'
  if (decision.modelReviewStatus === 'reviewed') return 'Skor disetujui; sumber NBA lain belum lengkap'
  return 'Status skor belum tersedia'
}
```

Catatan untuk Marvin:
1. Setelah menerapkan, jalankan `node docs/christ_business/demo/ui_score_status_check.mjs`; harus 11/11. Bila nama field di `App.tsx` berbeda dari yang dipakai skrip, sesuaikan skrip atau fungsinya, jangan mengubah hasil yang diharapkan.
2. Skor, band, CLV, dan EV tetap `Kosong` pada keadaan 1 dan 2; `expected_value == null` berarti Kosong, bukan Rp 0.
3. Tangkapan layar nyata tiap keadaan (§7) tetap dibutuhkan untuk UAT; skrip ini hanya menguji teks, bukan tampilan.
4. Baris keputusan lama yang tersimpan sebelum perbaikan serving bisa masih `serving_ready = true` untuk skor yang kini dianggap kedaluwarsa; evaluasi ulang menghasilkan nilai yang benar.

## 9. Faktor konteks (alasan churn tambahan) di UI

Respons evaluate dan `rationale` kini memuat `context_factors`: daftar `{code, text, source}` (`source` selalu `BUSINESS_RULE`). Ini **bukan kontribusi model**.

| Aturan tampilan | Isi |
|---|---|
| Judul daftar | **Faktor konteks (aturan bisnis, bukan hasil model)**, terpisah dari alasan model |
| Teks | Tampilkan `text` apa adanya; jangan menulis ulang |
| Kosong | Bila `context_factors` kosong, **jangan menampilkan apa pun** (jangan "tidak ada faktor"; kosong berarti tidak ada atau sumber belum tersambung) |
| Keadaan skor | Faktor konteks tidak bergantung pada skor: tetap tampil pada keadaan 1, 2, dan 3 karena itu fakta tentang pelanggan |
| Jumlah | Bila gabungan alasan model + faktor konteks < 3, tampilkan apa adanya (tanpa alasan palsu) dan teks "Hanya {n} alasan yang dapat dijelaskan dari data yang tersedia." |
| Hari ini | Daftar masih kosong karena feed kelayakan dan komplain belum tersambung (`unavailable_sources`); itu benar, bukan bug |

Kode yang mungkin muncul: `MEMBERSHIP_EXPIRING` ("Masa keanggotaan akan berakhir dalam 15 hari atau kurang.") dan `UNRESOLVED_COMPLAINT` ("Ada keluhan pelanggan yang belum selesai ditangani."). `NO_CROSS_CATEGORY` tidak pernah muncul.
