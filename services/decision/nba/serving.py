"""
serving.py — Jembatan NBA ke aplikasi (fungsi MURNI: data masuk, hasil keluar)
=============================================================================
Revisi mentor (Fase 4 lanjutan), bagian Christ:
  "sambungin NBA ke aplikasi bareng Marvin"
  "kode di services/ isinya fungsi murni; yang manggil dan yang nyimpen ke database
   itu api/ sama worker/"
  "jangan pernah nampilin angka contoh seolah hasil asli. kalau datanya kosong, tulis
   aja kosong"

Modul ini TIDAK membuka database, TIDAK memakai jaringan, TIDAK memakai FastAPI.
`api/decisions.py` (milik James/Marvin) membaca baris dari database, mengubahnya jadi
dict biasa, memanggil `evaluate_customer(...)`, lalu menyimpan hasil `DecisionOutput`
ke `dec.nba_decisions`, `gov.decision_traces`, dan audit event.

Prinsip fail-closed (data kosong = ditulis kosong, bukan diisi tebakan):
  * Skor dipakai HANYA bila run model sudah `reviewed` oleh orang LAIN dari pengunggah
    (aturan "versi model dicatat dan harus dicek orang lain" dari mentor).
  * Skor yang tidak lengkap (mis. CLV / propensity belum ada) dianggap TIDAK TERSEDIA;
    tidak ada nilai pengganti yang dikarang.
  * Sumber consent / komplain / riwayat kontak / kelayakan / kesesuaian produk yang
    belum tersambung (None) menghasilkan keputusan "tidak ada keputusan" yang jujur,
    bukan izin diam-diam.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Sequence

from services.decision.nba.engine import (
    ENGINE_VERSION,
    AIScores,
    DecisionRecord,
    EligibilityProfile,
    NBAEngine,
    ProductSuitability,
)
from services.decision.nba.explain import PLAIN_RATIONALE_VERSION, explain_decision
from services.decision.policy.fatigue import ContactRecord
from services.decision.policy.suppression import ComplaintTicket, CustomerConsent

# ---------------------------------------------------------------------------
# Konstanta
# ---------------------------------------------------------------------------

REVIEW_STATUS_APPROVED = "reviewed"
"""Nilai `ml.prediction_review_runs.review_status` untuk run yang sudah dicek manusia.

PENTING: `reviewed` BUKAN izin pakai. Menurut TEAM_ALIGNMENT_MVP_2026-11-21 §1 ada tiga
status berbeda (tersedia / terintegrasi / disetujui untuk digunakan). Izin pakai harus
datang dari kunci terpisah `usage_approved` (lihat `lookup_scores`) yang aturannya
ditentukan lewat keputusan D1/D2. Sampai kunci itu ada, skor TIDAK dipakai NBA."""

REQUIRED_SCORE_FIELDS = (
    "churn_score",
    "churn_risk_band",
    "propensity_purchase",
    "propensity_renew",
    "clv_amount",
    "clv_tier",
    "lifecycle_stage",
    "score_generated_at",
)

# Kode alasan skor TIDAK dipakai (disimpan di kolom rationale agar bisa diaudit).
SCORE_NO_ROW = "SCORE_ROW_MISSING"
SCORE_NOT_REVIEWED = "MODEL_RUN_NOT_REVIEWED"
SCORE_SELF_REVIEWED = "MODEL_RUN_REVIEWED_BY_SUBMITTER"
SCORE_USAGE_NOT_APPROVED = "MODEL_USAGE_NOT_APPROVED"
SCORE_INCOMPLETE = "SCORE_FIELDS_INCOMPLETE"
SCORE_INVALID = "SCORE_VALUES_INVALID"
SCORE_CONTRACT_NOT_SERVING = "SCORE_CONTRACT_NOT_SERVING"
SCORE_EXPIRED = "SCORE_EXPIRED"
SCORE_CUSTOMER_MISMATCH = "SCORE_CUSTOMER_MISMATCH"

NON_SERVING_CONTRACT_STATUSES = frozenset({"SCHEMA_PARTIAL", "INVALID_SCORE"})
"""Status kontrak producer Moses (`prediction_contract.STATUSES`) yang eksplisit bukan untuk serving.

