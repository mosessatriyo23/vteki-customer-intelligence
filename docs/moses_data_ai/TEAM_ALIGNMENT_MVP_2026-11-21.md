# Panduan bersama Moses, Christ, dan Marvin: progres dan penyelesaian MVP

> ## Pembaruan 2026-11-22 (baca dahulu; bagian di bawah ini adalah baseline `6b40f16`)
>
> `main` kini `dff1002`. Beberapa pernyataan "belum ada" di bawah **sudah tidak berlaku**:
>
> | Pernyataan lama | Kondisi terbaru |
> | --- | --- |
> | NBA dipanggil dengan `ai_scores=None` (§4.2) | `api/decisions.py` dan `worker/tasks.py` membaca prediksi lewat `api/decision_inputs.py` dan memanggil adapter `services/decision/nba/serving.py` |
> | Campaign hanya simulator tanpa riwayat kontak | Pipeline campaign Christ dipanggil worker; riwayat kontak (`act.campaign_contact_history`, migrasi 0026) disimpan dan dibaca NBA; outcome kosong berstatus `AWAITING_OUTCOMES`, bukan angka contoh |
> | Endpoint keputusan manual dan override ganda | `POST /decisions/next-best-actions` dan override di `api/decisions.py` dihapus; override tersisa di `api/governance.py` |
>
> **Masih berlaku, dan inilah penyebab skor belum bisa dipakai:**
>
> 1. `usage_approved` selalu `None` (`api/decision_inputs.py`). Belum ada sumber izin penggunaan, jadi NBA menjawab `MODEL_USAGE_NOT_APPROVED`. Perlu keputusan D1/D2 oleh manusia; jangan diganti `True`.
> 2. Producer churn Moses hanya mengeluarkan `SCHEMA_PARTIAL`/`INVALID_SCORE`. Loader kini menolak keduanya dan hanya membaca tipe `CHURN`, dengan cutoff diurutkan sebagai waktu (bukan teks). Akibatnya **tidak ada data nyata yang lolos sampai status yang lengkap dan disetujui ada**. Ini disengaja (fail-closed), bukan bug. Catatan: alasan yang tampil di UI untuk kasus ini masih "skor belum tersedia" (`SCORE_ROW_MISSING`), bukan "kontrak belum lengkap"; pembedaan alasan perlu disepakati dengan Christ.
> 3. Propensity, CLV, tier dan lifecycle dibaca dari `source_record`, belum dari sumber yang disetujui. Producer churn tidak menghasilkannya. Jangan mengisi nilai buatan.
> 4. Consent, komplain, kelayakan dan ketersediaan produk masih `None` di API/worker, sehingga evaluasi belum menghasilkan keputusan promosi walau skor sudah sah.
> 5. Worker scoring belum ada (`PIPELINE_STEPS = ("audit_summary",)`); kalimat alasan PR #58 belum dipanggil producer mana pun.
> 6. Jawaban Christ ([D1–D7](../christ_business/integration/JAWABAN_TIM_D1_D7_CHRIST.md), [D5](../christ_business/integration/D5_NBA_INPUT_CONTRACT.md)) adalah **usulan Christ, bukan keputusan tim/mentor**. P1–P8 belum dijawab. Nama pembuat model, reviewer dan PIC masih kosong.
>
> Pertanyaan yang belum diputuskan dan menjadi syarat sebelum implementasi berikutnya: sumber `usage_approved` (D1/D2), cut-off band 0,30/0,60/0,80, pemetaan tier CLV, "mode terbatas per aksi" (Christ mengusulkan ditunda), dan perubahan skema bila diperlukan (James dilibatkan karena migrasi 0026 sudah dibuat Marvin).

**Tanggal:** 21 November 2026. **Baseline kode:** `main` pada merge PR #58, `6b40f16`.
**Pembaca:** Moses (data/model), Christ/Chris (NBA dan kebijakan bisnis), Marvin (integrasi aplikasi/UI).

