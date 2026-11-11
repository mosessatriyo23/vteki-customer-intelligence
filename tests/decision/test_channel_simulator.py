"""
test_channel_simulator.py — Test Channel Simulator Internal (Minggu 9).

Jalankan: python -m pytest tests/decision/test_channel_simulator.py -v
"""

import ast
import socket
from datetime import datetime, timezone
from pathlib import Path

import pytest

from services.decision.campaign.holdout import split_audience
from services.decision.nudge.generator import (
    STATUS_GENERATED_DRAFT,
    NudgeDraft,
    approve_draft,
    generate_nudge,
)
from services.decision.simulator import channel_sim
from services.decision.simulator.channel_sim import (
    STATUS_REJECTED_NOT_APPROVED,
    STATUS_REJECTED_NOT_IN_AUDIENCE,
    STATUS_REJECTED_UNSUPPORTED_CHANNEL,
    STATUS_SIMULATED_SENT,
    STATUS_SKIPPED_CONTROL,
    ChannelSimulator,
    UnregisteredCampaignError,
    normalize_channel,
)

FACTS = {
    "first_name": "Budi",
    "preferred_branch": "Yogyakarta",
    "points_balance": 1200,
}
NOW = datetime(2026, 11, 2, 9, 0, 0)
IDS = [f"C{i:04d}" for i in range(400)]


def _draft(cid, channel="email", approve=True, action="LOYALTY_REWARD"):
    d = generate_nudge(cid, action, channel, FACTS)
    return approve_draft(d, "christ") if approve else d


@pytest.fixture
def setup():
    split = split_audience(IDS, 42, 0.10, "CMP-1")
    sim = ChannelSimulator(clock=lambda: NOW)
    sim.register_campaign(split)
    return sim, split


class TestNormalizeChannel:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("EMAIL", "email"),
            ("email_sim", "email"),
            ("Push_Sim", "push"),
            ("PUSH_NOTIFICATION", "push"),
            ("sms_sim", "sms"),
            ("whatsapp", "whatsapp"),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_channel(raw) == expected


class TestSending:
    def test_treatment_member_is_sent(self, setup):
        sim, split = setup
        r = sim.send(_draft(split.treatment_ids[0]), campaign_id="CMP-1")
        assert r.status == STATUS_SIMULATED_SENT and r.exposure_recorded
        assert r.is_simulated is True and r.external_delivery is False
        assert r.delivery_mode == "simulated"
        assert r.attempted_at == NOW and r.channel == "email"
        assert r.approved_by == "christ" and r.body

    @pytest.mark.parametrize("channel", ["email", "push"])
    def test_generator_channels(self, setup, channel):
        sim, split = setup
        r = sim.send(
            _draft(split.treatment_ids[0], channel=channel), campaign_id="CMP-1"
        )
        assert r.status == STATUS_SIMULATED_SENT and r.channel == channel

    def test_sms_supported_by_simulator(self, setup):
        # Katalog aksi saat ini tidak mengizinkan SMS, jadi draf dibuat manual.
        sim, split = setup
        d = NudgeDraft(
            customer_id=split.treatment_ids[0],
            action_id="LOYALTY_REWARD",
            channel="sms_sim",
            status=STATUS_GENERATED_DRAFT,
            body="Halo",
            approved_by="christ",
        )
        r = sim.send(d, campaign_id="CMP-1")
        assert r.status == STATUS_SIMULATED_SENT and r.channel == "sms"

    def test_push_alias_channel_supported(self, setup):
        sim, split = setup
        d = _draft(split.treatment_ids[0])
        d2 = type(d)(**{**d.__dict__, "channel": "push_notification"})
        assert sim.send(d2, campaign_id="CMP-1").channel == "push"

    def test_unapproved_draft_rejected(self, setup):
        sim, split = setup
        r = sim.send(_draft(split.treatment_ids[0], approve=False), campaign_id="CMP-1")
        assert r.status == STATUS_REJECTED_NOT_APPROVED and not r.exposure_recorded
        assert r.body == "" and r.approved_by is None

    def test_blocked_draft_rejected(self, setup):
        sim, split = setup
        facts = dict(FACTS, first_name="gratis diskon 90%")
        d = generate_nudge(split.treatment_ids[0], "LOYALTY_REWARD", "email", facts)
        r = sim.send(d, campaign_id="CMP-1")
        assert r.status == STATUS_REJECTED_NOT_APPROVED

    def test_unsupported_channel_rejected(self, setup):
        sim, split = setup
        d = _draft(split.treatment_ids[0])
        d2 = type(d)(**{**d.__dict__, "channel": "whatsapp"})
        r = sim.send(d2, campaign_id="CMP-1")
        assert r.status == STATUS_REJECTED_UNSUPPORTED_CHANNEL

    def test_non_audience_rejected(self, setup):
        sim, _ = setup
        r = sim.send(_draft("STRANGER"), campaign_id="CMP-1")
        assert r.status == STATUS_REJECTED_NOT_IN_AUDIENCE and r.group is None

    def test_unregistered_campaign_raises(self, setup):
        sim, split = setup
        with pytest.raises(UnregisteredCampaignError):
            sim.send(_draft(split.treatment_ids[0]), campaign_id="NOPE")

    def test_bad_correlation_id_rejected(self, setup):
        sim, split = setup
        with pytest.raises(ValueError):
            sim.send(
                _draft(split.treatment_ids[0]),
                campaign_id="CMP-1",
                correlation_id="bad id!",
            )

    def test_custom_correlation_id_kept(self, setup):
        sim, split = setup
        r = sim.send(
            _draft(split.treatment_ids[0]), campaign_id="CMP-1", correlation_id="abc-1"
        )
        assert r.correlation_id == "abc-1"

    def test_sent_at_timezone_aware_is_normalized(self, setup):
        sim, split = setup
        aware = datetime(2026, 11, 3, 7, 0, tzinfo=timezone.utc)
        r = sim.send(_draft(split.treatment_ids[0]), campaign_id="CMP-1", sent_at=aware)
        assert r.attempted_at == datetime(2026, 11, 3, 7, 0)

    def test_delivery_ids_are_sequential_and_unique(self, setup):
        sim, split = setup
        rs = sim.send_batch(
            [_draft(c) for c in split.treatment_ids[:5]], campaign_id="CMP-1"
        )
        assert [r.delivery_id for r in rs] == [f"SIM-{i:08d}" for i in range(1, 6)]


