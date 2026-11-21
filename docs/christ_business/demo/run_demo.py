"""
run_demo.py — Demo Closed-Loop Decisioning (milik Christ / Orang 2)
===================================================================
Menjalankan alur: skor model -> NBA -> alasan bahasa sederhana -> campaign simulasi
(holdout 10%) -> pengukuran Incremental Revenue.

PENTING (arahan mentor): "jangan pernah nampilin angka contoh seolah hasil asli".
Seluruh pelanggan, skor, dan hasil konversi di skrip ini 100% SINTETIS dan dicetak
dengan label itu di setiap bagian. Skrip ini tidak membaca/menulis database dan tidak
memakai jaringan. Untuk demo di aplikasi (data nyata dari database) pakai alur
`api/` + `worker/` yang dijelaskan di docs/christ_business/integration/.

Jalankan dari root repo:
    PYTHONPATH=. python docs/christ_business/demo/run_demo.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, TextIO

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.decision.campaign.pipeline import (  # noqa: E402
    AudienceMember,
    CampaignRunResult,
    run_campaign,
)
from services.decision.nba.engine import (  # noqa: E402
    EligibilityProfile,
    ProductSuitability,
)
from services.decision.nba.serving import evaluate_customer  # noqa: E402
from services.decision.policy.fatigue import ContactRecord  # noqa: E402
from services.decision.policy.suppression import (  # noqa: E402
    ComplaintStatus,
    ComplaintTicket,
)

SYNTHETIC_LABEL = "DATA SINTETIS UNTUK DEMO - BUKAN HASIL NYATA"
NOW = datetime(2026, 11, 20, 10, 0, 0)
SENT_AT = datetime(2026, 11, 21, 9, 0, 0)
AS_OF = datetime(2027, 2, 1)
CAMPAIGN: Dict[str, Any] = {
    "campaign_id": "CMP-DEMO-1",
    "channel": "email_sim",
    "approved_by": "demo-business-approver",
    "random_seed": 20261120,
    "conversion_window_days": 30,
    "adjustment_window_days": 14,
    "exposure_window": {
        "start_time": "2026-11-21T00:00:00Z",
        "end_time": "2026-11-28T00:00:00Z",
    },
}
FACTS = {
    "first_name": "Demo",
    "preferred_branch": "Yogyakarta",
    "offer_validity": "30-12-2026",
}


def _rp(amount: float) -> str:
    return "Rp " + f"{amount:,.0f}".replace(",", ".")


def _consent(ref: str, *, opt_out: bool = False) -> Dict[str, Any]:
    on = not opt_out
    channel = {
        "status": "OPT_IN" if on else "OPT_OUT",
        "opt_in": on,
        "effective_permission": "ALLOWED" if on else "BLOCKED",
    }
    return {
        "customer_id": ref,
        "global_consent": {
            "status": "OPT_OUT" if opt_out else "OPT_IN",
            "is_global_opt_out": opt_out,
        },
        "channels": {"email": channel, "push": channel},
        "unknown_expired_policy": "BLOCKED",
        "identity_merge_policy": "MOST_RESTRICTIVE_WINS",
        "most_restrictive_wins": True,
    }


def _score_row(ref: str, *, reviewed: bool = True) -> Dict[str, Any]:
    return {
        "customer_id": ref,
        "churn_score": 0.92,
        "churn_risk_band": "VERY_HIGH",
        "propensity_purchase": 0.6,
        "propensity_renew": 0.5,
        "clv_amount": 3_000_000.0,
        "clv_tier": "GOLD",
        "lifecycle_stage": "AT_RISK",
        "score_generated_at": (NOW - timedelta(days=1)).isoformat(),
        "reason_codes": ["PURCHASE_FREQUENCY_90D", "RETAINED_REVENUE_365D"],
        "model_version": "demo-model-0.0",
        "review_status": "reviewed" if reviewed else "pending_review",
        "reviewed_by": 7,
        "submitted_by": 3,
    }


def _member(ref: str, kind: str) -> AudienceMember:
    complaints: List[ComplaintTicket] = []
    contacts: List[ContactRecord] = []
    consent = _consent(ref, opt_out=(kind == "opt_out"))
    if kind == "complaint":
        complaints = [
            ComplaintTicket(
                f"T-{ref}",
                ref,
                ComplaintStatus.OPEN_SEVERE,
                "SEVERE",
                NOW - timedelta(days=1),
            )
        ]
    if kind == "fatigue":
        contacts = [
            ContactRecord(ref, "CROSS_SELL", "email", NOW - timedelta(days=d))
            for d in (1, 6)
        ]
    decision = evaluate_customer(
        customer_ref=ref,
        correlation_id=f"corr-demo-{ref}",
        score_row=_score_row(ref, reviewed=(kind != "unreviewed")),
        consent_doc=consent,
        complaint_tickets=complaints,
        contact_history=contacts,
        eligibility=EligibilityProfile(
            customer_id=ref,
            tenure_days=400,
            membership_days_remaining=20,
            has_active_membership=True,
            purchased_categories=["GROCERY"],
            days_until_replenishment=3,
        ),
        product_suitability=ProductSuitability(),
        evaluation_date=NOW,
    )
    return AudienceMember(ref, decision, consent, FACTS)


def _outcomes(result: CampaignRunResult) -> List[Dict[str, Any]]:
    """Konversi SINTETIS: 20% treatment dan 10% control berbelanja Rp 100.000."""
    assert result.split is not None
    rows: List[Dict[str, Any]] = []
    for group, ids, every in (
        ("T", result.split.treatment_ids, 5),
        ("C", result.split.control_ids, 10),
    ):
        for idx, cid in enumerate(ids):
            if idx % every == 0:
                rows.append(
                    {
                        "outcome_id": f"O-{group}-{idx}",
                        "customer_id": cid,
                        "conversion_type": "PURCHASE",
                        "gross_revenue": 100_000,
                        "occurred_at": (SENT_AT + timedelta(days=3)).isoformat(),
                    }
                )
    return rows


def main(out: Optional[TextIO] = None) -> CampaignRunResult:
    out = out or sys.stdout

    def say(text: str = "") -> None:
        print(text, file=out)

    say("=" * 72)
    say(f"  {SYNTHETIC_LABEL}")
    say("=" * 72)

    say("\n[1] Keputusan NBA untuk 5 profil pelanggan (sintetis)")
    profiles = [
        ("DEMO-A", "eligible", "Skor tinggi, semua izin lengkap"),
        ("DEMO-B", "opt_out", "Skor tinggi, pelanggan menolak dihubungi"),
        ("DEMO-C", "complaint", "Skor tinggi, ada keluhan berat terbuka"),
        ("DEMO-D", "fatigue", "Skor tinggi, sudah 2 pesan dalam 14 hari"),
        ("DEMO-E", "unreviewed", "Skor model belum diperiksa orang lain"),
    ]
    for ref, kind, note in profiles:
        member = _member(ref, kind)
        say(f"\n  {ref} - {note}")
        say(f"    Keputusan : {member.decision.selected_action_id}")
        say(f"    Alasan    : {member.decision.plain_rationale}")

    say("\n[2] Campaign simulasi (400 pelanggan sintetis, holdout 10%)")
    kinds = ["opt_out", "complaint", "fatigue"] + ["eligible"] * 7
    audience = [_member(f"DEMO-{i:04d}", kinds[i % 10]) for i in range(400)]
    result = run_campaign(
        campaign=CAMPAIGN,
        audience=audience,
        correlation_id="corr-demo-campaign",
        sent_at=SENT_AT,
    )
    say(f"    Audiens                 : {result.audience_size}")
    say(f"    Layak dikirimi pesan    : {result.targetable_count}")
    say(f"    Dilewati (diblokir NBA) : {len(result.skipped)}")
    say(f"    Treatment (terkirim sim): {result.sent_count}")
    say(f"    Holdout control         : {result.control_count}")
    say(f"    Paparan ke control      : {result.control_exposure_count} (harus 0)")
    say("    Mode pengiriman         : simulasi offline, tanpa pengiriman eksternal")
    say(f"    Status pengukuran       : {result.measurement_status}")
    say("    (belum ada hasil konversi -> angka lift TIDAK ditampilkan)")

    say("\n[3] Pengukuran setelah hasil konversi SINTETIS masuk")
    measured = run_campaign(
        campaign=CAMPAIGN,
        audience=audience,
        correlation_id="corr-demo-campaign",
        sent_at=SENT_AT,
        outcomes=_outcomes(result),
        as_of=AS_OF,
    )
    assert measured.measurement is not None
    inc = measured.measurement["incremental_conversion"]
    obs = measured.measurement["observed_conversion"]
    say(f"    [{SYNTHETIC_LABEL}]")
    say(f"    Status                         : {measured.measurement['status']}")
    say(f"    Observed revenue (treatment)   : {_rp(obs['treatment_revenue'])}")
    say(f"    Incremental revenue (vs control): {_rp(inc['incremental_revenue'])}")
    say(
        f"    Lift conversion rate (absolut) : {inc['conversion_rate_lift_absolute']:.3f}"
    )
    say("    Observed dan Incremental dilaporkan TERPISAH agar tidak menyesatkan.")

    say("\n[4] Jejak audit (X-Correlation-ID)")
    for event in measured.audit_events():
        say(f"    {event['event_type']:<18} corr={event['correlation_id']}")
    say(f"\n{SYNTHETIC_LABEL}")
    return measured


if __name__ == "__main__":
    main()