Dokumen ini merangkum arahan mentor yang disampaikan Moses, kondisi kode yang diperiksa, dan pekerjaan yang perlu disepakati. Ini **bukan persetujuan model atau perubahan kebijakan**. Tugas bersama di bawah adalah usulan pembagian kerja, bukan klaim bahwa anggota tim sudah menyetujuinya. James tetap dilibatkan jika perubahan menyentuh kontrak platform yang sebelumnya ia pegang.

## 1. Ringkasan yang perlu semua orang pahami

Menurut komentar mentor yang disampaikan Moses, progres dan arsitektur sudah sesuai MVP; fokus berikutnya adalah menyambungkan bagian model, bukan mengganti arsitektur atau mengejar model yang lebih rumit.

**Yang sudah tersedia:** pemrosesan data, fitur, model ML development, evaluasi, inferensi, penyimpanan prediksi untuk review, pencatatan versi, review oleh akun berbeda, mesin NBA, penyimpanan keputusan/campaign, dan layar review prediksi.

**Yang belum selesai:** jalur otomatis dari hasil model yang layak digunakan → database → pemeriksaan yang benar-benar menjadi syarat penggunaan → NBA → campaign → UI. Kalimat alasan Indonesia sudah dibuat di PR #58, tetapi belum dipanggil oleh aplikasi.

Artinya: **bukan mulai model dari nol, tetapi menutup sambungan dan aturan penggunaannya.** Jangan membuat tabel, endpoint, atau angka contoh baru sebelum memeriksa yang sudah tersedia.

### Tiga arti status yang berbeda

| Istilah | Artinya | Bukan berarti |
| --- | --- | --- |
| Tersedia | Fungsi/tabel/layar sudah ada | Otomatis dipakai alur aplikasi |
| Terintegrasi | Komponen benar-benar saling memanggil dan membaca hasil tersimpan | Hasil model sudah disetujui |
| Disetujui untuk digunakan | Ada pemeriksaan, kewenangan, dan aturan pemilihan hasil yang disepakati serta ditegakkan kode | Sekadar lolos tes atau berstatus `reviewed` |

## 2. Arahan mentor dan batas arsitektur

Ringkasan arahan mentor yang disampaikan di percakapan:

- **Moses:** simpan skor ke database agar dapat dipakai NBA; jelaskan alasan dengan bahasa sederhana; catat versi model dan minta orang lain memeriksa sebelum digunakan.
- **Christ:** sambungkan NBA dengan Marvin; jalankan alur campaign; siapkan demo dan UAT setelah web selesai.
- **Marvin:** hilangkan data/label palsu seperti “Ramadan Radiance” dan “78% Likelihood”; pastikan repo dapat dijalankan; sambungkan hasil Moses/Christ ke UI.
- **Bersama:** pertahankan arsitektur dan model ML sederhana. `services/` menghitung; `api/` dan `worker/` memanggil serta menyimpan. Simpan skor, keputusan, campaign dan jejak audit di database. Jangan tampilkan contoh sebagai hasil asli; bila kosong, tampilkan kosong. Periksa tumpang tindih fungsi endpoint, jangan menghapus hanya karena URL-nya mirip.

**Keputusan Moses yang sudah dicatat:** worker menjadi pelaksana batch scoring/penyimpanan; API menyediakan pembacaan hasil. Perubahan skema ditahan sampai ada konfirmasi tim. Ini rancangan alur target, **bukan kondisi worker saat ini**. Endpoint impor manual untuk review sudah ada dan tidak boleh dihapus tanpa menilai konsumennya.

```text
Alur target (belum tersambung seluruhnya):
Sumber/identitas valid → fitur → fungsi scoring services/
                                  ↓ dipanggil worker/
                         skor + versi + alasan di DB
                                  ↓ pemeriksaan independen dan izin pakai
                    API/orchestrator memuat input NBA yang sah
                                  ↓
                 fungsi NBA services/ → keputusan disimpan di DB
                                  ↓
                 campaign + hasil eksekusi + audit disimpan di DB
                                  ↓
                           API baca → UI Marvin
```

