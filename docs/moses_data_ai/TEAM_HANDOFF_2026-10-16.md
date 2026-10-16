# Team Handoff — Moses (Data Engineering & Predictive AI) — 2026-10-16

> **Status: Scope development mandiri SELESAI pada data sintetis.** Kode, tes, dan dokumen sudah di `main` dengan CI hijau. **Bukan model produksi / bukan performa final.**

---

## Halo James & Christ,

Bagian Data Engineering + EDA + Historical Features + Label & Baseline evaluasi yang bisa saya kerjakan mandiri sudah saya tutup. Semua berjalan end-to-end di lokal pada **data sintetis schema v2** (tanpa memakai ground truth sebagai input matching/model).

Mohon review bagian masing-masing sebelum kita buka fase production/model selanjutnya. File berversi, manifest checksum, dan `training_ready=false` tetap dipertahankan sampai kontrak historis & definisi bisnis disetujui.

---

## 1. Apa yang sudah selesai (di `main`)

| Area | Artefak utama | Catatan |
|---|---|---|
| **Synthetic Generator & Audit** | `generator/generate.py`, `generator/audit_generated.py` | 50.000 Golden Customers (~61.000 source identities), 20 branches, 160 items, ~18 bulan. Full dataset: 444.011 transaksi, 1.109.522 items. Audit penuh `ok:true`. |
| **Ingestion & Validasi** | `services/data/ingestion/validator.py`, `pg_loader.py`, `contracts.py` | Schema/type/FK/accounting/chronology, entire-batch rejection, staging SQLite dev, PostgreSQL loader + migrations sampai `0010`. |
| **Identity Resolution v1.1** | `services/data/identity/resolver.py`, `cli.py`, `registry.py` | Conservative ≥2 identifiers + name ≥0.75, complete-link, review queue. Full benchmark (synthetic alias): **50.640 clusters, precision 1.0, recall 93.89%**, 0 false-merge. |
| **Customer 360 dev** | `services/data/customer360/profile.py`, `cli.py` | 50.640 profil provisional (`PROVISIONAL`/`REVIEW_REQUIRED`), retained revenue, visits/renewals, cutoff `+07:00`. |
| **RFM & Lifecycle (PROPOSED)** | `services/data/segmentation/snapshot.py` | RFM fixed bins + lifecycle eksklusif 9 kategori. Full run: ACTIVE 6.092, LOYAL 12.026, OCCASIONAL 20.414, dll. |
| **PIT Features dev** | `services/data/features/snapshot.py` | Event-time `(cutoff-365d, cutoff]` marked `training_ready=false`, `CURRENT_SNAPSHOT_RETROSPECTIVE`. |
| **EDA** | `services/data/eda/report.py`, `golden.py` | Source EDA + Golden aggregate EDA (tanpa PII/ID). Validasi batch + hash manifest. |
| **Labels & Baseline** | `services/data/models/labels.py`, `baseline.py`, `diagnostics.py` | `churn90`/`clv90` PROPOSED 90d `(cutoff, cutoff+90]`, purged chronological holdout, rule `recency>90` & median revenue. Diagnostic agregat + model card. |

**PR yang sudah merge:**
- `#5` fondasi fitur historis development + fix sequential replay Identity Registry
- `#11` fix kontrak email & stabilisasi worker test
- `#10` EDA + label & baseline dev
- `#13` diagnostics & handoff (17f0ab9) — **CI hijau (Quality + Frontend Build)**

**Tes lokal terakhir:** `91 passed, 1 warning` (`tests/data + tests/security + tests/worker + tests/test_james_platform.py`). Artefak `artifacts/` dan `inbound/` tetap *ignored*.

---

## 2. Angka kunci (data sintetis, bukan KPI bisnis)

- **Source snapshot 2026-09-06:** 444.011 observed tx, 4.506 fingerprint replay, 421.859 qualifying purchases, retained revenue **696.643.476.095 IDR** (unattributed 12.701 / 20.878.101.160 IDR).
- **Golden EDA 2026-09-06:** 50.640 profiles (49.416 PROVISIONAL, 1.224 REVIEW_REQUIRED).
- **Baseline 2026-03-01 → 2026-06-01:** label 75.002 → joined 55.452 → train 22.602 / test 32.850 / purged 0. Churn accuracy **87.66%** (balanced 74.20%), always-non-churn 79.41% — bukti perlunya balanced metric. Median MAE 3.817.698 IDR.

