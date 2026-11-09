"""
test_nudge_generator.py — Test Personalized Nudge Generator (Minggu 8).

Jalankan: python -m pytest tests/decision/test_nudge_generator.py -v
"""

from datetime import date

import pytest

from services.decision.nba.catalogue import ACTION_CATALOGUE
from services.decision.nudge.generator import (
    ALLOWED_VARIABLES,
    STATUS_BLOCKED_BY_GUARDRAIL,
    STATUS_CHANNEL_NOT_ALLOWED,
    STATUS_GENERATED_DRAFT,
    STATUS_MISSING_FACTS,
    STATUS_NO_TEMPLATE,
    TEMPLATES,
    approve_draft,
    generate_nudge,
    required_facts,
)

FACTS = {
    "first_name": "Budi",
    "preferred_branch": "Yogyakarta",
    "points_balance": 1200,
    "offer_validity": date(2026, 12, 31),
}


def _gen(action="LOYALTY_REWARD", channel="email", facts=None, **kw):
    return generate_nudge(
        "C1", action, channel, FACTS if facts is None else facts, **kw
    )


class TestTemplates:
    def test_all_templates_use_only_whitelist_variables(self):
        for action_id in TEMPLATES:
            assert set(required_facts(action_id)) <= ALLOWED_VARIABLES

    def test_whitelist_is_exactly_the_four_variables(self):
        assert ALLOWED_VARIABLES == {
            "first_name",
            "preferred_branch",
            "points_balance",
            "offer_validity",
        }

    def test_templates_only_for_catalogue_actions_with_message_channels(self):
        for action_id in TEMPLATES:
            channels = ACTION_CATALOGUE[action_id].allowed_channels
            assert set(channels) & {"email", "push", "sms"}

    @pytest.mark.parametrize("action_id", list(TEMPLATES))
    def test_every_template_generates_safe_draft(self, action_id):
        channel = ACTION_CATALOGUE[action_id].allowed_channels[0]
        d = _gen(action_id, channel)
        assert d.status == STATUS_GENERATED_DRAFT, d.reason
        assert "{" not in d.body and "}" not in d.body


class TestGenerate:
    def test_draft_status_and_human_approval_required(self):
        d = _gen()
        assert d.status == STATUS_GENERATED_DRAFT == "GENERATED_DRAFT"
        assert d.requires_human_approval is True
        assert d.is_releasable is False
        assert d.approved_by is None

    def test_substitution_values(self):
        d = _gen()
        assert "Budi" in d.body and "1200" in d.body
        assert d.variables_used["first_name"] == "Budi"

    def test_offer_validity_substituted_for_offer_templates(self):
        d = _gen("UPSELL")
        assert "31-12-2026" in d.body

    def test_templates_do_not_misuse_offer_validity(self):
        """offer_validity = masa berlaku penawaran, bukan akhir membership / masa poin."""
        for aid in ("RENEWAL_REMINDER", "LOYALTY_REWARD"):
            assert "offer_validity" not in required_facts(aid)

    def test_missing_fact_rejected_not_invented(self):
        facts = dict(FACTS)
        del facts["points_balance"]
        d = _gen(facts=facts)
        assert d.status == STATUS_MISSING_FACTS
        assert d.missing_facts == ["points_balance"]
        assert d.body == ""

    @pytest.mark.parametrize("empty", ["", "   ", None])
    def test_blank_fact_counts_as_missing(self, empty):
        d = _gen(facts={**FACTS, "first_name": empty})
        assert d.status == STATUS_MISSING_FACTS and "first_name" in d.missing_facts

    def test_zero_points_is_valid_fact(self):
        d = _gen(facts={**FACTS, "points_balance": 0})
        assert d.status == STATUS_GENERATED_DRAFT and " 0 poin" in d.body

    def test_non_whitelist_facts_ignored(self):
        d = _gen(facts={**FACTS, "credit_card": "4111111111111111", "secret": "x"})
        assert "4111" not in d.body and "secret" not in d.variables_used

    def test_action_without_template(self):
        for aid in (
            "NO_ACTION",
            "COMPLAINT_RESOLUTION",
            "RELATIONSHIP_MANAGER_CONTACT",
            "NOPE",
        ):
            assert _gen(aid).status == STATUS_NO_TEMPLATE

    def test_channel_not_allowed(self):
        assert _gen(channel="whatsapp").status == STATUS_CHANNEL_NOT_ALLOWED

    def test_channel_case_insensitive(self):
        assert _gen(channel="EMAIL").status == STATUS_GENERATED_DRAFT

    def test_long_fact_truncated(self):
        d = _gen(facts={**FACTS, "first_name": "A" * 500})
        assert len(d.variables_used["first_name"]) <= 60


