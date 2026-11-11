"""
test_holdout.py — Test Holdout Control Group Splitter (Minggu 9).

Jalankan: python -m pytest tests/decision/test_holdout.py -v
"""

import pytest

from services.decision.campaign.holdout import (
    DEFAULT_HOLDOUT_RATIO,
    GROUP_CONTROL,
    GROUP_TREATMENT,
    HoldoutSplit,
    assign_group,
    hash_bucket,
    split_audience,
    split_from_campaign,
)

IDS = [f"C{i:05d}" for i in range(10_000)]


class TestHashing:
    def test_bucket_in_unit_interval(self):
        for cid in IDS[:500]:
            assert 0.0 <= hash_bucket(cid, 42) < 1.0

    def test_deterministic(self):
        assert hash_bucket("C1", 7) == hash_bucket("C1", 7)

    def test_known_value_is_stable_across_runs(self):
        # Nilai tetap: memastikan tidak memakai hash() bawaan Python (berubah per proses).
        assert hash_bucket("C00001", 42) == pytest.approx(
            0.48232119564027187, abs=1e-12
        )

    def test_matches_independent_sha256_computation(self):
        import hashlib

        digest = hashlib.sha256(b"C00001:42").digest()
        expected = (int.from_bytes(digest[:8], "big") >> 11) / 2**53
        assert hash_bucket("C00001", 42) == expected

    def test_seed_changes_assignment(self):
        assert hash_bucket("C1", 1) != hash_bucket("C1", 2)

    def test_whitespace_is_stripped(self):
        assert hash_bucket(" C1 ", 1) == hash_bucket("C1", 1)

    @pytest.mark.parametrize("bad", ["", "   ", None])
    def test_empty_customer_id_rejected(self, bad):
        with pytest.raises(ValueError):
            hash_bucket(bad, 1)

    @pytest.mark.parametrize("bad", [1.5, "1", True, None])
    def test_seed_must_be_int(self, bad):
        with pytest.raises(ValueError):
            hash_bucket("C1", bad)


class TestAssignGroup:
    def test_matches_bucket_rule(self):
        for cid in IDS[:200]:
            expected = GROUP_CONTROL if hash_bucket(cid, 9) < 0.1 else GROUP_TREATMENT
            assert assign_group(cid, 9, 0.1) == expected

    @pytest.mark.parametrize("bad", [0, 0.0, 1, 1.0, -0.1, 1.5, True, "0.1"])
    def test_ratio_must_be_strictly_between_0_and_1(self, bad):
        with pytest.raises(ValueError):
            assign_group("C1", 1, bad)


class TestSplitAudience:
    def test_default_ratio_is_ten_percent(self):
        assert DEFAULT_HOLDOUT_RATIO == 0.10

    def test_proportion_close_to_target(self):
        s = split_audience(IDS, 42, 0.10, "CMP-1")
        assert abs(s.actual_control_ratio - 0.10) < 0.015
        assert s.n_total == len(IDS)

    @pytest.mark.parametrize("ratio", [0.05, 0.2, 0.5])
    def test_other_ratios(self, ratio):
        s = split_audience(IDS, 7, ratio)
        assert abs(s.actual_control_ratio - ratio) < 0.02

    def test_reproducible_with_same_seed(self):
        a = split_audience(IDS, 42)
        b = split_audience(IDS, 42)
        assert a.control_ids == b.control_ids and a.treatment_ids == b.treatment_ids

    def test_order_of_input_does_not_change_membership(self):
        a = split_audience(IDS, 42)
        b = split_audience(list(reversed(IDS)), 42)
        assert set(a.control_ids) == set(b.control_ids)

    def test_different_seed_gives_different_control(self):
        assert set(split_audience(IDS, 1).control_ids) != set(
            split_audience(IDS, 2).control_ids
        )

    def test_membership_stable_when_audience_grows(self):
        small = split_audience(IDS[:5000], 42)
        big = split_audience(IDS, 42)
        assert set(small.control_ids) <= set(big.control_ids)

    def test_groups_are_disjoint_and_complete(self):
        s = split_audience(IDS, 42)
        assert not set(s.control_ids) & set(s.treatment_ids)
        assert set(s.control_ids) | set(s.treatment_ids) == set(IDS)

    def test_duplicates_counted_once(self):
        s = split_audience(["A", "B", "A", " A ", "B"], 1, 0.5)
        assert s.n_total == 2 and s.duplicates_removed == 3

    def test_empty_audience(self):
        s = split_audience([], 1)
        assert s.n_total == 0 and s.actual_control_ratio == 0.0
        assert s.has_control_group is False


class TestHoldoutSplit:
    def test_group_lookup(self):
        s = split_audience(IDS, 42, 0.1)
        c, t = s.control_ids[0], s.treatment_ids[0]
        assert s.group_of(c) == GROUP_CONTROL and s.is_control(c)
        assert s.group_of(t) == GROUP_TREATMENT and s.is_treatment(t)
        assert s.group_of("NOPE") is None
        assert not s.is_control("NOPE") and not s.is_treatment("NOPE")

    def test_overlap_rejected(self):
        with pytest.raises(ValueError):
            HoldoutSplit("X", 1, 0.1, ("A",), ("A",))

    def test_immutable(self):
        s = split_audience(IDS[:10], 1, 0.5)
        with pytest.raises(Exception):
            s.campaign_id = "Z"  # type: ignore[misc]

    def test_to_dict(self):
        s = split_audience(IDS[:100], 3, 0.1, "CMP-9")
        d = s.to_dict()
        assert d["campaign_id"] == "CMP-9" and d["random_seed"] == 3
        assert "control_ids" not in d
        assert set(s.to_dict(include_ids=True)["control_ids"]) == set(s.control_ids)


class TestSplitFromCampaign:
    def test_uses_control_holdout_ratio(self):
        s = split_from_campaign(
            {"campaign_id": "C1", "control_holdout_ratio": 0.2, "random_seed": 5}, IDS
        )
        assert s.holdout_ratio == 0.2 and s.campaign_id == "C1"

    def test_control_ratio_wins_over_ab_ratio(self):
        s = split_from_campaign(
            {
                "campaign_id": "C1",
                "control_holdout_ratio": 0.2,
                "ab_test_ratio": 50,
                "random_seed": 5,
            },
            IDS,
        )
        assert s.holdout_ratio == 0.2

    def test_falls_back_to_ab_test_ratio(self):
        s = split_from_campaign(
            {"campaign_id": "C1", "ab_test_ratio": 90, "random_seed": 5}, IDS
        )
        assert s.holdout_ratio == pytest.approx(0.10)

    def test_default_when_no_ratio(self):
        s = split_from_campaign({"campaign_id": "C1", "random_seed": 5}, IDS)
        assert s.holdout_ratio == DEFAULT_HOLDOUT_RATIO

    def test_seed_required(self):
        with pytest.raises(ValueError, match="random_seed"):
            split_from_campaign({"campaign_id": "C1"}, IDS)

    def test_campaign_id_required(self):
        with pytest.raises(ValueError, match="campaign_id"):
            split_from_campaign({"random_seed": 1}, IDS)

    def test_ab_ratio_100_means_no_holdout_and_is_rejected(self):
        with pytest.raises(ValueError):
            split_from_campaign(
                {"campaign_id": "C1", "ab_test_ratio": 100, "random_seed": 1}, IDS
            )
