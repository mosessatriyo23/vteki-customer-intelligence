# Sinkronisasi James Platform dengan `main` — 16 Oktober 2026

**Owner:** James / Platform Architect, Security & Full-Stack Interface Lead
**Basis verifikasi:** ekspor Git `origin/main` pada commit `32d89a0aa99501f70489d058a247ea8145434a46` dan branch James `92e25dc20e8316af8f5b8533874872233bb6359e`.
**Status:** IMPLEMENTATION REVIEW / PROPOSED. Dokumen ini bukan persetujuan bisnis atau bukti CI/deployment produksi.

## Ringkasan penyelarasan kode

| Area | Sumber perubahan | Keputusan integrasi |
|---|---|---|
| API email dan JSON Schema | James: tolak TLD numerik (`0@0.0`), special-use suffix, label DNS yang buruk. Main: helper `email_field`, `UserCreate(extra="ignore")` | Gabungkan regex James dengan helper dan kebijakan model `main`; JWT/RBAC tidak diubah |
| Pengujian autentikasi | Main: schema restriction, abaikan property tidak dikenal, domain reserved ditolak. James: regresi TLD numerik dan domain label | Gabungkan kedua kelompok tes tanpa menghapus tes milik `main` |
| Worker lock / budget | Main: satu tes untuk overlap dan budget. James: dua tes terpisah dan jam monotonic tiruan yang terisolasi | Pilih dua tes deterministik James, tidak mengubah runtime `worker/scheduler.py` |
| CI kontrak | James: login admin sungguhan untuk smoke test, exclude `/auth/login` dari fuzzing acak; main memakai JWT buatan untuk testing | Pertahankan workflow James; endpoint login tetap diverifikasi dengan kredensial CI dan tes unit |
| Identity registry | Main: sequential replay tidak mengganti keputusan published; menolak evidence baru di batch lama | **Pertahankan implementasi `main`** dan tes `tests/data/test_persistence.py`; jangan restore versi branch James yang memakai `session.merge` untuk pasangan natural-key |
| Data features, models, dan dokumentasi Moses | Main: PIT feature, diagnostics, baseline dev dan handoff pada tanggal 16 Okt | Ikuti `main`, jangan menimpa `services/data/features`, `services/data/models`, `services/data/identity/registry.py`, atau dokumen `docs/moses_data_ai` |
| Namespace docs | `docs/README.md` main | Tambahkan dokumen James di `docs/james_platform/` tanpa memindahkan dokumen milik tim lain |

> Catatan: `main` sudah menyediakan `docs/james_platform/IMPLEMENTASI_JAMES.md` (catatan implementasi awal). Dokumen ini melengkapi catatan tersebut dengan posisi integrasi terbaru; isi lama tidak ditulis ulang secara diam-diam.

## Kontrak kolaborasi dan keputusan belum final

Dokumen `docs/moses_data_ai/TEAM_HANDOFF_2026-10-16.md` pada `main` menyatakan eksperimen Moses memakai **data sintetis**; status feature historis `training_ready=false` dan label/baseline `PROPOSED` hingga kontrak teknis dan definisi bisnis disetujui.

Pertanyaan untuk **James** (status `PROPOSED`, butuh keputusan lintas tim):

1. **Event time / effective time:** siapa yang menetapkan dan menyimpan `available_at` untuk transaksi, refund, serta perubahan status? Bagaimana versi immutable ditautkan ke cutoff historis agar PIT tidak bocor data masa depan?
2. **Versioning Golden ID:** apakah `identity_registry_version` cukup untuk rekonstruksi historis, atau perlu interval `valid_from`/`valid_to` dan aturan efektif setelah review atau approved merge? Bagaimana referensi downstream diperbarui tanpa silent merge/split?
3. **Multi-batch source:** kapan master seperti `branches` dan `catalogue_items` di-upsert vs di-versioning (SCD)? Bagaimana collision source PK lintas batch ditangani tanpa overwrite publikasi yang tidak tercatat?
4. **Idempotency dan rollback:** definisi kunci batch+checksum, transaction boundary antara raw+typed source dan tahap identity/C360/segmentation, serta mekanisme retry/cancel worker.
5. **Permission & governance:** ownership migrasi PostgreSQL/DBA, privilege read/write per service, penanganan PII, retention audit, dan apakah promosi artefak dari development sudah boleh dilakukan.
6. **NFR/operasional:** bukti `pg_advisory_lock` lintas proses, trace rekontruksi dalam SLA yang disepakati, serta watchdog untuk handler yang tidak kembali sebelum batas worker.

**Batasan yang dipertahankan:** hindari `generator/ground_truth` sebagai input matching/model, jangan aktifkan komunikasi campaign sungguhan, jangan bypass login/JWT/RBAC, dan jangan menganggap hasil synthetic baseline sebagai angka performa produksi. RFM/lifecycle dan target label milik Christ masih **PROPOSED**, bukan otomatis `APPROVED` hanya karena source sudah di-merge.

## Checklist pengujian sebelum PR di-merge

Dijalankan dari root repo setelah konflik diselesaikan dan `main` terkini berhasil terintegrasi:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m black --check api worker migrations tests/security/test_auth.py tests/worker
.\.venv\Scripts\python.exe -m mypy services api worker --ignore-missing-imports
.\.venv\Scripts\python.exe -m pytest -q
Push-Location web
npm ci
npm run build
Pop-Location
```

- Jalankan workflow **Code Quality, T-SEC-03 Allowlist & Schemathesis Contract Testing** dan **React/Vite Production Build** di GitHub Actions terhadap commit PR terbaru; jangan menyimpulkan hijau dari pytest lokal.
- Periksa bahwa OpenAPI `POST /auth/users` menolak input schema seperti `0@0.0`; 422 untuk request yang **tidak cocok** dengan pattern adalah perilaku valid.
- Uji migrasi `alembic upgrade head` di PostgreSQL test terpisah yang benar-benar tersedia. Jangan gunakan database produksi untuk pengujian tanpa backup/approval.
- Dokumen dan kode harus sama-sama direview oleh pemilik modul. Pengujian integrasi lintas proses, beban, security, UI persona dan database role produksi belum dinyatakan lulus oleh paket sinkronisasi ini.

## Urutan Git yang aman

Karena user sedang dalam merge **yang dimulai sebelum** pembaruan `main` ke `32d89a0`, selesaikan konflik merge yang aktif dan jalankan tes terlebih dahulu. Commit merge tersebut; baru merge lagi `origin/main` terbaru dan ulangi tes. Bila muncul konflik baru, berhenti dan review sebelum commit/push. Jangan pakai `reset --hard`, `push --force`, atau `git add .`.