`services/` tidak membuka koneksi database dan tidak memanggil API balik. Worker tidak perlu memanggil endpoint HTTP milik aplikasinya sendiri jika fungsi persistensi bersama di lapisan orchestration sudah cukup. Pilihan implementasi pastinya masih perlu disepakati.

## 3. Bagian Moses: progres yang benar-benar sudah ada

| Area | Hasil yang tersedia | Batas yang masih berlaku |
| --- | --- | --- |
| Data dan identitas | Generator sintetis, validasi ingestion, identity resolution dan Golden ID | Identitas/as-of historis belum membuktikan data produksi aman; jangan menyamakan Golden ID dengan integer ID aplikasi |
| Fitur dan segmentasi | Snapshot fitur event-time, lifecycle/RFM development, behavioral clustering dan profiling | Nama/aturan segmen bisnis serta membership persisten tidak otomatis disetujui; clustering tidak perlu dibangun ulang |
| Model | Churn, propensity retail dan renewal sudah memiliki eksperimen/evaluasi development; reload inferensi tersedia | Tidak ada model pemenang atau izin serving; booking belum punya sumber/outcome yang disepakati |
| CLV | Agregasi `actual_revenue` dan wrapper formula proyeksi | Faktor retensi empiris final, pembulatan dan tier masih perlu keputusan; bukan fitted model CLV final |
| Penjelasan numerik | Kontribusi log-odds per fitur tersedia | Pengaruh pada perhitungan bukan penyebab bisnis, dan tiga fitur berkorelasi bukan otomatis tiga alasan bisnis berbeda |
| Penjelasan kalimat | PR #58: `score_explanations.explain_contributions()` menghasilkan kalimat Indonesia | Fungsi belum dipanggil worker/API/UI; tidak membuat reason-code taxonomy atau risk band |
| Monitoring dan kualitas | PSI/volume advisory, quality report offline dan tes leakage event-time | Bukan blocking platform; band mix/outcome segmen belum tersedia; bukan bukti `known_at`/identity-as-of safe |
| Versi dan review | Inventaris development, metadata versi; DB run prediksi dan review akun berbeda sudah ada | Review run belum menjadi izin pemakaian model oleh NBA; belum ada promosi model final |

Sumber implementasi utama: [fitur](../../services/data/features/snapshot.py), [segmentasi](../../services/data/segmentation/), [model](../../services/data/models/), [ledger pekerjaan](MOSES_INDEPENDENT_WORK_LEDGER_2026-11-20.md).

### Arti kalimat alasan dari PR #58

Fungsi menerima catatan kontribusi yang sudah dihasilkan inferensi churn/propensity, bukan mengarang alasan dari nilai skor saja. Hasilnya berisi `sentences`, `notice`, dan `version` (`score-explanation-id-1.0`).

- Arah kalimat mengikuti tanda kontribusi: mendorong skor naik atau turun.
- Kontribusi nol tidak dibuat menjadi alasan; daftar kosong tetap kosong.
- Jika fitur kosong, pemakaian nilai pengganti disebutkan hanya setelah nilai itu valid.
- Field wajib, angka tidak valid dan nilai imputasi yang tidak konsisten ditolak.
- Tidak ada angka persentase buatan, klaim kausal, atau status “disetujui” yang ditambahkan.

**Kalimat bukan pengganti `reason_codes`.** Christ perlu memastikan apakah NBA membutuhkan kode stabil untuk logika; Marvin menampilkan kalimat untuk pembaca. Keduanya tidak boleh dicampur diam-diam.

Sumber: [formatter](../../services/data/models/score_explanations.py), [31 tes formatter](../../tests/data/test_score_explanations.py).

