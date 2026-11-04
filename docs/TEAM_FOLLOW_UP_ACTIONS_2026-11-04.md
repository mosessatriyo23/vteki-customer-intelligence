# Tindak Lanjut Lintas Tim — Christ & James

**Tanggal:** 2026-11-04
**Pemilik dokumen:** Moses
**Status:** ACTION REQUIRED sebelum fase model/produksi dibuka
**Lingkup saat ini:** development sintetis dan integrasi akademik; bukan persetujuan produksi.

> Dokumen ini menjelaskan pekerjaan yang masih harus diselesaikan oleh Christ dan James. Merge PR atau keberadaan kode **tidak otomatis berarti** kontrak bisnis, kesiapan data, keamanan runtime, atau kesiapan produksi sudah disetujui.

---

## 1. Posisi saat ini

### Moses

Scope mandiri Moses sudah selesai sampai:

- generator dan audit data sintetis;
- validasi/ingestion development;
- identity resolution dan Customer360 development;
- RFM/lifecycle development;
- fitur historis event-time;
- label teknis PROPOSED;
- baseline evaluasi dan diagnostics;
- model card serta handoff.

Status yang harus tetap dipertahankan sampai gate dokumen ini terpenuhi:

```text
training_ready = false
experiment_ready = false
final_model = false
```

Moses **tidak akan mengubah label, fitur, atau baseline lama** berdasarkan kontrak baru sebelum ada keputusan tertulis dan versi kontrak yang jelas.

### Christ

PR yang sudah masuk `main`:

- **PR #17:** target definitions, NBA engine, action catalogue, fatigue policy, suppression policy.
- **PR #18:** JSON Schema K-06 sampai K-11 dan test reference untuk catalogue, engine, fatigue, serta suppression.

Kedua PR frontend build-nya PASS, tetapi job **Code Quality, T-SEC-03 Allowlist & Schemathesis Contract Testing** gagal pada langkah **Ruff Linter**. Karena itu perbaikan CI dan review kontrak masih wajib.

### James

PR yang sudah masuk `main` menambah platform, snapshot serving, API Golden Customer, worker hardening, PostgreSQL governance, serta CI. Namun kontrak berikut masih belum final:

- availability time (`available_at`) untuk transaksi, refund, dan perubahan status;
- effective-time identity registry;
- semantik ingestion antar-batch untuk master dan source IDs;
- histori refund/status immutable;
- runtime role isolation, SLA trace, dan E2E produksi.

---

## 2. Tugas Christ — Business & Decisioning

### C1 — Perbaiki CI PR #17 dan #18

**Prioritas:** P0 — wajib sebelum kontrak dianggap dapat dipakai.

#### Pekerjaan

1. Ambil log Ruff dari workflow PR #17 dan #18.
2. Perbaiki seluruh lint error pada implementasi dan test.
3. Jalankan lokal:

   ```bash
   ruff check .
   black --check services/decision docs/christ_business/reference/test
   mypy services/decision --ignore-missing-imports
   pytest -q docs/christ_business/reference/test
   ```

4. Buka PR perbaikan terpisah atau update branch Christ.
5. Pastikan job quality/security/contract dan frontend build sama-sama PASS.

#### Bukti selesai

- Link PR perbaikan.
- Log lokal singkat.
- Link workflow GitHub dengan kedua job PASS.
- Tidak ada `continue-on-error`, exclude baru, atau bypass lint untuk menyembunyikan error.

**Tidak dianggap selesai jika:** hanya frontend build yang PASS atau PR sudah merge tetapi quality job masih FAILURE.

---

### C2 — Finalisasi target churn

**Prioritas:** P0 — wajib sebelum Moses membuat label baru.

Dokumen `target_definitions.md` menyebut inactivity 180 hari dan horizon 90 hari. Christ harus menulis decision table yang menjawab:

1. Apa event churn yang tepat: transaksi, kunjungan, membership renewal, atau gabungannya?
2. Apakah `>180 hari` merupakan eligibility/history rule, target definition, atau risk segmentation rule?
3. Bagaimana memperlakukan kalimat “tidak diprediksi aktif dalam 90 hari ke depan”? Label training harus memakai **outcome yang diamati**, bukan prediksi model itu sendiri.
4. Apakah churn target baru menggantikan `churn90` development, atau menjadi target terpisah?
5. Bagaimana kasus boundary tepat 180 hari diperlakukan?
6. Bagaimana pelanggan tanpa membership history diperlakukan?
7. Bagaimana pelanggan `PROVISIONAL` dan `REVIEW_REQUIRED` diperlakukan?

#### Output wajib

```text
docs/christ_business/approved/churn_target_v1.x.md
```

Dokumen harus memuat contoh positif/negatif/boundary, sumber event, timezone, cutoff, eligibility, exclusion, dan label completeness.

---

### C3 — Finalisasi CLV/value definition

**Prioritas:** P0.

Christ harus menjelaskan dan menyetujui:

1. Apakah CLV adalah historical + estimated future gross revenue seperti formula saat ini?
2. Apakah `clv90` development tetap ada sebagai target teknis terpisah?
3. Cara menghitung discount, voucher, refund, tax, cancellation, dan net revenue.
4. Apakah `Retention_Factor` berasal dari model, rule, atau angka default akademik.
5. Minimum history dan cara menangani pelanggan yang hanya punya satu transaksi.
6. Mata uang, pembulatan IDR, negative adjustment, dan adjustment window.
7. Apakah nilai ini target prediksi, score decisioning, atau hanya tiering.

#### Output wajib

```text
docs/christ_business/approved/value_definition_v1.x.md
```

Harus disertai worked examples dan mapping field source → formula.

---

### C4 — Finalisasi lifecycle, RFM, dan treatment

**Prioritas:** P1.

Christ harus menetapkan:

- prioritas ketika satu pelanggan memenuhi lebih dari satu kategori;
- perbedaan `AT_RISK`, `DORMANT`, `CHURNED`, dan `REACTIVATED`;
- perbedaan churn risk 180 hari dengan lifecycle `CHURNED` 365 hari;
- perlakuan membership renewal sebagai transaksi;
- aturan pelanggan baru dan history tidak lengkap;
- mapping lifecycle/CLV/risk ke action catalogue;
- action yang bersifat service versus commercial.

#### Output wajib

```text
docs/christ_business/approved/lifecycle_treatment_v1.x.md
```

Dokumen harus memuat decision priority table dan minimal satu contoh untuk setiap boundary.

---

### C5 — Finalisasi consent, suppression, dan contact policy

**Prioritas:** P0 sebelum integrasi campaign apa pun.

Christ harus menetapkan:

1. Apakah `UNKNOWN` dan `EXPIRED` selalu blocked di semua kanal.
2. Apakah global opt-out mengalahkan channel opt-in.
3. Cara menangani consent setelah identity merge.
4. Sumber, timestamp, expiry, dan audit perubahan consent.
5. Definisi kontak yang dihitung dalam cap 2 kontak/14 hari.
6. Pengecualian service reminder dan complaint resolution.
7. Aturan severe complaint dan siapa yang boleh mengubah status.
8. Larangan outbound nyata selama fase akademik.

#### Output wajib

```text
contracts/K-10_consent_contract.json

docs/christ_business/approved/consent_treatment_v1.x.md
```

Schema harus diverifikasi terhadap contoh valid dan invalid. Policy tidak boleh mengandalkan skor AI untuk meng-override suppression mutlak.

---

### C6 — Lengkapi outcome, attribution, dan KPI

**Prioritas:** P1.

Christ harus menetapkan:

- definisi `BOOKING`, `PURCHASE`, `MEMBERSHIP_RENEWAL`, dan `UPGRADE`;
- occurred time versus availability time;
- gross, deduction, refund, net, dan finalization;
- attribution window dan last-touch rule;
- perbedaan observed conversion dan incremental conversion;
- control group dan treatment group;
- KPI utama, guardrail KPI, dan success threshold;
- alasan booking propensity tidak boleh diaktifkan tanpa booking event nyata.

