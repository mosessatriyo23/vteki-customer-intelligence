"""
test_e2e_decision_flow.py — End-to-End Closed-Loop Customer Decisioning (Fase 4, Minggu 13).

Skenario flagship (Panduan_Kerja_Christ.md, Minggu 13):

    Data Pelanggan -> Skor Prediksi AI -> Evaluasi Komplain/Consent/Fatigue
    -> NBA Recommendation (K-07) -> Nudge + Human Approval
    -> Channel Simulator (Holdout 10%) -> Incremental Revenue Measurement
    -> Audit Trace (K-11, X-Correlation-ID)

Yang dibuktikan:
  1. Setiap keputusan lolos skema K-07 dan setiap audit event lolos skema K-11.
  2. "Skor tinggi bukan izin": pelanggan skor tinggi yang opt-out / komplain berat /
     kena fatigue TIDAK pernah menerima pesan promosi.
  3. Control Group 0 paparan; seluruh pengiriman bersifat simulasi (offline).
  4. Incremental Revenue sama dengan rumus independen (dihitung ulang di test).
  5. Rantai keputusan satu pelanggan dapat direkonstruksi lewat X-Correlation-ID
     dalam waktu < 5 menit (batas dosen/FRD), diukur nyata dengan perf_counter.

CATATAN BATAS: audit store di file ini adalah `AuditTrail` in-memory milik test (meniru
bentuk K-11). Penyimpanan nyata (`gov.audit_event`, PostgreSQL) milik James (api/, migrations/);
SLA < 5 menit pada PostgreSQL diuji di sisi James. Data pelanggan 100% sintetis.

Jalankan: python -m pytest tests/decision/test_e2e_decision_flow.py -v
"""

from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

import jsonschema
import pytest

from services.decision.campaign.holdout import HoldoutSplit, split_from_campaign
from services.decision.measurement.uplift import (
    Outcome,
    UpliftResult,
    compute_uplift,
    incremental_revenue,
    window_from_campaign,
)
from services.decision.nba.engine import (
    AIScores,
    DecisionRecord,
    EligibilityProfile,
    NBAEngine,
    ProductSuitability,
)
from services.decision.nudge.generator import (
    STATUS_BLOCKED_BY_GUARDRAIL,
    STATUS_GENERATED_DRAFT,
    NudgeDraft,
    approve_draft,
    generate_nudge,
)
from services.decision.policy.fatigue import ContactRecord
from services.decision.policy.suppression import (
    ComplaintStatus,
    ComplaintTicket,
    CustomerConsent,
)
from services.decision.simulator.channel_sim import (
    STATUS_REJECTED_NOT_APPROVED,
    STATUS_SIMULATED_SENT,
    STATUS_SKIPPED_CONTROL,
    ChannelSimulator,
)

ROOT = Path(__file__).resolve().parents[2]
K07_SCHEMA = json.loads(
    (ROOT / "contracts" / "K-07_decision_record.json").read_text(encoding="utf-8")
)
K11_SCHEMA = json.loads(
    (ROOT / "contracts" / "K-11_audit_event_contract.json").read_text(encoding="utf-8")
)

NOW = datetime(2026, 11, 5, 10, 0, 0)
SENT_AT = datetime(2026, 11, 6, 9, 0, 0)
AS_OF_FINAL = datetime(2027, 2, 1)
CAMPAIGN_ID = "CMP-E2E-1"
CAMPAIGN_CORRELATION_ID = f"corr-e2e-campaign-{CAMPAIGN_ID}"
CAMPAIGN = {
    "campaign_id": CAMPAIGN_ID,
    "control_holdout_ratio": 0.10,
    "random_seed": 20261105,
    "conversion_window_days": 30,
    "adjustment_window_days": 14,
    "exposure_window": {
        "start_time": "2026-11-05T00:00:00Z",
        "end_time": "2026-11-12T00:00:00Z",
    },
}
ORDER_VALUE = 100_000
TREATMENT_BUY_EVERY = 5  # 20% grup treatment membeli
CONTROL_BUY_EVERY = 10  # 10% grup control membeli (baseline tanpa kampanye)

