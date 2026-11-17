# Review Moses → James dan proposal sinkronisasi Christ

**Reviewer:** Moses (review Data/AI melalui coding assistant) · **Tanggal:** 2026-11-17.
**Basis review:** `main` commit `40f5096`; kontrak `docs/james_platform/approved/historical_data_contract_v1.x.md` (judul v1.3, changelog sampai v1.4), implementasi transaksi/identity/Customer360 dan acceptance packet. Tidak mencakup perubahan lokal James yang belum dipush.

**Keputusan review Moses: REQUEST CHANGES untuk kelayakan sumber training; ACCEPT WITH LIMITATIONS untuk arah kontrak development di bawah.** Ini adalah respons review nyata dari sisi Moses, bukan approval Christ, mentor, atau penutupan Gate C. `training_ready=false`, `experiment_ready=false`, `final_model=false`; Gate D NOT OPEN.

## 1. Respons konkret atas permintaan James

| Bagian kontrak | Disposisi Moses | Makna / tindakan |
|---|---|---|
| §1 waktu/provenance | Diterima sebagai rancangan development | Pisahkan occurrence sumber dari receipt database; source event ID/revision wajib pada event baru. Jangan backdate availability. Baseline legacy tanpa provenance tidak boleh dipromosikan sebagai source event lengkap. |
| §2 source coverage | Diterima pembatasannya, belum diterima untuk training | `OBSERVED_EVENTS_ONLY`, first-capture visit/renewal, serta MISSING refund/status harus dipertahankan. API append bukan bukti source completeness. |
| §3 cutoff visibility | Diterima sebagai kontrak yang akan diuji | `occurred_at <= effective_at`, `available_at <= known_at`, batch origin/receipt PUBLISHED. PostgreSQL acceptance PR #36 dan implementasi PR #35/#37 adalah evidence engineering, bukan bukti seluruh feed. |
| §4 projection | REQUEST CHANGES | Correction baseline setelah refund/status berpotensi membuang efek event yang tidak dikoreksi; wajib regression dan definisi ordering sebelum dipakai sebagai input moneter. |
| §5 batch/retry | Diterima arah kontraknya | Origin/receipt terpisah, exact replay no-op, conflict ditolak, rollback atomic, catalogue version eksplisit. Lengkapi matriks skenario→test; tidak meminta implementasi ulang fitur yang sudah merged. |
| §6 identity | Diterima batas coverage; REQUEST CHANGES pada end-to-end stability | Jangan menebak mapping sebelum baseline; revoke/correct review bukan otomatis undo mapping. Buktikan konsistensi journal + mapping + consumer dan stabilitas snapshot. |
| §7 Customer360 | Diterima sebagai utility terbatas saja | Bukan training source resmi; identity-aware tidak menjadikan agregat CSV bitemporal. |
| §8–9 evidence/approval | REQUEST CHANGES dokumentasi | Refresh referensi v1.3/v1.4, stale UNKNOWN identity text, CI pending dan migration head. Review Moses kini tersedia di dokumen ini; approval akhir tetap belum diberikan. |

## 2. Proposal antarmuka kebutuhan Moses (untuk James implementasikan/review)

**Status: proposed interface, bukan feature/label version baru.** James bebas mempertahankan nama API existing; yang penting semantics/metadata di bawah dapat diperiksa. Tidak perlu menunggu keputusan churn/retention untuk membangun query ledger dan metadata.

