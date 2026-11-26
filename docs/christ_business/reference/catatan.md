# Catatan Pengerjaan — Christ (Orang 2: Decisioning, Activation & Measurement)

Aturan kerja: hanya menyentuh area Christ (`services/decision/`, `tests/decision/`, `docs/christ_business/`). Tidak ada perubahan di `api/`, `worker/`, `web/`, `migrations/`, `services/data/`, `contracts/`, `docs/moses_data_ai/`, `docker-compose.yml`, `.env.example`.

---

## Bagian A — Update Project Manager (Moses), 26 November 2026

### A.1 Status to-do Christ

| To-do (bagian A update Moses) | Status | Hasil |
|---|---|---|
| 1. Jawab P1–P8 di issue #70 (atau tulis "final") | **Draf siap, belum diposting** | `docs/christ_business/integration/JAWABAN_P1_P8_ISSUE70_CHRIST.md`. Christ meninjau dan menempelkannya ke issue #70. Saya tidak punya akses GitHub. |
| 2. Tulis 14 skenario UAT + hasil yang diharapkan | **Selesai** | `docs/christ_business/demo/UAT_PLAN.md` (14 skenario, selaras dengan 12 skenario wajib TEAM_ALIGNMENT §7) |
| 3. Rancang UI untuk 3 keadaan skor | **Selesai (rancangan + sisi engine)** | `docs/christ_business/integration/UI_SCORE_STATES_SPEC.md` + perubahan `services/decision/nba/serving.py` |

Bukan keputusan yang saya ambil: semua isi jawaban P1–P8 berstatus **USULAN**. D2/D3/D5 dan penunjukan orang (reviewer, PIC, penandatangan UAT) menunggu meeting. Tidak ada `usage_approved`, band, atau angka bisnis yang diisi.

### A.2 Yang dikerjakan, per folder dan file

**`services/decision/nba/serving.py` (diubah; kode Christ)**
- Alasan baru `SCORE_CONTRACT_NOT_SERVING`: baris skor yang ADA tetapi berstatus kontrak `SCHEMA_PARTIAL`/`INVALID_SCORE` (kunci opsional `contract_status` pada baris) kini dibedakan dari "baris tidak ada".
- Alasan baru `SCORE_EXPIRED`: skor lebih dari 30 hari sejak cutoff diberi label tidak dipakai. Aturan umur tetap satu sumber (engine); perilaku keputusan tidak berubah (engine tetap menerima skor dan menurunkannya ke default konservatif).
- Alasan baru `SCORE_CUSTOMER_MISMATCH`: skor milik pelanggan lain, atau `customer_id` kosong/tidak identik, ditolak; ID pelanggan lain tidak ditampilkan.
- Fungsi `score_state_for` dan properti `ScoreLookup.state`: memetakan setiap alasan ke tiga keadaan `SCORE_MISSING` / `SCORE_PRESENT_NOT_APPROVED` / `SCORE_READY`. Alasan tak dikenal = fail-closed ke keadaan 2.
- `ScoreLookup.usable` kini juga mensyaratkan tidak ada alasan penolakan.
- Respons `to_api_response` menambah `score_state`, `score_unavailable_reason`, `model_review_status`; kolom `rationale` menambah `score_state`. Semua penambahan **aditif** (tidak ada field yang dihapus atau diubah artinya, kecuali `serving_ready`, lihat A.3 temuan 2).

**`tests/decision/test_score_states.py` (baru, 43 test)**: tiga keadaan, pending vs rejected, kontrak non-serving, kedaluwarsa 30/31 hari, ID tidak cocok, dan "skor siap tidak berarti keputusan siap bila sumber lain belum tersambung".

**`tests/decision/test_cross_segment_matrix.py` (baru, 15 test)**: matriks CHURNED/REACTIVATED/NEVER_TRANSACTED × RM_CONTACT / RENEWAL_REMINDER / COMPLAINT_RESOLUTION dan prioritas opt-out; bukti jawaban P2. Mencatat perilaku **saat ini (Opsi A)**, bukan keputusan final.

**`docs/christ_business/integration/JAWABAN_P1_P8_ISSUE70_CHRIST.md` (baru)**: jawaban P1–P8, status D1–D7, konfirmasi mentor yang terbuka, dan posisi Christ untuk meeting.

