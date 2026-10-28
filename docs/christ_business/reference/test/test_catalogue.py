"""
test_catalogue.py — Unit Tests untuk services/decision/nba/catalogue.py
=========================================================================
Menguji definisi 11 aksi dalam ACTION_CATALOGUE, fungsi utilitas,
serta integritas data katalog.

Jalankan dengan:
    pytest docs/christ_business/reference/test/ -v
"""

import pytest

from services.decision.nba.catalogue import (
    ACTION_CATALOGUE,
    Action,
    ActionCategory,
    IncentiveBand,
    get_action,
    get_actions_by_category,
    list_all_action_ids,
)

# ID semua 11 aksi standar yang harus ada dalam katalog
EXPECTED_ACTION_IDS = {
    "NO_ACTION",
    "COMPLAINT_RESOLUTION",
    "RELATIONSHIP_MANAGER_CONTACT",
    "RETENTION_OUTREACH",
    "CROSS_SELL",
    "UPSELL",
    "RENEWAL_REMINDER",
    "SERVICE_REMINDER",
    "EDUCATION",
    "LOYALTY_REWARD",
    "WIN_BACK_OFFER",
}


# ---------------------------------------------------------------------------
# Tests: Integritas Katalog
# ---------------------------------------------------------------------------

class TestCatalogueIntegrity:

    def test_catalogue_has_exactly_11_actions(self):
        """Katalog harus memiliki tepat 11 aksi."""
        assert len(ACTION_CATALOGUE) == 11

    def test_all_expected_action_ids_present(self):
        """Semua 11 action_id standar harus ada dalam katalog."""
        assert set(ACTION_CATALOGUE.keys()) == EXPECTED_ACTION_IDS

    def test_all_actions_are_action_instances(self):
        """Semua nilai dalam katalog harus merupakan instance Action."""
        for action_id, action in ACTION_CATALOGUE.items():
            assert isinstance(action, Action), f"{action_id} bukan instance Action"

    def test_all_action_ids_match_keys(self):
        """action_id dalam objek Action harus cocok dengan kuncinya."""
        for key, action in ACTION_CATALOGUE.items():
            assert action.action_id == key, f"action_id '{action.action_id}' tidak cocok dengan key '{key}'"

    def test_all_actions_have_non_empty_name(self):
        """Semua aksi harus memiliki nama yang tidak kosong."""
        for action in ACTION_CATALOGUE.values():
            assert action.name, f"Action {action.action_id} tidak memiliki name"

    def test_all_actions_have_trigger_conditions(self):
        """Semua aksi (kecuali NO_ACTION) harus memiliki syarat pemicu."""
        for action_id, action in ACTION_CATALOGUE.items():
            assert len(action.trigger_conditions) > 0, \
                f"Action {action_id} tidak memiliki trigger_conditions"

    def test_all_actions_have_valid_category(self):
        """Semua aksi harus memiliki kategori yang valid."""
        for action in ACTION_CATALOGUE.values():
            assert isinstance(action.category, ActionCategory)

    def test_all_actions_have_valid_incentive_band(self):
        """Semua aksi harus memiliki incentive_band yang valid."""
        for action in ACTION_CATALOGUE.values():
            assert isinstance(action.incentive_band, IncentiveBand)

    def test_all_action_weights_are_non_negative(self):
        """Semua action_weight harus >= 0.0."""
        for action in ACTION_CATALOGUE.values():
            assert action.action_weight >= 0.0, \
                f"{action.action_id} memiliki action_weight negatif: {action.action_weight}"


# ---------------------------------------------------------------------------
# Tests: NO_ACTION
# ---------------------------------------------------------------------------

class TestNoAction:

    def test_no_action_exists(self):
        assert "NO_ACTION" in ACTION_CATALOGUE

    def test_no_action_has_zero_weight(self):
        """NO_ACTION harus memiliki action_weight = 0.0."""
        assert ACTION_CATALOGUE["NO_ACTION"].action_weight == 0.0

    def test_no_action_has_empty_channels(self):
        """NO_ACTION tidak boleh memiliki kanal komunikasi."""
        assert ACTION_CATALOGUE["NO_ACTION"].allowed_channels == []

    def test_no_action_has_no_incentive(self):
        """NO_ACTION harus menggunakan IncentiveBand.NONE."""
        assert ACTION_CATALOGUE["NO_ACTION"].incentive_band == IncentiveBand.NONE

    def test_no_action_is_not_commercial(self):
        """NO_ACTION bukan aksi komersial."""
        assert ACTION_CATALOGUE["NO_ACTION"].is_commercial is False

    def test_no_action_does_not_block_commercial(self):
        """NO_ACTION sendiri tidak memblokir commercial (tidak sama dengan COMPLAINT_RESOLUTION)."""
        assert ACTION_CATALOGUE["NO_ACTION"].blocks_all_commercial is False


# ---------------------------------------------------------------------------
# Tests: COMPLAINT_RESOLUTION
# ---------------------------------------------------------------------------