| Kebutuhan | Kontrak input/output yang diminta |
|---|---|
| Query | Parameter eksplisit `effective_at`, `known_at`, dataset/snapshot ID; timezone-aware. Jangan gunakan waktu sekarang secara implisit dalam replay. |
| Transaction | Source transaction ID, origin/receipt batch, contributing event IDs/revisions, projected status, gross, discount, cumulative refund, net dan actual revenue sebagai field terpisah. Jangan memilih gross vs actual untuk CLV atas nama bisnis. |
| Visit/membership | Source event ID, type/status, occurrence, authoritative receipt/recording, batch/schema/source revision semantics, previous/correction relation bila ada. RENEWAL dibedakan dari JOIN; membership expiry harus bersumber, bukan diasumsikan. |
| Identity | Mapping/registry version, effective/knowledge cutoff, coverage start, status AVAILABLE/BLOCKED/UNKNOWN dan unresolved count. Jangan drop unresolved tanpa audit atau membuat Golden ID palsu. |
| Coverage | Per family: first reliable capture, completeness evidence, observed-only flag, unknown/missing reason. Field kosong bukan nol, tidak aktif, atau tidak churn. |
| Publication | Immutable snapshot ID/key, source and rule/registry references, cutoff pair, row counts, schema version dan checksum. Exact replay no-op; changed payload pada key sama reject. Manifest tidak boleh berisi klaim training-ready dari CI saja. |

### Pemisahan fitur dan outcome yang diusulkan Moses

- **Feature snapshot:** hanya informasi yang memang diketahui pada `known_at` untuk business cutoff `effective_at`; jangan tambahkan correction yang baru datang belakangan ke snapshot lama.
- **Outcome extraction:** service/query terpisah dengan horizon serta observation/knowledge boundary eksplisit. Event setelah prediction cutoff boleh untuk outcome saja. Boundary ini bukan otomatis feature cutoff.
- **Maturity:** seluruh horizon dan coverage/settlement yang disepakati harus lengkap; bila belum, null + reason, bukan zero revenue/churn=0. Nilai horizon churn final dan lag **belum ditetapkan di sini**.
- **CLV:** kirim komponen moneter terpisah; calculator development menerima retention eksplisit. Moses mengusulkan metode di `RETENTION_METHOD_PROPOSAL_2026-11-17.md`; James tidak perlu menunggu angka retention untuk menyediakan histori. Tidak ada default 0.7 atau `1 - churn90`.
- **Lifecycle:** CHURNED tetap inactivity >365 hari **DAN** membership expiry >180 hari. Expiry yang tidak terbukti tidak boleh dijadikan CHURNED. Ini terpisah dari label churn ke depan.

## 3. Acceptance yang Moses minta sebelum review ulang

1. **Baseline correction ordering (P0):** transaction gross/net 1.000 pada t0, refund +100 t1, status CANCELLED t2, correction root TRANSACTION_RECORDED menjadi gross/net 1.200 pada t3 (baseline payload status COMPLETED, refund 0). Query sebelum correction tersedia harus mempertahankan histori lama; sesudah tersedia tidak boleh diam-diam membuang refund/status yang tidak dikoreksi. Tetapkan apakah replacement memakai posisi root atau aturan lain; setiap kontribusi harus auditable, hasil independen urutan input. Tambahkan pure regression dan PostgreSQL test. Jangan sekadar mempertahankan accumulator tanpa menangani root yang superseded.
2. **Identity (P0):** setelah merge lalu correction/revocation, journal dan mapping harus konsisten atau status eksplisit UNKNOWN/BLOCKED. Query cutoff lama dan snapshot terbit tidak berubah. Buktikan mutable `review_queue.decided_at` tidak mengubah hasil historis; populated-upgrade fixture harus mencakup review/coverage, bukan hanya transaction/visit/membership.
3. **Coverage (P0):** kirim matriks per event family dengan evidence atau UNKNOWN/MISSING. Integrasi feed sintetis harus traceable; jangan merekonstruksi original receipt dari event date. Fence yang jujur dapat menyelesaikan tugas dokumentasi tetapi tidak menutup training gap.
4. **Consumer (P0 untuk training, bukan untuk utility):** query ledger + known-at dipakai untuk semua agregat resmi; tidak membaca CSV current state secara diam-diam. Test event terlambat, refund correction, renewal/visit dan unresolved identity sampai output. Jika belum ada, utility tetap dev-only dan Gate C training scope BLOCKED.
5. **Evidence:** tautkan J-A..J-F yang relevan dari readiness packet ke test name, commit, CI run/result serta residual gap. Saya tidak mengklaim menjalankan PostgreSQL lokal; gunakan evidence CI yang sesuai head implementasi.