KIND_OPT_OUT = "OPT_OUT"
KIND_SEVERE_COMPLAINT = "SEVERE_COMPLAINT"
KIND_FATIGUED = "FATIGUED"
KIND_ELIGIBLE = "ELIGIBLE"


# ---------------------------------------------------------------------------
# Audit trail in-memory berbentuk K-11 (pengganti gov.audit_event untuk test)
# ---------------------------------------------------------------------------


class AuditTrail:
    """Penyimpan audit append-only in-memory; setiap event divalidasi terhadap K-11."""

    def __init__(self) -> None:
        self._events: List[Dict[str, Any]] = []
        self._validator = jsonschema.Draft7Validator(K11_SCHEMA)

    def record(
        self,
        *,
        event_type: str,
        action: str,
        entity_type: str,
        entity_id: str,
        status: str,
        correlation_id: str,
        occurred_at: datetime,
        details: Dict[str, Any],
    ) -> Dict[str, Any]:
        event = {
            "event_id": f"AUD-{len(self._events) + 1:08d}",
            "event_type": event_type,
            "occurred_at": occurred_at.isoformat() + "Z",
            "X-Correlation-ID": correlation_id,
            "correlation_id": correlation_id,
            "actor": {
                "actor_type": "SERVICE",
                "actor_id": "decision-engine",
                "actor_role": "system",
            },
            "action": action,
            "entity": {"entity_type": entity_type, "entity_id": entity_id},
            "status": status,
            "details": details,
            "immutability": {"is_append_only": True},
        }
        self._validator.validate(event)
        self._events.append(event)
        return event

    @property
    def events(self) -> List[Dict[str, Any]]:
        return list(self._events)

    def by_correlation(self, correlation_id: str) -> List[Dict[str, Any]]:
        return [e for e in self._events if e["X-Correlation-ID"] == correlation_id]


def customer_correlation_id(customer_id: str) -> str:
    return f"corr-e2e-{customer_id}"


def reconstruct_chain(audit: AuditTrail, customer_id: str) -> List[Dict[str, Any]]:
    """
    Rekonstruksi rantai keputusan satu pelanggan lewat X-Correlation-ID.

    Mengambil event milik pelanggan (decision -> nudge -> delivery) lalu menyambungkan
    event level kampanye (measurement) berdasarkan `campaign_id` pada event delivery.
    """
    chain = audit.by_correlation(customer_correlation_id(customer_id))
    campaign_ids = {
        e["details"]["campaign_id"]
        for e in chain
        if e["details"].get("campaign_id") is not None
    }
    for campaign_id in sorted(campaign_ids):
        chain.extend(audit.by_correlation(f"corr-e2e-campaign-{campaign_id}"))
    return chain


# ---------------------------------------------------------------------------
# Data sintetis pelanggan
# ---------------------------------------------------------------------------


@dataclass
class FlowResult:
    customer_kinds: Dict[str, str]
    records: Dict[str, DecisionRecord]
    drafts: Dict[str, NudgeDraft]
    target_ids: List[str]
    split: HoldoutSplit
    sim: ChannelSimulator
    outcomes: List[Outcome]
    uplift: UpliftResult
    audit: AuditTrail
    skipped_no_draft: List[str] = field(default_factory=list)


def _kind_for(index: int) -> str:
    bucket = index % 10
    if bucket == 0:
        return KIND_OPT_OUT
    if bucket == 1:
        return KIND_SEVERE_COMPLAINT
    if bucket == 2:
        return KIND_FATIGUED
    return KIND_ELIGIBLE