## 4. Sambungan aplikasi yang sudah ada dan yang belum

### 4.1 Prediksi sudah bisa disimpan, tetapi untuk review

Tabel `ml.prediction_review_runs` menyimpan identitas run: versi model/fitur/label, jenis prediksi, hash manifest, jumlah record, pengirim dan hasil review. Tabel `ml.prediction_review_records` menyimpan skor per pelanggan/cutoff, band, reason codes, fingerprint dan source record.

Endpoint yang **sudah ada** di [api/model_predictions.py](../../api/model_predictions.py):

| Endpoint | Kegunaan saat ini |
| --- | --- |
| `POST /model-predictions/runs/import` | Impor manifest/record tervalidasi, cek Golden ID, simpan run/record dan audit |
| `GET /model-predictions/runs` | Daftar run untuk review |
| `GET /model-predictions/runs/{run_id}/records` | Baca record, termasuk lookup pelanggan aplikasi untuk tampilan |
| `POST /model-predictions/runs/{run_id}/review` | Akun lain menandai `reviewed` atau `rejected`, dengan catatan dan audit |

Semua memerlukan role admin/analyst. Pengirim tidak boleh mereview run-nya sendiri. Namun **pengirim belum tentu sama dengan pelatih model**, jadi larangan ini belum membuktikan author model ≠ validator model. Respons tetap `serving_ready=False`, termasuk setelah `reviewed`.

Sumber skema: [api/models.py](../../api/models.py), [migrasi 0024](../../migrations/versions/0024_moses_prediction_review.py). **Belum diputuskan apakah tabel ini cukup untuk konsumsi NBA. Jangan langsung membuat tabel baru.**

### 4.2 NBA sudah berjalan dan tersimpan, tetapi belum memakai prediksi Moses

[api/decisions.py](../../api/decisions.py) sudah memiliki alur keputusan manual, evaluasi mesin NBA, dan override. Pada evaluasi saat baseline ini, pemanggilan mesin memakai **`ai_scores=None`**; consent/input lain yang belum tersedia diperlakukan unknown/kosong secara konservatif.

Mesin NBA menggunakan [AIScores](../../services/decision/nba/engine.py), yang menggabungkan churn, band, propensity pembelian/renewal, CLV/tier, lifecycle, waktu skor dan reason codes. Ini **berbeda** dari satu baris prediksi per target. Karena itu diperlukan adapter/pemetaan yang jelas, bukan sekadar menyalin satu angka ke layar.

Jangan mengisi skor target yang belum ada dengan nol untuk membuat kontrak lolos: nol adalah nilai prediksi, bukan tanda “tidak tersedia”. Tim harus menyepakati perilaku saat input hanya sebagian tersedia.

### 4.3 Worker belum menjadwalkan scoring Moses

[worker/scheduler.py](../../worker/scheduler.py) saat ini mencantumkan `PIPELINE_STEPS = ("audit_summary",)`. Handler campaign ada di [worker/tasks.py](../../worker/tasks.py), tetapi ini bukan scoring model. Jalur scoring → penyimpanan batch perlu ditambahkan setelah kontraknya disepakati.

### 4.4 Campaign dan UI bukan mulai dari nol

[api/campaigns.py](../../api/campaigns.py) sudah menyimpan campaign, approval, hubungan ke keputusan NBA, dan job eksekusi. Campaign dari keputusan `NO_ACTION` dan pelanggan yang ditandai demo ditolak. Launch mengantrekan **simulator channel**, bukan pengiriman pesan sungguhan.

[web/src/api.ts](../../web/src/api.ts) dan [web/src/App.tsx](../../web/src/App.tsx) sudah mempunyai pemanggilan keputusan/campaign serta layar review prediksi. Layar review belum menjadi sambungan prediksi yang disetujui ke NBA. Keberadaan UI/guard demo bukan bukti bahwa semua data palsu sudah bersih atau deploy sudah diterima; itu perlu diuji Marvin.

