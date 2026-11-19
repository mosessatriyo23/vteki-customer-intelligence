# Peringatan artefak kontrak prediksi development pertama

Artefak `artifacts/predictions/churn_contract_dev_20260906/` berasal dari implementasi pertama commit `dc51805`. **Jangan gunakan artefak ini untuk acceptance I-04 atau handoff serving.** Artefak disimpan untuk audit, tidak ditimpa atau dihapus.

Review independen menemukan:

- Status `CONTRACT_COMPLIANT` hanya memeriksa skor dan jumlah kode, padahal prediction_id, kalibrasi, taxonomy dan teks bisnis belum tersedia/disetujui.
- Adapter menghilangkan status development, sehingga keluaran dapat disalahartikan sebagai input terkelola.
- Tanggal referensi memakai generated_at, bukan cutoff fitur. Keduanya sama pada run September, tetapi berbeda pada data stale/delayed dan menghasilkan window yang salah.
- Hash prediction_manifest yang direkam reason manifest belum dicocokkan, dan konsistensi cutoff/publication per baris belum ditegakkan.

Perbaikan commit `4049e7a` telah menutup temuan review utama: semua record valid kini `SCHEMA_PARTIAL`, adapter menolak secara default dan hanya menghasilkan preview development eksplisit, tanggal berasal dari cutoff, source expiry dipertahankan dan hash lineage diperiksa. Artefak pengganti `artifacts/predictions/churn_contract_dev_20260906_reviewed_v2/` berisi 50.640 `SCHEMA_PARTIAL`, 0 `INVALID_SCORE`, 50.141 reason_count_ok dan 41.830 memenuhi tiga konsep menurut mapping usulan. Reviewer independen memverifikasi checksum, tanggal, flag dan default adapter refusal. Regresi tambahan non-null source expiry diperbaiki setelah review: 57 focused tests lulus (bersama suite kalibrasi/eksperimen: 93 passed). Artefak real dengan semua expiry null tidak terdampak koreksi tambahan itu.

Metadata `proposed_valid_until` bukan otorisasi masa berlaku sumber: `valid_until` sebenarnya tetap null pada run tersebut. Tidak ada klaim acceptance I-04 atau serving dari artefak pengganti.

## Angka lama yang boleh dibaca secara terbatas

50.141 dari 50.640 record memiliki setidaknya tiga kode kontribusi fitur; 41.830 memenuhi minimal tiga konsep menurut pengelompokan development (ketiga frequency windows dianggap satu konsep). Ini hanya hitungan menurut mapping usulan, **bukan kepatuhan FRD atau approval Christ**. Selisih 8.311 juga tidak menutup masalah prediction_id, label bisnis, kalibrasi dan lineage.

Tidak ada CLV atau propensity yang boleh diisi placeholder untuk handoff nyata. Test fixture dengan angka inert bukan keluaran model atau izin integrasi.
