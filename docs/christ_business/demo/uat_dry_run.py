"""
uat_dry_run.py — Uji coba 14 skenario UAT di sandbox lokal (BUKAN UAT resmi).

Apa ini:  menjalankan skenario `UAT_PLAN.md` terhadap API/worker repo ini (read-only: tidak
          mengubah api/, worker/, services/data/) memakai DB sqlite sementara di memori dan
          data SINTETIS berlabel. Hasil asli ditulis ke `UAT_HASIL_DRY_RUN.md`, termasuk
          yang GAGAL atau TERHALANG.

Apa BUKAN: UAT di lingkungan bersama, UAT lewat UI, atau UAT yang ditandatangani penguji
          independen. Tidak ada model riil yang direview; skor di sini hanya fixture uji.

Cara menjalankan (dari root repo):
    export DATABASE_URL=sqlite:// JWT_SECRET=<min 32 karakter>
    PYTHONPATH=. python docs/christ_business/demo/uat_dry_run.py

Arti verdict:
    PASS         hasil nyata sama dengan hasil yang diharapkan pada level yang dijalankan.
    FAIL         hasil nyata BERBEDA dari yang diharapkan (temuan, perlu tindak lanjut).
    TERHALANG    prasyarat belum ada (mis. feed belum tersambung); bukan kegagalan logika.
    TIDAK DIJALANKAN  butuh lingkungan bersama / UI / orang; tidak bisa dari sandbox.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

os.environ.setdefault("JWT_SECRET", "uat-dry-run-secret-that-is-long-enough-for-hmac")
os.environ["DATABASE_URL"] = "sqlite://"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import worker.tasks as worker_tasks  # noqa: E402
from api.database import SQLITE_SCHEMA_TRANSLATE_MAP, Base, get_db  # noqa: E402
from api.main import app  # noqa: E402
from api.models import (  # noqa: E402
    AuditEvent,
    BatchJob,
    Customer,
    GoldenCustomer,
    NBADecision,
    RegistryVersion,
    Role,
    SourceIdentityMapping,
    User,
)
from api.security import hash_password  # noqa: E402
from services.decision.nba.engine import (  # noqa: E402
    EligibilityProfile,
    ProductSuitability,
)
from services.decision.nba.serving import evaluate_customer, lookup_scores  # noqa: E402
from services.decision.policy.fatigue import ContactRecord  # noqa: E402
from services.decision.policy.suppression import (  # noqa: E402
    ComplaintStatus,
    ComplaintTicket,
)

ROOT = Path(__file__).resolve().parents[3]
OUT_MD = Path(__file__).with_name("UAT_HASIL_DRY_RUN.md")
PASSWORD = "correct-horse-battery"
DATA_LABEL = "SINTETIS (fixture uji), bukan data atau model riil"


# --------------------------------------------------------------------------- infrastruktur
class Scenario:
    """Mengumpulkan sub-pemeriksaan satu skenario."""

    def __init__(self, uat_id: str, title: str) -> None:
        self.uat_id, self.title = uat_id, title
        self.level = ""
        self.checks: list[tuple[bool, str]] = []
        self.blocked: list[str] = []
        self.not_run: list[str] = []
        self.observed: list[str] = []
        self.error: str | None = None

    def check(self, ok: bool, description: str) -> None:
        self.checks.append((bool(ok), description))

    def block(self, reason: str) -> None:
        self.blocked.append(reason)

    def skip(self, reason: str) -> None:
        self.not_run.append(reason)

    def note(self, text: str) -> None:
        self.observed.append(text)

    @property
    def verdict(self) -> str:
        if self.error:
            return "FAIL"
        if any(not ok for ok, _ in self.checks):
            return "FAIL"
        if self.blocked:
            return "TERHALANG"
        if self.not_run and not self.checks:
            return "TIDAK DIJALANKAN"
        return "PASS"


@contextmanager
def environment():
    """DB sqlite sementara + klien API + 3 pengguna + 3 pelanggan sintetis."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    ).execution_options(schema_translate_map=SQLITE_SCHEMA_TRANSLATE_MAP)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    golden = {"c1": str(uuid4()), "c2": str(uuid4())}
    with factory.begin() as db:
        admin, analyst = Role(name="admin"), Role(name="analyst")
        db.add_all([admin, analyst])
        db.flush()
        users = [
            User(
                email=f"{name}@example.com",
                password_hash=hash_password(PASSWORD),
                roles=[role],
            )
            for name, role in (
                ("submitter", admin),
                ("reviewer", analyst),
                ("decider", admin),
            )
        ]
        db.add_all(users)
        db.add(RegistryVersion(version_tag="uat-v1", algorithm="exact"))
        for gid in golden.values():
            db.add(
                GoldenCustomer(
                    golden_customer_id=gid,
                    first_source_batch_id="uat-batch",
                    anchor_source_id=f"anchor-{gid[:6]}",
                    status="APPROVED",
                )
            )
        db.flush()
        customers = {}
        for key, code in (
            ("c1", "UAT-C1"),
            ("c2", "UAT-C2"),
            ("c3", "UAT-C3-TANPA-PEMETAAN"),
        ):
            gid = golden.get(key)
            customer = Customer(
                customer_code=code,
                full_name=f"Pelanggan Sintetis {key.upper()}",
                email=f"{key}@example.com",
                segment="uat",
                is_demo=False,
                golden_customer_id=gid,
            )
            db.add(customer)
            db.flush()
            customers[key] = customer.id
            if gid:
                db.add(
                    SourceIdentityMapping(
                        source_customer_id=code,
                        golden_customer_id=gid,
                        registry_version="uat-v1",
                        source_batch_id="uat-batch",
                        assignment_type="EXACT",
                    )
                )
        ids = {
            name: user.id
            for name, user in zip(("submitter", "reviewer", "decider"), users)
        }

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.state.audit_session_factory = factory
    original_session_local = worker_tasks.SessionLocal
    worker_tasks.SessionLocal = factory  # worker memakai DB sandbox yang sama
    try:
        with TestClient(app) as client:
            headers = {}
            for name in ids:
                login = client.post(
                    "/auth/login",
                    json={"email": f"{name}@example.com", "password": PASSWORD},
                )
                assert login.status_code == 200, login.text
                headers[name] = {
                    "Authorization": f"Bearer {login.json()['access_token']}"
                }
            yield client, factory, golden, customers, ids, headers
    finally:
        worker_tasks.SessionLocal = original_session_local
        app.dependency_overrides.clear()
        del app.state.audit_session_factory
        engine.dispose()


