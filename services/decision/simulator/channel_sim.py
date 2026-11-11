"""
channel_sim.py — Channel Simulator Internal (Minggu 9)
======================================================
Menyimulasikan pengiriman Email, Push Notification, dan SMS TANPA panggilan jaringan apa pun
(NFR-10 / T-SEC-03). Modul ini tidak mengimpor socket, http, urllib, requests, smtplib, dll.;
"pengiriman" hanyalah pencatatan rekaman di memori.

Setiap rekaman selalu `is_simulated=True`, `external_delivery=False`, `delivery_mode="simulated"`
(selaras dengan `worker/tasks.py: campaign_execution`).

Aturan pengiriman (diperiksa berurutan di `ChannelSimulator.send`):
  1. Kampanye harus terdaftar bersama `HoldoutSplit`-nya (`register_campaign`).
  2. Pelanggan bukan bagian audiens           -> REJECTED_NOT_IN_AUDIENCE
  3. Pelanggan anggota CONTROL                -> SKIPPED_CONTROL_HOLDOUT (zero exposure)
  4. Kanal bukan email/push/sms               -> REJECTED_UNSUPPORTED_CHANNEL
  5. Draf belum disetujui manusia / diblokir  -> REJECTED_NOT_APPROVED
  6. Selain itu                               -> SIMULATED_SENT (tercatat sebagai exposure)

Pemeriksaan control (langkah 3) sengaja dilakukan SEBELUM pemeriksaan lain, sehingga anggota
control tidak pernah menghasilkan exposure apa pun, apa pun status drafnya.

Penyimpanan bersifat in-memory per instance. Persistensi ke database (jika diperlukan)
dilakukan pemanggil (James) lewat `exposure_events()`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from services.decision.campaign.holdout import (
    GROUP_CONTROL,
    HoldoutSplit,
)
from services.decision.nudge.generator import NudgeDraft
from services.decision.timeutil import to_naive_utc, utc_now

# ---------------------------------------------------------------------------
# Konstanta
# ---------------------------------------------------------------------------

DELIVERY_MODE = "simulated"
SUPPORTED_CHANNELS: Tuple[str, ...] = ("email", "push", "sms")

CHANNEL_ALIASES: Dict[str, str] = {
    "email_sim": "email",
    "push_sim": "push",
    "sms_sim": "sms",
    "push_notification": "push",
}
"""Nama kanal lain (K-08 `*_sim`, katalog DB `PUSH_NOTIFICATION`) -> kanal kanonik."""

STATUS_SIMULATED_SENT = "SIMULATED_SENT"
STATUS_SKIPPED_CONTROL = "SKIPPED_CONTROL_HOLDOUT"
STATUS_REJECTED_NOT_APPROVED = "REJECTED_NOT_APPROVED"
STATUS_REJECTED_UNSUPPORTED_CHANNEL = "REJECTED_UNSUPPORTED_CHANNEL"
STATUS_REJECTED_NOT_IN_AUDIENCE = "REJECTED_NOT_IN_AUDIENCE"

_CORRELATION_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class UnregisteredCampaignError(ValueError):
    """Kampanye belum didaftarkan dengan HoldoutSplit; pengiriman ditolak."""


def normalize_channel(channel: str) -> str:
    """Huruf kecil + alias -> kanal kanonik (belum tentu didukung)."""
    key = str(channel).strip().lower()
    return CHANNEL_ALIASES.get(key, key)


# ---------------------------------------------------------------------------
# Rekaman
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SimulatedDelivery:
    """Satu percobaan pengiriman tersimulasi."""

    delivery_id: str
    campaign_id: str
    customer_id: str
    action_id: str
    channel: str
    status: str
    group: Optional[str]
    attempted_at: datetime
    correlation_id: str
    exposure_recorded: bool
    reason: str = ""
    body: str = ""
    approved_by: Optional[str] = None
    is_simulated: bool = field(default=True, init=False)
    external_delivery: bool = field(default=False, init=False)
    delivery_mode: str = field(default=DELIVERY_MODE, init=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "delivery_id": self.delivery_id,
            "campaign_id": self.campaign_id,
            "customer_id": self.customer_id,
            "action_id": self.action_id,
            "channel": self.channel,
            "status": self.status,
            "group": self.group,
            "attempted_at": self.attempted_at.isoformat(),
            "correlation_id": self.correlation_id,
            "exposure_recorded": self.exposure_recorded,
            "reason": self.reason,
            "approved_by": self.approved_by,
            "is_simulated": self.is_simulated,
            "external_delivery": self.external_delivery,
            "delivery_mode": self.delivery_mode,
        }


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------


class ChannelSimulator:
    """Simulator pengiriman pesan 100% offline."""

    def __init__(self, clock: Optional[Callable[[], datetime]] = None) -> None:
        self._clock: Callable[[], datetime] = clock or utc_now
        self._splits: Dict[str, HoldoutSplit] = {}
        self._attempts: List[SimulatedDelivery] = []
        self._counter = 0

    # -- pendaftaran kampanye ------------------------------------------------

    def register_campaign(self, split: HoldoutSplit) -> None:
        """
        Mendaftarkan kampanye beserta pembagian grupnya.

        Mendaftar ulang dengan split BERBEDA ditolak, agar anggota control tidak dapat
        "ditukar" di tengah kampanye.
        """
        if not split.campaign_id:
            raise ValueError("HoldoutSplit harus memiliki campaign_id.")
        existing = self._splits.get(split.campaign_id)
        if existing is not None and existing != split:
            raise ValueError(
                f"Kampanye {split.campaign_id} sudah terdaftar dengan pembagian grup berbeda."
            )
        self._splits[split.campaign_id] = split

    # -- pengiriman ----------------------------------------------------------

    def send(
        self,
        draft: NudgeDraft,
        *,
        campaign_id: str,
        correlation_id: Optional[str] = None,
        sent_at: Optional[datetime] = None,
    ) -> SimulatedDelivery:
        """Menyimulasikan pengiriman satu draf. Lihat aturan di docstring modul."""
        split = self._splits.get(campaign_id)
        if split is None:
            raise UnregisteredCampaignError(
                f"Kampanye {campaign_id} belum didaftarkan (register_campaign)."
            )
        if correlation_id is not None and not _CORRELATION_ID_RE.match(correlation_id):
            raise ValueError("correlation_id tidak sesuai pola K-11 / K-07.")

        self._counter += 1
        delivery_id = f"SIM-{self._counter:08d}"
        corr = correlation_id or delivery_id
        when = to_naive_utc(sent_at) if sent_at is not None else self._clock()
        group = split.group_of(draft.customer_id)
        channel = normalize_channel(draft.channel)

        def make(status: str, reason: str, exposure: bool) -> SimulatedDelivery:
            record = SimulatedDelivery(
                delivery_id=delivery_id,
                campaign_id=campaign_id,
                customer_id=draft.customer_id,
                action_id=draft.action_id,
                channel=channel,
                status=status,
                group=group,
                attempted_at=when,
                correlation_id=corr,
                exposure_recorded=exposure,
                reason=reason,
                body=draft.body if exposure else "",
                approved_by=draft.approved_by if exposure else None,
            )
            self._attempts.append(record)
            return record

        if group is None:
            return make(
                STATUS_REJECTED_NOT_IN_AUDIENCE,
                "Pelanggan bukan bagian audiens kampanye.",
                False,
            )
        if group == GROUP_CONTROL:
            return make(
                STATUS_SKIPPED_CONTROL,
                "Anggota Holdout Control Group tidak boleh menerima paparan.",
                False,
            )
        if channel not in SUPPORTED_CHANNELS:
            return make(
                STATUS_REJECTED_UNSUPPORTED_CHANNEL,
                f"Kanal '{draft.channel}' tidak didukung simulator.",
                False,
            )
        if not draft.is_releasable:
            return make(
                STATUS_REJECTED_NOT_APPROVED,
                f"Draf berstatus {draft.status} dan/atau belum disetujui manusia.",
                False,
            )
        return make(STATUS_SIMULATED_SENT, "", True)

    def send_batch(
        self, drafts: Iterable[NudgeDraft], *, campaign_id: str
    ) -> List[SimulatedDelivery]:
        return [self.send(d, campaign_id=campaign_id) for d in drafts]

    # -- kueri ---------------------------------------------------------------

    @property
    def attempts(self) -> Tuple[SimulatedDelivery, ...]:
        """Seluruh percobaan (terkirim maupun ditolak/dilewati)."""
        return tuple(self._attempts)

    @property
    def exposures(self) -> Tuple[SimulatedDelivery, ...]:
        """Hanya percobaan yang benar-benar tercatat sebagai paparan."""
        return tuple(a for a in self._attempts if a.exposure_recorded)

    def exposure_count(
        self, customer_id: Optional[str] = None, campaign_id: Optional[str] = None
    ) -> int:
        return sum(
            1
            for a in self._attempts
            if a.exposure_recorded
            and (customer_id is None or a.customer_id == customer_id)
            and (campaign_id is None or a.campaign_id == campaign_id)
        )

    def has_exposure(self, customer_id: str) -> bool:
        return self.exposure_count(customer_id=customer_id) > 0

    def exposed_customer_ids(self, campaign_id: str) -> List[str]:
        seen: Dict[str, None] = {}
        for a in self._attempts:
            if a.exposure_recorded and a.campaign_id == campaign_id:
                seen.setdefault(a.customer_id, None)
        return list(seen)

    def control_exposure_count(self, campaign_id: str) -> int:
        """Jumlah paparan yang diterima anggota control. HARUS selalu 0."""
        split = self._splits.get(campaign_id)
        if split is None:
            raise UnregisteredCampaignError(f"Kampanye {campaign_id} belum terdaftar.")
        return sum(
            1
            for a in self._attempts
            if a.exposure_recorded
            and a.campaign_id == campaign_id
            and split.is_control(a.customer_id)
        )

    def verify_control_isolation(self, campaign_id: str) -> bool:
        """True bila Control Group memiliki 0 rekaman paparan."""
        return self.control_exposure_count(campaign_id) == 0

    def exposure_events(
        self, campaign_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Rekaman paparan sebagai dict (untuk atribusi / persistensi oleh pemanggil)."""
        return [
            a.to_dict()
            for a in self._attempts
            if a.exposure_recorded
            and (campaign_id is None or a.campaign_id == campaign_id)
        ]
