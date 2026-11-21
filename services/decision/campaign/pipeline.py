"""
pipeline.py — Campaign yang benar-benar berjalan (fungsi MURNI)
===============================================================
Revisi mentor (Fase 4 lanjutan), bagian Christ: "campaign harus jalan beneran".

Sebelumnya `worker/tasks.py::campaign_execution` hanya menghitung ukuran audiens dan
membagi 50/50. Modul ini merangkai komponen yang sudah ada menjadi satu alur nyata:

    keputusan NBA tiap pelanggan (DecisionOutput)
      -> draf pesan dari fact package + Safety Scanner      (nudge/generator)
      -> persetujuan manusia (approved_by dari kampanye)    (nudge/generator)
      -> audiens yang BISA dihubungi dibagi Treatment/Holdout (campaign/holdout)
      -> pengiriman SIMULASI offline, control = 0 paparan   (simulator/channel_sim)
      -> Incremental Revenue bila hasil konversi tersedia    (measurement/uplift)

Batas arsitektur (arahan mentor): fungsi ini TIDAK membuka database/jaringan. Pemanggil
(`worker/` atau `api/`) yang membaca data, memanggil `run_campaign`, lalu menyimpan
`CampaignRunResult` ke database (hasil job, `msr.campaign_measurements`, audit trail).

Prinsip data kosong: bila hasil konversi belum ada, `measurement` = None dan
`measurement_status` = "AWAITING_OUTCOMES" (kosong ditulis kosong, tidak ada angka contoh).

Catatan metode: holdout diambil dari pelanggan yang SUDAH lolos NBA dan punya draf pesan
aman (populasi yang memang akan dikirimi). Pelanggan yang diblokir (opt-out, komplain,
fatigue, fakta kurang) tidak ikut grup mana pun, sehingga uplift tidak "diencerkan"
oleh orang yang memang tidak pernah akan dikirimi pesan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from services.decision.campaign.holdout import HoldoutSplit, split_from_campaign
from services.decision.measurement.uplift import (
    Outcome,
    UpliftResult,
    compute_uplift,
    window_from_campaign,
)
from services.decision.nba.serving import DecisionOutput
from services.decision.nudge.generator import (
    STATUS_GENERATED_DRAFT,
    NudgeDraft,
    approve_draft,
    generate_nudge,
)
from services.decision.policy.suppression import CustomerConsent, is_opted_out
from services.decision.simulator.channel_sim import (
    ChannelSimulator,
    SimulatedDelivery,
    normalize_channel,
)
from services.decision.timeutil import to_naive_utc, utc_now

# Aksi yang bukan pesan promosi otomatis (tidak punya templat / ditangani manusia).
NON_MESSAGE_ACTIONS = frozenset({"NO_ACTION", "COMPLAINT_RESOLUTION"})

STATUS_COMPLETED_SIMULATED = "COMPLETED_SIMULATED"
MEASUREMENT_AWAITING_OUTCOMES = "AWAITING_OUTCOMES"
MEASUREMENT_CONTROL_EMPTY = "CONTROL_GROUP_EMPTY"
MEASUREMENT_COMPUTED = "COMPUTED"

SKIP_NO_PROMO_DECISION = "NBA_NO_PROMOTION"
SKIP_CHANNEL_OPTED_OUT = "CHANNEL_NOT_CONSENTED"
SKIP_DRAFT_NOT_SAFE = "DRAFT_NOT_RELEASABLE"
SKIP_DUPLICATE = "DUPLICATE_CUSTOMER"

EVENT_CAMPAIGN_EXECUTED = "campaign.executed"
EVENT_CAMPAIGN_MEASURED = "campaign.measured"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AudienceMember:
    """Satu pelanggan dalam audiens: keputusan NBA-nya + data untuk membuat pesan."""

    customer_ref: str
    decision: DecisionOutput
    consent_doc: Mapping[str, Any]
    fact_package: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CampaignRunResult:
    campaign_id: str
    correlation_id: str
    status: str
    channel: str
    approved_by: str
    audience_size: int
    targetable_count: int
    treatment_count: int
    control_count: int
    sent_count: int
    control_exposure_count: int
    deliveries: tuple[Dict[str, Any], ...]
    skipped: tuple[Dict[str, Any], ...]
    contact_rows: tuple[Dict[str, Any], ...]
    measurement_status: str
    measurement: Optional[Dict[str, Any]]
    measurement_rows: tuple[Dict[str, Any], ...]
    split: Optional[HoldoutSplit] = None

    @property
    def control_isolated(self) -> bool:
        return self.control_exposure_count == 0

    def to_job_result(self) -> Dict[str, Any]:
        """
        Hasil untuk `act.batch_jobs.result` (kunci lama dipertahankan agar UI/API yang
        sudah ada tetap jalan, ditambah kunci baru untuk alur yang sebenarnya).
        """
        return {
            "delivery_mode": "simulated",
            "external_delivery": False,
            "channel": self.channel,
            "target_mode": "segment",
            "audience_size": self.audience_size,
            "variant_a_count": self.treatment_count,
            "variant_b_count": self.control_count,
            "customer_ids": [d["customer_id"] for d in self.deliveries],
            "campaign_id": self.campaign_id,
            "correlation_id": self.correlation_id,
            "status": self.status,
            "targetable_count": self.targetable_count,
            "sent_count": self.sent_count,
            "skipped_count": len(self.skipped),
            "control_exposure_count": self.control_exposure_count,
            "control_isolated": self.control_isolated,
            "approved_by": self.approved_by,
            "measurement_status": self.measurement_status,
            "deliveries": list(self.deliveries),
            "skipped": list(self.skipped),
        }

    def audit_events(self) -> List[Dict[str, Any]]:
        """Event audit (diteruskan ke `record_audit_event` oleh pemanggil)."""
        events = [
            {
                "event_type": EVENT_CAMPAIGN_EXECUTED,
                "correlation_id": self.correlation_id,
                "entity_type": "campaign",
                "entity_id": self.campaign_id,
                "details": {
                    "channel": self.channel,
                    "delivery_mode": "simulated",
                    "external_delivery": False,
                    "approved_by": self.approved_by,
                    "audience_size": self.audience_size,
                    "targetable_count": self.targetable_count,
                    "treatment_count": self.treatment_count,
                    "control_count": self.control_count,
                    "sent_count": self.sent_count,
                    "skipped_count": len(self.skipped),
                    "control_exposure_count": self.control_exposure_count,
                },
            }
        ]
        if self.measurement is not None:
            incremental = self.measurement["incremental_conversion"]
            events.append(
                {
                    "event_type": EVENT_CAMPAIGN_MEASURED,
                    "correlation_id": self.correlation_id,
                    "entity_type": "campaign",
                    "entity_id": self.campaign_id,
                    "details": {
                        "status": self.measurement["status"],
                        "revenue_basis": self.measurement["revenue_basis"],
                        "incremental_revenue": incremental["incremental_revenue"],
                        "conversion_rate_lift_absolute": incremental[
                            "conversion_rate_lift_absolute"
                        ],
                        "warnings": self.measurement["warnings"],
                    },
                }
            )
        return events


# ---------------------------------------------------------------------------
# Fungsi utama
# ---------------------------------------------------------------------------


def _skip(member: AudienceMember, reason: str, detail: str = "") -> Dict[str, Any]:
    return {
        "customer_id": member.customer_ref,
        "reason": reason,
        "detail": detail,
        "selected_action": member.decision.selected_action_id,
    }


def run_campaign(
    *,
    campaign: Mapping[str, Any],
    audience: Sequence[AudienceMember],
    correlation_id: str,
    outcomes: Optional[Sequence[Mapping[str, Any]]] = None,
    as_of: Optional[datetime] = None,
    sent_at: Optional[datetime] = None,
    clock: Optional[Callable[[], datetime]] = None,
) -> CampaignRunResult:
    """
    Menjalankan satu campaign simulasi dari ujung ke ujung.

    Args:
        campaign: metadata K-08 + field aplikasi. Wajib: `campaign_id` (str),
            `random_seed` (int), `channel` (mis. "email_sim"), `approved_by`
            (identitas manusia penyetuju; tanpa ini tidak ada pesan yang boleh keluar).
            Opsional: `control_holdout_ratio` / `ab_test_ratio`, `exposure_window`,
            `conversion_window_days`, `adjustment_window_days`.
        audience: pelanggan + keputusan NBA-nya (`AudienceMember`).
        correlation_id: X-Correlation-ID kampanye (pola K-11).
        outcomes: konversi bentuk K-09 (kosong/None = belum ada hasil).
        as_of: waktu pengukuran uplift (default sekarang).

    Raises:
        ValueError: `approved_by`/`channel` kosong, atau channel bukan simulator.
    """
    approved_by = campaign.get("approved_by")
    if not isinstance(approved_by, str) or not approved_by.strip():
        raise ValueError(
            "Campaign belum disetujui manusia (approved_by kosong); tidak ada pesan dikirim."
        )
    channel_raw = campaign.get("channel")
    if not isinstance(channel_raw, str) or not channel_raw.strip():
        raise ValueError("channel campaign wajib diisi.")
    if not channel_raw.lower().endswith("_sim"):
        raise ValueError("Hanya kanal simulator (*_sim) yang boleh dipakai (NFR-10).")
    channel = normalize_channel(channel_raw)
    campaign_id = str(campaign.get("campaign_id") or "").strip()
    if not campaign_id:
        raise ValueError("campaign_id wajib diisi (K-08).")

    # 1) Draf pesan per pelanggan (duplikat dibuang; pelanggan yang tak layak dicatat).
    skipped: List[Dict[str, Any]] = []
    drafts: Dict[str, NudgeDraft] = {}
    seen: set[str] = set()
    for member in audience:
        if member.customer_ref in seen:
            skipped.append(_skip(member, SKIP_DUPLICATE))
            continue
        seen.add(member.customer_ref)
        action_id = member.decision.selected_action_id
        if action_id in NON_MESSAGE_ACTIONS or member.decision.record is None:
            skipped.append(
                _skip(member, SKIP_NO_PROMO_DECISION, member.decision.plain_rationale)
            )
            continue
        consent = CustomerConsent.from_k10(member.consent_doc, now=sent_at)
        if is_opted_out(consent, channel):
            skipped.append(_skip(member, SKIP_CHANNEL_OPTED_OUT, channel))
            continue
        draft = generate_nudge(
            member.customer_ref, action_id, channel, member.fact_package
        )
        if draft.status != STATUS_GENERATED_DRAFT:
            skipped.append(_skip(member, SKIP_DRAFT_NOT_SAFE, draft.status))
            continue
        drafts[member.customer_ref] = approve_draft(draft, approved_by.strip())

    # 2) Pembagian Treatment/Holdout hanya untuk pelanggan yang akan dikirimi pesan.
    targetable_ids = list(drafts)
    split: Optional[HoldoutSplit] = None
    sim = ChannelSimulator(clock=clock)
    deliveries: List[SimulatedDelivery] = []
    if targetable_ids:
        # Holdout selalu 10% (K-08) kecuali `control_holdout_ratio` diisi eksplisit.
        # `ab_test_ratio` aplikasi (rasio varian A/B) sengaja TIDAK dipakai sebagai
        # ukuran control, agar kampanye tidak menahan 50% pelanggan tanpa sengaja.
        split_meta = {k: v for k, v in campaign.items() if k != "ab_test_ratio"}
        split_meta["campaign_id"] = campaign_id
        split = split_from_campaign(split_meta, targetable_ids)
        sim.register_campaign(split)
        for customer_ref in targetable_ids:
            deliveries.append(
                sim.send(
                    drafts[customer_ref],
                    campaign_id=split.campaign_id,
                    correlation_id=correlation_id,
                    sent_at=sent_at,
                )
            )

    sent = [d for d in deliveries if d.exposure_recorded]
    control_exposure = sim.control_exposure_count(campaign_id) if split else 0
    contact_rows = tuple(
        {
            "customer_id": d.customer_id,
            "action_id": d.action_id,
            "channel": d.channel,
            "sent_at": d.attempted_at.isoformat(),
            "is_commercial": True,
        }
        for d in sent
    )

    # 3) Pengukuran uplift: hanya bila ada split, grup control terisi, dan hasil tersedia.
    measurement_status = MEASUREMENT_AWAITING_OUTCOMES
    uplift: Optional[UpliftResult] = None
    if split is not None and not outcomes:
        measurement_status = MEASUREMENT_AWAITING_OUTCOMES
    elif split is not None and outcomes:
        if split.n_control == 0 or split.n_treatment == 0:
            measurement_status = MEASUREMENT_CONTROL_EMPTY
        else:
            uplift = compute_uplift(
                split,
                [Outcome.from_k09(record) for record in outcomes],
                window_from_campaign(campaign),
                as_of=to_naive_utc(as_of) if as_of is not None else utc_now(),
                exposed_customer_ids=sim.exposed_customer_ids(campaign_id),
            )
            measurement_status = MEASUREMENT_COMPUTED

    return CampaignRunResult(
        campaign_id=campaign_id,
        correlation_id=correlation_id,
        status=STATUS_COMPLETED_SIMULATED,
        channel=channel,
        approved_by=approved_by.strip(),
        audience_size=len(seen),
        targetable_count=len(targetable_ids),
        treatment_count=split.n_treatment if split else 0,
        control_count=split.n_control if split else 0,
        sent_count=len(sent),
        control_exposure_count=control_exposure,
        deliveries=tuple(d.to_dict() for d in deliveries),
        skipped=tuple(skipped),
        contact_rows=contact_rows,
        measurement_status=measurement_status,
        measurement=uplift.to_dict() if uplift is not None else None,
        measurement_rows=tuple(uplift.measurement_rows()) if uplift is not None else (),
        split=split,
    )
