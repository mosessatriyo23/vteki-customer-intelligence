# Panduan Implementasi Lintas Tim — membuka fase model Moses

**Status:** Panduan kerja / belum merupakan approval bisnis

**Pemilik koordinasi:** Moses

**Tim:** Christ (Business & Decisioning), James (Platform & Data), Moses (Data & ML)

**Terakhir diperbarui:** 2026-11-14

Dokumen ini mengubah follow-up dan readiness gate menjadi daftar kerja yang dapat diimplementasikan dan diverifikasi. Ini **tidak menggantikan** kontrak Christ, kontrak platform James, atau proses approval mentor. Jangan menganggap contoh teknis sebagai keputusan bisnis.

## 1. Tujuan dan keadaan saat ini

Tujuan fase berikutnya adalah menghasilkan dataset historis yang dapat direkonstruksi sesuai waktu, lalu membuat versi label/fitur/model development yang disetujui dan dapat diaudit.

Pekerjaan Moses untuk scope sintetis mandiri sudah selesai. Evaluator churn development PR #31 sudah merged dan CI lulus. Diagnostik sintetis dapat dipakai untuk memeriksa pipeline, bukan untuk mengklaim performa bisnis.

Readiness tetap:

```text
training_ready=false
experiment_ready=false
final_model=false
```

Gate A–C di `docs/TEAM_FOLLOW_UP_ACTIONS_2026-11-04.md` masih harus ditutup sebelum Gate D atau training model baru dibuka.

## 2. Aturan kolaborasi yang wajib

1. **Pemilik memutuskan domainnya.** Christ menyetujui semantik bisnis; James menyetujui semantik dan bukti platform; Moses mengimplementasikan label/fitur/model setelah kontraknya tersedia.
2. **Tidak ada keputusan lewat asumsi kode.** Bila dokumen bisnis belum menjawab pertanyaan, catat `OPEN` dan gunakan perilaku fail-closed; jangan mengisi default bisnis.
3. **Perubahan bersifat versioned.** Jangan mengedit baseline lama, label lama, atau manifest historis. Buat versi dan output run baru serta changelog.
4. **Bukti wajib disimpan.** PR berisi kontrak, contoh valid/invalid, test, pemilik, reviewer, dan CI link. Jangan menandai gate selesai hanya karena file atau schema ada.
5. **Data sintetis saja untuk development saat ini.** Jangan gunakan `generator/ground_truth/` sebagai input identity, feature, label, atau training. Jangan commit data lokal/artefak `artifacts/`.
6. **Tidak ada campaign nyata.** Nudge/message tetap draft dengan human approval; tidak ada customer selection atau production scoring dari output ini.
7. Identitas `PROVISIONAL`/`REVIEW_REQUIRED` tidak digunakan untuk tindakan komersial tanpa policy tertulis.

## 3. Work package Christ — Gate A: Business contract

Setiap keputusan di bawah harus memiliki satu sumber kebenaran berversi, approval eksplisit, approver, tanggal, changelog, contoh boundary, dan status. Dokumen `target_definitions.md` v1.2 saat ini berstatus `REVISI`; jangan menganggap semua isinya final.

### C-BIZ-01 — Churn target

**Output yang diminta:** `docs/christ_business/approved/churn_target_v1.x.md` (atau versi yang dipilih Christ).

Decision table minimal:

| Topik | Keputusan eksplisit yang harus ditulis |
|---|---|
| Target | Definisi label observed outcome; bedakan churn prediction 90 hari dari lifecycle `CHURNED` 365 hari. |
| Negation events | POS status yang diterima, completed visit, membership renewal; sumber resmi dan aturan duplikasi. |
| Cohort eligibility | Definisi “terdaftar dan aktif”, lookback, perlakuan tanpa membership history dan pelanggan tanpa transaksi. |
| Identitas | Aturan untuk `PROVISIONAL`, `REVIEW_REQUIRED`, unmatched, merged/split identity. |
| Waktu | `prediction_date`, timezone, interval endpoint inklusif/eksklusif, `occurred_at` vs `available_at`. |
| Labelability | Horizon incomplete => null; bagaimana late-arriving/corrected events memengaruhi label. |
| Boundary | Contoh event tepat pada cutoff, tepat pada akhir horizon, dan batas 180/365 hari yang relevan. |
| Versioning | Apakah kontrak baru menggantikan `churn90` atau membuat target baru; effective date dan migration policy. |

**Acceptance:** contoh positif/negatif/null/boundary dapat dijadikan tests; tidak ada kontradiksi yang belum diberi owner dan due date; approver dan tanggal terisi.

### C-BIZ-02 — CLV/value

**Output yang diminta:** `docs/christ_business/approved/value_definition_v1.x.md`.

Christ perlu memutuskan dan memberi worked examples untuk:

