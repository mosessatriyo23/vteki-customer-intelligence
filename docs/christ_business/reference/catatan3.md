# Catatan Pengerjaan 3 — Christ (Orang 2: Decisioning, Activation & Measurement)

Lanjutan `catatan2.md`. Dikerjakan 28 November 2026, menanggapi tiga jawaban Christ atas butir yang akan diajukan ke mentor:

| Butir | Jawaban Christ | Arti dan pelaksanaan |
|---|---|---|
| 1. Horizon churn 90 hari | **setuju** | Sikap penyusun ditegaskan di `target_definitions.md` §1.1 |
| 2. Alasan churn kurang dari 3 | **ubah: tambahkan alasan menurut pertimbangan saya** | Ditambah dua faktor konteks bisnis (§2) |
| 3. Pembulatan CLV half-up ke rupiah | **ubah menurut pertimbangan saya** | Diubah: tier dari nilai tepat, half-up hanya simpan/tampil (§3) |

Catatan Christ: **jangan berhalusinasi; gunakan jawaban yang relevan untuk proyek ini.** Karena itu setiap perubahan di bawah dicek dulu terhadap kode, kontrak, dan data yang benar-benar ada di repo.

**Cara saya membaca jawaban itu:** sebagai **keputusan Christ sendiri**, bukan balasan tertulis dari mentor (Gio). Karena itu kolom approver/tanggal di `target_definitions.md` **tetap PENDING**, dan butir 2 dan 3 yang kini berubah harus dikirim ulang ke mentor. Bila jawaban itu sebenarnya balasan tertulis mentor, beri tahu saya agar dicatat sebagai persetujuan beratribusi, dan jangan diisi sebelum ada buktinya.

**Aturan kerja:** hanya `docs/christ_business/`, `services/decision/`, `tests/decision/`. Tidak ada perubahan di `api/`, `worker/`, `web/`, `migrations/`, `services/data/`, `contracts/`, `.github/`.

---

## 1. Butir 1: horizon 90 hari (setuju)

Tidak ada perubahan keputusan. Panduan kerjamu sendiri menetapkan window 90 hari (Minggu 1), `labels.py` menolak horizon selain 90, dan Requirement menulis 180 dan 90 dalam bab yang sama. Yang diubah hanya penegasan: `target_definitions.md` §1.1 kini mencatat "horizon 90 hari dipertahankan (sikap penyusun, bukan persetujuan dosen)". Konfirmasi mentor tetap diminta.

## 2. Butir 2: alasan churn ditambah

**Yang dicek dulu (supaya tidak mengarang):** dari enam kode alasan v1.4, mana yang punya data dan aturan nyata di proyek?

| Kode v1.4 | Dasar nyata di repo | Keputusan |
|---|---|---|
| `RECENCY_LONG`, `FREQUENCY_DROP`, `SPEND_DECLINE` | Ada fitur model (7 fitur di `churn_reasons.py`) | Sudah aktif sebagai alasan model (26 Nov) |
| `MEMBERSHIP_EXPIRING` | Aturan nyata: `RENEWAL_REMINDER` memakai `has_active_membership` dan `membership_days_remaining <= 15` (`evaluator.py`); data ada di `EligibilityProfile` | **Diaktifkan** sebagai faktor konteks |
| `UNRESOLVED_COMPLAINT` | Status tiket nyata (`OPEN_SEVERE`, `OPEN_MILD`, `IN_PROGRESS`) di `suppression.py` | **Diaktifkan** sebagai faktor konteks |
| `NO_CROSS_CATEGORY` | `target_definitions.md` §3.2.C sendiri menulis syarat kategori "tidak ditegakkan, tidak ada data kepemilikan kategori" | **Tetap tidak aktif** |

**Prinsip yang menjaga kejujuran:** keduanya adalah **faktor konteks bisnis** (aturan deterministik atas data yang sudah menjadi masukan engine), **bukan kontribusi model**. Selalu ditandai `source = BUSINESS_RULE`, dipisahkan dari alasan model, dan tidak mengubah aksi yang dipilih. Sumber yang belum tersambung (`None`) tidak menghasilkan faktor apa pun.

**Kejujuran tentang manfaatnya:** consent, komplain, dan kelayakan belum tersambung di `api/decisions.py` dan `worker/tasks.py`. Jadi **hari ini daftar faktor konteks masih kosong**, dan hampir semua pelanggan tetap hanya punya alasan model (maksimum 4). Penambahan ini baru berdampak setelah James menyambungkan feed. Penyimpangan dari "minimal 3" tidak hilang; hanya jarang terjadi bila feed lengkap.

**Interpretasi yang perlu diketahui mentor:** menghitung faktor konteks ke target tiga adalah pilihan saya. Bila mentor lebih suka hanya alasan model yang dihitung, aturan "kurang dari 3 tetap tampil tanpa alasan palsu" sudah mencakupnya.

## 3. Butir 3: pembulatan CLV (diubah, dengan koreksi)