## 4. Proposal Moses untuk keputusan Christ — bukan approval pengganti

Christ dapat merespons tabel ini langsung dalam PR bisnisnya. Kolom respons saat ini **PENDING**; tidak ada angka bisnis atau approval yang diisi oleh Moses.

| ID | Proposal/permintaan dari Moses | Respons Christ |
|---|---|---|
| C1 churn | Pertahankan label development three-event 90 hari tanpa overwrite; minta keputusan spesifik 180/90 di Bab 2.1 dan measurable active cohort sebelum versi baru. Lifecycle CHURNED tidak diubah. | PENDING |
| C2 observability | Terima pemisahan feature-known-at dari outcome observation boundary pada §2; tentukan aturan finalisasi/refund/late event bersama James. | PENDING |
| C3 gross CLV | Tentukan field/status/refund/discount dan calendar 12m vs rolling 365d. James menyediakan komponen terpisah sehingga tidak perlu mengarang arti gross. | PENDING |
| C4 retention | Moses bertanggung jawab metode estimasi; proposal cohort sebagai reference transparan, survival sebagai kandidat bila event/coverage mendukung. Christ diminta review estimand/eligible cohort/reactivation, bukan mengarang faktor per pelanggan. Belum ada metode dipilih atau dilatih. | PENDING |
| C5 lifecycle/identity | Konfirmasi priority/fallback, arti unresolved/provisional, dan ketiadaan expiry; jangan samakan approval review dengan source completeness. | PENDING |
| C6 decisioning | Tutup consent, action eligibility/EV parameters, replenishment source, dan outcome/KPI melalui Gate A closure plan §4. Missing input tetap ineligible/default konservatif. | PENDING |

## 5. Urutan sinkronisasi agar tidak saling menunggu

1. **Moses (diserahkan sekarang):** review kontrak + proposed data interface di dokumen ini, retention/evaluation/reason-code designs PR #41; hasilnya bukan lagi “review Moses belum diberikan”. Final training-source approval tetap REQUEST CHANGES.
2. **James (bisa langsung):** konfirmasi interface §2, kerjakan P0 correction/identity, lengkapi coverage/evidence dan query ledger. Jika pilihan membutuhkan bisnis, bawa contoh konkret ke C1–C6; jangan hentikan seluruh pekerjaan platform.
3. **Christ:** respons C1–C6 dengan keputusan, contoh positif/negatif/boundary dan versioned rationale; minta actual authorized approval sesuai Gate A. Bisa paralel dengan James. Moses tidak mengatasnamakan Christ.
4. **James:** kirim PR/commit dan matriks test; Moses melakukan review ulang pada head tersebut. Catat ACCEPT/REQUEST CHANGES per issue, bukan meminta persetujuan abstrak seluruh proyek sekaligus.
5. **Bersama:** tutup gate hanya jika acceptance dan reviewer nyata lengkap. Tidak ada training/feature-label version baru sebelum Gates A–C dan Gate D review.

**Pesan siap kirim ke James:** “Bagian review/proposal Moses sudah tersedia di `docs/moses_data_ai/MOSES_REVIEW_JAMES_HANDOFF_2026-11-17.md`. Semantics cutoff/provenance dan dev-only fence diterima secara terbatas; training-source review REQUEST CHANGES dengan P0 spesifik di §3. Silakan lanjut interface/query ledger §2 dan regressions tanpa menunggu retention angka. Balas dengan commit + scenario/test matrix; keputusan bisnis C1–C6 menunggu Christ.”

**Pesan siap kirim ke Christ:** “Mohon respons C1–C6 di dokumen handoff Moses, bersama Gate A closure plan §4. Proposal metode retention sudah dibuat oleh Moses, bukan permintaan angka retention dari Christ. Kita butuh keputusan bisnis dengan boundary examples dan actual approval; James dapat paralel mengerjakan ledger/provenance. Jangan ubah status APPROVED sebelum reviewer berwenang menyetujui.”