- sumber gross revenue resmi (field sumber → formula);
- rolling 365 hari atau 12 calendar months;
- gross, discount/voucher, refund/partial refund, tax, cancellation, correction, dan adjustment window;
- Retention_Factor: metode/sumber/owner/validasi. **Tidak ada default** dan jangan menyamakan dengan `1 - churn90` tanpa persetujuan eksplisit;
- minimum history, customer dengan 0/1 transaksi, mata uang, negative adjustment, dan rounding IDR;
- output adalah prediction target, decision score, atau tier historis;
- hubungan `clv90` development dengan definisi CLV bisnis.

**Acceptance:** worked examples dapat dihitung ulang manual dan dites; field mapping disepakati; tidak ada variabel yang belum punya owner/metode.

### C-BIZ-03 — Lifecycle/RFM/treatment

**Output yang diminta:** `docs/christ_business/approved/lifecycle_treatment_v1.x.md`.

Tetapkan prioritas eksklusif, syarat `NEW`, `ACTIVE`, `LOYAL`, `AT_RISK`, `DORMANT`, `CHURNED`, `REACTIVATED`; aturan membership; boundary 30/60/90/180/365; status `UNCLASSIFIED`; dan keputusan apakah `OCCASIONAL`/`NEVER_TRANSACTED` resmi. Tulis mapping segmen → action, service vs commercial, serta fallback `NO_ACTION`.

Jangan mengarang replenishment cycle atau menyamakan renewal dengan purchase pada fitur/target kecuali kontrak menetapkannya.

**Acceptance:** decision priority table, contoh setiap boundary dan overlap, dan test expected lifecycle untuk setiap contoh.

### C-BIZ-04 — Consent/suppression/contact

**Output yang diminta:** dokumen approved versi baru dan kontrak/schema terkait (termasuk K-10 bila perlu).

Tentukan fail-closed treatment untuk consent `UNKNOWN`/`EXPIRED`, global opt-out, channel opt-in, identity merge, sumber/timestamp/expiry, fatigue window, definisi kontak, pengecualian service/complaint, severe complaint, dan larangan outbound fase akademik.

**Acceptance:** payload valid/invalid dan policy decision tests; suppression mutlak tidak dapat dioverride oleh model; human approval tetap wajib.

### C-BIZ-05 — Outcome/KPI/attribution

**Output yang diminta:** `docs/christ_business/approved/outcome_kpi_v1.x.md` dan update kontrak K-09 bila dibutuhkan.

Definisikan BOOKING/PURCHASE/MEMBERSHIP_RENEWAL/UPGRADE, finalization/refunds, occurred/available time, attribution window, last-touch, observed vs incremental conversion, treatment/control, primary/guardrail KPI dan success threshold. Nyatakan booking propensity tetap out-of-scope tanpa booking event nyata.

**Acceptance:** satu worked example per event, kontrak dapat diuji, KPI memiliki denominator/window/source yang jelas.

## 4. Work package James — Gate C: Historical/platform contract

**Output:** kontrak platform berversi + migration/schema bila diperlukan + test dan evidence CI/PostgreSQL. Update `docs/james_platform/STATUS_TUGAS_JAMES.md` saat item ditutup.

### J-PLAT-01 — Event availability dan lineage

Untuk transaksi, visit, renewal, refund, status change, dan correction, dokumentasikan serta implementasikan:

- waktu bisnis `occurred_at` dengan timezone;
- waktu sistem `available_at`/ingestion yang tidak dapat di-backdate untuk berpura-pura tersedia lebih awal;
- event/source ID dan idempotency key;
- immutable append/correction lineage, actor/source, batch ID, dan referensi record yang dikoreksi;
- aturan ordering dan late-arriving events.

**Acceptance tests:** event terjadi sebelum cutoff tapi baru tersedia setelah cutoff tidak terlihat pada snapshot cutoff itu; correction/refund kemudian tidak mengubah snapshot historis yang sudah diterbitkan; replay identik idempotent.

### J-PLAT-02 — Identity as-of

Sediakan cara membangun mapping efektif pada cutoff dengan riwayat keputusan, effective time, recorded/available time, reviewer, dan versi registry. Merge/split baru tidak boleh diam-diam mengubah snapshot masa lalu.

**Acceptance tests:** query pada cutoff lama menghasilkan mapping lama setelah merge/split baru; unresolved cases tetap statusnya; checksum/replay menghasilkan output identik.

### J-PLAT-03 — Multi-batch semantics

Tuliskan aturan untuk duplicate batch, source ID baru/lama, master-data updates, correction batches, partial failure, retry, rollback, dan urutan batch. Uji pada PostgreSQL sesuai workflow CI, bukan hanya mock/unit test.

**Acceptance:** test concurrency/idempotency/rollback; bukti migration dan DB test di CI; output tidak menerbitkan snapshot parsial.

### J-PLAT-04 — Runtime evidence (untuk serving/experiment kemudian)

Catat status role DB runtime, worker timeout/retry/cancellation/idempotency, trace pagination/truncation, SLA benchmark pada volume yang disepakati, monitoring/rollback, dan frontend E2E. Ini tidak menggantikan Gate A/C, tetapi wajib sebelum integrasi serving/experiment yang memerlukan operasi tersebut.

