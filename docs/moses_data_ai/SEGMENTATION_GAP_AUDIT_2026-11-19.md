# Audit gap segmentasi terhadap FRD/TRD dan Christ v1.3

Audit read-only terhadap implementasi dan definisi tests; bukan sertifikasi test dijalankan. Acuan `target_definitions.md` v1.3 adalah arah revisi, bukan bukti approval final mentor. Laporan ini memperbarui bagian segmentasi alignment 17 November yang sudah tertinggal.

## Sudah tersedia

`services/data/segmentation/snapshot.py` menghitung fixed-band RFM dan lifecycle development. Prioritas sudah sesuai arah v1.3: REACTIVATED > LOYAL > NEW > NEVER_TRANSACTED > inactivity stages > ACTIVE > OCCASIONAL. AT_RISK recency-only sudah mengikuti keputusan C v1.3; jangan menyebutnya bug yang harus ditambah membership gate tanpa memeriksa keputusan itu.

`persistence.py` menyimpan snapshot immutable dengan key customer/cutoff/identity-version/rule-version: replay identik no-op, perubahan payload key sama ditolak, versi lama tetap tersimpan. Ini histori snapshot nyata, tetapi **bukan** effective-dated segment membership lengkap dengan valid_from/valid_to dan transition record.

## Gap teknis jelas

- NEW sebelumnya belum membatasi lifetime qualifying POS count <=2. Diperbaiki commit `586088b` dengan rule version `lifecycle-proposed-1.2-christ-new-lifetime-guard`: count memakai history cutoff/dedup, bukan rolling-window count. Tests mencakup count/tenure boundary, future/duplicate isolation, preservation nilai fitur dan snapshot versi lama. Focused segmentation/atomicity 10 passed; isolated SQLite setup kini mendaftarkan source-table metadata secara eksplisit.
- RFM memakai fixed thresholds, bukan population quintiles seperti TRD §9.2.
- Tidak ada mapping RFM code ke nama segment, audience exclusion eksplisit, konfigurasi band/mapping tersimpan.
- RFM recency memakai stream aktivitas termasuk visits/renewal, padahal FRD RFM menyebut positive-net purchase; perlu pisahkan dari lifecycle activity recency tanpa merusak fitur/model lama.
- Behavioral K-means, silhouette k=3..8, profiling lima fitur pembeda, serta gating nama/deskripsi manusia belum tersedia.
- API Customer360 belum mengekspos segmentation rule version terpisah dari profile version; integrasi James diperlukan.

## Jangan memutuskan policy diam-diam

| Pertanyaan | Mengapa belum ditutup |
|---|---|
| DORMANT recency-only atau wajib expiry overdue 1–60? | Tabel dan judul keputusan C v1.3 tidak cukup jelas; contoh operatif keputusan itu menyebut AT_RISK |
| Recency >365 dengan expiry unknown/current/recent? | CHURNED guard benar menolak asumsi expiry; UNCLASSIFIED fallback belum masuk daftar sembilan label |
| ACTIVE membership digunakan 60 hari | Tidak ada bukti bahwa completed visit atau renewal otomatis merupakan penggunaan membership |
| Renewal sebagai frequency/revenue resmi | Perlu aturan pencatatan agar tidak double count transaksi POS terkait renewal |
| REACTIVATED | Implementasi satu purchase setelah gap>180 dan persistence30d tidak setara prior DORMANT/CHURNED lalu >=2 purchases atau renewal; perlu durasi status dan bukti prior-state |
| NEVER_TRANSACTED | Kode mendeteksi ketiadaan semua aktivitas qualifying, bukan POS saja; tentukan semantik visit-only/renewal-only |
| RFM active cohort, named mapping, monetary basis | Jangan mengarang Champions mapping atau menyamakan actual_revenue/net_amount tanpa konvensi sumber |
| Label antar kontrak | FRD LAPSED/RECLAIMED vs Christ DORMANT/REACTIVATED memerlukan mapping resmi |

## Behavioral slice yang masih bisa dilakukan

Perhitungan cluster dan profiling dapat dibuat sebagai development proposal berbasis fitur behavioral yang benar-benar tersedia, tanpa label bisnis buatan. Targeting harus fail-closed sampai manusia memberi nama/deskripsi dan acceptance. Keterbatasan cakupan fitur harus dinyatakan bila belum ada app/complaint/exposure.

## Bukti tests existing yang terbatas

`test_segmentation.py` menguji boundary/fallback dan future transaction isolation; belum membuktikan quintiles, membership usage, event-derived REACTIVATED atau cluster. Snapshot atomicity tests membuktikan version preservation/overwrite rejection, bukan interval membership. Tests downstream decision dengan label supplied tidak membuktikan classifier menghasilkan label benar.

Jangan menyatakan seluruh data/AI selesai hanya karena model sudah dilatih: segmentasi merupakan bagian FRD/TRD yang masih memiliki gap implementasi dan policy di atas.
