# Handoff: menyambungkan NBA dan Campaign ke aplikasi

Dari: Christ (Orang 2) — Untuk: James (`api/`, `worker/`) dan Marvin (`web/`)

Sesuai arahan mentor: kode di `services/` adalah fungsi murni. **Yang memanggil dan menyimpan ke database adalah `api/` dan `worker/`.** Christ tidak mengubah `api/`, `worker/`, `web/`, maupun `migrations/`. Dokumen ini menjelaskan apa yang perlu dipanggil.

## 1. Yang sudah tersedia (semuanya fungsi murni, ada test)

| Modul | Fungsi utama |
|---|---|
| `services/decision/nba/serving.py` | `evaluate_customer(...) -> DecisionOutput` |
| `services/decision/nba/explain.py` | dipakai otomatis oleh `evaluate_customer` (alasan bahasa sederhana) |
| `services/decision/campaign/pipeline.py` | `run_campaign(...) -> CampaignRunResult` |

## 2. `api/decisions.py` — endpoint `POST /next-best-actions/evaluate`

> **Status 26 Nov 2026: bagian ini sudah dikerjakan.** `api/decisions.py` dan `worker/tasks.py` memanggil `evaluate_customer`, `api/decision_inputs.py::load_serving_score_row` membaca skor, status review, dan izin pakai dari DB serta mengirim `contract_status`, dan fallback `customer_code` sudah dihapus (D4: hanya `golden_customer_id` terpetakan pasti). Yang **belum** tersambung: consent, komplain, kelayakan, dan kesesuaian produk (masih `None` di `api/decisions.py` dan `worker/tasks.py`; consent pada job campaign ditulis `UNKNOWN` yang tidak pernah memberi izin kirim; jadi NBA menjawab "belum ada keputusan" dan campaign tidak mengirim apa pun). Contoh di bawah dipertahankan sebagai referensi bentuk pemanggilan; **jangan** memakai `or customer.customer_code`.

Bentuk pemanggilan:

```python
from services.decision.nba.serving import evaluate_customer

identity_ref = customer.golden_customer_id  # hanya Golden ID yang terpetakan pasti (D4); tanpa fallback customer_code

output = evaluate_customer(
    customer_ref=identity_ref,
    correlation_id=request.state.correlation_id,
    score_row=load_serving_score_row(db, identity_ref),  # dict atau None (lihat bagian 4)
    consent_doc=None,          # None = sumber belum tersambung (jujur, bukan izin)
    complaint_tickets=None,    # [] hanya bila sumbernya tersambung dan memang kosong
    contact_history=None,
    eligibility=None,
    product_suitability=None,
    score_explanation=load_score_explanation(db, identity_ref),  # keluaran formatter Moses atau None
)

decision = NBADecision(**output.to_nba_decision_row(customer_db_id=customer.id))
db.add(decision)
db.flush()
record_audit_event(
    db,
    correlation_id=request.state.correlation_id,
    event_type="nba.engine_evaluated",
    actor_id=actor.id,
    entity_type="customer",
    entity_id=customer.id,
    details=output.to_audit_details(decision_id=decision.id),
)
db.add(DecisionTrace(**output.to_trace_row(customer_code=customer.customer_code)))
db.commit()
return output.to_api_response(decision_id=decision.id, status=decision.status)
```

Catatan:
- `None` vs `[]` penting. `None` berarti belum tersambung, sehingga hasilnya "belum ada keputusan promosi" dengan alasan jelas. `[]` berarti tersambung dan kosong, sehingga engine berjalan penuh.
- Bila sumber consent, komplain, riwayat kontak, kelayakan, atau ketersediaan produk sudah tersambung, kirim datanya: consent sebagai dict K-10, komplain sebagai `list[ComplaintTicket]`, kontak sebagai `list[ContactRecord]`, kelayakan sebagai `EligibilityProfile`, ketersediaan sebagai `ProductSuitability`.
- Respons API memuat `reason` (kalimat sederhana), `expected_value` (null bila skor tidak dipakai), `serving_ready`, dan `unavailable_sources`.

## 3. `worker/tasks.py` — `campaign_execution`

Sekarang task hanya menghitung ukuran audiens dan membagi menurut `ab_test_ratio`. Untuk campaign yang berjalan sungguhan:

```python
from services.decision.campaign.pipeline import AudienceMember, run_campaign

# 1) untuk tiap pelanggan target: baca data dari DB -> evaluate_customer(...)
audience = [
    AudienceMember(customer_ref=ref, decision=output, consent_doc=consent_doc, fact_package=facts)
    for ref, output, consent_doc, facts in prepared_rows
]

# 2) jalankan
result = run_campaign(
    campaign={
        "campaign_id": f"CMP-{campaign.id}",
        "channel": campaign.channel,            # harus berakhiran _sim
        "approved_by": approver_identity,       # manusia; wajib
        "random_seed": campaign.id,             # tetap -> grup deterministik
        # "control_holdout_ratio": 0.10  (default 10%)
    },
    audience=audience,
    correlation_id=correlation_id,
    outcomes=outcome_rows_or_None,              # K-09; None bila belum ada
)

# 3) simpan ke database
job_result = result.to_job_result()             # -> act.batch_jobs.result
for event in result.audit_events():             # -> audit trail
    record_audit_event(session, **event_args(event))
for row in result.measurement_rows:             # -> msr.campaign_measurements
    ...                                         # source_mode="simulated"
# result.contact_rows -> riwayat kontak (untuk fatigue cap pada run berikutnya)
```

Catatan:
- `ab_test_ratio` tidak dipakai sebagai ukuran control. Holdout default 10%.
- Kanal harus simulator (`*_sim`). Selain itu pipeline menolak dengan `ValueError`.
- `approved_by` kosong: `ValueError`, tidak ada pesan keluar.
- `result.control_exposure_count` harus selalu 0. Tampilkan di UI.
- Bila `measurement_status == "AWAITING_OUTCOMES"`, UI menulis "belum ada hasil" dan tidak menampilkan angka lift.

## 4. Ketergantungan (perlu keputusan tim)

1. **Sumber skor (`load_serving_score_row`) — Moses.** Fungsi ini harus mengembalikan dict dengan kunci: `churn_score`, `churn_risk_band`, `propensity_purchase`, `propensity_renew`, `clv_amount`, `clv_tier`, `lifecycle_stage`, `score_generated_at`, `reason_codes`, `model_version`, `review_status`, `reviewed_by`, `submitted_by`, **`usage_approved`** (wajib boolean `True`; `reviewed` saja bukan izin pakai), dan opsional `model_author`. Importer saat ini hanya menghasilkan skor churn, band, dan reason code, jadi sampai field lain tersedia hasilnya `SCORE_FIELDS_INCOMPLETE` (NBA tidak merekomendasikan apa pun, dan itu perilaku yang benar).
2. **Riwayat kontak — James.** `contact_rows` perlu tempat penyimpanan agar fatigue cap (maks. 2 pesan / 14 hari) bekerja antar-run. Belum ada tabel khusus; bila dibuat, itu migrasi milik James.
3. **Consent dan komplain — James/Moses.** Fixture `consent_events.csv` dan `service_cases.csv` ada; pastikan sudah dimuat ke tabel yang bisa dibaca `api/`.
4. **Endpoint ganda.** `POST /next-best-actions` (manual, teks bebas) tumpang tindih dengan `/evaluate`. Sesuai arahan mentor, sisakan satu.

### Pembaruan 21 Nov 2026 (setelah dokumen TEAM_ALIGNMENT Moses)

- `lookup_scores` kini menolak skor bila `usage_approved` bukan `True` (`MODEL_USAGE_NOT_APPROVED`) dan bila reviewer = pembuat model (`model_author`, bila diketahui). Sumber `usage_approved` belum ada; sampai ada, NBA menjawab "belum disetujui untuk dipakai".
- `explain.py` tidak lagi menerjemahkan reason code. Kalimat alasan skor dari `score_explanations.explain_contributions` disisipkan **apa adanya** lewat parameter `score_explanation`, hanya bila skor dipakai.
- Jangan membuat `EligibilityProfile` dengan `tenure_days=0` / `has_active_membership=False` bila sumbernya belum ada; kirim `None`.
- Kontrak input lengkap dan jawaban D5: `D5_NBA_INPUT_CONTRACT.md`.

## 5. Untuk Marvin (UI)

- Tampilkan field `reason` apa adanya (sudah kalimat sederhana).
- `expected_value == null`, `unavailable_sources` tidak kosong, atau `measurement_status == "AWAITING_OUTCOMES"`: tampilkan "kosong/belum tersedia". Jangan isi angka contoh dan jangan tampilkan label "AI" atau persentase yang tidak berasal dari respons API.
- Tampilkan `model_version` dan `serving_ready` agar jelas keputusan memakai model yang sudah direview.
- Semua angka berasal dari respons API/database, bukan dari data tetap di frontend.

## 6. Cara memverifikasi

```
python -m pytest tests/decision -q
PYTHONPATH=. python docs/christ_business/demo/run_demo.py   # data sintetis, berlabel
```
