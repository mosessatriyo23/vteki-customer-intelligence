# Catatan Pengerjaan 2 — Christ (Orang 2: Decisioning, Activation & Measurement)

Lanjutan `catatan.md`. Dikerjakan 26 November 2026, menanggapi dua pesan Moses ("Aku sudah menulis tindak lanjut di #70 dan #71" dan "Update Moses — sisa pekerjaan sebelum pengumpulan").

**Aturan kerja:** hanya menyentuh area Christ: `docs/christ_business/`, `services/decision/`, `tests/decision/`. Tidak ada perubahan di `api/`, `worker/`, `web/`, `migrations/`, `services/data/`, `contracts/`, `docs/moses_data_ai/`, `docs/james_platform/`, `.env.example`, `docker-compose.yml`, `.github/`. Pada putaran ini `services/decision/` dan `tests/decision/` hanya disentuh satu file (docstring test, lihat §3).

---

## 1. Status to-do Christ dari Moses

| To-do | Status | Hasil |
|---|---|---|
| 1. Samakan dokumen dengan keputusan final: P2 Opsi A, P6 half-up `Decimal`, P7 alasan < 3 tetap tampil tanpa alasan palsu, P8 RFM di luar MVP | **Selesai (sisi dokumen)** | `target_definitions.md` v1.5 (draf), `JAWABAN_P1_P8_ISSUE70_CHRIST.md`, `UAT_PLAN.md`, `HANDOFF_JAMES_MARVIN.md`, `D5_NBA_INPUT_CONTRACT.md`, `GATE_A_REVIEW_REQUEST_2026-11-19.md`, docstring `test_cross_segment_matrix.py` |
| 2. Finalkan taxonomy alasan beserta teks Indonesianya | **Selesai (sisi Christ)** | `approved/reason_taxonomy.md` (baru). Implementasi penggabungan konsep di producer: pekerjaan Moses |
| 3. Pastikan UI membedakan skor kosong, belum diizinkan, kedaluwarsa, siap | **Diperiksa; UI belum sepenuhnya memenuhi** | 7 dari 11 kondisi sesuai; kedaluwarsa, kontrak belum lengkap, dan ID tidak cocok belum dibedakan. Usulan perbaikan terbukti 11/11: `integration/UI_SCORE_STATES_SPEC.md` §8. Perubahan di `web/` milik Marvin |
| 4. Jalankan 14 skenario UAT dan catat hasil asli, termasuk yang gagal | **Dry run di sandbox selesai; UAT resmi BELUM** | 11 PASS, 3 TERHALANG, 0 FAIL di `demo/UAT_HASIL_DRY_RUN.md`. Bukan UAT resmi (lihat §5) |

**Catatan tentang label "final":** Moses menulis keputusan P1–P8 mewakili tim dan meminta Christ menyamakan dokumen. Saya memperlakukan instruksimu untuk mengerjakan pesan itu sebagai konfirmasi untuk **P2 (Opsi A), P6, P7, P8, dan taxonomy**, ditandai "final dari sisi Christ". **Persetujuan mentor tetap PENDING dan tidak diisi** (kolom approver/tanggal di `target_definitions.md` kosong). P1, P3, P4, P5 **tidak** saya ubah menjadi final; tetap USULAN sampai kamu menyatakannya. Bila ada yang tidak sesuai pendapatmu, ubah label di `JAWABAN_P1_P8_ISSUE70_CHRIST.md` (tabel "Pernyataan status per poin").

## 2. Keadaan zip terbaru (hasil pekerjaan orang lain yang saya periksa)