def _decide_for(engine: NBAEngine, customer_id: str, kind: str) -> DecisionRecord:
    """Semua profil memakai skor churn TINGGI agar jelas: skor tinggi bukan izin."""
    scores = AIScores(
        customer_id=customer_id,
        churn_score=0.92,
        churn_risk_band="VERY_HIGH",
        propensity_purchase=0.6,
        propensity_renew=0.5,
        clv_amount=3_000_000.0,
        clv_tier="GOLD",
        lifecycle_stage="AT_RISK",
        score_generated_at=NOW - timedelta(days=1),
        reason_codes=["RECENCY_GAP", "FREQ_DROP", "BASKET_DROP"],
    )
    eligibility = EligibilityProfile(
        customer_id=customer_id,
        tenure_days=400,
        membership_days_remaining=20,
        has_active_membership=True,
        purchased_categories=["GROCERY"],
        days_until_replenishment=3,
    )
    consent = CustomerConsent(customer_id)
    tickets: List[ComplaintTicket] = []
    history: List[ContactRecord] = []

    if kind == KIND_OPT_OUT:
        consent = CustomerConsent(customer_id, global_opt_out=True)
    elif kind == KIND_SEVERE_COMPLAINT:
        tickets = [
            ComplaintTicket(
                ticket_id=f"TKT-{customer_id}",
                customer_id=customer_id,
                status=ComplaintStatus.OPEN_SEVERE,
                severity="SEVERE",
                opened_at=NOW - timedelta(days=1),
            )
        ]
    elif kind == KIND_FATIGUED:
        history = [
            ContactRecord(customer_id, "CROSS_SELL", "email", NOW - timedelta(days=d))
            for d in (1, 6)
        ]

    return engine.decide(
        customer_id=customer_id,
        ai_scores=scores,
        consent=consent,
        complaint_tickets=tickets,
        contact_history=history,
        eligibility=eligibility,
        product_suitability=ProductSuitability(),
        evaluation_date=NOW,
        correlation_id=customer_correlation_id(customer_id),
        decision_id=f"DEC-E2E-{customer_id}",
    )