**Temuan yang mengoreksi pekerjaan saya sendiri.** Jawaban 26 Nov ("bulatkan dulu half-up, tier setelah pembulatan") **tidak sesuai kode**. `services/data/models/business_clv.py` tidak membulatkan sama sekali: tier ditentukan dari float yang belum dibulatkan dengan `>=` ke 200.000 / 500.000 / 1.000.000. Diverifikasi dengan menjalankan fungsinya: 199.999,5 → `INSUFFICIENT_HISTORY`, 499.999,5 → `SILVER`, 999.999,5 → `GOLD`. Jadi dokumen 26 Nov menjanjikan perilaku yang tidak ada dan meminta Moses menambah boundary test untuk perilaku itu.

**Keputusan baru:**
1. **Tier ditentukan dari nilai CLV tepat** (aturan minimal 2 transaksi tetap). Sama dengan kode sekarang, **tanpa perubahan kode**.
2. **Pembulatan hanya untuk simpan/tampil**: half-up ke rupiah utuh, `Decimal(str(nilai))` dengan `ROUND_HALF_UP`, paling akhir, tidak dipakai ulang untuk keputusan. (`Decimal(str())` menghindari artefak biner float: `Decimal(2.675)` menghasilkan 2,67499999..., `Decimal("2.675")` menghasilkan 2,675.)
3. Konsekuensi yang diterima dan ditulis: nilai tampil 200.000 bisa berstatus `INSUFFICIENT_HISTORY` bila nilai tepat 199.999,5; tampilan harus menyebut "dibulatkan untuk tampilan".

**Mengapa ini lebih baik daripada versi 26 Nov:** tidak ada kenaikan tier karena selisih setengah rupiah; CLV memuat proyeksi dengan retention sebagai probabilitas sehingga presisi rupiah tidak bermakna; dan tidak ada pekerjaan tambahan untuk Moses. EV (`ev_calculator.py`, `round(ev, 2)`) tidak diubah dan bukan bagian keputusan ini.

## 4. Yang dikerjakan, per folder dan file

### `services/decision/nba/`
- **`context_factors.py` (baru).** Fungsi murni `compute_context_factors(customer_ref, eligibility, complaint_tickets)` menghasilkan faktor `MEMBERSHIP_EXPIRING` (jendela 15 hari yang sama dengan `RENEWAL_REMINDER`) dan `UNRESOLVED_COMPLAINT`. Sumber `None` dan `[]` tidak menghasilkan faktor; data pelanggan lain diabaikan; urutan tetap; teks netral tanpa sebab atau angka uang. **Tidak memengaruhi pemilihan aksi.**
- **`serving.py` (diedit, aditif).** `DecisionOutput` punya field `context_factors`; `evaluate_customer` menghitungnya sebelum cek sumber (faktor dari sumber tersambung tetap dihitung walau sumber lain belum); `rationale` dan `to_api_response` memuat `context_factors`. Tidak ada field lama yang diubah.

### `tests/decision/`
- **`test_context_factors.py` (baru, 26 test).** Batas 15/16 hari; membership tidak aktif; profil pelanggan lain; semua status keluhan; keluhan pelanggan lain; sumber `None` vs `[]`; urutan; `NO_CROSS_CATEGORY` tidak pernah muncul; teks netral; faktor ikut respons API dan `rationale`; faktor **tidak mengubah aksi**; dan **keselarasan dengan aturan RENEWAL_REMINDER di engine** pada sisa 15 dan 16 hari (satu sumber kebenaran). Satu test sempat gagal karena kesalahan desain test saya (pada pelanggan ACTIVE, aksi lain memenangkan EV sehingga "aksi terpilih" bukan ukuran kelayakan); diperbaiki memakai segmen CHURNED tempat RENEWAL satu-satunya aksi yang lolos, bukan melemahkan test.

### `docs/christ_business/approved/`
- **`reason_taxonomy.md` (ditulis ulang, 10 bagian).** Dua jenis alasan (model dan konteks) selalu berlabel sumber; §3 faktor konteks (aturan, sumber data, teks); §4 hanya `NO_CROSS_CATEGORY` yang tidak aktif; §7 jumlah alasan dengan interpretasi yang perlu diketahui mentor; §8 teks Indonesia termasuk faktor konteks (identik dengan kode); §10 status terbuka per pemilik.
- **`target_definitions.md` (diedit).** §1.1 penegasan 90 hari; §1.3 ditulis ulang (alasan model + faktor konteks); §2.4 pembulatan dikoreksi + contoh yang diverifikasi terhadap kode; riwayat revisi v1.5 ditambah catatan revisi 28 Nov. Approver/tanggal tetap PENDING.
- **`GATE_A_REVIEW_REQUEST_2026-11-19.md` (diedit).** Catatan pembaruan kini memuat lima butir untuk dijawab tertulis oleh mentor.