- **Loader skor (James/Moses)** sudah memenuhi permintaan §5 spesifikasi UI: `api/decision_inputs.py` mengirim `contract_status` dan field izin pakai dari DB. Skor yang tersimpan kini tampil "ada, belum dipakai", bukan "belum ada". Tidak ada tindakan lanjutan.
- **D4** sudah dikerjakan: pelanggan tanpa pemetaan Golden pasti ditolak (409); `customer_code` hanya tersisa sebagai label baris trace, bukan identitas fallback.
- **Izin pakai (migrasi 0027)**: admin memberi/mencabut izin, tercatat di audit, reviewer harus orang lain; terbukti lewat dry run (UAT-04, 05, 06).
- Area Christ di zip terbaru **identik** dengan yang saya serahkan sebelumnya (tidak ada yang mengubah file Christ). Test seluruh repo: 1759 lulus.
- **Belum tersambung**: consent, komplain, kelayakan, kesesuaian produk (masih `None` di `api/decisions.py` dan `worker/tasks.py`; consent pada job campaign ditulis `UNKNOWN`). Akibatnya NBA belum bisa menghasilkan keputusan promosi lewat API. Ini yang membuat UAT-01, UAT-10, UAT-13 TERHALANG.

## 3. Yang dikerjakan, per folder dan file

### `docs/christ_business/approved/`
- **`reason_taxonomy.md` (baru).** Taxonomy alasan churn versi `christ-reason-taxonomy-1.5-draft`:
  - Empat konsep aktif sesuai fitur model yang benar-benar ada (`RECENCY`, `FREQUENCY`, `SPEND`, `TENURE`) dengan pemetaan ke 7 fitur/kode producer. Tiga kode v1.4 (`MEMBERSHIP_EXPIRING`, `UNRESOLVED_COMPLAINT`, `NO_CROSS_CATEGORY`) **tidak aktif** karena tidak ada fitur pendukung.
  - Penggabungan konsep: kontribusi konsep = jumlah kontribusi log-odds fitur anggota yang diobservasi (model logistik aditif); arah = tanda jumlah; ambang 0,05 tetap konvensi development (PROVISIONAL).
  - `INCREASES_RISK` sebagai "alasan risiko", `DECREASES_RISK` sebagai "faktor penahan" (tidak dihitung ke minimum).
  - Kurang dari 3 alasan: tampil apa adanya, skor tetap dipakai, tidak ada alasan palsu.
  - Delapan kalimat Indonesia netral (konsep × arah) dan teks tambahan; tidak menyiratkan sebab dan tidak memuat angka.
  - Temuan yang dicatat: `recency_days` dihitung dari **aktivitas** terakhir (transaksi, kunjungan selesai, renewal), bukan hanya pembelian, sehingga kode producer `PURCHASE_RECENCY` menyesatkan; teks memakai "aktivitas".
- **`target_definitions.md` (diedit, jadi v1.5 draf).** §1.3 menunjuk ke taxonomy dan mencatat penyimpangan dari "wajib minimal 3"; §2.4 pembulatan half-up `Decimal`, tier setelah pembulatan, dengan contoh; §3.2.A konfirmasi Opsi A; §3.3 baru RFM di luar MVP; §8 menambah butir konfirmasi mentor; Riwayat Revisi baris v1.5. Bagian lain tidak diubah. **Approver/tanggal tetap PENDING.**
- **`GATE_A_REVIEW_REQUEST_2026-11-19.md` (diedit).** Catatan pembaruan di bagian atas: dokumen yang direview kini v1.5 + taxonomy, dan empat butir baru yang butuh jawaban tertulis mentor.

### `docs/christ_business/integration/`
- **`JAWABAN_P1_P8_ISSUE70_CHRIST.md` (diedit).** Tabel "Pernyataan status per poin" dan teks siap tempel untuk #70; P2, P6, P7, P8 ditandai final (sisi Christ, mentor belum); P1, P3, P4, P5 tetap usulan; catatan bahwa izin pakai/loader sudah diimplementasi Moses.
- **`UI_SCORE_STATES_SPEC.md` (diedit).** §1 dan §5 diperbarui (loader sudah dikerjakan); §8 baru: tabel 11 kondisi hasil uji terhadap `App.tsx` asli, penyebab, dan usulan fungsi pengganti untuk Marvin.
- **`HANDOFF_JAMES_MARVIN.md` (diedit).** §2 yang sebelumnya usang kini menyatakan bagian itu sudah dikerjakan dan apa yang masih belum; contoh kode tidak lagi memakai fallback `customer_code`.
- **`D5_NBA_INPUT_CONTRACT.md` (diedit).** Daftar alasan skor ditambah `SCORE_CONTRACT_NOT_SERVING`, `SCORE_EXPIRED`, `SCORE_CUSTOMER_MISMATCH`, pemetaan ke tiga keadaan, dan pernyataan bahwa alasan < 3 bukan alasan menolak skor.

