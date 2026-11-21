# Jawaban Christ untuk TEAM_ALIGNMENT_MVP_2026-11-21 (format §10)

**Tanggal:** 21 November 2026
**Status seluruh isi:** **USULAN Christ, bukan keputusan tim.** Tidak ada persetujuan mentor, model, atau
kebijakan dalam dokumen ini. Kolom bertanda `[ISI]` sengaja dikosongkan karena hanya manusia yang
bisa menunjuk orangnya.
**Bukti teknis:** `D5_NBA_INPUT_CONTRACT.md` (setiap klaim dikunci test terhadap engine asli).

Christ memiliki D5 dan ikut menentukan D2, D3, D7. D1, D4, D6 adalah keputusan Moses/Marvin/James;
yang ditulis di bawah hanyalah **kebutuhan dari sisi NBA**, bukan keputusan.

```text
Tanggal / link PR atau issue: 21 Nov 2026 / [ISI link PR Christ]

D1. Tabel/struktur yang dipakai dan perubahan minimal:
    Sisi NBA: pakai ml.prediction_review_runs/records yang sudah ada, TANPA tabel baru.
    Kebutuhan minimal NBA yang belum ada di struktur itu:
      (a) status izin pakai (usage_approved) + penyetuju + waktu, pada level run;
      (b) cara menggabungkan CHURN + propensity + CLV + lifecycle per pelanggan, karena satu
          record hanya memuat satu skor + band. Usulan: digabung di loader, bukan di tabel.
    Keputusan akhir: Moses + Marvin (James bila kontrak platform berubah).

D2. Identitas pembuat model, reviewer independen, aturan izin/cabut:
    Pembuat model: [ISI]    Reviewer independen: [ISI]    Penerima bisnis: Christ
    Aturan dari sisi NBA:
      - "reviewed" BUKAN izin pakai. NBA hanya memakai skor bila usage_approved bernilai True.
      - reviewer harus berbeda dari pengirim run DAN dari pembuat model (bila pembuat diketahui).
      - izin dicabut = usage_approved False -> NBA berhenti memakai skor itu pada evaluasi berikutnya.
      - Sampai sumber usage_approved ada, NBA menjawab "belum disetujui untuk dipakai". Ini benar.
    Peran Christ: menerima bahwa skor bermakna untuk keputusan aksi (penerimaan bisnis), BUKAN
    memvalidasi kualitas statistik model.

D3. Pemilihan versi/cutoff, expiry dan skor parsial:
    - Cutoff terbaru yang sah per pelanggan; tidak menggabungkan komponen dari cutoff berbeda.
    - Expiry 30 hari dari cutoff/generasi skor (bukan dari waktu impor). Tepat 30 hari masih sah.
    - Skor parsial, kosong, atau di luar rentang: ditolak seluruhnya, tanpa nilai pengganti.
    - Record berstatus SCHEMA_PARTIAL / INVALID_SCORE tidak dipakai.

D4. Pemetaan Golden ID -> pelanggan aplikasi:
    Kebutuhan NBA: customer_ref = golden_customer_id atau customer_code; pelanggan tanpa pemetaan
    pasti ATAU berstatus demo tidak dievaluasi. Tidak ada tebakan. Keputusan: Moses + Marvin (+ James).

D5. Input minimum NBA, band, reason codes dan perilaku saat kosong:
    Lihat D5_NBA_INPUT_CONTRACT.md. Ringkas:
      - reason codes: tidak dipakai logika, tidak menolak skor bila < 3; kalimat tampilan dari Moses.
      - band: wajib, harus konsisten dengan skor, berasal dari satu fungsi pemotong Moses.
      - CLV (angka) wajib untuk semua aksi promosi; tier CLV wajib untuk sebagian aksi.
      - kosong/expired/parsial: tolak seluruh skor (fail-closed); hanya COMPLAINT_RESOLUTION yang
        tetap jalan; nol adalah nilai, bukan "kosong".
      - sumber non-skor belum tersambung (None): "belum ada keputusan promosi", bukan izin.
    Butuh persetujuan: cut-off band FRD, pemetaan tier CLV, serta ditundanya "mode terbatas per aksi".

D6. Jadwal/pemicu worker, retry, PIC operasi:
    Kebutuhan NBA: batch scoring idempoten per (pelanggan, cutoff, jenis prediksi, run); retry tidak
    menggandakan record; hasil parsial tidak boleh tampak lengkap. Jadwal dan PIC: Moses + Marvin + James.
    PIC operasi: [ISI]

D7. Channel campaign demo dan skenario UAT yang disetujui:
    Usulan Christ: simulator ber-label jelas cukup untuk demo MVP; tidak ada pengiriman nyata (tidak
    ada kredensial, consent, maupun izin uji). MINTA KONFIRMASI MENTOR atas arti "campaign jalan
    beneran". Skenario UAT: docs/christ_business/demo/UAT_PLAN.md (14 kasus; semuanya masih
    "BELUM DIJALANKAN"), akan diselaraskan dengan daftar skenario wajib §7 TEAM_ALIGNMENT.
    Penandatangan UAT: [ISI]    Keputusan NO_ACTION yang benar ikut didemokan.

PIC tiap PR / reviewer / urutan merge (usulan):
    1) Moses: sumber usage_approved + loader skor.  2) James/Marvin: panggil evaluate_customer dan
    run_campaign di api/ dan worker/, simpan ke DB.  3) Marvin: tampilkan hasil DB.  4) Bersama: UAT.
    PIC/reviewer: [ISI]

Pertanyaan yang masih belum terjawab:
    - Sumber CLV dan lifecycle yang disetujui untuk NBA (hari ini keduanya dev-only/belum ada di tabel review).
    - Jawaban P1–P8 (rekonsiliasi v1.4) masih milik Christ + mentor dan BELUM dijawab di dokumen ini.
    - Arti "campaign jalan beneran" menurut mentor.
```

