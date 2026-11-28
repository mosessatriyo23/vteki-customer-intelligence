# Permintaan Review Gate A — `target_definitions.md` v1.4
> **Pembaruan 2026-11-28:** dokumen yang direview kini `target_definitions.md` **v1.5 (draf)** (riwayat revisi di akhir dokumen) dan `reason_taxonomy.md`. Selain D1–D4 di bawah, mohon jawaban tertulis untuk **butir baru**: (a) **horizon churn 90 hari** (Christ menegaskan 90; Requirement menulis 180 dan 90); (b) **alasan churn**: ditambah dua faktor konteks bisnis (`MEMBERSHIP_EXPIRING`, `UNRESOLVED_COMPLAINT`) yang dihitung dari data nyata dan ditandai bukan hasil model; bila tetap kurang dari 3 alasan, yang ada tetap tampil tanpa alasan palsu (menyimpang dari "wajib minimal 3 Reason Codes"; juga mohon pendapat apakah faktor konteks boleh dihitung ke angka 3) (`target_definitions.md` §1.3, `reason_taxonomy.md` §3 dan §7); (c) **pembulatan CLV**: tier dari nilai tepat (sama dengan kode), half-up ke rupiah hanya untuk simpan/tampil (§2.4); (d) aksi lintas segmen untuk CHURNED/REACTIVATED/NEVER_TRANSACTED tidak dikalahkan NO_ACTION (§3.2.A); (e) RFM di luar MVP (§3.3). Belum ada persetujuan; approver/tanggal tetap `PENDING`.

**Dari:** Christ · **Tanggal:** 2026-11-19 · **Status:** MENUNGGU REVIEW. Belum ada persetujuan. Kolom approver/tanggal di `target_definitions.md` tetap `PENDING`.

## 1. Untuk Dosen Pembimbing / Mentor V-TEKI (persetujuan formal)
Mohon jawaban tertulis (nama, tanggal) untuk butir berikut. Tanpa itu Gate A tidak ditutup.

| # | Pertanyaan | Usulan penyusun | Dampak bila dijawab lain |
|---|---|---|---|
| D1 | `Requirement_Capstone` Bab 2.1 memuat "180 hari ke depan" (definisi churn) dan "jendela prediksi 90 hari". Mana yang menentukan **label**? | 90 hari | `labels.py` (menolak ≠ 90), konstanta horizon, contoh dokumen → versi baru |
| D2 | Pemetaan nama tier Bab 2.2 ("Platinum/Gold", "Gold/Silver", "Silver/Bronze") ke 4 label sistem | ≥1jt PLATINUM; 500rb–1jt GOLD; 200–500rb SILVER; sisanya INSUFFICIENT_HISTORY | tier & aturan aksi |
| D3 | Penyimpangan dari Bab 4: RETENTION_OUTREACH HIGH **dan** VERY_HIGH; RM_CONTACT tanpa batas lifecycle & keluhan aktif lewat COMPLAINT_RESOLUTION; WIN_BACK hanya DORMANT (181+), bukan "91–180"; RENEWAL_REMINDER tanpa ambang propensity | Diterima (alasan di §3.2) | Ubah `evaluator.py` + tes |
| D4 | Cakupan opt-out: channel-level + global hard stop (§4.3) | Diterima | Jika "opt-out kanal mana pun = blokir semua": ubah `is_opted_out`/gerbang consent |
| D5 | Pilihan bisnis KPI yang sengaja dikosongkan: jendela konversi per aksi, minimum lift, ukuran sampel minimum | Dosen/tim menetapkan | §7.4 tetap PENDING |

## 2. Untuk Moses (data/model — di luar wewenang Christ)
1. Label versi baru: cohort = ≥1 dari 3 negation event dalam (cutoff−365d, cutoff] (sekarang transaksi saja). Jangan timpa `churn90` lama.
2. `snapshot.py`: hapus `UNCLASSIFIED` (non-member recency > 365 → CHURNED; member aktif/kedaluwarsa ≤180 hari → DORMANT); NEW wajib total transaksi ≤ 2; selaraskan REACTIVATED dengan Requirement (≥2 belanja ATAU renewal).
3. Tabel Retention Factor = retensi empiris **12 bulan** per segmen (bukan 90 hari), sel < 30 pelanggan → null.
4. Data replenishment: kategori eligible, `replenishment_cycle_days` per kategori, `last_purchase_date` per kategori.
5. Data kepemilikan kategori (CROSS_SELL) dan tier membership (UPSELL).

## 3. Untuk James (kontrak historis v1.8 masih DRAFT — belum ada permintaan sign-off yang diajukan)
Saat sign-off diajukan, tinjauan Christ akan memeriksa makna bisnis berikut (bukan implementasi):
- **Refund/koreksi:** CLV historis memakai refund yang `known_at ≤ cutoff`; refund/koreksi yang tiba kemudian tidak mengubah skor cutoff lama. Selaras dengan §3 James (late event tidak dihitung ulang).
- **Ketersediaan:** `occurred_at` menentukan masuk jendela; `available_at` menentukan boleh dipakai. Feed refund/status belum ada: `MISSING`, bukan refund nol → CLV/label yang butuh refund **tidak boleh** dianggap lengkap.
- **Perpanjangan membership:** apakah nilainya ada di `transactions`? (menentukan CLV, §2.2).
- **Identitas:** `PROVISIONAL`/`REVIEW_REQUIRED` tidak dipakai untuk aksi komersial atau label produksi tanpa policy tertulis.
- **Consent:** sumber, timestamp, expiry, audit, dan perilaku setelah merge (most-restrictive-wins) — butuh producer.
Sign-off Christ hanya setelah dokumen James diajukan; tidak ada persetujuan di sini.

## 4. Draf pesan konfirmasi untuk dosen/mentor
> Selamat siang Bapak/Ibu. Pada Requirement Bab 2.1 terdapat dua angka: definisi churn "180 hari ke depan" dan jendela prediksi "90 hari ke depan". Kami mengusulkan 90 hari sebagai jendela label ML (alasan: label harus sama dengan horizon skor; seluruh implementasi dan contoh memakai 90). Mohon konfirmasi tertulis mana yang berlaku, serta tinjauan atas dokumen `target_definitions.md` v1.4 (lima butir D1–D5 di atas). Terima kasih.

## 5. Bukti teknis (lokal, 2026-11-19)
`pytest tests/decision docs/christ_business/reference/test` → 808 passed, 3 xfailed; `ruff`, `black --check`, `mypy services/decision` bersih. Belum ada bukti CI GitHub (Gate B). Perbaikan `OverflowError` `scores_are_valid()` (PR #39) sudah ada di kode beserta tes `TestScoresAreValidOverflowGuard`; diverifikasi untuk `10**400` pada CLV maupun skor probabilitas → mengembalikan `False`, engine memakai default konservatif.