### `docs/christ_business/integration/`
- **`JAWABAN_P1_P8_ISSUE70_CHRIST.md`**: P6 ditulis ulang dengan koreksi dan tabel contoh; P7 memuat faktor konteks; tabel status dan teks #70 disesuaikan.
- **`UI_SCORE_STATES_SPEC.md`**: bagian 9 baru, aturan tampilan `context_factors` untuk Marvin (judul "bukan hasil model", kosong = tidak tampil apa pun, tidak bergantung keadaan skor).
- **`D5_NBA_INPUT_CONTRACT.md`**: menyebut `context_factors` dan bahwa ia tidak memengaruhi aksi.

### `docs/christ_business/demo/`
- **`uat_dry_run.py` dan `UAT_HASIL_DRY_RUN.md`**: runner ditambah pemeriksaan faktor konteks pada UAT-01 dan UAT-10, dijalankan ulang. Hasil tetap **11 PASS, 3 TERHALANG, 0 FAIL**.
- **`UAT_PLAN.md`**: harapan UAT-01 dan UAT-10 menyebut `context_factors`.

### `docs/christ_business/reference/`
- **`catatan3.md`**: file ini. (`catatan2.md` dibiarkan sebagai log putaran 26 Nov; ia masih menyebut "tier setelah pembulatan", yang dikoreksi di sini.)

## 5. Catatan untuk rekan (tanpa menyentuh file mereka)

**Moses**
- **Pembulatan CLV: tidak ada perubahan kode.** Cukup boundary test untuk perilaku yang sudah ada (kolom "Tier" di `JAWABAN_P1_P8_ISSUE70_CHRIST.md` P6) dan, bila ada fungsi tampil, bulatkan dengan `Decimal(str(nilai))` + `ROUND_HALF_UP`. Mohon abaikan permintaan 26 Nov yang menyebut "tier setelah pembulatan".
- Penggabungan konsep alasan model dan penggantian nama `PURCHASE_RECENCY` (aktivitas, bukan hanya pembelian) tetap pekerjaanmu. Faktor konteks tidak perlu dibuat di producer; sudah ada di engine.

**James**
- Faktor konteks baru terisi setelah **feed kelayakan** (`EligibilityProfile`) dan **komplain** (`ComplaintTicket`) tersambung; kirim `None` bila belum ada, `[]` bila tersambung dan kosong. Ini juga syarat UAT-01, 10, 13.

**Marvin**
- Tampilkan `context_factors` sesuai bagian 9 spesifikasi UI: judul "Faktor konteks (aturan bisnis, bukan hasil model)", kosong berarti tidak menampilkan apa pun. Respons sudah memuat field ini.

## 6. Yang perlu Christ lakukan

1. **Kirim ulang ke mentor** butir yang berubah: butir 2 (faktor konteks + interpretasinya) dan butir 3 (pembulatan). Pesan siap pakai ada di balasan pengerjaan ini dan ringkasannya di `GATE_A_REVIEW_REQUEST_2026-11-19.md`. Jangan mengisi approver/tanggal sendiri.
2. Perbarui pernyataan #70 sesuai tabel status P6 dan P7 yang baru (teks siap tempel di `JAWABAN_P1_P8_ISSUE70_CHRIST.md`).
3. Beri tahu Moses bahwa pembulatan **tidak** membutuhkan perubahan kode.
4. Sebelum push: gunakan `black>=24,<26`; jangan ikutkan file di luar area Christ.

## 7. Verifikasi

| Pemeriksaan | Hasil |
|---|---|
| `pytest tests/decision` | 968 passed |
| `pytest tests` (tanpa `tests/integration`, sqlite seperti CI) | **1785 passed** (1759 sebelumnya + 26 baru) |
| `pytest docs/christ_business/reference/test` | 107 passed |
| `ruff check .`, `black --check .` (black 25.12, rentang CI), `mypy services api worker` | bersih |
| `run_demo.py` | exit 0 |
| `uat_dry_run.py` | 11 PASS, 3 TERHALANG, 0 FAIL |
| Contoh pembulatan | diverifikasi dengan menjalankan `calculate_business_clv` dan `Decimal` |
| Diff terhadap zip terakhir yang kamu kirim | 9 file diubah, 8 file baru (kumulatif termasuk putaran 26 Nov), semua di area Christ |

Perintah ulang:
```
export DATABASE_URL=sqlite:// JWT_SECRET=<min 32 karakter>
python -m pytest tests -q --ignore=tests/integration
ruff check . && black --check .          # black>=24,<26
mypy services api worker --ignore-missing-imports
PYTHONPATH=. python docs/christ_business/demo/uat_dry_run.py
```

## 8. Yang sengaja tidak dilakukan
- Tidak mengisi persetujuan mentor, `usage_approved`, band, tier, atau angka bisnis; tidak menyebut UAT lulus.
- Tidak mengaktifkan `NO_CROSS_CATEGORY` (tidak ada data) dan tidak menambah alasan dari fitur yang tidak ada di model.
- Tidak mengubah `business_clv.py`, `evaluator.py`, atau file di luar area Christ.
- Tidak membulatkan sebelum menentukan tier (itu yang saya koreksi).