**`docs/christ_business/integration/UI_SCORE_STATES_SPEC.md` (baru)**: penyebab tiga keadaan tampil sama, definisi tiap keadaan, tabel alasan → teks (siap disalin Marvin ke `scoreAvailabilityLabel`), sketsa kartu, aturan "Kosong", dan permintaan perbaikan loader.

**`docs/christ_business/demo/UAT_PLAN.md` (ditulis ulang)**: 14 skenario beserta prasyarat, hasil diharapkan, tes otomatis yang menjaganya, dan kesiapan dijalankan. Semua "Hasil aktual" tetap `BELUM DIJALANKAN`. Skrip demo lama dipertahankan.

**`docs/christ_business/reference/catatan.md`**: file ini.

### A.3 Temuan

1. **Akar "ketiganya tampil SCORE_ROW_MISSING"** ada di dua tempat. Sisi Christ sudah diperbaiki (di atas). Sisi loader **belum**: `api/decision_inputs.py::load_serving_score_row` mengembalikan `None` untuk status kontrak `SCHEMA_PARTIAL`/`INVALID_SCORE`, sedangkan producer Moses saat ini hanya menghasilkan dua status itu. Selama itu tidak diubah, semua skor Moses yang sudah tersimpan tetap tampil "belum ada". Ini milik James/Moses (lihat A.4).
2. **Skor kedaluwarsa tampil siap.** Sebelum perbaikan, skor berumur 31 hari menghasilkan `serving_ready = true` padahal keputusannya `NO_ACTION` dengan `degraded_input = true`. Sekarang `serving_ready = false` untuk kasus itu (perubahan arti `serving_ready` yang disengaja). Jika Marvin sudah memakai `serving_ready` di UI, perilakunya menjadi lebih benar, bukan lebih longgar.
3. **Skor pelanggan lain bisa dipakai.** `lookup_scores` tidak membandingkan `customer_id` baris dengan pelanggan yang dievaluasi (skor `ORANG-LAIN-999` dipakai untuk `GOLD-0001`). Loader memfilter per ID sehingga risikonya kecil, tetapi tidak ada pertahanan berlapis. Kini ditolak.
4. **Run "ditolak" dan "menunggu" berbagi kode** `MODEL_RUN_NOT_REVIEWED` (dikunci test lama). Saya tidak mengubah kode itu; UI memilih teks dari `model_review_status`.
5. **Jawaban P6:** tiga contoh pembulatan dari Moses (`x99999,5`) tidak membedakan half-up dan half-even. Usulan contoh pembeda ada di jawaban P6.
6. **Jawaban P4:** data hanya punya event membership `JOIN`/`RENEWAL`; tidak ada event "penggunaan membership". Usulan memakai transaksi/kunjungan saat membership aktif sebagai proksi.
7. **Jawaban P2:** konflik lintas segmen vs NO_ACTION praktis hanya nyata untuk REACTIVATED (CHURNED hampir pasti CLV ≈ 0 dan tanpa membership aktif).

### A.4 Catatan untuk rekan (tanpa menyentuh file mereka)

**James** (`api/`, `worker/`, `.env.example`, `docker-compose.yml`)
- `api/decision_inputs.py::load_serving_score_row`: jangan kembalikan `None` untuk status kontrak non-serving; sertakan `"contract_status": record.contract_status` di dict. Sisi engine sudah siap dan tetap fail-closed (tidak ada skor yang dipakai). Perbarui test James yang mengharapkan `None`. Detail: `UI_SCORE_STATES_SPEC.md` §5.
- To-do James di update PM (folder `PREDICTION_IMPORT_ROOT`, estimasi feed historis) tidak menyentuh area Christ.
- `api/decisions.py` dan `worker/tasks.py` masih mengirim consent/komplain `None` (belum tersambung): UAT-10 dan UAT-01 baru bisa dijalankan setelah itu.