> Semua angka di atas **hanya diagnostik rekayasa pada data sintetis retrospektif**, jangan dipakai sebagai klaim performa produksi.

---

## 3. Cara reproduce (tanpa DB produksi)

```bash
# 1. EDA source
python3 -m services.data.eda.cli --inbound inbound/2026-09-06 --cutoff-at 2026-09-06T23:59:59+07:00 --output-dir artifacts/eda/dev-runN

# 2. EDA Golden
python3 -m services.data.eda.golden --inbound inbound/2026-09-06 --resolution artifacts/identity/v11 --cutoff-at 2026-09-06T23:59:59+07:00 --output-dir artifacts/eda/golden-runN

# 3. Historical features
python3 -m services.data.features.cli --inbound inbound/2026-09-06 --resolution artifacts/identity/v11 --cutoff-at 2026-03-01T23:59:59+07:00 --cutoff-at 2026-06-01T23:59:59+07:00 --output-dir artifacts/features/event-time-runN

# 4. Labels + baseline
python3 -m services.data.models.cli --inbound inbound/2026-09-06 --resolution artifacts/identity/v11 --cutoff-at 2026-03-01T23:59:59+07:00 --cutoff-at 2026-06-01T23:59:59+07:00 --output-dir artifacts/models/dev-baseline-runN

# 5. Diagnostics
python3 -m services.data.models.diagnostics --source artifacts/models/dev-baseline-runN --output-dir artifacts/models/diag-runN
```
Gunakan path output baru setiap run. Output membawa `*_manifest.json` dengan SHA256. Jangan commit `artifacts/`, `inbound/`, `generator/ground_truth/`, `chat.md`, atau `.env`.

---

## 4. Apa yang **belum** selesai / butuh kalian

| Milik | Keputusan yang ditunggu | Output yang diminta |
|---|---|---|
| **James (Platform)** | `available_at` & versi immutabel untuk transaksi/refund/status; effective-time registry identitas berversi; semantik multi-batch source (master `branches` dll upsert vs versioned); permission & production persistence/monitoring/rollback. | ERD/schema, migration, kontrak batch, strategi idempotency/locking, daftar pertanyaan tertulis. |
| **Christ (Business)** | Definisi final churn/CLV/propensity (event, horizon, eligibility/exclusion, value), rule lifecycle/RFM final, KPI, consent/treatment & suppression. Booking propensity butuh event booking nyata. | Decision table lifecycle, definisi RFM/label, mapping segment→treatment, KPI. |

Tanpa ini, pipeline tetap **`training_ready=false` / `experiment_ready=false` / `final_model=false`** — **sengaja diblokir**.

---

## 5. Batasan yang harus dijaga

- Jangan pakai `generator/ground_truth/` sebagai input sistem/model (hanya evaluasi terpisah).
- Jangan anggap 50.640 cluster = 50.000 pelanggan unik terverifikasi.
- Jangan klaim accuracy baseline sebagai performa bisnis; jangan bandingkan `REVIEW_REQUIRED` sebagai bukti fairness.
- Jangan aktifkan campaign/messaging nyata; worker/campaign hanya simulator.
- Jangan force-merge saat CI merah; jangan commit secret/dataset besar.

---

## 6. Langkah selanjutnya (usulan)

1. James & Christ kirim keputusan tertulis sesuai tabel di atas.
2. Update kontrak + tes, lalu buka kembali fase model *hanya* bila minimal satu readiness blocker terselesaikan (mis. dataset historis berversi + definisi target disetujui).
3. Presentasi EDA & demo pipeline lokal untuk stakeholder — tetap berlabel *synthetic development*.

Terima kasih — scope mandiri saya **closed**. Siap lanjut ke fase production setelah handoff ini disetujui.

— **Moses**