**Makna “campaign jalan beneran” perlu dikonfirmasi mentor:** apakah alur end-to-end tersimpan dengan simulator yang diberi label jelas sudah cukup untuk MVP, atau diperlukan channel sandbox/nyata. Jangan membuka pengiriman nyata dengan hanya mematikan flag simulator; dibutuhkan kredensial, consent dan izin pengujian yang sesuai.

## 5. Keputusan bersama yang membuka pekerjaan Moses

Isi keputusan ini lewat PR/issue atau catatan rapat yang dapat dirujuk. Status seluruh baris masih **menunggu kesepakatan**, kecuali pilihan worker dan penahanan skema pada §2.

| ID | Pertanyaan yang harus dijawab | Pengambil keputusan yang diusulkan | Setelah dijawab |
| --- | --- | --- | --- |
| D1 | Apakah tabel review existing dipakai juga untuk konsumsi NBA? Perlukah perubahan minimal untuk alasan, status izin pakai atau referensi versi? | Moses + Marvin; James bila kontrak platform berubah | Moses dapat merancang persistensi tanpa duplikasi skema |
| D2 | Siapa pelatih/penghasil model dan validator yang berbeda? Apa arti review run dibanding persetujuan versi model? Kapan hasil boleh dipakai dan bagaimana ditolak/dicabut? | Moses + reviewer independen yang ditunjuk; Christ untuk penerimaan bisnis | Moses dapat menegakkan gate izin penggunaan, bukan cuma label UI |
| D3 | Versi/jenis skor mana dipakai NBA? Bagaimana memilih cutoff terbaru yang sah, expiry, dan menangani hasil parsial/expired? | Moses + Christ + Marvin | Adapter dan query pembacaan bisa diuji |
| D4 | Bagaimana Golden ID dipetakan ke ID pelanggan aplikasi tanpa tebakan dan tanpa pelanggan demo? | Moses + Marvin; James untuk kontrak identitas | Skor dan keputusan bisa dihubungkan ke pelanggan yang benar |
| D5 | Band/tier, reason codes dan input minimum apa yang dibutuhkan NBA? Apakah alasan yang belum mencukupi menolak penggunaan atau masuk mode terbatas? | Christ + Moses | Tidak perlu mengarang band/CLV/3 alasan agar kontrak lolos |
| D6 | Jadwal scoring, pemicu manual bila perlu, aturan retry/idempotensi dan siapa yang mengoperasikan worker? | Moses + Marvin; James untuk deployment worker | Batch bisa dijalankan ulang tanpa menduplikasi hasil |
| D7 | Campaign simulator cukup untuk demo MVP atau perlu channel lain? Skenario dan penandatangan UAT siapa? | Christ + Marvin + mentor | Target demo jelas tanpa klaim pesan sudah terkirim |

**Paling minimum agar Moses lanjut ke integrasi:** putuskan D1–D4 dan bagian input minimum D5. D6 bisa diselesaikan saat slice worker; D7 diperlukan sebelum menyatakan demo campaign selesai.

## 6. Pembagian pekerjaan berikutnya

### Moses — skor dan alasan yang dapat ditelusuri

1. Setelah keputusan skema: hubungkan fungsi scoring existing ke worker, tanpa akses DB di fungsi perhitungan.
2. Simpan skor, target, versi/referensi artefak, waktu cutoff/generasi, status ketersediaan, dan alasan menurut kontrak final. Gunakan/revisi struktur existing terlebih dahulu.
3. Sambungkan formatter PR #58; pertahankan kontribusi numerik dan jejak asal. Kalimat tidak boleh membuat skor seolah sudah disetujui.
4. Terapkan pemeriksaan independen yang disepakati; pastikan hasil pending/rejected/expired tidak dipakai NBA. Review kode oleh agen bukan pengganti persetujuan model oleh validator tim.
5. Buat adapter input NBA bersama Christ dan acceptance fixtures bersama Marvin; verifikasi identitas, timestamp dan hasil parsial.
6. Berikan kontrak baca serta bukti run database kepada tim; model tidak diganti hanya untuk mengejar akurasi.