#### Output wajib

```text
docs/christ_business/approved/outcome_kpi_v1.x.md
```

K-09 tidak dianggap siap produksi hanya karena JSON Schema valid; harus ada producer, consumer, contoh payload, dan acceptance test.

---

## 3. Tugas James — Platform & Historical Data

### J1 — Finalisasi availability-time contract

**Prioritas:** P0.

James harus mendefinisikan untuk setiap event:

| Event | Field wajib | Makna |
|---|---|---|
| Transaksi | `occurred_at`, `available_at`, source version | Kapan terjadi dan kapan pertama tersedia untuk pipeline |
| Refund/return | event ID, `occurred_at`, `available_at`, correction/version | Kapan refund terjadi dan kapan diketahui |
| Membership/status | effective time, availability time, version | Kapan status berlaku dan kapan diterima sistem |
| Identity decision | registry version, effective time, audit time | Kapan keputusan berlaku untuk snapshot historis |

#### Output wajib

```text
docs/james_platform/approved/historical_data_contract_v1.x.md
```

Harus ada contoh late-arriving event, correction, refund setelah cutoff, dan aturan apakah event boleh masuk training row tertentu.

---

### J2 — Selesaikan effective-time identity registry

**Prioritas:** P0.

James harus menjawab:

1. Apakah `identity_registry_version` saja cukup untuk merekonstruksi Golden ID pada cutoff?
2. Jika tidak, bagaimana `valid_from`/`valid_to` bekerja?
3. Bagaimana merge/split setelah snapshot published diperlakukan?
4. Bagaimana downstream snapshot/model/campaign menjaga lineage?
5. Bagaimana review approval menghasilkan versi baru tanpa silent merge?
6. Bagaimana data `PROVISIONAL`, `REVIEW_REQUIRED`, `APPROVED`, dan `REJECTED` boleh digunakan?

#### Output wajib

- ERD atau diagram lifecycle registry.
- Migration proposal.
- Test untuk lookup identity berdasarkan cutoff.
- Test anti silent merge/split.
- Aturan rekey/alias downstream.

---

### J3 — Finalisasi multi-batch ingestion

**Prioritas:** P0.

James harus memilih dan mendokumentasikan semantik untuk:

- `branches` dan `catalogue_items` yang muncul kembali di batch berikutnya;
- source primary key yang sama dengan payload sama;
- source primary key yang sama dengan payload berbeda;
- source ID baru dengan natural key lama;
- batch checksum sama versus berbeda;
- retry setelah partial failure;
- rollback dan publication boundary.

Pilihan harus eksplisit: reject, idempotent no-op, upsert, atau SCD/versioned. Tidak boleh bergantung pada perilaku accidental database.

#### Output wajib

```text
docs/james_platform/approved/multi_batch_contract_v1.x.md
```

Wajib ada integration tests untuk minimal dua batch berbeda dan payload conflict.

---

### J4 — Implementasi histori refund/status dan lineage

**Prioritas:** P1.

James harus menyediakan:

- model append-only atau versioned untuk refund/status;
- event ID/idempotency key;
- correction chain;
- audit actor/source;
- query “state as known at availability time”;
- query “state effective at event time”;
- rollback/replay yang dapat diulang.

Tes harus membuktikan bahwa future correction tidak mengubah training row lama secara diam-diam.

---

### J5 — Validasi PostgreSQL dan runtime roles

**Prioritas:** P1.

James harus membuktikan:

- `alembic upgrade head` dari database kosong;
- repeat migration;
- ingestion dua batch;
- snapshot publish atomik;
- append-only audit;
- privilege writer/reviewer/reader;
- service API dan worker menggunakan login role terpisah;
- failure/retry tidak meninggalkan partial publish.

Bukti harus berasal dari PostgreSQL nyata di CI atau environment test yang terdokumentasi, bukan hanya SQLite.

---

### J6 — Validasi worker, trace, dan E2E persona

**Prioritas:** P2 sebelum klaim production readiness.

James perlu melengkapi:

- advisory lock lintas proses;
- timeout, terminate, retry, dan cancellation;
- idempotensi setelah handler dihentikan;
- audit trace pada volume representatif;
- pagination/truncation marker untuk trace besar;
- browser E2E untuk persona dan RBAC utama.

CI hijau saja tidak membuktikan SLA produksi atau load capacity.

---

## 4. Acceptance gate sebelum Moses membuka fase berikutnya

Semua syarat berikut harus terpenuhi:

### Gate A — Business contract

- Dokumen target churn, value/CLV, lifecycle/treatment, consent, dan outcome/KPI berstatus **APPROVED**.
- Ada approver, tanggal, versi, change log, dan contoh boundary.
- Tidak ada kontradiksi yang belum diputuskan.

### Gate B — CI dan contract tests

- Ruff, Black, mypy, unit tests, security tests, contract tests, dan frontend build PASS.
- Tidak ada bypass baru untuk menutupi kegagalan.
- Schema JSON diuji dengan payload valid dan invalid.

### Gate C — Historical data contract

- `occurred_at` dan `available_at` tersedia dan bermakna.
- Refund/status correction dapat direkonstruksi.
- Identity registry dapat direkonstruksi sesuai cutoff.
- Multi-batch semantics sudah diuji PostgreSQL.

### Gate D — Model readiness review

Setelah Gate A-C, Moses baru boleh:

1. membuat label versi baru;
2. menyesuaikan historical features;
3. menjalankan baseline baru;
4. membandingkan dengan baseline development lama;
5. menulis model card baru;
6. meminta keputusan experiment readiness.

Sampai semua gate ini terpenuhi, status tetap:

```text
training_ready = false
experiment_ready = false
final_model = false
```

---

## 5. Batasan yang tidak boleh dilanggar

- Jangan memakai `generator/ground_truth/` sebagai input matching atau model.
- Jangan mengubah baseline lama tanpa versioning dan changelog.
- Jangan menyebut schema valid sebagai bukti data historis tersedia.
- Jangan menyebut PR merged sebagai bukti CI atau produksi siap.
- Jangan mengaktifkan outbound messaging/campaign nyata.
- Jangan memakai data `PROVISIONAL` atau `REVIEW_REQUIRED` untuk aksi komersial tanpa policy tertulis.
- Jangan menganggap `BOOKING` siap dimodelkan tanpa event booking nyata.
- Jangan menghapus atau menimpa artefak development yang sudah ada.

---

## 6. Checklist tanggapan tim

### Christ

- [ ] PR perbaikan Ruff dan semua CI PASS.
- [ ] Churn target v1.x disepakati.
- [ ] CLV/value definition v1.x disepakati.
- [ ] Lifecycle/treatment v1.x disepakati.
- [ ] Consent/suppression v1.x disepakati.
- [ ] Outcome/KPI/attribution v1.x disepakati.

### James

- [ ] Historical `available_at` contract v1.x disepakati.
- [ ] Effective-time identity registry disepakati dan diuji.
- [ ] Multi-batch contract disepakati dan diuji PostgreSQL.
- [ ] Refund/status lineage tersedia.
- [ ] Runtime roles, migration, publish atomicity diuji.
- [ ] Worker/trace/E2E evidence tersedia sesuai target.

### Moses

- [ ] Menunggu keputusan dan evidence di atas.
- [ ] Tidak mengubah pipeline target sebelum Gate A-C selesai.
- [ ] Membuat PR model baru hanya setelah kontrak versi disetujui.

---

## 7. Referensi

- `docs/moses_data_ai/TEAM_HANDOFF_2026-10-16.md`
- `docs/moses_data_ai/model_card_development_v1.md`
- `docs/christ_business/approved/target_definitions.md`
- `docs/james_platform/STATUS_TUGAS_JAMES.md`
- `docs/james_platform/SINKRONISASI_MAIN_2026-10-16.md`
- `contracts/K-06_action_catalogue.json` sampai `contracts/K-11_audit_event_contract.json`
- PR #17 dan PR #18 (Christ)
- PR #15 dan PR #16 (James)