def run_flow(n_customers: int = 1000) -> FlowResult:
    """Menjalankan seluruh alur flagship secara deterministik dan 100% offline."""
    audit = AuditTrail()
    engine = NBAEngine()
    customer_ids = [f"CUST-E2E-{i:04d}" for i in range(n_customers)]
    kinds = {cid: _kind_for(i) for i, cid in enumerate(customer_ids)}

    # Langkah 1-4: data pelanggan -> skor AI -> evaluasi gerbang -> NBA (K-07)
    records: Dict[str, DecisionRecord] = {}
    for cid in customer_ids:
        record = _decide_for(engine, cid, kinds[cid])
        records[cid] = record
        audit.record(
            event_type="decision.evaluation",
            action="EVALUATE_NBA",
            entity_type="customer",
            entity_id=cid,
            status=(
                "SUCCESS" if record.selected_action_id != "NO_ACTION" else "SUPPRESSED"
            ),
            correlation_id=record.correlation_id,
            occurred_at=NOW,
            details={
                "decision_id": record.decision_id,
                "selected_action_id": record.selected_action_id,
                "no_action_reason": record.no_action_reason,
                "expected_value": record.expected_value,
            },
        )

    # Langkah 5: Nudge + persetujuan manusia (hanya aksi komersial dengan kanal pesan)
    drafts: Dict[str, NudgeDraft] = {}
    skipped: List[str] = []
    for cid, record in records.items():
        channel = record.channel_selected
        if record.selected_action_id == "NO_ACTION" or channel not in ("email", "push"):
            skipped.append(cid)
            continue
        draft = generate_nudge(
            cid,
            record.selected_action_id,
            channel,
            {
                "first_name": f"Pelanggan{cid[-4:]}",
                "preferred_branch": "Yogyakarta",
                "offer_validity": "30-11-2026",
            },
        )
        if draft.status != STATUS_GENERATED_DRAFT:
            skipped.append(cid)
            continue
        approved = approve_draft(draft, "business-approver-01")
        drafts[cid] = approved
        audit.record(
            event_type="nudge.approval",
            action="APPROVE_NUDGE",
            entity_type="customer",
            entity_id=cid,
            status="SUCCESS",
            correlation_id=record.correlation_id,
            occurred_at=NOW + timedelta(hours=1),
            details={
                "action_id": approved.action_id,
                "channel": approved.channel,
                "approved_by": approved.approved_by,
                "draft_status": approved.status,
            },
        )

    # Langkah 6: Holdout 10% + Channel Simulator (offline)
    target_ids = sorted(drafts)
    split = split_from_campaign(CAMPAIGN, target_ids)
    sim = ChannelSimulator()
    sim.register_campaign(split)
    for cid in target_ids:
        delivery = sim.send(
            drafts[cid],
            campaign_id=CAMPAIGN_ID,
            correlation_id=records[cid].correlation_id,
            sent_at=SENT_AT,
        )
        audit.record(
            event_type="delivery.simulated",
            action="SIMULATE_SEND",
            entity_type="customer",
            entity_id=cid,
            status=(
                "SUCCESS" if delivery.status == STATUS_SIMULATED_SENT else "SUPPRESSED"
            ),
            correlation_id=records[cid].correlation_id,
            occurred_at=SENT_AT,
            details={
                "campaign_id": CAMPAIGN_ID,
                "delivery_id": delivery.delivery_id,
                "delivery_status": delivery.status,
                "group": delivery.group,
                "is_simulated": delivery.is_simulated,
                "exposure_recorded": delivery.exposure_recorded,
            },
        )

    # Langkah 7: perilaku sintetis (20% treatment vs 10% control membeli 3 hari kemudian)
    outcomes: List[Outcome] = []
    purchase_time = SENT_AT + timedelta(days=3)
    for idx, cid in enumerate(split.treatment_ids):
        if idx % TREATMENT_BUY_EVERY == 0:
            outcomes.append(
                Outcome(f"OT-{cid}", cid, "PURCHASE", purchase_time, ORDER_VALUE)
            )
    for idx, cid in enumerate(split.control_ids):
        if idx % CONTROL_BUY_EVERY == 0:
            outcomes.append(
                Outcome(f"OC-{cid}", cid, "PURCHASE", purchase_time, ORDER_VALUE)
            )

    # Langkah 8: Incremental Revenue (Treatment vs Control)
    uplift = compute_uplift(
        split,
        outcomes,
        window_from_campaign(CAMPAIGN),
        as_of=AS_OF_FINAL,
        exposed_customer_ids=sim.exposed_customer_ids(CAMPAIGN_ID),
    )
    audit.record(
        event_type="measurement.computed",
        action="COMPUTE_UPLIFT",
        entity_type="campaign",
        entity_id=CAMPAIGN_ID,
        status="SUCCESS",
        correlation_id=CAMPAIGN_CORRELATION_ID,
        occurred_at=AS_OF_FINAL,
        details={
            "campaign_id": CAMPAIGN_ID,
            "status": uplift.status,
            "incremental_revenue": uplift.incremental_revenue,
            "conversion_rate_lift_absolute": uplift.cr_absolute_lift,
        },
    )

    return FlowResult(
        customer_kinds=kinds,
        records=records,
        drafts=drafts,
        target_ids=target_ids,
        split=split,
        sim=sim,
        outcomes=outcomes,
        uplift=uplift,
        audit=audit,
        skipped_no_draft=skipped,
    )


@pytest.fixture(scope="module")
def flow() -> FlowResult:
    return run_flow()


def _ids_of(flow: FlowResult, kind: str) -> List[str]:
    return [cid for cid, k in flow.customer_kinds.items() if k == kind]


# ---------------------------------------------------------------------------
# 1. Keputusan NBA & kontrak K-07
# ---------------------------------------------------------------------------