### Christ — makna bisnis, NBA dan penerimaan demo

1. Jawab kebutuhan input minimum NBA, band, alasan bisnis dan aturan penanganan skor kosong/expired; bedakan kode mesin dari kalimat tampilan.
2. Tentukan perilaku NBA ketika data consent/eligibility belum ada. Jangan memberi izin otomatis dari data kosong.
3. Bersama Marvin, sambungkan input sah ke evaluasi NBA dan simpan jejak input/versi/keputusan.
4. Tutup alur keputusan → campaign → approval → eksekusi sesuai channel yang disepakati.
5. Susun skenario demo/UAT dan bukti hasil; keputusan `NO_ACTION` yang benar juga harus dapat didemokan, bukan dipaksa menjadi penawaran.

### Marvin — jalur aplikasi yang jujur dan dapat dijalankan

1. Sepakati penggunaan tabel/API existing bersama Moses; tampilkan skor, versi, waktu, status review dan kalimat tanpa angka hardcoded.
2. Tampilkan keadaan kosong, belum disetujui, ditolak, expired, gagal dan loading secara berbeda. Jangan menyamakan error dengan skor nol.
3. Sambungkan tombol/halaman NBA dan campaign ke hasil database, bukan nilai contoh pada kolom pelanggan.
4. Verifikasi pembersihan “Ramadan Radiance”/“78% Likelihood” dan data demo; jangan menampilkan data sintetis sebagai hasil pelanggan nyata.
5. Uji startup dari clone bersih, konfigurasi, migrasi, worker, build UI dan demo bersama Christ. Catat langkah run dan kegagalan aktual.

Pembagian ini tidak menghapus tanggung jawab platform James. Perubahan shared schema/migration, identitas, keamanan dan audit perlu koordinasi dengannya bila masih menjadi kontraknya.

## 7. Urutan pengerjaan dan bukti selesai

| Tahap | Pekerjaan | Bukti yang harus terlihat |
| --- | --- | --- |
| 0 — Kesepakatan | Isi D1–D5, catat PIC/reviewer dan kontrak | Link keputusan; tidak ada nama tabel/status izin pakai yang masih ditebak |
| 1 — Persistensi | Worker memanggil scoring, menyimpan hasil dan kalimat | Run DB sesuai jumlah record, versi/asal terlacak; retry tidak menggandakan record; kegagalan tidak meninggalkan hasil parsial seolah lengkap |
| 2 — Pemeriksaan | Tegakkan aturan pemeriksa dan izin penggunaan | Pelaku yang tidak berwenang/self-review ditolak; pending/rejected tidak bisa masuk NBA; reviewer dan waktu tercatat |
| 3 — NBA | Muat skor yang sah, petakan identitas dan gabungkan input sesuai kontrak | Trace keputusan menunjuk hasil/versi asal; kasus kosong/expired/parsial dan consent unknown ditangani sesuai keputusan |
| 4 — UI/campaign | Tampilkan hasil DB dan jalankan alur campaign | Refresh tetap menampilkan hasil tersimpan; tidak ada likelihood palsu; approval/eksekusi tercatat dan channel berlabel benar |
| 5 — UAT | Jalankan bersama dari repo | Catatan skenario, hasil aktual, bug, PIC perbaikan dan penerimaan manusia; tidak cukup screenshot/CI saja |

Skenario wajib: hasil valid; belum ada skor; run pending; run ditolak; skor expired; ID tidak cocok; data sebagian hilang; worker gagal/retry; self-review; `NO_ACTION`; campaign tanpa approval; serta data kosong pada UI. Kriteria spesifiknya mengikuti keputusan tim, bukan asumsi dokumen ini.

