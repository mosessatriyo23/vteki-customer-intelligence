# Rencana UAT — Decisioning (NBA + Campaign)

UAT dilakukan **setelah web selesai** dan NBA/campaign tersambung ke aplikasi. Dokumen ini hanya rencana: semua kolom **Hasil** sengaja `BELUM DIJALANKAN`. Isi hanya setelah benar-benar diuji, dengan bukti (screenshot, ID keputusan, atau `correlation_id`).

## Prasyarat

- Aplikasi berjalan dari repo, data tampil dari database (bukan data contoh).
- Run model sudah berstatus `reviewed` oleh orang berbeda dari pengunggah.
- Sumber consent, komplain, dan riwayat kontak sudah tersambung (kalau belum, UAT-02 s.d. UAT-04 diuji sebagai "belum tersambung").
- Penguji bukan pembuat kode.

## Kasus uji

| ID | Skenario | Langkah | Hasil yang diharapkan | Hasil |
|---|---|---|---|---|
| UAT-01 | Rekomendasi normal | Evaluasi pelanggan dengan skor ter-review, consent lengkap, tanpa komplain | Aksi disarankan, alasan kalimat Indonesia sederhana, nilai Rp berformat titik, `model_version` tercatat | BELUM DIJALANKAN |
| UAT-02 | Pelanggan opt-out | Evaluasi pelanggan yang menolak dihubungi | `NO_ACTION`, alasan menyebut penolakan kontak | BELUM DIJALANKAN |
| UAT-03 | Komplain berat terbuka | Evaluasi pelanggan dengan komplain berat terbuka | `COMPLAINT_RESOLUTION`, tidak ada promosi | BELUM DIJALANKAN |
| UAT-04 | Fatigue | Pelanggan sudah menerima 2 pesan dalam 14 hari | `NO_ACTION`, alasan menyebut batas pesan 14 hari | BELUM DIJALANKAN |
| UAT-05 | Skor belum direview | Pakai run model berstatus `pending_review` | Tidak ada rekomendasi; alasan menyebut skor belum diperiksa orang lain; tidak ada angka skor/EV | BELUM DIJALANKAN |
| UAT-06 | Review oleh pengunggah sendiri | Run di-review akun yang sama dengan pengunggah | Skor ditolak, alasan "orang yang sama" | BELUM DIJALANKAN |
| UAT-07 | Data kosong tampil kosong | Pelanggan tanpa skor / sumber belum tersambung | UI menampilkan "kosong/belum tersambung", tanpa angka contoh | BELUM DIJALANKAN |
| UAT-08 | Campaign tanpa persetujuan | Jalankan campaign tanpa `approved_by` | Ditolak, tidak ada pesan terkirim | BELUM DIJALANKAN |
| UAT-09 | Campaign berjalan | Setujui lalu jalankan campaign simulasi | Ringkasan: audiens, layak, terkirim (simulasi), holdout ≈10%, paparan control = 0, tanpa pengiriman eksternal | BELUM DIJALANKAN |
| UAT-10 | Yang diblokir tidak dikirimi | Audiens berisi opt-out, komplain, fatigue | Mereka muncul di daftar "dilewati" dengan alasan, tidak di pengiriman | BELUM DIJALANKAN |
| UAT-11 | Pengukuran kosong | Lihat hasil campaign sebelum ada konversi | Status `AWAITING_OUTCOMES`, angka lift tidak ditampilkan | BELUM DIJALANKAN |
| UAT-12 | Pengukuran dengan hasil | Masukkan hasil konversi, ukur | Observed dan Incremental revenue terpisah, status PROVISIONAL/FINAL sesuai jendela | BELUM DIJALANKAN |
| UAT-13 | Jejak audit | Buka audit trail keputusan dan campaign | Ada `nba.engine_evaluated`, `campaign.executed`, `campaign.measured` dengan `correlation_id` sama | BELUM DIJALANKAN |
| UAT-14 | Hasil tersimpan di database | Muat ulang aplikasi / restart server | Keputusan, hasil job campaign, dan pengukuran masih ada (bukan hanya di file/memori) | BELUM DIJALANKAN |

## Bukti pra-UAT otomatis (bukan pengganti UAT)

Perilaku inti kasus di atas sudah dijaga test otomatis pada level fungsi:
`tests/decision/test_nba_serving.py` (UAT-01 s.d. UAT-07) dan `tests/decision/test_campaign_pipeline.py` (UAT-08 s.d. UAT-12). UAT-13 dan UAT-14 baru bisa diuji setelah `api/` dan `worker/` menyimpan hasilnya.

Jalankan demo untuk gambaran alur (data sintetis): `PYTHONPATH=. python docs/christ_business/demo/run_demo.py`

## Skrip demo (±5 menit)

1. Tunjukkan 5 profil pelanggan dan alasan tiap keputusan (bagian [1] demo).
2. Jalankan campaign: tunjukkan holdout dan paparan control = 0 (bagian [2]).
3. Tunjukkan bahwa sebelum ada konversi, angka lift tidak ditampilkan (bagian [2]).
4. Masukkan hasil konversi, tunjukkan Observed vs Incremental (bagian [3]).
5. Tutup dengan jejak audit (bagian [4]).

Untuk demo di aplikasi, ulangi langkah 1-5 lewat UI dengan data dari database dan sebutkan apa adanya bagian yang masih kosong.