**Marvin** (`web/`, `api/monitoring.py`)
- Terapkan `score_state`, `score_unavailable_reason`, `model_review_status`: tabel di `UI_SCORE_STATES_SPEC.md` §3 siap disalin ke `scoreAvailabilityLabel` di `web/src/App.tsx`. Kode baru `SCORE_CONTRACT_NOT_SERVING`, `SCORE_EXPIRED`, `SCORE_CUSTOMER_MISMATCH` sementara jatuh ke teks default "Skor belum dapat digunakan".
- Skor/band/CLV/EV tampil `Kosong` untuk keadaan 1 dan 2; `expected_value = null` berarti Kosong, bukan Rp 0.
- Pastikan evaluate menolak `customer_id=true` (to-do Marvin) tanpa mengubah `services/decision`.

**Moses** (`services/data/`, `worker/prediction_import.py`)
- `usage_approved` tetap `None` sampai D2 diputuskan; Christ tidak mengisinya. Keadaan 3 hanya bisa dilihat setelah itu.
- Boundary test P1 dapat ditulis dari tabel di jawaban P1 setelah Christ menyatakan "final".
- `services/data/models/score_contract.py` masih mengimpor `AIScores` dari `services.decision.nba.engine`: jangan mengubah nama/field `AIScores` tanpa kabar ke Christ. Saya tidak mengubah `AIScores`.

### A.5 Yang perlu Christ lakukan

1. Baca `JAWABAN_P1_P8_ISSUE70_CHRIST.md`, ubah bagian yang tidak sesuai pendapatmu, lalu tempel ke issue #70. Untuk P2, pilih Opsi A atau B. Untuk P1, P3, P5, P6, P7 nyatakan "final" bila setuju.
2. Kirim review Gate A (`GATE_A_REVIEW_REQUEST_2026-11-19.md`) ke mentor; v1.4 masih PENDING dan tidak boleh self-approve.
3. Ikut meeting 30–45 menit (D2/D3/D5 dan lainnya); bawa Bagian 4 di file jawaban.
4. Jalankan UAT hanya setelah urutan C dari Moses selesai (gate izin pakai → folder artefak → UI → UAT).

### A.6 Verifikasi (dijalankan sebelum menyerahkan)

| Pemeriksaan | Hasil |
|---|---|
| `pytest tests/decision` | 942 passed |
| `pytest tests` (tanpa `tests/integration`, DB sqlite seperti CI) | **1736 passed**, 0 xfail |
| `pytest docs/christ_business/reference/test` | 107 passed |
| `ruff`, `black --check`, `mypy services/decision` | bersih |
| Sintaks Python 3.11 (versi di CI) | tidak ada sintaks khusus 3.12 |
| `run_demo.py` | exit 0 |
| Diff terhadap zip terbaru | hanya 4 file diubah + 5 file baru, semuanya di area Christ (daftar di Bagian A.2 dan Bagian B) |

Perintah ulang:
```
export DATABASE_URL=sqlite:// JWT_SECRET=<min 32 karakter>
python -m pytest tests/decision -q
python -m pytest tests -q --ignore=tests/integration
ruff check services/decision tests/decision && black --check services/decision tests/decision
mypy services/decision --ignore-missing-imports
PYTHONPATH=. python docs/christ_business/demo/run_demo.py
```

### A.7 Hal yang sengaja tidak dilakukan
- Tidak mengisi `usage_approved`, band, tier, CLV, atau angka bisnis; tidak menyetujui `target_definitions.md`.
- Tidak mengubah `api/`, `worker/`, `web/`, loader, migrasi, `.env.example`, atau `docker-compose.yml`.
- Tidak memposting ke issue #70/#71 (tidak ada akses GitHub).
- Tidak mengubah `evaluator.py` untuk P2: itu bergantung pada pilihan Opsi A/B oleh Christ.

---

## Bagian B — Pengerjaan sebelumnya: penutupan 3 xfail Safety Scanner

> Perubahan ini berasal dari sesi sebelumnya. **Zip terbaru tidak memuatnya** (`safety.py` dan `test_phase4_hardening.py` identik dengan versi lama), jadi saya memasangnya ulang pada basis zip terbaru. Bila Christ tidak ingin memakainya, kembalikan dua file itu ke versi zip; tidak ada file lain yang bergantung padanya.