### `docs/christ_business/demo/`
- **`uat_dry_run.py` (baru).** Runner yang dapat diulang: DB sqlite memori + `TestClient`, data sintetis berlabel, menjalankan 14 skenario lewat API/worker tanpa mengubah `api/`, `worker/`, `services/data/`. Menulis `UAT_HASIL_DRY_RUN.md`. Pemeriksaan yang awalnya lemah sudah diperbaiki (mis. validasi folder worker diuji langsung, bukan lewat error acak).
- **`UAT_HASIL_DRY_RUN.md` (baru, dihasilkan runner).** Hasil asli per skenario.
- **`ui_score_status_check.mjs` (baru).** Menjalankan fungsi status skor asli dari `web/src/App.tsx` (tanpa mengubahnya) untuk 11 kondisi backend. Node 22.13+. Saat ini melaporkan 7/11 terhadap `App.tsx` yang ada.
- **`UAT_PLAN.md` (diedit).** Penunjuk ke dry run; UAT-01/03/05 dan keputusan P2 diselaraskan dengan hasil nyata; kolom "Hasil aktual" resmi tetap `BELUM DIJALANKAN`.

### `tests/decision/`
- **`test_cross_segment_matrix.py` (diedit, hanya docstring).** Dari "mencatat perilaku saat ini, bukan keputusan" menjadi "mengunci keputusan P2 Opsi A (mentor belum menyetujui dokumen)". Tidak ada perubahan kode test.

### `docs/christ_business/reference/`
- **`catatan2.md`**: file ini.

## 4. Temuan

1. **UI belum membedakan kedaluwarsa.** `scoreServingStatus` memeriksa `modelReviewStatus` sebelum alasan skor. Akibatnya: skor kedaluwarsa tampil teks umum; ID tidak cocok tampil teks umum; dan kontrak belum lengkap dengan status `pending_review` (kondisi nyata hari ini) tampil "menunggu pemeriksaan reviewer", padahal review tidak membuatnya bisa dipakai. Perbaikan diusulkan (§3, `UI_SCORE_STATES_SPEC.md` §8), diuji 11/11 pada salinan sementara.
2. **Rantai audit tidak tersambung.** Tiap permintaan API memakai `correlation_id` sendiri, sehingga import → review → izin → keputusan tidak terhubung oleh satu id. Keputusan NBA menyimpan `model_version` dan status review, tetapi bukan `run_id`. Rekonstruksi penuh harus menggabungkan jejak lewat `model_version` dan waktu. Definisi selesai Moses menyebut "audit" dari impor sampai NBA; ini perlu dipikirkan Moses/James (bukan kegagalan test).
3. **Campaign berjalan tetapi tidak mengirim apa pun.** Job worker untuk campaign yang disetujui: 2 pelanggan terpetakan dilewati (consent/komplain/kelayakan belum tersambung), 1 dilewati karena tanpa pemetaan, `sent_count = 0`. Itu perilaku fail-closed yang benar, tetapi "campaign jalan beneran" belum tercapai. Angka "paparan holdout = 0" belum bermakna karena tidak ada yang ditarget.
4. **Producer hanya punya 4 konsep alasan.** Banyak pelanggan akan punya kurang dari tiga alasan risiko; ini konsekuensi P7, bukan regresi.
5. **Field wajib hilang** (mis. `clv_amount`): impor diterima (201), tetapi skor tidak dipakai (`SCORE_FIELDS_INCOMPLETE`) walau sudah direview dan diberi izin. Benar.
6. **Self-review dicegah di pintu API (409)**, jadi kode `MODEL_RUN_REVIEWED_BY_SUBMITTER` di gerbang skor hanya pertahanan berlapis. `UAT_PLAN.md` UAT-05 sudah disesuaikan.
7. **Versi `black`:** `black` terbaru (26.x) menandai 16 file milik orang lain sebagai "akan diformat ulang". CI memakai `black>=24,<26`; dengan 25.12 seluruh repo bersih. **Jangan menjalankan `black .` dengan versi 26 di repo kerjamu**; itu akan mengubah file orang lain dan memicu konflik merge.