class TestComplaintResolution:

    def test_complaint_resolution_is_not_commercial(self):
        """COMPLAINT_RESOLUTION bukan aksi komersial, tidak dihitung dalam fatigue."""
        assert ACTION_CATALOGUE["COMPLAINT_RESOLUTION"].is_commercial is False

    def test_complaint_resolution_blocks_all_commercial(self):
        """COMPLAINT_RESOLUTION harus memblokir semua aksi komersial lain."""
        assert ACTION_CATALOGUE["COMPLAINT_RESOLUTION"].blocks_all_commercial is True

    def test_complaint_resolution_has_highest_weight(self):
        """COMPLAINT_RESOLUTION harus memiliki action_weight tertinggi atau sangat tinggi."""
        cr_weight = ACTION_CATALOGUE["COMPLAINT_RESOLUTION"].action_weight
        assert cr_weight >= 1.5, f"COMPLAINT_RESOLUTION weight terlalu rendah: {cr_weight}"

    def test_complaint_resolution_channels(self):
        """COMPLAINT_RESOLUTION harus mencakup kanal RM atau branch."""
        channels = ACTION_CATALOGUE["COMPLAINT_RESOLUTION"].allowed_channels
        assert any("rm" in ch.lower() or "branch" in ch.lower() for ch in channels)


# ---------------------------------------------------------------------------
# Tests: Aksi Komersial
# ---------------------------------------------------------------------------

class TestCommercialActions:

    COMMERCIAL_ACTION_IDS = {
        "RELATIONSHIP_MANAGER_CONTACT",
        "RETENTION_OUTREACH",
        "CROSS_SELL",
        "UPSELL",
        "RENEWAL_REMINDER",
        "LOYALTY_REWARD",
        "WIN_BACK_OFFER",
        "EDUCATION",
    }

    def test_commercial_actions_have_channels(self):
        """Aksi komersial harus memiliki minimal satu kanal komunikasi."""
        for action_id in self.COMMERCIAL_ACTION_IDS:
            action = ACTION_CATALOGUE[action_id]
            assert len(action.allowed_channels) > 0, \
                f"{action_id} tidak memiliki allowed_channels"

    def test_retention_outreach_has_discount_incentive(self):
        """RETENTION_OUTREACH harus menggunakan insentif diskon berbatas waktu."""
        action = ACTION_CATALOGUE["RETENTION_OUTREACH"]
        assert action.incentive_band == IncentiveBand.DISCOUNT_LIMITED

    def test_loyalty_reward_has_loyalty_points_incentive(self):
        """LOYALTY_REWARD harus menggunakan insentif poin loyalitas."""
        action = ACTION_CATALOGUE["LOYALTY_REWARD"]
        assert action.incentive_band == IncentiveBand.LOYALTY_POINTS

    def test_service_reminder_is_not_commercial(self):
        """SERVICE_REMINDER adalah pengingat layanan, bukan promosi komersial."""
        assert ACTION_CATALOGUE["SERVICE_REMINDER"].is_commercial is False


# ---------------------------------------------------------------------------
# Tests: get_action
# ---------------------------------------------------------------------------

class TestGetAction:

    def test_get_existing_action(self):
        action = get_action("NO_ACTION")
        assert action is not None
        assert action.action_id == "NO_ACTION"

    def test_get_all_standard_actions(self):
        for action_id in EXPECTED_ACTION_IDS:
            action = get_action(action_id)
            assert action is not None, f"get_action('{action_id}') mengembalikan None"

    def test_get_nonexistent_action_returns_none(self):
        assert get_action("NONEXISTENT_ACTION") is None

    def test_get_action_returns_correct_type(self):
        action = get_action("CROSS_SELL")
        assert isinstance(action, Action)


# ---------------------------------------------------------------------------
# Tests: get_actions_by_category
# ---------------------------------------------------------------------------

class TestGetActionsByCategory:

    def test_get_retention_actions(self):
        actions = get_actions_by_category(ActionCategory.RETENTION)
        assert len(actions) > 0
        assert all(a.category == ActionCategory.RETENTION for a in actions)

    def test_get_protection_actions(self):
        actions = get_actions_by_category(ActionCategory.PROTECTION)
        action_ids = [a.action_id for a in actions]
        assert "NO_ACTION" in action_ids

    def test_get_growth_actions(self):
        actions = get_actions_by_category(ActionCategory.GROWTH)
        action_ids = [a.action_id for a in actions]
        assert "CROSS_SELL" in action_ids
        assert "UPSELL" in action_ids

    def test_empty_result_for_nonexistent_category(self):
        """Kategori yang tidak memiliki aksi mengembalikan list kosong."""
        # Buat kategori fake dengan nilai string
        class FakeCategory:
            value = "FAKE_CATEGORY"
        result = get_actions_by_category(FakeCategory())
        assert result == []


# ---------------------------------------------------------------------------
# Tests: list_all_action_ids
# ---------------------------------------------------------------------------

class TestListAllActionIds:

    def test_returns_list_of_strings(self):
        ids = list_all_action_ids()
        assert isinstance(ids, list)
        assert all(isinstance(i, str) for i in ids)

    def test_contains_all_expected_ids(self):
        ids = set(list_all_action_ids())
        assert EXPECTED_ACTION_IDS.issubset(ids)

    def test_count_matches_catalogue(self):
        assert len(list_all_action_ids()) == len(ACTION_CATALOGUE)
