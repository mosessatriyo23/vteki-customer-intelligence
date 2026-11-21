"""
test_campaign_pipeline.py — Revisi mentor: "campaign harus jalan beneran".

Yang dibuktikan:
  1. Alur nyata: keputusan NBA -> draf pesan -> persetujuan manusia -> holdout ->
     simulator -> uplift, bukan sekadar menghitung ukuran audiens.
  2. Tanpa `approved_by` manusia, tidak ada pesan keluar. Hanya kanal simulator (*_sim).
  3. Holdout Control = 0 paparan; pelanggan yang diblokir (opt-out, komplain, fatigue,
     kanal tanpa consent, fakta kurang) TIDAK pernah menerima pesan.
  4. Incremental Revenue sama dengan rumus independen.
  5. Hasil konversi kosong => pengukuran ditulis kosong (AWAITING_OUTCOMES), bukan angka.
  6. Campaign deterministik dan 100% offline.

Data pelanggan di file ini 100% sintetis dan hanya dipakai untuk test.

Jalankan: python -m pytest tests/decision/test_campaign_pipeline.py -v
"""

from __future__ import annotations

import socket
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pytest

from services.decision.campaign.pipeline import (
    MEASUREMENT_AWAITING_OUTCOMES,
    MEASUREMENT_COMPUTED,
    SKIP_CHANNEL_OPTED_OUT,
    SKIP_DRAFT_NOT_SAFE,
    SKIP_NO_PROMO_DECISION,
    AudienceMember,
    CampaignRunResult,
    run_campaign,
)
from services.decision.nba.engine import EligibilityProfile, ProductSuitability
from services.decision.nba.serving import evaluate_customer
from services.decision.policy.fatigue import ContactRecord
from services.decision.policy.suppression import ComplaintStatus, ComplaintTicket

NOW = datetime(2026, 11, 20, 10, 0, 0)
SENT_AT = datetime(2026, 11, 21, 9, 0, 0)
AS_OF_FINAL = datetime(2027, 2, 1)
CAMPAIGN_CORR = "corr-campaign-test-0001"

CAMPAIGN: Dict[str, Any] = {
    "campaign_id": "CMP-PIPE-1",
    "channel": "email_sim",
    "approved_by": "business-approver-01",
    "random_seed": 20261120,
    "ab_test_ratio": 50,  # rasio varian aplikasi; TIDAK boleh menjadi ukuran control
    "conversion_window_days": 30,
    "adjustment_window_days": 14,
    "exposure_window": {
        "start_time": "2026-11-21T00:00:00Z",
        "end_time": "2026-11-28T00:00:00Z",
    },
}
FACTS = {
    "first_name": "Pelanggan",
    "preferred_branch": "Yogyakarta",
    "offer_validity": "30-12-2026",
    "points_balance": "100",
}


def consent_doc(
    ref: str, *, email: bool = True, push: bool = False, global_opt_out: bool = False
):
    def ch(on: bool) -> Dict[str, Any]:
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
        "channels": {"email": ch(email), "push": ch(push)},
        "unknown_expired_policy": "BLOCKED",
        "identity_merge_policy": "MOST_RESTRICTIVE_WINS",
        "most_restrictive_wins": True,
    }