class TestDecisionStage:
    def test_every_decision_conforms_to_k07(self, flow):
        validator = jsonschema.Draft7Validator(K07_SCHEMA)
        for record in flow.records.values():
            validator.validate(record.to_dict())

    def test_decision_mix_matches_profiles(self, flow):
        for cid in _ids_of(flow, KIND_OPT_OUT):
            rec = flow.records[cid]
            assert rec.selected_action_id == "NO_ACTION"
            assert rec.no_action_reason == "OPT_OUT_SUPPRESSED"
        for cid in _ids_of(flow, KIND_FATIGUED):
            rec = flow.records[cid]
            assert rec.selected_action_id == "NO_ACTION"
            assert rec.no_action_reason == "FREQ_CAP_SUPPRESSED"
        for cid in _ids_of(flow, KIND_SEVERE_COMPLAINT):
            assert flow.records[cid].selected_action_id == "COMPLAINT_RESOLUTION"
        for cid in _ids_of(flow, KIND_ELIGIBLE):
            rec = flow.records[cid]
            assert rec.selected_action_id == "RETENTION_OUTREACH"
            assert rec.expected_value > 0
            assert rec.channel_selected == "email"

    def test_high_score_is_not_permission(self, flow):
        """Skor churn 0.92 untuk semua; hanya profil ELIGIBLE yang boleh dikirimi pesan."""
        blocked = (
            _ids_of(flow, KIND_OPT_OUT)
            + _ids_of(flow, KIND_FATIGUED)
            + _ids_of(flow, KIND_SEVERE_COMPLAINT)
        )
        assert blocked, "skenario harus punya pelanggan terblokir"
        for cid in blocked:
            assert flow.records[cid].scores_snapshot["churn_score"] == pytest.approx(
                0.92
            )
            assert cid not in flow.drafts
            assert flow.sim.has_exposure(cid) is False

    def test_severe_complaint_never_receives_promotion(self, flow):
        for cid in _ids_of(flow, KIND_SEVERE_COMPLAINT):
            assert flow.records[cid].selected_action_id == "COMPLAINT_RESOLUTION"
            assert cid not in flow.drafts

    def test_degraded_input_is_flagged_not_hidden(self):
        record = NBAEngine().decide(
            customer_id="CUST-DEG",
            ai_scores=None,
            consent=CustomerConsent("CUST-DEG"),
            complaint_tickets=[],
            contact_history=[],
            eligibility=EligibilityProfile("CUST-DEG", 400, 20, True),
            product_suitability=ProductSuitability(),
            evaluation_date=NOW,
            correlation_id="corr-e2e-deg",
        )
        assert record.degraded_input is True
        assert record.selected_action_id == "NO_ACTION"
        jsonschema.Draft7Validator(K07_SCHEMA).validate(record.to_dict())


# ---------------------------------------------------------------------------
# 2. Nudge, Human Approval, Channel Simulator, Holdout
# ---------------------------------------------------------------------------