## 5. Mengapa dry run bukan UAT resmi

- Dijalankan di DB sqlite memori, bukan PostgreSQL bersama; lewat API/worker, bukan UI; skor adalah fixture sintetis (tidak ada model riil yang direview atau diberi izin pakai); dijalankan oleh pembuat kode, bukan penguji independen.
- Verdict: `PASS` sesuai harapan; `TERHALANG` prasyarat belum ada (bukan kegagalan logika); tidak ada `FAIL`. Bagian yang tidak bisa diperiksa dari sandbox (tampilan UI, hasil campaign di DB bersama, pengukuran dengan konversi nyata) ditulis eksplisit di tiap skenario.
- **UAT resmi** tetap harus dijalankan setelah alur impor → review → izin → NBA → simulator → audit berjalan di lingkungan bersama, dicatat di `UAT_PLAN.md` kolom "Hasil aktual" dengan bukti (tangkapan layar, `correlation_id`), oleh penguji yang bukan pembuat kode.

| ID | Dry run | Alasan singkat |
|---|---|---|
| UAT-01 Hasil valid | TERHALANG | Keputusan valid lewat API butuh consent/komplain/kelayakan/produk; di level service dengan sumber sintetis: lolos |
| UAT-02..09 | PASS | Tiga keadaan skor, run ditolak, self-review, izin/cabut, kedaluwarsa, ID tidak cocok, data sebagian hilang |
| UAT-10 NO_ACTION kebijakan | TERHALANG | Lewat API tidak bisa dipicu; di level service: opt-out, fatigue, komplain berat lolos |
| UAT-11 Worker/retry | PASS | Impor ulang 409, artefak rusak 400, validasi folder, 21 test worker Moses lulus |
| UAT-12 Campaign tanpa persetujuan | PASS | Draft dan PendingApproval ditolak (409), non-simulator ditolak |
| UAT-13 Campaign berjalan + pengukuran | TERHALANG | `targetable = 0`; tidak ada konversi untuk diukur |
| UAT-14 Tersimpan + audit | PASS | Keputusan tersimpan, audit event ada; temuan §4.2 |

## 6. Catatan untuk rekan (tanpa menyentuh file mereka)

**Marvin** (`web/`)
- Terapkan fungsi pengganti di `UI_SCORE_STATES_SPEC.md` §8 pada `scoreAvailabilityLabel` dan `scoreServingStatus`, lalu jalankan `node docs/christ_business/demo/ui_score_status_check.mjs`; harus 11/11. Hasil sekarang: 7/11. Yang kurang: kedaluwarsa, kontrak belum lengkap, ID tidak cocok.
- Skor/band/CLV/EV `Kosong` pada keadaan 1 dan 2; `expected_value == null` berarti Kosong, bukan Rp 0.
- Perbaiki `POST /monitoring/measurements` (masih muncul di CI menurut Moses) dan pastikan `customer_id=true` ditolak.

**James** (`api/`, `worker/`, infrastruktur)
- Jalankan migrasi 0027 di PostgreSQL bersama (upgrade + rollback); isi `PREDICTION_IMPORT_ROOT`; jalankan worker impor.
- Sambungkan feed consent, komplain, kelayakan, produk yang memang tersedia (kirim `None` bila belum ada, `[]` bila tersambung dan kosong). Tanpa itu UAT-01, 10, 13 tidak bisa lulus di lingkungan bersama.
- Pertimbangkan membawa `run_id` model ke baris keputusan agar rantai audit impor → NBA dapat direkonstruksi (§4.2). Bila `run_id` dikirim lewat loader, Christ dapat menambah penyimpanannya di `rationale` (perubahan kecil di `serving.py`, belum dikerjakan).