Dicatat: 26 Nov 2026. Isi: apa yang dicek, apa yang diubah (folder, file, isi), dan catatan untuk rekan tim.
Aturan: hanya menyentuh area Christ (`services/decision/`, `tests/decision/`, `contracts/`, `docs/christ_business/`).

### 1. Hasil pengecekan (sebelum perubahan, angka pada sesi itu)

| Pemeriksaan | Hasil |
|---|---|
| `pytest tests/decision` | 872 passed, 3 xfailed |
| `pytest tests` (seluruh repo, tanpa `tests/integration`, DB = sqlite seperti CI) | 1645 passed, 3 xfailed |
| `pytest docs/christ_business/reference/test` | 107 passed |
| `ruff`, `black --check`, `mypy services/decision` | bersih |
| Sintaks Python 3.11 (versi di CI) | tidak ada sintaks khusus 3.12 di `services/decision` dan `tests/decision` |
| Rumus: EV, Incremental Revenue, fatigue 2 kontak/14 hari, holdout 10% (SHA-256) | sesuai Panduan |
| Kelengkapan file Fase 1-4 menurut Panduan | semua ada, kecuali yang tercantum di bagian 4 |

### 2. Perubahan yang dilakukan (3 file, semuanya milik Christ)

#### a. `services/decision/nudge/safety.py` (diubah)
Menutup 3 "risiko sisa" yang sebelumnya ditandai xfail:
- **Homoglyph Kiril/Yunani**: `_normalize` kini melipat huruf mirip (mis. `а` Kiril) ke Latin lewat `_HOMOGLYPH_MAP`.
- **Huruf berjarak** ("p a s t i", "m.e.d.i.s"): fungsi baru `_collapse_spaced_letters` merapatkan 3+ huruf tunggal berpemisah, lalu dipindai ulang.
- **Diskon ditulis kata** ("sembilan puluh persen"): `_parse_indonesian_number` dan `_numberwords_to_digits` mengubahnya ke angka (0-199), lalu pola diskon yang ada memeriksa pagu.
- `scan_message` kini memindai teks dasar + varian (hanya bila berbeda dari dasar, tanpa duplikat). Isi pemindaian dipindah ke `_scan_normalized`. Teks biasa berperilaku persis seperti sebelumnya.
- `scan_message` hanya dipakai `services/decision/nudge/generator.py` (milik Christ). API, worker, dan kode Moses tidak memanggilnya.

#### b. `tests/decision/test_phase4_hardening.py` (diubah)
- Kelas `TestResidualRisks` (3 test xfail strict) diganti `TestEvasionTechniquesAreDetected`: 3 test asli menjadi test biasa, ditambah test titik (`m.e.d.i.s`), diskon kata di atas pagu (+ `requires_escalation`), dan test false-positive (diskon tepat 30%, "Paket A B C", "opsi a, b, atau c", teks poin biasa).
- Docstring bagian D diperbarui.

#### c. `docs/christ_business/reference/catatan.md` (dibuat)
File ini.

### 3. Hasil setelah perubahan (angka pada sesi itu; angka terbaru ada di A.6)
`pytest tests` (tanpa integration): **1657 passed, 0 xfailed**. `tests/decision` hijau, `reference/test` 107 passed, ruff/black/mypy bersih, `run_demo.py` jalan (exit 0).

**Dampak ke Lampiran M:** "risiko sisa" homoglyph / huruf berjarak / diskon kata tidak lagi berlaku. Risiko yang masih ada: teknik penghindaran lain di luar blacklist (mis. leetspeak "p4sti", sinonim). Mitigasi tetap: variabel whitelist, panjang fakta <= 60, Human Approval wajib. Perbarui Defect Log bila sudah ditulis.