class TestActivationStage:
    def test_all_eligible_customers_get_approved_draft(self, flow):
        eligible = _ids_of(flow, KIND_ELIGIBLE)
        assert sorted(flow.drafts) == sorted(eligible)
        assert all(d.is_releasable for d in flow.drafts.values())
        assert all(d.status == STATUS_GENERATED_DRAFT for d in flow.drafts.values())

    def test_holdout_is_roughly_ten_percent_and_deterministic(self, flow):
        assert flow.split.n_total == len(flow.target_ids)
        assert 0.06 <= flow.split.actual_control_ratio <= 0.14
        again = split_from_campaign(CAMPAIGN, flow.target_ids)
        assert again.control_ids == flow.split.control_ids

    def test_control_group_has_zero_exposure(self, flow):
        assert flow.split.n_control > 0
        assert flow.sim.verify_control_isolation(CAMPAIGN_ID)
        assert all(flow.sim.has_exposure(c) is False for c in flow.split.control_ids)
        assert (
            flow.sim.exposure_count(campaign_id=CAMPAIGN_ID) == flow.split.n_treatment
        )

    def test_control_attempts_are_logged_as_skipped(self, flow):
        skipped = [
            a for a in flow.sim.attempts if a.customer_id in set(flow.split.control_ids)
        ]
        assert len(skipped) == flow.split.n_control
        assert all(a.status == STATUS_SKIPPED_CONTROL for a in skipped)

    def test_all_deliveries_are_simulated_and_offline(self, flow):
        assert flow.sim.attempts
        assert all(a.is_simulated for a in flow.sim.attempts)
        assert all(not a.external_delivery for a in flow.sim.attempts)

    def test_unapproved_or_blocked_draft_is_never_exposed(self, flow):
        treatment_id = flow.split.treatment_ids[0]
        sim = ChannelSimulator()
        sim.register_campaign(flow.split)

        facts = {
            "first_name": "Budi",
            "preferred_branch": "Yogyakarta",
            "offer_validity": "30-11-2026",
        }
        unapproved = generate_nudge(treatment_id, "RETENTION_OUTREACH", "email", facts)
        assert unapproved.status == STATUS_GENERATED_DRAFT
        rejected = sim.send(unapproved, campaign_id=CAMPAIGN_ID, sent_at=SENT_AT)
        assert rejected.status == STATUS_REJECTED_NOT_APPROVED
        assert rejected.exposure_recorded is False

        blocked = generate_nudge(
            treatment_id,
            "RETENTION_OUTREACH",
            "email",
            {**facts, "first_name": "Budi dijamin sembuh 100%"},
        )
        assert blocked.status == STATUS_BLOCKED_BY_GUARDRAIL
        with pytest.raises(ValueError):
            approve_draft(blocked, "business-approver-01")
        rejected_blocked = sim.send(blocked, campaign_id=CAMPAIGN_ID, sent_at=SENT_AT)
        assert rejected_blocked.exposure_recorded is False
        assert sim.exposure_count(campaign_id=CAMPAIGN_ID) == 0


# ---------------------------------------------------------------------------
# 3. Pengukuran Incremental Revenue
# ---------------------------------------------------------------------------


class TestMeasurementStage:
    def test_uplift_matches_independent_formula(self, flow):
        t_rev = ORDER_VALUE * sum(
            1 for o in flow.outcomes if flow.split.is_treatment(o.customer_id)
        )
        c_rev = ORDER_VALUE * sum(
            1 for o in flow.outcomes if flow.split.is_control(o.customer_id)
        )
        expected = t_rev - c_rev * (flow.split.n_treatment / flow.split.n_control)
        assert flow.uplift.is_final
        assert flow.uplift.treatment.revenue == t_rev
        assert flow.uplift.control.revenue == c_rev
        assert flow.uplift.incremental_revenue == pytest.approx(expected)
        assert flow.uplift.incremental_revenue == pytest.approx(
            incremental_revenue(
                t_rev, c_rev, flow.split.n_treatment, flow.split.n_control
            )
        )
        assert flow.uplift.incremental_revenue > 0
        assert flow.uplift.cr_absolute_lift > 0

    def test_observed_is_not_reported_as_incremental(self, flow):
        report = flow.uplift.to_dict()
        observed = report["observed_conversion"]["treatment_revenue"]
        incremental = report["incremental_conversion"]["incremental_revenue"]
        assert observed > incremental > 0
        assert "observed_conversion" in report and "incremental_conversion" in report

    def test_control_exposure_is_zero_in_measurement(self, flow):
        assert flow.uplift.control_exposed_count == 0
        assert flow.uplift.exposed_treatment_count == flow.split.n_treatment

    def test_provisional_before_finalization(self, flow):
        early = compute_uplift(
            flow.split,
            flow.outcomes,
            window_from_campaign(CAMPAIGN),
            as_of=datetime(2026, 11, 20),
        )
        assert not early.is_final


# ---------------------------------------------------------------------------
# 4. Audit Trace (K-11) & rekonstruksi < 5 menit
# ---------------------------------------------------------------------------

MAX_RECONSTRUCTION_SECONDS = 5 * 60