## 5. Work package Moses — setelah kontrak tersedia

Moses tidak membuat label/fitur baru sebelum decision docs berstatus approved dan Gate C memiliki evidence. Setelah itu:

1. Buat compatibility matrix: kontrak approved → field sumber → transformasi → label/feature → tests.
2. Ajukan versi label/feature baru dan migration note; pertahankan hasil lama sebagai baseline referensi.
3. Tambah tests untuk cutoff, available-time, correction/refund, identity-as-of, missingness, eligibility dan null horizon.
4. Jalankan build pada dataset development yang memiliki semantik historis tervalidasi; simpan manifest/checksum pada path output baru.
5. Evaluasi baseline lama vs baseline baru dengan chronological split, purge label overlap, dan metrik yang disetujui. Jangan fit preprocessing pada holdout.
6. Buat model card baru: purpose, approved target, feature allowlist, split, metrics/uncertainty, limits, prohibited use, data lineage, owners.
7. Minta review lintas tim untuk `training_ready`/`experiment_ready`; flags tidak berubah otomatis karena test lulus atau PR merged.

**Training model ML tidak termasuk langkah otomatis.** Setelah Gate A–C, sepakati juga review Gate D dan acceptance metric sebelum estimator baru ditambahkan.

## 6. Handoff, PR, dan cara menutup item

Untuk tiap work package:

1. Owner membuka issue/PR dengan ID item (mis. `C-BIZ-01`), pertanyaan yang dijawab, file kontrak yang diubah, dan reviewer lintas tim.
2. Jangan menimpa dokumen/baseline existing; naikkan versi dan tulis changelog.
3. Sertakan contoh valid, invalid, boundary dan test yang mengunci keputusan.
4. Minta pemilik domain memberi approval eksplisit pada dokumen—label directory `approved/` atau merge PR bukan pengganti approval yang tercatat.
5. Jalankan seluruh CI yang relevan; catat workflow URL dan bukti PostgreSQL bila terkait.
6. Update matriks gate di Section 7 setelah owner dan reviewer menyetujui evidence.
7. Bila kontrak berbeda antar tim, tandai `BLOCKED` dan catat dua interpretasi; jangan menyelesaikan konflik dengan asumsi kode.

## 7. Gate tracker

| Gate / item | Owner | Status awal 2026-11-14 | Bukti untuk ditutup |
|---|---|---|---|
| A / C-BIZ-01 churn | Christ | BLOCKED — v1.2 REVISI | Approved version, approver/date, decision table, boundary tests |
| A / C-BIZ-02 value | Christ | BLOCKED — retention/source semantics open | Approved formula, field mapping, worked examples |
| A / C-BIZ-03 lifecycle | Christ | BLOCKED — priorities/treatment unresolved | Approved priority/treatment table, boundary tests |
| A / C-BIZ-04 consent | Christ | BLOCKED — approval/evidence review needed | Approved policy, valid/invalid contract tests |
| A / C-BIZ-05 outcome/KPI | Christ | BLOCKED — semantics/approval incomplete | Approved outcome/KPI/attribution contract and tests |
| B / CI/contracts | Joint | PASS for merged evaluator PR #31 only | Required current checks green for each implementing PR; no bypass |
| C / J-PLAT-01 availability/lineage | James | BLOCKED | Schema/contract, late-arrival and correction PostgreSQL tests |
| C / J-PLAT-02 identity as-of | James | BLOCKED | Effective-time design and as-of replay/merge/split tests |
| C / J-PLAT-03 multi-batch | James | BLOCKED | Written semantics plus PostgreSQL retry/idempotency/rollback tests |
| D / new Moses model work | Moses + reviewers | NOT OPEN | Gates A–C closed, acceptance criteria agreed, explicit model-readiness review |

**Gate close rule:** Gate A requires all C-BIZ items closed; Gate B requires the relevant PR checks/contracts pass; Gate C requires all J-PLAT-01..03 closed with evidence. Then schedule Gate D review. Do not set readiness flags as part of this checklist.

## 8. References

- `docs/TEAM_FOLLOW_UP_ACTIONS_2026-11-04.md` — owners, detailed acceptance gate, prohibitions.
- `docs/moses_data_ai/sprint_gate_status_2026-11-14.md` — current sprint status and synthetic diagnostics.
- `docs/moses_data_ai/TEAM_HANDOFF_2026-10-16.md` — delivered scope and existing handoff.
- `docs/moses_data_ai/independent_scope_completion.md` — independent scope closure and reopening conditions.
- `docs/moses_data_ai/model_card_development_v1.md` — limitations and prohibited uses of development baseline.
- `docs/christ_business/approved/target_definitions.md` — current business target draft/revision; review status before relying on it.
- `docs/james_platform/STATUS_TUGAS_JAMES.md` — platform implementation and operational blockers.
- `contracts/K-06_action_catalogue.json` through `contracts/K-11_audit_event_contract.json` — existing integration contract references.