def make_member(
    ref: str,
    kind: str = "ELIGIBLE",
    facts: Optional[Dict[str, Any]] = None,
) -> AudienceMember:
    complaints: List[ComplaintTicket] = []
    contacts: List[ContactRecord] = []
    doc = consent_doc(ref)
    if kind == "OPT_OUT":
        doc = consent_doc(ref, global_opt_out=True)
    elif kind == "PUSH_ONLY_CONSENT":
        # NBA masih boleh memilih push, tetapi campaign ini memakai email.
        doc = consent_doc(ref, email=False, push=True)
    elif kind == "COMPLAINT":
        complaints = [
            ComplaintTicket(
                f"T-{ref}",
                ref,
                ComplaintStatus.OPEN_SEVERE,
                "SEVERE",
                NOW - timedelta(days=1),
            )
        ]
    elif kind == "FATIGUED":
        contacts = [
            ContactRecord(ref, "CROSS_SELL", "email", NOW - timedelta(days=d))
            for d in (1, 6)
        ]
    decision = evaluate_customer(
        customer_ref=ref,
        correlation_id=f"corr-{ref}",
        score_row={
            "customer_id": ref,
            "churn_score": 0.92,
            "churn_risk_band": "VERY_HIGH",
            "propensity_purchase": 0.6,
            "propensity_renew": 0.5,
            "clv_amount": 3_000_000.0,
            "clv_tier": "GOLD",
            "lifecycle_stage": "AT_RISK",
            "score_generated_at": (NOW - timedelta(days=1)).isoformat(),
            "reason_codes": ["PURCHASE_FREQUENCY_90D"],
            "model_version": "churn-dev-1.0",
            "review_status": "reviewed",
            "reviewed_by": 7,
            "submitted_by": 3,
            "usage_approved": True,
        },
        consent_doc=doc,
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
    return AudienceMember(ref, decision, doc, FACTS if facts is None else facts)


def build_audience(n: int = 400) -> List[AudienceMember]:
    kinds = ["OPT_OUT", "COMPLAINT", "FATIGUED"] + ["ELIGIBLE"] * 7
    return [make_member(f"CUST-{i:04d}", kinds[i % 10]) for i in range(n)]


@pytest.fixture(scope="module")
def audience() -> List[AudienceMember]:
    return build_audience(400)


@pytest.fixture(scope="module")
def result(audience) -> CampaignRunResult:
    return run_campaign(
        campaign=CAMPAIGN,
        audience=audience,
        correlation_id=CAMPAIGN_CORR,
        sent_at=SENT_AT,
    )


def outcomes_for(res: CampaignRunResult, treat_every: int, ctrl_every: int):
    outcomes = []
    for idx, cid in enumerate(res.split.treatment_ids):
        if idx % treat_every == 0:
            outcomes.append(_k09(f"O-T-{idx}", cid))
    for idx, cid in enumerate(res.split.control_ids):
        if idx % ctrl_every == 0:
            outcomes.append(_k09(f"O-C-{idx}", cid))
    return outcomes


def _k09(outcome_id: str, customer_id: str) -> Dict[str, Any]:
    return {
        "outcome_id": outcome_id,
        "customer_id": customer_id,
        "conversion_type": "PURCHASE",
        "gross_revenue": 100_000,
        "occurred_at": (SENT_AT + timedelta(days=3)).isoformat(),
    }


# ---------------------------------------------------------------------------
# 1-3. Alur nyata + keamanan
# ---------------------------------------------------------------------------


class TestRealRun:
    def test_pipeline_really_sends_simulated_messages(self, result):
        assert result.status == "COMPLETED_SIMULATED"
        assert result.sent_count > 0
        assert result.sent_count == result.treatment_count
        sent = [d for d in result.deliveries if d["exposure_recorded"]]
        assert len(sent) == result.sent_count
        assert all(d["status"] == "SIMULATED_SENT" for d in sent)
        assert all(d["is_simulated"] and not d["external_delivery"] for d in sent)
        assert all(d["approved_by"] == "business-approver-01" for d in sent)
        assert all(d["channel"] == "email" for d in sent)

    def test_holdout_control_gets_zero_exposure(self, result):
        assert result.control_count > 0
        assert result.control_exposure_count == 0 and result.control_isolated
        control_deliveries = [d for d in result.deliveries if d["group"] == "CONTROL"]
        assert len(control_deliveries) == result.control_count
        assert all(
            d["status"] == "SKIPPED_CONTROL_HOLDOUT" and not d["exposure_recorded"]
            for d in control_deliveries
        )

    def test_control_is_about_ten_percent_even_when_ab_ratio_is_50(self, result):
        share = result.control_count / result.targetable_count
        assert 0.05 <= share <= 0.15, share

    def test_blocked_customers_never_receive_a_message(self, result, audience):
        kind_by_ref = {m.customer_ref: i % 10 for i, m in enumerate(audience)}
        blocked = {r for r, bucket in kind_by_ref.items() if bucket in (0, 1, 2)}
        delivered_refs = {d["customer_id"] for d in result.deliveries}
        assert blocked.isdisjoint(delivered_refs)
        skipped_refs = {s["customer_id"] for s in result.skipped}
        assert blocked == skipped_refs
        assert all(s["reason"] == SKIP_NO_PROMO_DECISION for s in result.skipped)

    def test_counts_add_up(self, result, audience):
        assert result.audience_size == len(audience)
        assert result.targetable_count + len(result.skipped) == result.audience_size
        assert result.treatment_count + result.control_count == result.targetable_count

    def test_sent_messages_become_contact_rows_for_future_fatigue_checks(self, result):
        assert len(result.contact_rows) == result.sent_count
        assert all(row["is_commercial"] for row in result.contact_rows)

    def test_no_human_approval_means_nothing_is_sent(self, audience):
        for bad in (None, "", "   "):
            with pytest.raises(ValueError, match="belum disetujui"):
                run_campaign(
                    campaign={**CAMPAIGN, "approved_by": bad},
                    audience=audience[:20],
                    correlation_id=CAMPAIGN_CORR,
                )

    @pytest.mark.parametrize("channel", ["email", "twilio_sms", "", None])
    def test_only_simulator_channels_are_accepted(self, audience, channel):
        with pytest.raises(ValueError):
            run_campaign(
                campaign={**CAMPAIGN, "channel": channel},
                audience=audience[:20],
                correlation_id=CAMPAIGN_CORR,
            )

    def test_customer_without_consent_for_campaign_channel_is_skipped(self):
        members = [make_member(f"C-{i}", "ELIGIBLE") for i in range(30)]
        members.append(make_member("C-NOEMAIL", "PUSH_ONLY_CONSENT"))
        assert members[-1].decision.selected_action_id != "NO_ACTION"  # lolos NBA
        res = run_campaign(
            campaign=CAMPAIGN,
            audience=members,
            correlation_id=CAMPAIGN_CORR,
            sent_at=SENT_AT,
        )
        reasons = {s["customer_id"]: s["reason"] for s in res.skipped}
        assert reasons["C-NOEMAIL"] == SKIP_CHANNEL_OPTED_OUT
        assert "C-NOEMAIL" not in {d["customer_id"] for d in res.deliveries}

    def test_missing_facts_block_the_message_instead_of_guessing(self):
        members = [make_member(f"C-{i}", "ELIGIBLE") for i in range(20)]
        members.append(make_member("C-NOFACTS", "ELIGIBLE", facts={}))
        res = run_campaign(
            campaign=CAMPAIGN,
            audience=members,
            correlation_id=CAMPAIGN_CORR,
            sent_at=SENT_AT,
        )
        skipped = {s["customer_id"]: s for s in res.skipped}
        assert skipped["C-NOFACTS"]["reason"] == SKIP_DRAFT_NOT_SAFE
        assert skipped["C-NOFACTS"]["detail"] == "DRAFT_REJECTED_MISSING_FACTS"

    def test_customers_without_connected_data_are_never_messaged(self):
        silent = evaluate_customer(
            customer_ref="C-SILENT",
            correlation_id="corr-silent",
            score_row=None,
            consent_doc=None,
            complaint_tickets=None,
            contact_history=None,
            eligibility=None,
            product_suitability=None,
            evaluation_date=NOW,
        )
        members = [make_member(f"C-{i}", "ELIGIBLE") for i in range(20)]
        members.append(
            AudienceMember("C-SILENT", silent, consent_doc("C-SILENT"), FACTS)
        )
        res = run_campaign(
            campaign=CAMPAIGN,
            audience=members,
            correlation_id=CAMPAIGN_CORR,
            sent_at=SENT_AT,
        )
        assert "C-SILENT" not in {d["customer_id"] for d in res.deliveries}
        assert "C-SILENT" in {s["customer_id"] for s in res.skipped}

    def test_duplicate_customers_are_counted_once(self):
        member = make_member("C-DUP", "ELIGIBLE")
        res = run_campaign(
            campaign=CAMPAIGN,
            audience=[member, member] + [make_member(f"C-{i}") for i in range(10)],
            correlation_id=CAMPAIGN_CORR,
            sent_at=SENT_AT,
        )
        assert res.audience_size == 11
        assert sum(1 for d in res.deliveries if d["customer_id"] == "C-DUP") == 1

    def test_empty_audience_runs_without_crashing_and_reports_zero(self):
        res = run_campaign(campaign=CAMPAIGN, audience=[], correlation_id=CAMPAIGN_CORR)
        assert res.audience_size == 0 and res.sent_count == 0
        assert res.measurement is None
        assert res.measurement_status == MEASUREMENT_AWAITING_OUTCOMES


# ---------------------------------------------------------------------------
# 4-5. Pengukuran + data kosong
# ---------------------------------------------------------------------------


class TestMeasurement:
    def test_without_outcomes_measurement_stays_empty_not_invented(self, result):
        assert result.measurement is None
        assert result.measurement_status == MEASUREMENT_AWAITING_OUTCOMES
        assert result.measurement_rows == ()
        assert [e["event_type"] for e in result.audit_events()] == ["campaign.executed"]

    def test_incremental_revenue_matches_independent_formula(self, audience):
        res = run_campaign(
            campaign=CAMPAIGN,
            audience=audience,
            correlation_id=CAMPAIGN_CORR,
            sent_at=SENT_AT,
        )
        outcomes = outcomes_for(res, treat_every=5, ctrl_every=10)
        full = run_campaign(
            campaign=CAMPAIGN,
            audience=audience,
            correlation_id=CAMPAIGN_CORR,
            sent_at=SENT_AT,
            outcomes=outcomes,
            as_of=AS_OF_FINAL,
        )
        assert full.measurement_status == MEASUREMENT_COMPUTED
        n_t, n_c = full.treatment_count, full.control_count
        rev_t = 100_000 * sum(1 for o in outcomes if o["outcome_id"].startswith("O-T"))
        rev_c = 100_000 * sum(1 for o in outcomes if o["outcome_id"].startswith("O-C"))
        expected = rev_t - rev_c * (n_t / n_c)
        incremental = full.measurement["incremental_conversion"]["incremental_revenue"]
        assert incremental == pytest.approx(expected)
        assert full.measurement["status"] == "FINAL"
        assert full.measurement["data_quality"]["control_exposed_count"] == 0

    def test_measurement_rows_are_ready_for_msr_campaign_measurements(self, audience):
        res = run_campaign(
            campaign=CAMPAIGN,
            audience=audience,
            correlation_id=CAMPAIGN_CORR,
            sent_at=SENT_AT,
        )
        full = run_campaign(
            campaign=CAMPAIGN,
            audience=audience,
            correlation_id=CAMPAIGN_CORR,
            sent_at=SENT_AT,
            outcomes=outcomes_for(res, 5, 10),
            as_of=AS_OF_FINAL,
        )
        assert {r["metric_name"] for r in full.measurement_rows} == {
            "conversion_rate",
            "converting_customers",
            "revenue",
        }
        assert all(
            set(r) == {"metric_name", "observed_value", "incremental_value"}
            for r in full.measurement_rows
        )
        events = [e["event_type"] for e in full.audit_events()]
        assert events == ["campaign.executed", "campaign.measured"]

    def test_early_measurement_is_marked_provisional(self, audience):
        res = run_campaign(
            campaign=CAMPAIGN,
            audience=audience,
            correlation_id=CAMPAIGN_CORR,
            sent_at=SENT_AT,
        )
        early = run_campaign(
            campaign=CAMPAIGN,
            audience=audience,
            correlation_id=CAMPAIGN_CORR,
            sent_at=SENT_AT,
            outcomes=outcomes_for(res, 5, 10),
            as_of=SENT_AT + timedelta(days=5),
        )
        assert early.measurement["status"] == "PROVISIONAL"
        assert any("PROVISIONAL" in w for w in early.measurement["warnings"])


# ---------------------------------------------------------------------------
# 6. Bentuk hasil job, determinisme, offline
# ---------------------------------------------------------------------------


class TestJobResultAndDeterminism:
    def test_job_result_keeps_legacy_keys_and_adds_real_ones(self, result):
        job = result.to_job_result()
        for legacy in (
            "delivery_mode",
            "external_delivery",
            "channel",
            "target_mode",
            "audience_size",
            "variant_a_count",
            "variant_b_count",
            "customer_ids",
        ):
            assert legacy in job
        assert job["delivery_mode"] == "simulated" and job["external_delivery"] is False
        assert job["control_isolated"] is True
        assert job["measurement_status"] == MEASUREMENT_AWAITING_OUTCOMES
        assert job["sent_count"] == result.sent_count

    def test_audit_event_carries_correlation_id_and_no_external_delivery(self, result):
        event = result.audit_events()[0]
        assert event["correlation_id"] == CAMPAIGN_CORR
        assert event["details"]["external_delivery"] is False
        assert event["details"]["control_exposure_count"] == 0

    def test_same_input_gives_same_groups(self, audience, result):
        again = run_campaign(
            campaign=CAMPAIGN,
            audience=audience,
            correlation_id=CAMPAIGN_CORR,
            sent_at=SENT_AT,
        )
        assert again.split.control_ids == result.split.control_ids
        assert again.split.treatment_ids == result.split.treatment_ids

    def test_pipeline_never_opens_a_network_socket(self, audience, monkeypatch):
        def forbidden(*args, **kwargs):
            raise AssertionError("pipeline tidak boleh memakai jaringan")

        monkeypatch.setattr(socket, "socket", forbidden)
        res = run_campaign(
            campaign=CAMPAIGN,
            audience=audience[:50],
            correlation_id=CAMPAIGN_CORR,
            sent_at=SENT_AT,
        )
        assert res.sent_count >= 0