class TestAuditTrace:
    def test_every_audit_event_conforms_to_k11(self, flow):
        validator = jsonschema.Draft7Validator(K11_SCHEMA)
        assert flow.audit.events
        for event in flow.audit.events:
            validator.validate(event)
            assert event["X-Correlation-ID"] == event["correlation_id"]

    def test_treatment_customer_chain_is_complete_and_ordered(self, flow):
        cid = flow.split.treatment_ids[0]
        chain = reconstruct_chain(flow.audit, cid)
        assert [e["event_type"] for e in chain] == [
            "decision.evaluation",
            "nudge.approval",
            "delivery.simulated",
            "measurement.computed",
        ]
        assert chain[0]["details"]["decision_id"] == f"DEC-E2E-{cid}"
        assert chain[2]["details"]["exposure_recorded"] is True
        assert chain[2]["details"]["is_simulated"] is True
        assert chain[3]["details"]["campaign_id"] == CAMPAIGN_ID

    def test_control_customer_chain_shows_no_exposure(self, flow):
        cid = flow.split.control_ids[0]
        chain = reconstruct_chain(flow.audit, cid)
        delivery = next(e for e in chain if e["event_type"] == "delivery.simulated")
        assert delivery["status"] == "SUPPRESSED"
        assert delivery["details"]["delivery_status"] == STATUS_SKIPPED_CONTROL
        assert delivery["details"]["exposure_recorded"] is False

    def test_blocked_customer_chain_stops_at_decision(self, flow):
        cid = _ids_of(flow, KIND_OPT_OUT)[0]
        chain = reconstruct_chain(flow.audit, cid)
        assert [e["event_type"] for e in chain] == ["decision.evaluation"]
        assert chain[0]["status"] == "SUPPRESSED"
        assert chain[0]["details"]["no_action_reason"] == "OPT_OUT_SUPPRESSED"

    def test_reconstruction_is_under_five_minutes(self, flow):
        started = time.perf_counter()
        chain = reconstruct_chain(flow.audit, flow.split.treatment_ids[0])
        elapsed = time.perf_counter() - started
        assert len(chain) == 4
        assert elapsed < MAX_RECONSTRUCTION_SECONDS

    def test_reconstruct_every_customer_under_five_minutes(self, flow):
        started = time.perf_counter()
        for cid in flow.customer_kinds:
            assert reconstruct_chain(flow.audit, cid), cid
        elapsed = time.perf_counter() - started
        assert elapsed < MAX_RECONSTRUCTION_SECONDS

    def test_correlation_ids_are_unique_per_customer(self, flow):
        ids = {r.correlation_id for r in flow.records.values()}
        assert len(ids) == len(flow.records)


# ---------------------------------------------------------------------------
# 5. Determinisme & larangan jaringan (NFR-10 / T-SEC-03)
# ---------------------------------------------------------------------------


class TestDeterminismAndOffline:
    def test_flow_is_deterministic(self, flow):
        again = run_flow()
        assert {c: r.selected_action_id for c, r in again.records.items()} == {
            c: r.selected_action_id for c, r in flow.records.items()
        }
        assert again.split.control_ids == flow.split.control_ids
        assert again.uplift.incremental_revenue == flow.uplift.incremental_revenue
        assert len(again.audit.events) == len(flow.audit.events)

    def test_flow_runs_with_network_disabled(self, monkeypatch):
        def _blocked(*_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("Akses jaringan terdeteksi saat flow berjalan!")

        monkeypatch.setattr(socket.socket, "connect", _blocked)
        monkeypatch.setattr(socket, "getaddrinfo", _blocked)
        result = run_flow(n_customers=200)
        assert result.sim.verify_control_isolation(CAMPAIGN_ID)
        assert result.uplift.is_final

    def test_small_audience_without_control_is_handled(self):
        """Audiens sangat kecil bisa menghasilkan 0 anggota control; harus gagal jelas."""
        tiny = split_from_campaign(CAMPAIGN, ["CUST-A", "CUST-B"])
        if tiny.has_control_group:
            pytest.skip("seed ini kebetulan menghasilkan control group")
        with pytest.raises(ValueError):
            compute_uplift(
                tiny,
                [],
                window_from_campaign(CAMPAIGN),
                as_of=AS_OF_FINAL,
            )
