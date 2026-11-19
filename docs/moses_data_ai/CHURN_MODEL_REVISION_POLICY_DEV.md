# Revisi definisi bisnis dan model churn development

Status: development sintetis, bukan kontrak serving atau persetujuan Gate A/C/D. Moses mengerjakan model; Christ tetap pemilik keputusan bisnis. Tidak diperlukan rangkaian persetujuan formal untuk mencoba iterasi tugas kuliah; keputusan final cukup dicatat bersama versi dan contoh uji.

## Jika Christ mengubah aturan

| Perubahan | Dampak dan tindakan |
|---|---|
| Jenis event churn, cohort eligibility, batas waktu/horizon, perlakuan status/refund | **Breaking target change.** Catat keputusan/contoh, buat `label_version` baru, regenerasi labels dan training rows, lalu latih ulang dan evaluasi semua kandidat pada split temporal yang sama. Jangan bandingkan AUC versi berbeda sebagai kenaikan model pada target yang sama. Artefak lama tetap ada. |
| Definisi fitur atau mapping identitas historis | Buat `feature_version` baru dan snapshot baru. Latih ulang; jangan memuat model lama dengan fitur baru meskipun kolom/namanya sama. |
| Threshold risk band, treatment CRM, consent, cooldown | Catat `rule_version`/policy version baru; evaluasi dampak di layer decisioning bersama Christ. Jika input/target ML tidak berubah, model tidak otomatis harus dilatih ulang. Skor mentah tidak otomatis menjadi band/kampanye. |
| Rumus CLV, retention factor 12 bulan atau target propensity | Pisahkan dari churn. Retensi 90 hari deskriptif bukan faktor CLV; jangan mengganti output churn menjadi CLV atau booking proxy. |

## Syarat demo offline sekarang

- Train/evaluate pada label `christ-churn90-three-events-dev-1.2`, fitur `event-time-dev-1.0`. Output model development menyimpan versi label/fitur, artefak dan checksum. `training_ready=false`, `experiment_ready=false`, `final_model=false`, `serving_ready=false`.
- Prediksi offline hanya mengonsumsi **baris fitur tanpa label**, dengan metadata versi dan batas cutoff eksplisit. File evaluasi holdout yang memuat outcome tidak boleh digunakan sebagai input scoring atau dikirim ke NBA.
- Seluruh data adalah sintetis; retrospective current identity dan CSV final-status tidak menjamin historical `known_at`. Tidak ada bukti kalibrasi, reason codes bisnis minimal tiga, valid_until serving, atau I-04 governed producer. Jangan mengklaim model siap campaign.
- Jika Christ nanti memilih definisi lain, alur yang benar adalah **revisi kontrak → test boundary → hasilkan label/fitur versi baru → retrain → bandingkan di cohort baru**, bukan mengganti metadata versi pada model lama.

## Ketergantungan lintas tim yang tidak perlu menahan demo offline

James: feed PIT `known_at`, refund/status correction dan identity-as-of; Christ: keputusan target final, cohort never-transacted, suppression/policy dan treatment. Demo offline development tetap dapat dilakukan secara jujur sambil mencatat batas ini. Integrasi scoring ke API/worker dan pengiriman campaign adalah pekerjaan terpisah setelah protokol data consumer disepakati.