class TestGuardrailIntegration:
    def test_forbidden_claim_in_fact_is_blocked(self):
        """Fakta berisi klaim terlarang tidak boleh lolos ke pesan."""
        d = _gen(
            facts={**FACTS, "first_name": "Diskon 90% dijamin 100%"},
            max_discount_percent=30,
        )
        assert d.status == STATUS_BLOCKED_BY_GUARDRAIL == "MESSAGE_BLOCKED_BY_GUARDRAIL"
        assert d.violations
        assert d.is_releasable is False

    def test_braces_in_fact_cannot_inject_placeholders(self):
        d = _gen(facts={**FACTS, "first_name": "{offer_validity}"})
        assert "{" not in d.body and "}" not in d.body

    def test_discount_in_fact_within_global_cap_for_unrestricted_band(self):
        """LOYALTY_REWARD (band poin loyalitas) memakai pagu global 30%."""
        assert (
            _gen(facts={**FACTS, "first_name": "Diskon 30%"}).status
            == STATUS_GENERATED_DRAFT
        )
        d = _gen(facts={**FACTS, "first_name": "Diskon 31%"})
        assert d.status == STATUS_BLOCKED_BY_GUARDRAIL

    @pytest.mark.parametrize(
        "action,channel,allowed,blocked",
        [
            ("RENEWAL_REMINDER", "email", None, 5),  # Tanpa Insentif: 0%
            ("CROSS_SELL", "email", 10, 11),  # Band Rendah: <= 10%
            ("UPSELL", "email", 20, 21),  # Band Sedang: <= 20%
        ],
    )
    def test_per_band_discount_limits(self, action, channel, allowed, blocked):
        if allowed is not None:
            ok = _gen(
                action, channel, facts={**FACTS, "first_name": f"Diskon {allowed}%"}
            )
            assert ok.status == STATUS_GENERATED_DRAFT, (action, allowed)
        bad = _gen(action, channel, facts={**FACTS, "first_name": f"Diskon {blocked}%"})
        assert bad.status == STATUS_BLOCKED_BY_GUARDRAIL, (action, blocked)

    def test_discount_violation_is_marked_for_escalation(self):
        d = _gen("CROSS_SELL", "email", facts={**FACTS, "first_name": "Diskon 50%"})
        assert d.status == "MESSAGE_BLOCKED_BY_GUARDRAIL"
        assert d.escalation == "INCENTIVE_ESCALATED"
        with pytest.raises(ValueError):
            approve_draft(d, "christ")

    def test_non_discount_violation_is_not_escalated(self):
        d = _gen(facts={**FACTS, "first_name": "Pasti sembuh"})
        assert d.status == STATUS_BLOCKED_BY_GUARDRAIL and d.escalation is None

    def test_forbidden_term_in_fact_is_blocked(self):
        d = _gen(
            "CROSS_SELL", "email", facts={**FACTS, "preferred_branch": "Klinik medis"}
        )
        assert d.status == STATUS_BLOCKED_BY_GUARDRAIL

    def test_explicit_override_replaces_band_limits(self):
        d = _gen(
            "CROSS_SELL",
            "email",
            facts={**FACTS, "first_name": "Diskon 40%"},
            max_discount_percent=50,
        )
        assert d.status == STATUS_GENERATED_DRAFT

    def test_fail_closed_when_global_cap_is_none(self, monkeypatch):
        from services.decision.nudge import safety

        monkeypatch.setattr(safety, "MAX_DISCOUNT_PERCENT", None)
        d = _gen(facts={**FACTS, "first_name": "Diskon 5%"})
        assert d.status == STATUS_BLOCKED_BY_GUARDRAIL

    def test_clean_draft_has_no_escalation(self):
        assert _gen().escalation is None

    def test_templates_contain_no_numeric_discount(self):
        """Template bawaan tidak boleh memuat klaim diskon persentase."""
        import re

        for aid, text in TEMPLATES.items():
            assert not re.search(r"\d\s*(%|persen)", text), aid

    def test_blocked_draft_cannot_be_approved(self):
        d = _gen(facts={**FACTS, "first_name": "Pasti berhasil"})
        assert d.status == STATUS_BLOCKED_BY_GUARDRAIL
        with pytest.raises(ValueError):
            approve_draft(d, "christ")

    def test_missing_facts_draft_cannot_be_approved(self):
        d = _gen(facts={})
        with pytest.raises(ValueError):
            approve_draft(d, "christ")


class TestApproval:
    def test_human_approval_makes_releasable(self):
        d = approve_draft(_gen(), "christ")
        assert d.is_releasable is True and d.approved_by == "christ"
        assert d.status == STATUS_GENERATED_DRAFT

    @pytest.mark.parametrize("bad", ["", "   "])
    def test_empty_approver_rejected(self, bad):
        with pytest.raises(ValueError):
            approve_draft(_gen(), bad)

    def test_original_draft_not_mutated(self):
        d = _gen()
        approve_draft(d, "christ")
        assert d.approved_by is None