def artifact(
    golden_id: str,
    *,
    age_days: float = 1,
    contract_status: str = "CONTRACT_COMPLIANT",
    drop: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Skor lengkap SINTETIS (bukan model riil). `age_days` = umur cutoff saat diimpor."""
    versions = {
        "model_version": "uat-sintetis-churn-1",
        "feature_set_version": "uat-sintetis-fitur-1",
        "label_version": "uat-sintetis-label-1",
    }
    row: dict[str, Any] = {
        **versions,
        "customer_id": golden_id,
        "cutoff_at": (
            datetime.now(timezone.utc) - timedelta(days=age_days)
        ).isoformat(),
        "score": 0.92,
        "band": "VERY_HIGH",
        "propensity_purchase": 0.6,
        "propensity_renew": 0.5,
        "clv_amount": 3000000.0,
        "clv_tier": "GOLD",
        "lifecycle_stage": "AT_RISK",
        "reason_codes": ["PURCHASE_FREQUENCY_90D"],
        "contract_status": contract_status,
        "serving_ready": False,
        "approved": False,
    }
    for key in drop:
        row.pop(key, None)
    canonical = (json.dumps(row, sort_keys=True, allow_nan=False) + "\n").encode(
        "utf-8"
    )
    manifest = {
        **versions,
        "prediction_type": "CHURN",
        "producer_version": "uat-sintetis-producer-1",
        "development_only": True,
        "serving_ready": False,
        "approved": False,
        "prediction_id_produced": False,
        "rows": 1,
        "output_sha256": {"records.jsonl": hashlib.sha256(canonical).hexdigest()},
    }
    return {"manifest": manifest, "records": [row]}


def import_run(client, headers, art) -> tuple[int, Any]:
    response = client.post("/model-predictions/runs/import", json=art, headers=headers)
    return response.status_code, response


def review(client, run_id, headers, decision="reviewed"):
    return client.post(
        f"/model-predictions/runs/{run_id}/review",
        json={
            "decision": decision,
            "review_note": "UAT sintetis: bukan review model riil",
        },
        headers=headers,
    )


def grant_usage(client, run_id, headers, author_id, approved=True):
    body: dict[str, Any] = {
        "approved": approved,
        "note": "UAT sintetis: bukan izin pakai riil",
    }
    if approved:
        body["model_author"] = author_id
    return client.post(
        f"/model-predictions/runs/{run_id}/usage", json=body, headers=headers
    )


def evaluate(client, customer_id, headers):
    return client.post(
        "/decisions/next-best-actions/evaluate",
        json={"customer_id": customer_id},
        headers=headers,
    )


def prepared_run(client, headers, ids, golden_id, **art_kwargs):
    """Impor -> review (reviewer independen) -> izin pakai. Mengembalikan run_id."""
    status, resp = import_run(
        client, headers["submitter"], artifact(golden_id, **art_kwargs)
    )
    assert status == 201, resp.text
    run_id = resp.json()["id"]
    assert review(client, run_id, headers["reviewer"]).status_code == 200
    assert (
        grant_usage(client, run_id, headers["decider"], ids["submitter"]).status_code
        == 200
    )
    return run_id


# --------------------------------------------------------------------------- skenario
def uat_01() -> Scenario:
    s = Scenario("UAT-01", "Hasil valid")
    s.level = "API sandbox + service murni"
    with environment() as (client, factory, golden, customers, ids, headers):
        prepared_run(client, headers, ids, golden["c1"])
        resp = evaluate(client, customers["c1"], headers["decider"])
        body = resp.json()
        s.check(resp.status_code == 201, "evaluate mengembalikan 201")
        s.check(
            body.get("score_state") == "SCORE_READY",
            "skor: SCORE_READY (alur impor→review→izin sah)",
        )
        s.note(
            f"API: score_state={body.get('score_state')}, serving_ready={body.get('serving_ready')}, "
            f"selected_action={body.get('selected_action')}, expected_value={body.get('expected_value')}, "
            f"unavailable_sources={body.get('unavailable_sources')}"
        )
        if body.get("serving_ready") is not True:
            s.block(
                "Keputusan valid belum bisa dihasilkan lewat API: sumber "
                f"{body.get('unavailable_sources')} belum tersambung (loader mengirim None). "
                "Hasil diharapkan (serving_ready=true, aksi + EV angka) tidak tercapai."
            )
    # level service murni: SEMUA sumber sintetis disediakan -> logika keputusan valid
    now = datetime(2026, 11, 20, 10, 0, 0)
    ref = "UAT-C1"
    out = evaluate_customer(
        customer_ref=ref,
        correlation_id="uat-01-service",
        score_row={
            "customer_id": ref,
            "churn_score": 0.92,
            "churn_risk_band": "VERY_HIGH",
            "propensity_purchase": 0.6,
            "propensity_renew": 0.5,
            "clv_amount": 3_000_000.0,
            "clv_tier": "GOLD",
            "lifecycle_stage": "AT_RISK",
            "score_generated_at": (now - timedelta(days=1)).isoformat(),
            "reason_codes": ["PURCHASE_FREQUENCY_90D"],
            "model_version": "uat-sintetis",
            "review_status": "reviewed",
            "reviewed_by": 7,
            "submitted_by": 3,
            "usage_approved": True,
        },
        consent_doc=_consent(ref),
        complaint_tickets=[],
        contact_history=[],
        eligibility=EligibilityProfile(ref, 400, 20, True, ["GROCERY"], 3),
        product_suitability=ProductSuitability(),
        evaluation_date=now,
    )
    resp2 = out.to_api_response(decision_id=1, status="proposed")
    s.check(
        resp2["serving_ready"] is True and resp2["score_state"] == "SCORE_READY",
        "service murni (sumber sintetis lengkap): serving_ready=true",
    )
    s.check(
        resp2["selected_action"] != "NO_ACTION"
        and isinstance(resp2["expected_value"], float),
        "service murni: aksi dipilih dan EV berupa angka dari sistem",
    )
    s.note(
        f"service murni: aksi={resp2['selected_action']}, EV={resp2['expected_value']} ({DATA_LABEL})"
    )
    return s


def _consent(ref: str, *, global_opt_out: bool = False) -> dict[str, Any]:
    def ch(on: bool) -> dict[str, Any]:
        return {
            "status": "OPT_IN" if on else "OPT_OUT",
            "opt_in": on,
            "effective_permission": "ALLOWED" if on else "BLOCKED",
        }

    return {
        "customer_id": ref,
        "global_consent": {
            "status": "OPT_OUT" if global_opt_out else "OPT_IN",
            "is_global_opt_out": global_opt_out,
        },
        "channels": {"email": ch(True), "push": ch(True)},
        "unknown_expired_policy": "BLOCKED",
        "identity_merge_policy": "MOST_RESTRICTIVE_WINS",
        "most_restrictive_wins": True,
    }


def uat_02() -> Scenario:
    s = Scenario("UAT-02", "Belum ada skor (keadaan 1)")
    s.level = "API sandbox"
    with environment() as (client, factory, golden, customers, ids, headers):
        body = evaluate(client, customers["c2"], headers["decider"]).json()
    s.check(body["score_state"] == "SCORE_MISSING", "score_state = SCORE_MISSING")
    s.check(
        body["score_unavailable_reason"] == "SCORE_ROW_MISSING",
        "alasan = SCORE_ROW_MISSING",
    )
    s.check(body["selected_action"] == "NO_ACTION", "aksi = NO_ACTION")
    s.check(
        body["expected_value"] is None,
        "expected_value = null (UI harus menulis Kosong)",
    )
    s.check(body["model_review_status"] is None, "model_review_status = null")
    s.skip(
        "Tampilan UI (lencana 'Belum ada skor', kolom Kosong) tidak dapat diperiksa dari sandbox."
    )
    return s


def uat_03() -> Scenario:
    s = Scenario("UAT-03", "Run menunggu review (keadaan 2)")
    s.level = "API sandbox"
    with environment() as (client, factory, golden, customers, ids, headers):
        status, resp = import_run(client, headers["submitter"], artifact(golden["c1"]))
        body = evaluate(client, customers["c1"], headers["decider"]).json()
    s.check(status == 201, "impor artefak sintetis berhasil (201)")
    s.check(
        body["score_state"] == "SCORE_PRESENT_NOT_APPROVED",
        "score_state = SCORE_PRESENT_NOT_APPROVED",
    )
    s.check(
        body["score_unavailable_reason"] == "MODEL_RUN_NOT_REVIEWED",
        "alasan = MODEL_RUN_NOT_REVIEWED",
    )
    s.check(
        body["model_review_status"] == "pending_review",
        "model_review_status = pending_review",
    )
    s.check(
        body["expected_value"] is None and body["selected_action"] == "NO_ACTION",
        "tanpa EV, aksi NO_ACTION",
    )
    s.skip(
        "Tampilan UI (amber 'menunggu pemeriksaan', skor Kosong) tidak dapat diperiksa dari sandbox."
    )
    return s


def uat_04() -> Scenario:
    s = Scenario("UAT-04", "Run ditolak (keadaan 2)")
    s.level = "API sandbox"
    with environment() as (client, factory, golden, customers, ids, headers):
        _, resp = import_run(client, headers["submitter"], artifact(golden["c1"]))
        run_id = resp.json()["id"]
        rev = review(client, run_id, headers["reviewer"], decision="rejected")
        body = evaluate(client, customers["c1"], headers["decider"]).json()
        approve_try = grant_usage(client, run_id, headers["decider"], ids["submitter"])
    s.check(rev.status_code == 200, "reviewer independen dapat menolak run")
    s.check(body["model_review_status"] == "rejected", "model_review_status = rejected")
    s.check(
        body["score_unavailable_reason"] == "MODEL_RUN_NOT_REVIEWED",
        "alasan = MODEL_RUN_NOT_REVIEWED",
    )
    s.check(
        body["score_state"] == "SCORE_PRESENT_NOT_APPROVED"
        and body["expected_value"] is None,
        "keadaan 2, tanpa EV",
    )
    s.check(approve_try.status_code == 409, "izin pakai pada run yang ditolak = 409")
    s.skip(
        "UI harus memilih teks 'ditolak' (bukan 'menunggu') dari model_review_status; tidak diperiksa di sini."
    )
    return s


def uat_05() -> Scenario:
    s = Scenario("UAT-05", "Review oleh pengunggah / pembuat model")
    s.level = "API sandbox + service murni"
    with environment() as (client, factory, golden, customers, ids, headers):
        _, resp = import_run(client, headers["submitter"], artifact(golden["c1"]))
        run_id = resp.json()["id"]
        self_review = review(client, run_id, headers["submitter"])
        review(client, run_id, headers["reviewer"])
        author_is_reviewer = grant_usage(
            client, run_id, headers["decider"], ids["reviewer"]
        )
        body = evaluate(client, customers["c1"], headers["decider"]).json()
    s.check(
        self_review.status_code == 409, "pengunggah mereview run sendiri ditolak (409)"
    )
    s.check(
        author_is_reviewer.status_code == 409,
        "izin pakai ditolak bila pembuat model = reviewer (409)",
    )
    s.check(
        body["score_unavailable_reason"] == "MODEL_USAGE_NOT_APPROVED",
        "skor tetap tidak dipakai",
    )
    row = {
        "customer_id": "X",
        "churn_score": 0.9,
        "churn_risk_band": "HIGH",
        "propensity_purchase": 0.5,
        "propensity_renew": 0.5,
        "clv_amount": 1.0,
        "clv_tier": "GOLD",
        "lifecycle_stage": "ACTIVE",
        "score_generated_at": "2026-11-19T10:00:00",
        "model_version": "v",
        "review_status": "reviewed",
        "reviewed_by": 3,
        "submitted_by": 3,
        "usage_approved": True,
    }
    result = lookup_scores(row, customer_id="X")
    s.check(
        result.unavailable_reason == "MODEL_RUN_REVIEWED_BY_SUBMITTER",
        "pertahanan berlapis di gerbang skor: reviewer = pengunggah ditolak",
    )
    s.note(
        "di API, pelanggaran ini sudah dicegah saat review (409), "
        "jadi kode MODEL_RUN_REVIEWED_BY_SUBMITTER hanya muncul bila data DB rusak."
    )
    return s


def uat_06() -> Scenario:
    s = Scenario("UAT-06", "Sudah direview, belum ada izin pakai / izin dicabut")
    s.level = "API sandbox"
    with environment() as (client, factory, golden, customers, ids, headers):
        _, resp = import_run(client, headers["submitter"], artifact(golden["c1"]))
        run_id = resp.json()["id"]
        review(client, run_id, headers["reviewer"])
        before = evaluate(client, customers["c1"], headers["decider"]).json()
        grant_usage(client, run_id, headers["decider"], ids["submitter"])
        approved = evaluate(client, customers["c1"], headers["decider"]).json()
        revoke = grant_usage(
            client, run_id, headers["decider"], ids["submitter"], approved=False
        )
        after = evaluate(client, customers["c1"], headers["decider"]).json()
    s.check(
        before["score_unavailable_reason"] == "MODEL_USAGE_NOT_APPROVED",
        "reviewed tanpa izin → MODEL_USAGE_NOT_APPROVED",
    )
    s.check(
        before["score_state"] == "SCORE_PRESENT_NOT_APPROVED"
        and before["expected_value"] is None,
        "keadaan 2, tanpa EV",
    )
    s.check(approved["score_state"] == "SCORE_READY", "setelah izin pakai: SCORE_READY")
    s.check(revoke.status_code == 200, "pencabutan izin berhasil (200)")
    s.check(
        after["score_unavailable_reason"] == "MODEL_USAGE_NOT_APPROVED"
        and after["expected_value"] is None,
        "setelah dicabut: skor diblokir pada evaluasi berikutnya",
    )
    return s


def uat_07() -> Scenario:
    s = Scenario("UAT-07", "Skor kedaluwarsa")
    s.level = "API sandbox + service murni (batas 30/31 hari)"
    with environment() as (client, factory, golden, customers, ids, headers):
        prepared_run(client, headers, ids, golden["c1"], age_days=29)
        fresh = evaluate(client, customers["c1"], headers["decider"]).json()
    with environment() as (client, factory, golden, customers, ids, headers):
        prepared_run(client, headers, ids, golden["c1"], age_days=31)
        stale = evaluate(client, customers["c1"], headers["decider"]).json()
    s.check(fresh["score_state"] == "SCORE_READY", "umur 29 hari: SCORE_READY")
    s.check(
        stale["score_state"] == "SCORE_PRESENT_NOT_APPROVED"
        and stale["score_unavailable_reason"] == "SCORE_EXPIRED",
        "umur 31 hari: SCORE_EXPIRED",
    )
    s.check(
        stale["serving_ready"] is False
        and stale["degraded_input"] is True
        and stale["expected_value"] is None,
        "kedaluwarsa: serving_ready=false, degraded_input=true, EV null",
    )
    s.check(stale["selected_action"] == "NO_ACTION", "aksi = NO_ACTION")
    s.note(
        "Batas tepat 30 hari (masih sah) dan 31 hari dikunci test service `TestExpiredScoreIsNotReady`; "
        "di API waktu berjalan sehingga batas tepat tidak dapat diuji stabil."
    )
    return s


def uat_08() -> Scenario:
    s = Scenario("UAT-08", "ID tidak cocok / tanpa pemetaan pasti")
    s.level = "API sandbox + service murni"
    with environment() as (client, factory, golden, customers, ids, headers):
        unmapped = evaluate(client, customers["c3"], headers["decider"])
    s.check(
        unmapped.status_code == 409,
        "pelanggan tanpa pemetaan Golden pasti: 409, tidak dievaluasi",
    )
    s.note(f"detail API: {unmapped.json().get('detail')}")
    row = {
        "customer_id": "ORANG-LAIN-999",
        "churn_score": 0.9,
        "churn_risk_band": "HIGH",
        "propensity_purchase": 0.5,
        "propensity_renew": 0.5,
        "clv_amount": 1.0,
        "clv_tier": "GOLD",
        "lifecycle_stage": "ACTIVE",
        "score_generated_at": "2026-11-19T10:00:00",
        "model_version": "v",
        "review_status": "reviewed",
        "reviewed_by": 7,
        "submitted_by": 3,
        "usage_approved": True,
    }
    result = lookup_scores(row, customer_id="UAT-C1")
    s.check(
        result.unavailable_reason == "SCORE_CUSTOMER_MISMATCH"
        and result.ai_scores is None,
        "skor milik ID lain ditolak (SCORE_CUSTOMER_MISMATCH)",
    )
    s.skip(
        "Penghapusan fallback customer_code di LINGKUNGAN BERSAMA (data nyata) perlu diperiksa oleh James/Moses."
    )
    return s


def uat_09() -> Scenario:
    s = Scenario("UAT-09", "Data sebagian hilang")
    s.level = "API sandbox"
    with environment() as (client, factory, golden, customers, ids, headers):
        prepared_run(
            client, headers, ids, golden["c1"], contract_status="SCHEMA_PARTIAL"
        )
        partial = evaluate(client, customers["c1"], headers["decider"]).json()
    s.check(
        partial["score_unavailable_reason"] == "SCORE_CONTRACT_NOT_SERVING",
        "kontrak SCHEMA_PARTIAL (walau sudah direview + diberi izin): SCORE_CONTRACT_NOT_SERVING",
    )
    s.check(
        partial["score_state"] == "SCORE_PRESENT_NOT_APPROVED"
        and partial["expected_value"] is None,
        "keadaan 2 (ada, tidak dipakai), bukan 'belum ada'",
    )
    s.check(partial["serving_ready"] is False, "serving_ready = false")
    with environment() as (client, factory, golden, customers, ids, headers):
        status, resp = import_run(
            client, headers["submitter"], artifact(golden["c1"], drop=("clv_amount",))
        )
        s.note(f"impor tanpa field clv_amount: HTTP {status}")
        if status == 201:
            run_id = resp.json()["id"]
            review(client, run_id, headers["reviewer"])
            grant_usage(client, run_id, headers["decider"], ids["submitter"])
            missing = evaluate(client, customers["c1"], headers["decider"]).json()
            s.check(
                missing["score_state"] != "SCORE_READY"
                and missing["expected_value"] is None,
                "field wajib (clv_amount) hilang, walau sudah direview + diberi izin: "
                "skor TIDAK dipakai dan tanpa EV",
            )
            s.note(
                f"alasan = {missing['score_unavailable_reason']}; "
                f"score_state = {missing['score_state']}"
            )
        else:
            s.check(True, "impor dengan field wajib hilang ditolak di pintu masuk")
    sources = set(partial["unavailable_sources"])
    s.check(
        {"consent", "complaint_history", "eligibility", "product_suitability"}
        <= sources,
        "sumber non-skor yang belum tersambung dilaporkan di unavailable_sources (bukan data palsu)",
    )
    s.note(f"unavailable_sources = {sorted(sources)}")
    return s


def uat_10() -> Scenario:
    s = Scenario("UAT-10", "NO_ACTION karena kebijakan")
    s.level = "service murni (sumber sintetis); API terhalang"
    s.block(
        "Lewat API/UI: consent, komplain, dan kelayakan belum tersambung sehingga skenario kebijakan "
        "tidak dapat dipicu dengan data nyata. Diuji di level service dengan sumber sintetis berlabel."
    )
    now = datetime(2026, 11, 20, 10, 0, 0)
    ref = "UAT-C1"
    base_row = {
        "customer_id": ref,
        "churn_score": 0.92,
        "churn_risk_band": "VERY_HIGH",
        "propensity_purchase": 0.6,
        "propensity_renew": 0.5,
        "clv_amount": 3_000_000.0,
        "clv_tier": "GOLD",
        "lifecycle_stage": "AT_RISK",
        "score_generated_at": (now - timedelta(days=1)).isoformat(),
        "reason_codes": ["PURCHASE_FREQUENCY_90D"],
        "model_version": "uat-sintetis",
        "review_status": "reviewed",
        "reviewed_by": 7,
        "submitted_by": 3,
        "usage_approved": True,
    }

    def run(consent, tickets=(), contacts=()):
        out = evaluate_customer(
            customer_ref=ref,
            correlation_id="uat-10",
            score_row=base_row,
            consent_doc=consent,
            complaint_tickets=list(tickets),
            contact_history=list(contacts),
            eligibility=EligibilityProfile(ref, 400, 20, True, ["GROCERY"], 3),
            product_suitability=ProductSuitability(),
            evaluation_date=now,
        )
        return out.to_api_response(decision_id=1, status="proposed")

    optout = run(_consent(ref, global_opt_out=True))
    s.check(
        optout["selected_action"] == "NO_ACTION"
        and optout["no_action_reason"] == "OPT_OUT_SUPPRESSED",
        "(a) global opt-out → NO_ACTION / OPT_OUT_SUPPRESSED",
    )
    contacts = [
        ContactRecord(ref, "RETENTION_OUTREACH", "email", now - timedelta(days=d), True)
        for d in (1, 5)
    ]
    fatigue = run(_consent(ref), contacts=contacts)
    s.check(
        fatigue["selected_action"] == "NO_ACTION",
        "(b) 2 pesan komersial dalam 14 hari → NO_ACTION",
    )
    s.note(f"(b) alasan = {fatigue['no_action_reason']}")
    ticket = ComplaintTicket(
        "T-UAT", ref, ComplaintStatus.OPEN_SEVERE, "SEVERE", now - timedelta(days=1)
    )
    complaint = run(_consent(ref), tickets=[ticket])
    s.check(
        complaint["selected_action"] == "COMPLAINT_RESOLUTION",
        "(c) komplain berat terbuka → COMPLAINT_RESOLUTION",
    )
    s.note(f"data: {DATA_LABEL}")
    return s


def _pytest_summary(*targets: str) -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *targets, "-q", "-p", "no:cacheprovider"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    tail = [line for line in proc.stdout.strip().splitlines() if line.strip()][-1:]
    return proc.returncode == 0, (tail[0] if tail else proc.stderr[-200:])


def _artifact_dir_checks(s: Scenario) -> tuple[bool, str]:
    """Validasi folder artefak worker: ground_truth, path keluar root, dan folder tak ada ditolak."""
    import tempfile

    from worker.prediction_import import _artifact_dir

    with tempfile.TemporaryDirectory() as root:
        (Path(root) / "ground_truth_dev").mkdir()
        (Path(root) / "churn_ok_20261126").mkdir()
        previous = os.environ.get("PREDICTION_IMPORT_ROOT")
        os.environ["PREDICTION_IMPORT_ROOT"] = root
        try:
            outcomes = {}
            for name in (
                "ground_truth_dev",
                "../etc",
                "tidak_ada",
                "churn_ok_20261126",
            ):
                try:
                    _artifact_dir(name)
                    outcomes[name] = "DITERIMA"
                except ValueError as error:
                    outcomes[name] = f"ditolak ({error})"
        finally:
            if previous is None:
                os.environ.pop("PREDICTION_IMPORT_ROOT", None)
            else:
                os.environ["PREDICTION_IMPORT_ROOT"] = previous
    s.note(f"validasi folder worker: {outcomes}")
    ok = (
        outcomes["ground_truth_dev"].startswith("ditolak")
        and outcomes["../etc"].startswith("ditolak")
        and outcomes["tidak_ada"].startswith("ditolak")
        and outcomes["churn_ok_20261126"] == "DITERIMA"
    )
    return ok, (
        "validasi folder worker: ground_truth, path keluar root, dan folder tak ada "
        "ditolak; folder sah diterima"
    )


def uat_11() -> Scenario:
    s = Scenario("UAT-11", "Worker gagal / retry impor skor")
    s.level = "API sandbox + test worker Moses"
    with environment() as (client, factory, golden, customers, ids, headers):
        art = artifact(golden["c1"])
        first, _ = import_run(client, headers["submitter"], art)
        second, resp2 = import_run(client, headers["submitter"], art)
        tampered = artifact(golden["c1"])
        tampered["records"][0]["score"] = 0.11
        bad, _ = import_run(client, headers["submitter"], tampered)
        runs = client.get("/model-predictions/runs", headers=headers["decider"]).json()
        run_count = (
            len(runs) if isinstance(runs, list) else len(runs.get("items", runs))
        )
    s.check(first == 201, "impor pertama berhasil")
    s.check(
        second == 409,
        "impor ulang manifest yang sama ditolak (409), tidak ada baris ganda",
    )
    s.note(f"detail impor ulang: {resp2.json().get('detail')}")
    s.check(
        bad == 400, "artefak yang isinya berubah (checksum tidak cocok) ditolak (400)"
    )
    s.check(
        run_count == 1,
        "hanya 1 run tersimpan setelah retry + artefak rusak (tidak ada hasil parsial)",
    )
    s.check(*_artifact_dir_checks(s))
    ok, tail = _pytest_summary("tests/worker/test_prediction_import_job.py")
    s.check(ok, f"test worker impor milik Moses: {tail}")
    s.skip(
        "Retry di LINGKUNGAN BERSAMA (PREDICTION_IMPORT_ROOT nyata, PostgreSQL) belum diuji."
    )
    return s


def _campaign_env_steps(client, headers, *, approve: bool):
    created = client.post(
        "/campaigns",
        json={
            "name": "UAT Kampanye Sintetis",
            "target_segment": "uat",
            "channel": "email_sim",
            "ab_test_ratio": 50,
            "message_draft": "Halo, ini pesan uji sintetis.",
        },
        headers=headers["decider"],
    )
    cid = created.json()["id"]
    unapproved_launch = client.post(
        f"/campaigns/{cid}/launch", headers=headers["decider"]
    )
    client.post(f"/campaigns/{cid}/request-approval", headers=headers["decider"])
    launch_pending = client.post(f"/campaigns/{cid}/launch", headers=headers["decider"])
    if approve:
        client.post(f"/campaigns/{cid}/approve", headers=headers["decider"])
    return cid, created, unapproved_launch, launch_pending


def uat_12() -> Scenario:
    s = Scenario("UAT-12", "Campaign tanpa persetujuan")
    s.level = "API sandbox + worker"
    with environment() as (client, factory, golden, customers, ids, headers):
        cid, created, draft_launch, pending_launch = _campaign_env_steps(
            client, headers, approve=False
        )
        error = None
        try:
            worker_tasks.campaign_execution(
                {"campaign_id": cid, "batch_job_id": 1, "channel_simulator": False}
            )
        except Exception as e:  # noqa: BLE001
            error = f"{type(e).__name__}: {e}"
    s.check(
        created.status_code == 201,
        "kampanye sintetis (per segmen) dapat dibuat sebagai Draft",
    )
    s.check(draft_launch.status_code == 409, "launch saat Draft ditolak (409)")
    s.check(
        pending_launch.status_code == 409, "launch saat PendingApproval ditolak (409)"
    )
    s.check(
        error is not None and "simulator" in error.lower(),
        "eksekusi non-simulator ditolak worker",
    )
    s.note(f"worker non-simulator → {error}")
    return s


def uat_13() -> Scenario:
    s = Scenario("UAT-13", "Campaign berjalan dan pengukuran")
    s.level = "API sandbox + worker + test service"
    with environment() as (client, factory, golden, customers, ids, headers):
        prepared_run(client, headers, ids, golden["c1"])
        cid, _, _, _ = _campaign_env_steps(client, headers, approve=True)
        launch = client.post(f"/campaigns/{cid}/launch", headers=headers["decider"])
        job_id = launch.json().get("batch_job_id")
        with factory() as db:
            payload = db.get(BatchJob, job_id).payload
        result = worker_tasks.campaign_execution(payload)
    s.check(
        launch.status_code == 200,
        "kampanye yang disetujui manusia dapat di-launch (200)",
    )
    keys = (
        "audience_count",
        "targetable_count",
        "sent_count",
        "skipped_count",
        "control_exposure_count",
        "external_delivery",
        "identity_mapping_skipped_count",
    )
    s.note(
        "hasil job worker: "
        + ", ".join(f"{k}={result.get(k)}" for k in keys if k in result)
    )
    s.check(
        result.get("external_delivery") is False,
        "tanpa pengiriman eksternal (simulator)",
    )
    s.check(
        result.get("control_exposure_count", 0) == 0,
        "paparan kelompok holdout = 0 (belum bermakna: tidak ada pelanggan yang ditarget)",
    )
    if not result.get("targetable_count"):
        s.block(
            "Tidak ada pelanggan yang layak ditarget (targetable = 0) karena consent/komplain/kelayakan belum "
            "tersambung: 'campaign berjalan beneran' belum tercapai; tidak ada pesan simulasi terkirim."
        )
    ok, tail = _pytest_summary(
        "tests/decision/test_campaign_pipeline.py",
        "tests/decision/test_uplift_measurement.py",
        "tests/decision/test_campaign_execution_service.py",
    )
    s.check(ok, f"test pipeline campaign + pengukuran (service murni): {tail}")
    s.skip(
        "Pengukuran setelah hasil konversi nyata (Observed vs Incremental di UI) belum bisa diuji: belum ada hasil."
    )
    return s


def uat_14() -> Scenario:
    s = Scenario("UAT-14", "Data tersimpan, audit trail, UI kosong")
    s.level = "API sandbox"
    with environment() as (client, factory, golden, customers, ids, headers):
        prepared_run(client, headers, ids, golden["c1"])
        t0 = time.perf_counter()
        resp = evaluate(client, customers["c1"], headers["decider"])
        correlation = resp.headers.get("x-correlation-id") or resp.json().get(
            "correlation_id"
        )
        # "muat ulang": sesi baru terhadap DB yang sama
        with factory() as db:
            decisions = db.scalars(select(NBADecision)).all()
            events = db.scalars(select(AuditEvent)).all()
            types = sorted({e.event_type for e in events})
            by_corr = [
                e for e in events if correlation and e.correlation_id == correlation
            ]
        elapsed = time.perf_counter() - t0
    s.check(
        len(decisions) == 1, "keputusan tersimpan di database (terbaca dari sesi baru)"
    )
    s.check(
        any(t.startswith("model.prediction_run.") for t in types),
        "audit mencatat siklus run model",
    )
    s.note(f"jenis audit event: {types}")
    s.check(bool(correlation), "respons evaluate memuat correlation_id")
    s.check(
        any(e.event_type.startswith("nba.") for e in events) or bool(by_corr),
        "keputusan NBA dapat dilacak lewat audit/correlation_id",
    )
    s.note(
        f"jejak per correlation_id: {[e.event_type for e in by_corr]}; waktu rekonstruksi {elapsed:.2f} dtk"
    )
    s.note(
        "Temuan: setiap permintaan API memakai correlation_id sendiri, sehingga "
        "import→review→izin→keputusan TIDAK terhubung oleh satu correlation_id; keputusan NBA "
        "memuat model_version dan status review tetapi bukan run_id. Rekonstruksi penuh harus "
        "menggabungkan jejak lewat model_version/waktu. Dicatat sebagai temuan untuk Moses/James "
        "(definisi selesai: audit dari impor sampai NBA)."
    )
    s.skip(
        "Penyimpanan hasil CAMPAIGN dan pengukuran di DB bersama, serta tampilan 'Kosong' di UI, belum diperiksa."
    )
    return s


TITLES = {
    "UAT-01": "Hasil valid",
    "UAT-02": "Belum ada skor (keadaan 1)",
    "UAT-03": "Run menunggu review (keadaan 2)",
    "UAT-04": "Run ditolak (keadaan 2)",
    "UAT-05": "Review oleh pengunggah / pembuat model",
    "UAT-06": "Sudah direview, belum ada izin pakai / izin dicabut",
    "UAT-07": "Skor kedaluwarsa",
    "UAT-08": "ID tidak cocok / tanpa pemetaan pasti",
    "UAT-09": "Data sebagian hilang",
    "UAT-10": "NO_ACTION karena kebijakan",
    "UAT-11": "Worker gagal / retry impor skor",
    "UAT-12": "Campaign tanpa persetujuan",
    "UAT-13": "Campaign berjalan dan pengukuran",
    "UAT-14": "Data tersimpan, audit trail, UI kosong",
}

SCENARIOS: list[Callable[[], Scenario]] = [
    uat_01,
    uat_02,
    uat_03,
    uat_04,
    uat_05,
    uat_06,
    uat_07,
    uat_08,
    uat_09,
    uat_10,
    uat_11,
    uat_12,
    uat_13,
    uat_14,
]


def run_all() -> list[Scenario]:
    results = []
    for fn in SCENARIOS:
        uat_id = fn.__name__.replace("uat_", "UAT-").replace("_", "-")
        try:
            scenario = fn()
        except (
            Exception
        ) as error:  # noqa: BLE001 - kegagalan runner dicatat sebagai FAIL apa adanya
            scenario = Scenario(uat_id, TITLES[uat_id])
            scenario.level = "runner berhenti"
            scenario.error = f"{type(error).__name__}: {error}"
        results.append(scenario)
        print(f"{scenario.uat_id:7} {scenario.verdict:17} {scenario.title}", flush=True)
    return results


def write_markdown(results: list[Scenario]) -> None:
    counts: dict[str, int] = {}
    for r in results:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1
    lines = [
        "# Hasil uji coba UAT (dry run) — sandbox lokal",
        "",
        f"**Dijalankan:** {datetime.now().strftime('%Y-%m-%d %H:%M')} oleh `uat_dry_run.py` (dapat diulang).",
        f"**Data:** {DATA_LABEL}. Tidak ada model riil yang direview atau diberi izin pakai.",
        "",
        "> **Ini BUKAN UAT resmi.** Dijalankan di DB sqlite memori, lewat API/worker, tanpa UI, tanpa lingkungan "
        "bersama, dan tanpa penguji independen. Gunakan sebagai pemeriksaan awal; UAT resmi tetap harus dijalankan "
        "dan dicatat di `UAT_PLAN.md` setelah alur impor→review→izin→NBA→simulator→audit berjalan di lingkungan bersama.",
        "",
        "Verdict: `PASS` = sesuai harapan pada level yang dijalankan; `FAIL` = berbeda dari harapan; "
        "`TERHALANG` = prasyarat belum ada (bukan kegagalan logika); `TIDAK DIJALANKAN` = butuh lingkungan/UI.",
        "",
        "Ringkasan: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())),
        "",
        "| ID | Skenario | Level | Verdict |",
        "|---|---|---|---|",
    ]
    for r in results:
        lines.append(f"| {r.uat_id} | {r.title} | {r.level} | **{r.verdict}** |")
    lines.append("")
    for r in results:
        lines += [
            f"## {r.uat_id} · {r.title} — {r.verdict}",
            "",
            f"Level: {r.level}",
            "",
        ]
        if r.error:
            lines += [f"- ❌ Runner berhenti dengan error: `{r.error}`"]
        for ok, description in r.checks:
            lines.append(f"- {'✅' if ok else '❌'} {description}")
        for text in r.observed:
            lines.append(f"- Catatan: {text}")
        for text in r.blocked:
            lines.append(f"- ⛔ TERHALANG: {text}")
        for text in r.not_run:
            lines.append(f"- ⏸ Tidak diperiksa di sandbox: {text}")
        lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    outcome = run_all()
    write_markdown(outcome)
    print(f"\nDitulis ke {OUT_MD.relative_to(ROOT)}")
    sys.exit(0 if all(r.verdict != "FAIL" for r in outcome) else 1)