### 4. Yang masih kurang / perlu tindakan Christ
1. **Gate A belum ditutup**: `target_definitions.md` v1.4 masih PENDING (approver/tanggal kosong). Tidak boleh self-approve. Kirim `GATE_A_REVIEW_REQUEST_2026-11-19.md` ke dosen/mentor. Butir D1 (90 vs 180 hari) paling menentukan.
2. **`docs/christ_business/FINAL_HANDOFF_CHRIST.md` belum ada** (target Minggu 15 di Panduan).
3. **Lampiran M, N, O belum ada** sebagai dokumen. Yang ada baru `demo/UAT_PLAN.md` (semua hasil "BELUM DIJALANKAN"). Bahan Lampiran M: laporan pytest di atas.
4. **`integration/HANDOFF_JAMES_MARVIN.md` §2 usang**: tertulis `api/decisions.py` "sekarang" memanggil `NBAEngine().decide()`. Kode terbaru James sudah memakai `evaluate_customer` dan `load_contact_history`. Rekomendasi: ubah §2 jadi "sudah tersambung" (belum diubah, karena belum diminta).
5. **UAT-13/14 (audit trail, data tersimpan di DB)** baru bisa diuji setelah consent/komplain/skor lengkap tersambung (lihat bagian 5).
6. **Micro-task 1 (`dec.action_catalogue`) tidak ada di repo ini.** Jika masih ada di branch lokal `71230997-Christ-Jevicto-2`, JANGAN di-push:
   - `0007_create_action_catalogue.py` bentrok: revisi `0007_pipeline_runs` (James) sudah memakai nomor 0007, sehingga akan ada 2 head Alembic dan langkah CI "Verify Alembic Heads" gagal.
   - Mengubah `migrations/versions/0005_governance_schemas_and_traceability.py` dan `api/models.py` berarti menyentuh file James.
   - ID aksinya (`RETENTION_CALL_OFFER`, dst.) berbeda dari `services/decision/nba/catalogue.py` dan `contracts/K-06` (`RETENTION_OUTREACH`, `CROSS_SELL`, `UPSELL`, dst.). Sumber kebenaran saat ini adalah catalogue.py + K-06, dan test `test_catalogue_k06.py` menjaga keduanya.
   - Bila tabel katalog di DB memang dibutuhkan, minta James membuat migrasi barunya (nomor setelah 0026) dengan ID dari catalogue.py.
7. **CI memakai Python 3.11, `pyproject.toml` menulis target py312.** Kode Christ aman di 3.11; cukup beri tahu James bila ingin diselaraskan.

### 5. Catatan untuk rekan tim (tanpa menyentuh file mereka)

**Untuk James (`api/`, `worker/`):**
- `api/decisions.py` dan `worker/tasks.py` masih mengirim `consent_doc=None` dan `complaint_tickets=None`. Di worker, `eligibility`/`product_suitability` belum dikirim sama sekali dan consent ditulis `UNKNOWN`. Akibatnya (fail-closed, benar) tidak ada rekomendasi promosi sampai sumber consent (`consent_events.csv`), komplain (`service_cases.csv`), kelayakan, dan kesesuaian produk dibaca dari DB. Mohon dibuat loader seperti `load_contact_history`; kirim `[]` hanya bila sumber tersambung dan memang kosong.
- Endpoint ganda `POST /next-best-actions` (manual) dan `/evaluate`: arahan mentor sisakan satu.

**Untuk Moses (`services/data/`):**
- `load_serving_score_row` mengisi `usage_approved = None` (sumbernya belum ada) sehingga `lookup_scores` menolak skor (`MODEL_USAGE_NOT_APPROVED`). Perlu kunci izin pakai yang terpisah dari `review_status = reviewed`.
- Importer baru mengirim skor churn, band, reason code. `propensity_purchase`, `propensity_renew`, `clv_amount`, `clv_tier`, `lifecycle_stage` masih `None` (`SCORE_FIELDS_INCOMPLETE`).
- `services/data/models/score_contract.py` mengimpor `AIScores` dari `services.decision.nba.engine`: jangan ubah nama/field `AIScores` tanpa kabar ke Christ.

**Untuk Marvin (`web/`):** tampilkan "kosong/belum tersedia" bila `expected_value == null`, `unavailable_sources` tidak kosong, atau `measurement_status == "AWAITING_OUTCOMES"`; jangan menampilkan angka contoh.

### 6. Cara memverifikasi
```
export DATABASE_URL=sqlite:// JWT_SECRET=<min 32 karakter>
python -m pytest tests/decision -q
python -m pytest tests -q --ignore=tests/integration
ruff check services/decision tests/decision && black --check services/decision tests/decision
mypy services/decision --ignore-missing-imports
PYTHONPATH=. python docs/christ_business/demo/run_demo.py
```