**Moses** (`services/data/`, `worker/prediction_import.py`)
- Implementasikan penggabungan konsep per `reason_taxonomy.md` §4 dan ganti nama kode `PURCHASE_RECENCY` (maknanya aktivitas); tambahkan penanda `reasons_below_minimum` bila disepakati. Jangan menambah kode di luar §2 taxonomy.
- Boundary test P1 dapat ditulis dari tabel di jawaban P1 setelah Christ menyatakan P1 final; boundary test P6 dari contoh di `target_definitions.md` §2.4 (termasuk `200000,5` yang membedakan half-up dan half-even).
- Jangan memberi izin pakai pada model sebelum review nyata. Skor di dry run ini sintetis dan tidak boleh dijadikan dasar izin.
- Mohon periksa apakah `usage_approved` untuk skor propensity/CLV/lifecycle sudah punya produser (NBA tetap `NO_ACTION` selama belum, dan itu benar).

## 7. Yang perlu Christ lakukan

1. **Tinjau label "final"** di tabel status `JAWABAN_P1_P8_ISSUE70_CHRIST.md`; nyatakan P1 (rekomendasi: final) dan posisi P3/P4/P5; tempel blok pernyataan ke issue #70.
2. **Kirim Gate A v1.5** ke mentor dan minta jawaban tertulis untuk empat butir baru (terutama penyimpangan "alasan < 3"). Jangan mengisi approver/tanggal sendiri.
3. **Ikut meeting** D1/D2 (siapa pemberi izin dan reviewer independen); Moses menunggu ini untuk menyambungkan sumber izin yang sah.
4. **Jalankan UAT resmi** hanya setelah urutan Moses selesai; gunakan `UAT_PLAN.md`; penguji bukan pembuat kode. Dry run di sini bukan pengganti.
5. **Sebelum push:** salin hanya file di §3; periksa `git status` (jangan ada file di luar area Christ, tidak ada `__pycache__`, tidak ada file Micro-task 1: migrasi `0007_create_action_catalogue`, perubahan `api/models.py`); jalankan `ruff check .` dan `black --check .` dengan `black<26`; `git pull --rebase origin main` dulu.

## 8. Verifikasi (dijalankan sebelum menyerahkan)

| Pemeriksaan | Hasil |
|---|---|
| `pytest tests/decision` | 942 passed |
| `pytest tests` (tanpa `tests/integration`, sqlite seperti CI) | 1759 passed |
| `pytest docs/christ_business/reference/test` | 107 passed |
| `ruff check .`, `black --check .` (black 25.12, rentang CI), `mypy services api worker` | bersih |
| `run_demo.py` | exit 0 |
| `uat_dry_run.py` | 11 PASS, 3 TERHALANG, 0 FAIL |
| `ui_score_status_check.mjs` terhadap `App.tsx` saat ini | 7/11 sesuai (temuan §4.1) |
| Fungsi usulan di spec §8 pada salinan sementara | 11/11 sesuai |
| Diff terhadap zip terbaru | 8 file diubah + 5 file baru (termasuk ini), semuanya di area Christ |

Perintah ulang:
```
export DATABASE_URL=sqlite:// JWT_SECRET=<min 32 karakter>
python -m pytest tests -q --ignore=tests/integration
ruff check . && black --check .          # gunakan black>=24,<26 seperti CI
mypy services api worker --ignore-missing-imports
PYTHONPATH=. python docs/christ_business/demo/uat_dry_run.py
node docs/christ_business/demo/ui_score_status_check.mjs
```

## 9. Yang sengaja tidak dilakukan
- Tidak mengisi persetujuan mentor, `usage_approved`, band, tier, atau angka bisnis; tidak menyatakan UAT lulus.
- Tidak mengubah `web/`, `api/`, `worker/`, `migrations/`, `services/data/`, `contracts/`.
- Tidak memposting ke issue #70/#71 (tidak ada akses GitHub).
- Tidak mengubah `evaluator.py` maupun `serving.py` (tidak ada keputusan baru yang membutuhkannya).
- Tidak menjadikan P1/P3/P4/P5 final tanpa pernyataanmu.