Disalin (bukan diimpor) agar `services/decision` tidak bergantung pada api/ atau services/data.
Dipakai bila loader mengirim kunci opsional `contract_status` pada baris skor."""

# Tiga keadaan skor untuk UI (to-do PM 26 Nov: "belum ada" / "ada tapi belum disetujui" / "siap").
SCORE_STATE_MISSING = "SCORE_MISSING"
SCORE_STATE_PRESENT_NOT_APPROVED = "SCORE_PRESENT_NOT_APPROVED"
SCORE_STATE_READY = "SCORE_READY"

_SCORE_STATE_BY_REASON = {
    SCORE_NO_ROW: SCORE_STATE_MISSING,
    SCORE_NOT_REVIEWED: SCORE_STATE_PRESENT_NOT_APPROVED,
    SCORE_SELF_REVIEWED: SCORE_STATE_PRESENT_NOT_APPROVED,
    SCORE_USAGE_NOT_APPROVED: SCORE_STATE_PRESENT_NOT_APPROVED,
    SCORE_CONTRACT_NOT_SERVING: SCORE_STATE_PRESENT_NOT_APPROVED,
    SCORE_EXPIRED: SCORE_STATE_PRESENT_NOT_APPROVED,
    SCORE_CUSTOMER_MISMATCH: SCORE_STATE_PRESENT_NOT_APPROVED,
    SCORE_INCOMPLETE: SCORE_STATE_PRESENT_NOT_APPROVED,
    SCORE_INVALID: SCORE_STATE_PRESENT_NOT_APPROVED,
}


def score_state_for(unavailable_reason: Optional[str], *, usable: bool) -> str:
    """
    Memetakan hasil pembacaan skor ke salah satu dari TIGA keadaan tampilan.

    * `SCORE_READY`                 - skor lolos semua gerbang dan dipakai.
    * `SCORE_MISSING`               - tidak ada baris skor sama sekali.
    * `SCORE_PRESENT_NOT_APPROVED`  - baris skor ada, tetapi belum boleh/bisa dipakai
      (belum direview, reviewer tidak sah, belum ada izin pakai, kontrak producer
      belum lengkap, field kosong, atau nilai tidak valid).

    Alasan yang tidak dikenal diperlakukan fail-closed sebagai "ada tapi belum dipakai",
    BUKAN "siap" dan BUKAN "belum ada" (agar tidak menyamarkan masalah jadi kosong).
    """
    if usable:
        return SCORE_STATE_READY
    return _SCORE_STATE_BY_REASON.get(
        unavailable_reason or "", SCORE_STATE_PRESENT_NOT_APPROVED
    )


DECISION_STATUS_PROPOSED = "proposed"
DECISION_STATUS_ACCEPTED = "accepted"
SOURCE_UNAVAILABLE = "INPUT_SOURCE_UNAVAILABLE"

EVENT_ENGINE_EVALUATED = "nba.engine_evaluated"

_SCORE_NOTES = {
    SCORE_NO_ROW: "Skor prediksi untuk pelanggan ini belum ada, jadi tidak ada angka yang dipakai.",
    SCORE_NOT_REVIEWED: (
        "Skor prediksi dari model belum diperiksa orang lain, jadi belum boleh "
        "dipakai untuk keputusan."
    ),
    SCORE_SELF_REVIEWED: (
        "Skor prediksi diperiksa oleh orang yang sama dengan pengunggahnya, jadi "
        "belum boleh dipakai untuk keputusan."
    ),
    SCORE_USAGE_NOT_APPROVED: (
        "Skor prediksi sudah diperiksa, tetapi belum disetujui untuk dipakai dalam "
        "keputusan, jadi belum dipakai."
    ),
    SCORE_INCOMPLETE: "Skor prediksi pelanggan ini belum lengkap, jadi tidak dipakai.",
    SCORE_INVALID: "Skor prediksi pelanggan ini tidak valid, jadi tidak dipakai.",
    SCORE_CONTRACT_NOT_SERVING: (
        "Skor prediksi sudah tersimpan, tetapi formatnya belum lengkap menurut "
        "kontrak, jadi belum dipakai."
    ),
    SCORE_EXPIRED: "Skor prediksi pelanggan ini sudah kedaluwarsa, jadi tidak dipakai.",
    SCORE_CUSTOMER_MISMATCH: (
        "Skor yang ditemukan tidak cocok dengan identitas pelanggan ini, jadi tidak dipakai."
    ),
}

_PLAIN_SOURCE_NAMES = {
    "consent": "data izin kontak (consent)",
    "complaint_history": "data keluhan pelanggan",
    "contact_history": "riwayat pesan yang sudah dikirim",
    "eligibility": "data kelayakan pelanggan",
    "product_suitability": "data ketersediaan produk",
}


# ---------------------------------------------------------------------------
# Skor model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoreLookup:
    """Hasil membaca satu baris skor: dipakai atau tidak, dan kenapa."""

    ai_scores: Optional[AIScores]
    model_version: Optional[str]
    review_status: Optional[str]
    reviewed_by: Optional[Any]
    unavailable_reason: Optional[str] = None
    missing_fields: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        # `ai_scores` tetap diisi untuk skor kedaluwarsa (engine yang menurunkannya ke
        # default konservatif + degraded_input), tetapi skor itu TIDAK dianggap dipakai.
        return self.ai_scores is not None and self.unavailable_reason is None

    @property
    def state(self) -> str:
        """Salah satu dari tiga keadaan tampilan (lihat `score_state_for`)."""
        return score_state_for(self.unavailable_reason, usable=self.usable)


def _parse_dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None
    return None


def _is_number(value: Any) -> bool:
    try:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        )
    except (OverflowError, ValueError):
        return False


def lookup_scores(row: Optional[Mapping[str, Any]], *, customer_id: str) -> ScoreLookup:
    """
    Mengubah satu baris skor (dict) menjadi `AIScores` atau menolaknya (fail-closed).

    Baris yang diharapkan (gabungan skor + run model-nya; sumber data diisi Moses,
    dibaca oleh api/):
        customer_id, churn_score, churn_risk_band, propensity_purchase,
        propensity_renew, clv_amount, clv_tier, lifecycle_stage,
        score_generated_at, reason_codes, model_version,
        review_status, reviewed_by, submitted_by, usage_approved
    Opsional: model_author (pembuat/pelatih model; bila ada, reviewer tidak boleh sama),
    contract_status (bila `SCHEMA_PARTIAL`/`INVALID_SCORE` -> `SCORE_CONTRACT_NOT_SERVING`).

    Ditolak bila: baris kosong, `customer_id` baris tidak sama dengan pelanggan yang dievaluasi, run belum `reviewed`, `reviewed_by` kosong atau sama
    dengan `submitted_by`/`model_author` (harus orang lain), `usage_approved` bukan
    `True` (review saja bukan izin pakai), ada field wajib yang kosong, atau ada nilai
    di luar rentang. Penolakan TIDAK diganti angka pengganti.
    """
    if not row:
        return ScoreLookup(None, None, None, None, SCORE_NO_ROW)

    model_version = row.get("model_version")
    review_status = row.get("review_status")
    reviewed_by = row.get("reviewed_by")
    base: Dict[str, Any] = {
        "model_version": model_version,
        "review_status": review_status,
        "reviewed_by": reviewed_by,
    }

    # Pertahanan berlapis: loader (api/) sudah memfilter per ID, tetapi skor milik pelanggan
    # LAIN tidak boleh dipakai walau loader salah. ID kosong juga ditolak (tidak ada tebakan, D4).
    if row.get("customer_id") != customer_id:
        return ScoreLookup(None, unavailable_reason=SCORE_CUSTOMER_MISMATCH, **base)

    # Baris ADA tetapi kontrak producer menandainya bukan untuk serving. Dibedakan dari
    # "baris tidak ada" agar UI tidak menulis "belum ada skor" untuk skor yang sudah tersimpan.
    if row.get("contract_status") in NON_SERVING_CONTRACT_STATUSES:
        return ScoreLookup(None, unavailable_reason=SCORE_CONTRACT_NOT_SERVING, **base)
    if review_status != REVIEW_STATUS_APPROVED:
        return ScoreLookup(None, unavailable_reason=SCORE_NOT_REVIEWED, **base)
    if (
        reviewed_by is None
        or reviewed_by == row.get("submitted_by")
        or (row.get("model_author") is not None and reviewed_by == row["model_author"])
    ):
        return ScoreLookup(None, unavailable_reason=SCORE_SELF_REVIEWED, **base)
    if row.get("usage_approved") is not True:
        return ScoreLookup(None, unavailable_reason=SCORE_USAGE_NOT_APPROVED, **base)

    missing = tuple(k for k in REQUIRED_SCORE_FIELDS if row.get(k) in (None, ""))
    if missing:
        return ScoreLookup(
            None, unavailable_reason=SCORE_INCOMPLETE, missing_fields=missing, **base
        )

    generated_at = _parse_dt(row["score_generated_at"])
    numeric_ok = all(
        _is_number(row[k])
        for k in (
            "churn_score",
            "propensity_purchase",
            "propensity_renew",
            "clv_amount",
        )
    )
    if (
        generated_at is None
        or not numeric_ok
        or any(
            not 0.0 <= row[k] <= 1.0
            for k in ("churn_score", "propensity_purchase", "propensity_renew")
        )
        or row["clv_amount"] < 0
    ):
        return ScoreLookup(None, unavailable_reason=SCORE_INVALID, **base)

    scores = AIScores(
        customer_id=customer_id,
        churn_score=float(row["churn_score"]),
        churn_risk_band=str(row["churn_risk_band"]),
        propensity_purchase=float(row["propensity_purchase"]),
        propensity_renew=float(row["propensity_renew"]),
        clv_amount=float(row["clv_amount"]),
        clv_tier=str(row["clv_tier"]),
        lifecycle_stage=str(row["lifecycle_stage"]),
        score_generated_at=generated_at,
        reason_codes=[str(c) for c in (row.get("reason_codes") or [])],
    )
    return ScoreLookup(scores, **base)


# ---------------------------------------------------------------------------
# Hasil keputusan siap-simpan
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DecisionOutput:
    """
    Keputusan NBA lengkap + baris siap-simpan untuk api/ (tanpa menyentuh database).

    `record` bernilai None HANYA bila ada sumber data yang belum tersambung; dalam
    kasus itu tidak ada rekaman K-07 palsu yang dibuat.
    """

    customer_ref: str
    correlation_id: str
    record: Optional[DecisionRecord]
    plain_rationale: str
    score_lookup: ScoreLookup
    unavailable_sources: tuple[str, ...] = ()
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    score_explanation: Optional[Mapping[str, Any]] = None

    @property
    def selected_action_id(self) -> str:
        return self.record.selected_action_id if self.record else "NO_ACTION"

    @property
    def is_no_action(self) -> bool:
        return self.selected_action_id == "NO_ACTION"

    @property
    def degraded_input(self) -> bool:
        return True if self.record is None else self.record.degraded_input

    def _input_availability(self) -> Dict[str, str]:
        availability = {
            name: ("unavailable" if name in self.unavailable_sources else "provided")
            for name in _PLAIN_SOURCE_NAMES
        }
        availability["model_scores"] = (
            "used"
            if self.score_lookup.usable
            else f"unavailable: {self.score_lookup.unavailable_reason}"
        )
        return availability

    def rationale_payload(self) -> Dict[str, Any]:
        """Isi kolom JSON `dec.nba_decisions.rationale` (semua nilai berasal dari data nyata)."""
        record = self.record
        return {
            "reason": self.plain_rationale,
            "reason_version": PLAIN_RATIONALE_VERSION,
            "technical_reason": record.rationale_text if record else None,
            "engine_version": record.engine_version if record else ENGINE_VERSION,
            "model_version": self.score_lookup.model_version,
            "model_review_status": self.score_lookup.review_status,
            "model_reviewed_by": self.score_lookup.reviewed_by,
            "score_explanation_version": (
                self.score_explanation.get("version")
                if self.score_explanation and self.score_lookup.usable
                else None
            ),
            "score_unavailable_reason": self.score_lookup.unavailable_reason,
            "score_state": self.score_lookup.state,
            "score_missing_fields": list(self.score_lookup.missing_fields),
            # Angka EV hanya ditulis bila skor nyata dipakai; selain itu null (kosong).
            "expected_value": (
                record.expected_value
                if record is not None and not record.degraded_input
                else None
            ),
            "no_action_reason": (
                record.no_action_reason if record else SOURCE_UNAVAILABLE
            ),
            "degraded_input": self.degraded_input,
            "serving_ready": self.score_lookup.usable and not self.unavailable_sources,
            "identity_ref": self.customer_ref,
            "unavailable_sources": list(self.unavailable_sources),
            "input_availability": self._input_availability(),
            "checks": record.checks if record else [],
            "candidates": record.candidates if record else [],
        }

    def to_nba_decision_row(self, *, customer_db_id: int) -> Dict[str, Any]:
        """Kolom untuk `dec.nba_decisions` (dipakai api/ untuk membuat `NBADecision`)."""
        return {
            "customer_id": customer_db_id,
            "correlation_id": self.correlation_id,
            "recommended_action": self.selected_action_id,
            "rationale": self.rationale_payload(),
            "status": (
                DECISION_STATUS_ACCEPTED
                if self.is_no_action
                else DECISION_STATUS_PROPOSED
            ),
        }

    def to_trace_row(self, *, customer_code: str) -> Dict[str, Any]:
        """Kolom untuk `gov.decision_traces` (jejak audit keputusan)."""
        return {
            "correlation_id": self.correlation_id,
            "customer_code": customer_code,
            "trigger_event": EVENT_ENGINE_EVALUATED,
            "decision_output": self.selected_action_id,
            "step_logs": [
                (
                    self.record.to_dict()
                    if self.record is not None
                    else {
                        "customer_id": self.customer_ref,
                        "selected_action_id": "NO_ACTION",
                        "no_action_reason": SOURCE_UNAVAILABLE,
                        "unavailable_sources": list(self.unavailable_sources),
                        "rationale_text": self.plain_rationale,
                        "correlation_id": self.correlation_id,
                    }
                )
            ],
        }

    def to_audit_details(self, *, decision_id: Optional[int] = None) -> Dict[str, Any]:
        """Isi `details` untuk `record_audit_event(event_type="nba.engine_evaluated")`."""
        payload = self.rationale_payload()
        return {
            "decision_id": decision_id,
            "selected_action": self.selected_action_id,
            "engine_version": payload["engine_version"],
            "model_version": payload["model_version"],
            "degraded_input": payload["degraded_input"],
            "serving_ready": payload["serving_ready"],
            "identity_ref": self.customer_ref,
            "unavailable_sources": payload["unavailable_sources"],
        }

    def to_api_response(
        self, *, decision_id: Optional[int], status: str
    ) -> Dict[str, Any]:
        """Bentuk respons endpoint evaluate (dibaca langsung oleh UI Marvin)."""
        payload = self.rationale_payload()
        return {
            "id": decision_id,
            "status": status,
            "selected_action": self.selected_action_id,
            "reason": self.plain_rationale,
            "engine_version": payload["engine_version"],
            "model_version": payload["model_version"],
            "no_action_reason": payload["no_action_reason"],
            "degraded_input": payload["degraded_input"],
            "serving_ready": payload["serving_ready"],
            "expected_value": payload["expected_value"],
            "unavailable_sources": payload["unavailable_sources"],
            "score_state": payload["score_state"],
            "score_unavailable_reason": payload["score_unavailable_reason"],
            # Status review run model apa adanya (pending_review / rejected / reviewed / None):
            # kode alasan MODEL_RUN_NOT_REVIEWED sama untuk "menunggu" dan "ditolak".
            "model_review_status": payload["model_review_status"],
        }


# ---------------------------------------------------------------------------
# Fungsi utama
# ---------------------------------------------------------------------------


def _plain_unavailable_sentence(sources: Sequence[str]) -> str:
    names = ", ".join(_PLAIN_SOURCE_NAMES[s] for s in sources)
    return (
        f"Belum ada keputusan promosi karena sumber data berikut belum tersambung: "
        f"{names}. Data yang kosong ditampilkan kosong, tidak diisi angka contoh."
    )


def evaluate_customer(
    *,
    customer_ref: str,
    correlation_id: str,
    score_row: Optional[Mapping[str, Any]],
    consent_doc: Optional[Mapping[str, Any]],
    complaint_tickets: Optional[Sequence[ComplaintTicket]],
    contact_history: Optional[Sequence[ContactRecord]],
    eligibility: Optional[EligibilityProfile],
    product_suitability: Optional[ProductSuitability],
    evaluation_date: Optional[datetime] = None,
    engine: Optional[NBAEngine] = None,
    score_explanation: Optional[Mapping[str, Any]] = None,
) -> DecisionOutput:
    """
    Mengevaluasi satu pelanggan dan mengembalikan `DecisionOutput`.

    `None` pada sebuah sumber berarti "sumber ini BELUM TERSAMBUNG" (bukan "kosong").
    Sumber yang tersambung tetapi memang kosong dikirim sebagai daftar kosong `[]`.
    Bila ada sumber None, tidak ada keputusan promosi yang dibuat.

    `score_explanation` = keluaran formatter Moses (`explain_contributions`), disisipkan
    apa adanya ke alasan HANYA bila skor dipakai; tidak pernah ditulis ulang di sini.
    """
    when = evaluation_date or datetime.now(timezone.utc)
    nba = engine or NBAEngine()
    lookup = lookup_scores(score_row, customer_id=customer_ref)
    if (
        lookup.ai_scores is not None
        and lookup.unavailable_reason is None
        and nba._is_score_expired(lookup.ai_scores, when)
    ):
        # Aturan kedaluwarsa SATU sumber (engine). Skor tetap diteruskan ke engine agar
        # perilaku keputusan tidak berubah; yang berubah hanya label: bukan "siap dipakai".
        lookup = replace(lookup, unavailable_reason=SCORE_EXPIRED)

    unavailable = tuple(
        name
        for name, value in (
            ("consent", consent_doc),
            ("complaint_history", complaint_tickets),
            ("contact_history", contact_history),
            ("eligibility", eligibility),
            ("product_suitability", product_suitability),
        )
        if value is None
    )
    if unavailable:
        return DecisionOutput(
            customer_ref=customer_ref,
            correlation_id=correlation_id,
            record=None,
            plain_rationale=_plain_unavailable_sentence(unavailable),
            score_lookup=lookup,
            unavailable_sources=unavailable,
            evaluated_at=when,
        )

    assert consent_doc is not None  # dipersempit oleh pemeriksaan di atas
    assert complaint_tickets is not None
    assert contact_history is not None
    assert eligibility is not None
    assert product_suitability is not None

    consent = CustomerConsent.from_k10(consent_doc, now=when)
    record = nba.decide(
        customer_id=customer_ref,
        ai_scores=lookup.ai_scores,
        consent=consent,
        complaint_tickets=list(complaint_tickets),
        contact_history=list(contact_history),
        eligibility=eligibility,
        product_suitability=product_suitability,
        evaluation_date=when,
        correlation_id=correlation_id,
    )
    return DecisionOutput(
        customer_ref=customer_ref,
        correlation_id=correlation_id,
        record=record,
        plain_rationale=explain_decision(
            record,
            score_note=_SCORE_NOTES.get(lookup.unavailable_reason or ""),
            score_explanation=score_explanation,
        ),
        score_lookup=lookup,
        evaluated_at=when,
        score_explanation=score_explanation,
    )