## 8. Bukti pengujian dan batas hasil model

Pada PR #58, merge `6b40f16`:

- 31 tes formatter lulus; temuan review tentang klaim imputasi diperbaiki dengan tes gagal dahulu, lalu review ulang tanpa temuan wajib.
- Suite lokal dengan `DATABASE_URL=sqlite://`: **1512 passed, 19 skipped, 3 xfailed**, 1 warning. Ruff/Black/Mypy bersih; CI PR #58 hijau sebelum merge.
- Angka tersebut bukti pengujian kode pada baseline itu, **bukan** akurasi model, persetujuan model, bukti integrasi baru, atau acceptance PostgreSQL lokal. Tes skipped/xfail tidak dihitung lulus.

Hasil development yang harus tetap jujur: identity pair recall sekitar 93,89% masih di bawah aspirasi 95%; tidak ada model final/pemenang yang disetujui; kalibrasi tidak otomatis memperbaiki hasil. Lihat [benchmark](BENCHMARK_EVIDENCE_2026-11-20.md). Data sintetis/retrospektif bukan bukti performa pelanggan nyata.

PR #58 tidak mengubah model, skor, DB atau API. Model/artefak development tetap non-serving. Jangan mengganti flag saja untuk melewati review, kualitas data atau keterbatasan target.

## 9. Isu lanjutan: jangan dicampur dengan prioritas integrasi MVP

[Pesan P1–P8 ke Christ](CHRIST_V14_RECONCILIATION_MESSAGE_2026-11-20.md) masih memuat keputusan rinci lifecycle, cutoff WIB, NO_ACTION, CLV, reason taxonomy, RFM dan definisi churn/horizon. Komentar mentor tentang progres MVP **bukan jawaban tertulis atas semua pertanyaan itu**. Sebagian dapat dipersempit untuk demo, tetapi pengurangan scope harus dicatat; jangan menganggap semuanya otomatis wajib untuk setiap slice UI.

Sisa keterbatasan terpisah: data historis `known_at`/refund/identity-as-of; sumber booking; registry persisten; effective-dated membership; outcome monitoring per segmen; timeout ingestion pertama yang belum ditemukan penyebabnya; dan error intermiten `/monitoring/drift` yang belum didiagnosis tuntas. Detail di [ledger](MOSES_INDEPENDENT_WORK_LEDGER_2026-11-20.md) dan [handoff historis](MOSES_CURRENT_HANDOFF.md). Jangan mengklaim isu ini tertutup oleh dokumentasi atau retry sukses.

## 10. Format jawaban tim yang bisa langsung diisi

```text
Tanggal / link PR atau issue:
D1. Tabel/struktur yang dipakai dan perubahan minimal:
D2. Identitas pembuat model, reviewer independen, aturan izin/cabut:
D3. Pemilihan versi/cutoff, expiry dan skor parsial:
D4. Pemetaan Golden ID → pelanggan aplikasi:
D5. Input minimum NBA, band, reason codes dan perilaku saat kosong:
D6. Jadwal/pemicu worker, retry, PIC operasi:
D7. Channel campaign demo dan skenario UAT yang disetujui:
PIC tiap PR / reviewer / urutan merge:
Pertanyaan yang masih belum terjawab:
```

**Pesan singkat untuk Christ dan Marvin:** model dan fungsi penjelasan Moses sudah tersedia untuk development; penyimpanan/review prediksi juga ada. Yang perlu kita sepakati sekarang adalah cara memakai struktur existing, siapa pemeriksanya, pemilihan hasil yang sah, dan pemetaan ID. Setelah itu Moses bisa menghubungkan worker ke database dan menyediakan input NBA; Christ menutup aturan/aksi/campaign; Marvin menampilkan hasil tersimpan serta menyiapkan alur aplikasi. Tidak perlu mengganti arsitektur atau menambahkan angka contoh agar demo terlihat penuh.