class TestControlZeroExposure:
    def test_control_member_skipped_even_with_valid_approved_draft(self, setup):
        sim, split = setup
        cid = split.control_ids[0]
        r = sim.send(_draft(cid), campaign_id="CMP-1")
        assert r.status == STATUS_SKIPPED_CONTROL
        assert not r.exposure_recorded and r.body == ""
        assert sim.has_exposure(cid) is False

    def test_control_skipped_regardless_of_draft_state(self, setup):
        sim, split = setup
        r = sim.send(_draft(split.control_ids[0], approve=False), campaign_id="CMP-1")
        assert r.status == STATUS_SKIPPED_CONTROL

    def test_full_audience_blast_gives_zero_control_exposure(self, setup):
        sim, split = setup
        sim.send_batch([_draft(c) for c in IDS], campaign_id="CMP-1")
        assert sim.control_exposure_count("CMP-1") == 0
        assert sim.verify_control_isolation("CMP-1") is True
        assert sim.exposure_count(campaign_id="CMP-1") == split.n_treatment
        assert set(sim.exposed_customer_ids("CMP-1")) == set(split.treatment_ids)
        assert len(sim.attempts) == len(IDS)

    def test_register_with_different_split_rejected(self, setup):
        sim, _ = setup
        other = split_audience(IDS, 99, 0.10, "CMP-1")
        with pytest.raises(ValueError):
            sim.register_campaign(other)

    def test_reregister_same_split_is_ok(self, setup):
        sim, split = setup
        sim.register_campaign(split)

    def test_register_requires_campaign_id(self):
        with pytest.raises(ValueError):
            ChannelSimulator().register_campaign(split_audience(IDS, 1))

    def test_control_exposure_count_unregistered(self):
        with pytest.raises(UnregisteredCampaignError):
            ChannelSimulator().control_exposure_count("X")


class TestQueries:
    def test_exposure_events_only_for_sent(self, setup):
        sim, split = setup
        sim.send(_draft(split.treatment_ids[0]), campaign_id="CMP-1")
        sim.send(_draft(split.control_ids[0]), campaign_id="CMP-1")
        events = sim.exposure_events("CMP-1")
        assert len(events) == 1 and events[0]["is_simulated"] is True
        assert events[0]["customer_id"] == split.treatment_ids[0]
        assert sim.exposure_events("OTHER") == []

    def test_record_to_dict(self, setup):
        sim, split = setup
        r = sim.send(_draft(split.treatment_ids[0]), campaign_id="CMP-1")
        d = r.to_dict()
        assert d["external_delivery"] is False and d["delivery_mode"] == "simulated"


class TestOffline:
    def test_no_network_during_send(self, setup, monkeypatch):
        sim, split = setup

        def boom(*a, **k):
            raise AssertionError("Simulator tidak boleh memakai jaringan")

        monkeypatch.setattr(socket, "socket", boom)
        monkeypatch.setattr(socket, "create_connection", boom)
        sim.send_batch(
            [_draft(c) for c in split.treatment_ids[:20]], campaign_id="CMP-1"
        )

    def test_module_imports_no_network_libraries(self):
        banned = {
            "socket", "http", "urllib", "requests", "httpx", "smtplib",
            "aiohttp", "ftplib", "telnetlib", "ssl", "websockets",
        }  # fmt: skip
        tree = ast.parse(Path(channel_sim.__file__).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert not imported & banned