---

## Pesan siap kirim

### Ke Moses

> Halo Moses, makasih dokumennya. Jawaban sisi aku sudah ada di
> `docs/christ_business/integration/JAWABAN_TIM_D1_D7_CHRIST.md` dan `D5_NBA_INPUT_CONTRACT.md`.
> Intinya D5: reason code tidak dipakai logika NBA (tidak perlu ditolak kalau < 3), band wajib dan
> harus konsisten dengan skor dari satu fungsi pemotong, dan **CLV wajib untuk semua aksi promosi**,
> jadi skor churn + band saja belum cukup untuk rekomendasi apa pun. Kalau skor kosong/expired/sebagian,
> NBA menolak seluruh skor (tidak mengisi nol). Kalimat alasan dari PR #58 aku sisipkan apa adanya
> ke alasan keputusan; aku sudah hapus terjemahan reason code di sisiku supaya sumbernya tunggal.
> Satu hal penting: adapter NBA sekarang hanya memakai skor kalau `usage_approved` bernilai True
> (review saja bukan izin pakai), jadi butuh sumbernya dari kamu (D1/D2). Yang belum kujawab:
> P1–P8 dan nama reviewer/PIC.

### Ke James dan Marvin

> Update dari Christ: kode NBA dan campaign sisi `services/` sudah ada (`evaluate_customer`,
> `run_campaign`, contoh pemanggilan di `HANDOFF_JAMES_MARVIN.md`). Integrasi skor Moses ke NBA masih
> menunggu tiga hal: sumber `usage_approved` (D1/D2), sumber CLV + lifecycle, dan pemetaan Golden ID
> (D4). Selama itu NBA menjawab jujur "belum ada keputusan"/"belum disetujui", dan UI cukup
> menampilkan itu, bukan angka. Satu catatan untuk `api/decisions.py`: tolong jangan isi kelayakan
> dengan `tenure_days=0` dan `has_active_membership=False` saat sumbernya belum ada. Kirim `None`
> supaya hasilnya "belum tersambung", bukan "pelanggan ini bukan member".
