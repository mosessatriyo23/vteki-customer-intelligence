"""
test_contracts.py — Test kontrak integrasi INTG-v1.0 (K-06 s/d K-11) dan sinkronisasi
dengan `target_definitions.md` serta kode `services/decision/` (evaluasi Fase 1).

Jalankan: python -m pytest tests/decision/test_contracts.py -v
"""

import json
import re
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")
Draft7Validator = jsonschema.Draft7Validator

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
TARGET_DEFS = ROOT / "docs" / "christ_business" / "approved" / "target_definitions.md"
NAMES = [
    "K-06_action_catalogue",
    "K-07_decision_record",
    "K-08_campaign_identifier",
    "K-09_outcome_definition",
    "K-10_consent_contract",
    "K-11_audit_event_contract",
]


def load(name):
    return json.loads((CONTRACTS / f"{name}.json").read_text(encoding="utf-8"))


def k06_action_validator():
    k06 = load("K-06_action_catalogue")
    return Draft7Validator(
        {"$ref": "#/definitions/ActionDefinition", "definitions": k06["definitions"]}
    )


# --------------------------- Validitas skema ---------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_schema_is_valid_draft07_and_id_matches_filename(name):
    schema = load(name)
    Draft7Validator.check_schema(schema)
    assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert schema["$id"].endswith(f"/{name}.json")


# --------------------------- K-06 --------------------------------------------


class TestK06:
    BASE = dict(
        action_id="NO_ACTION",
        category="Proteksi / System",
        allowed_channels=[],
        incentive_band="Tanpa Insentif",
        required_fact_package=[],
    )

    def test_no_action_valid_without_facts_channels_or_incentive(self):
        assert k06_action_validator().is_valid(self.BASE)

    @pytest.mark.parametrize(
        "override",
        [
            {"allowed_channels": ["email"]},
            {"incentive_band": "Band Sedang"},
            {"required_fact_package": ["first_name"]},
        ],
    )
    def test_no_action_must_have_no_channel_no_incentive_no_facts(self, override):
        """Requirement Bab 4: NO_ACTION = Tanpa Kanal / Tanpa Insentif."""
        assert not k06_action_validator().is_valid({**self.BASE, **override})

    def test_business_action_requires_fact_package(self):
        action = {
            **self.BASE,
            "action_id": "CROSS_SELL",
            "category": "Pertumbuhan",
            "allowed_channels": ["email"],
            "incentive_band": "Band Rendah",
            "required_fact_package": ["first_name"],
        }
        v = k06_action_validator()
        assert v.is_valid(action)
        assert not v.is_valid({**action, "required_fact_package": []})

    def test_required_fields_per_panduan_minggu_2(self):
        required = load("K-06_action_catalogue")["definitions"]["ActionDefinition"][
            "required"
        ]
        assert set(required) == {
            "action_id",
            "category",
            "allowed_channels",
            "incentive_band",
            "required_fact_package",
        }

    def test_ten_business_actions_plus_no_action(self):
        enum = load("K-06_action_catalogue")["definitions"]["ActionDefinition"][
            "properties"
        ]["action_id"]["enum"]
        assert len(enum) == 11 and "NO_ACTION" in enum


# --------------------------- K-07 --------------------------------------------


class TestK07:
    def test_action_ids_match_k06(self):
        k06 = load("K-06_action_catalogue")["definitions"]["ActionDefinition"][
            "properties"
        ]["action_id"]["enum"]
        k07 = load("K-07_decision_record")["properties"]["selected_action_id"]["enum"]
        assert k06 == k07

    def test_required_fields_per_panduan_minggu_2(self):
        assert set(load("K-07_decision_record")["required"]) == {
            "decision_id",
            "customer_id",
            "selected_action_id",
            "expected_value",
            "candidates",
            "checks",
            "rationale_text",
            "correlation_id",
        }

    @staticmethod
    def _doc(**extra):
        return {
            "decision_id": "DEC-1",
            "customer_id": "C1",
            "selected_action_id": "NO_ACTION",
            "expected_value": 0.0,
            "candidates": [],
            "checks": [],
            "rationale_text": "NO_ACTION",
            "correlation_id": "corr-1",
            **extra,
        }

    @pytest.mark.parametrize(
        "reason",
        ["OPT_OUT_SUPPRESSED", "FREQ_CAP_SUPPRESSED", "ALL_CANDIDATES_BLOCKED", None],
    )
    def test_no_action_reason_accepts_documented_codes(self, reason):
        v = Draft7Validator(load("K-07_decision_record"))
        assert v.is_valid(self._doc(no_action_reason=reason, degraded_input=True))

    def test_no_action_reason_rejects_unknown_code(self):
        v = Draft7Validator(load("K-07_decision_record"))
        assert not v.is_valid(self._doc(no_action_reason="SOMETHING_ELSE"))

    def test_degraded_input_must_be_boolean(self):
        v = Draft7Validator(load("K-07_decision_record"))
        assert not v.is_valid(self._doc(degraded_input="yes"))


# --------------------------- K-08 / K-09 / K-11 -------------------------------


def test_k08_windows_per_panduan_minggu_3():
    k08 = load("K-08_campaign_identifier")
    props = k08["properties"]
    assert props["conversion_window_days"]["default"] == 30
    assert props["adjustment_window_days"]["default"] == 14
    assert {
        "campaign_id",
        "exposure_window",
        "conversion_window_days",
        "adjustment_window_days",
    } <= set(k08["required"])


def test_k09_conversion_types_per_panduan_minggu_4():
    enum = load("K-09_outcome_definition")["properties"]["conversion_type"]["enum"]
    assert set(enum) == {"BOOKING", "PURCHASE", "MEMBERSHIP_RENEWAL", "UPGRADE"}


def test_k11_requires_x_correlation_id():
    assert "X-Correlation-ID" in load("K-11_audit_event_contract")["required"]


def test_correlation_id_pattern_is_identical_across_contracts():
    patterns = set()
    for name, key in [
        ("K-07_decision_record", "correlation_id"),
        ("K-08_campaign_identifier", "correlation_id"),
        ("K-09_outcome_definition", "correlation_id"),
        ("K-10_consent_contract", "correlation_id"),
        ("K-11_audit_event_contract", "X-Correlation-ID"),
    ]:
        patterns.add(load(name)["properties"][key]["pattern"])
    assert patterns == {"^[A-Za-z0-9._:-]{1,128}$"}


# --------------------------- K-10 --------------------------------------------


class TestK10:
    @staticmethod
    def _doc(channels, **extra):
        return {
            "customer_id": "C1",
            "global_consent": {"status": "OPT_IN", "is_global_opt_out": False},
            "channels": channels,
            "unknown_expired_policy": "BLOCKED",
            "identity_merge_policy": "MOST_RESTRICTIVE_WINS",
            "most_restrictive_wins": True,
            **extra,
        }

    @pytest.mark.parametrize("status", ["UNKNOWN", "EXPIRED", "OPT_OUT", "BLOCKED"])
    def test_non_opt_in_status_cannot_be_allowed(self, status):
        """Panduan Minggu 3: unknown/expired = blocked."""
        v = Draft7Validator(load("K-10_consent_contract"))
        blocked = {"status": status, "opt_in": False, "effective_permission": "BLOCKED"}
        allowed = {"status": status, "opt_in": True, "effective_permission": "ALLOWED"}
        assert v.is_valid(self._doc({"email": blocked}))
        assert not v.is_valid(self._doc({"email": allowed}))

    def test_opt_in_can_be_allowed(self):
        v = Draft7Validator(load("K-10_consent_contract"))
        ok = {"status": "OPT_IN", "opt_in": True, "effective_permission": "ALLOWED"}
        assert v.is_valid(self._doc({"push": ok}))

    def test_most_restrictive_wins_cannot_be_false(self):
        v = Draft7Validator(load("K-10_consent_contract"))
        assert not v.is_valid(self._doc({}, most_restrictive_wins=False))

    def test_customer_id_types_consistent_with_k07(self):
        """K-10 harus menerima semua tipe customer_id yang diterima K-07."""
        k07_types = set(
            load("K-07_decision_record")["properties"]["customer_id"]["type"]
        )
        k10_types = load("K-10_consent_contract")["properties"]["customer_id"]["type"]
        assert k07_types <= set(k10_types)


# --------------------------- Sinkronisasi dengan kode -------------------------


def _doc_constants():
    text = TARGET_DEFS.read_text(encoding="utf-8")
    block = re.search(r"## Lampiran.*?```python\n(.*?)```", text, re.S).group(1)
    ns = {}
    exec(block, {}, ns)  # noqa: S102 - blok konstanta statis milik repo ini
    return ns


def test_doc_constants_match_code():
    from services.decision.nba.engine import DEFAULT_SCORE_VALIDITY_DAYS
    from services.decision.policy.fatigue import (
        FREQ_CAP_MAX_CONTACTS,
        FREQ_CAP_WINDOW_DAYS,
    )

    c = _doc_constants()
    assert c["FREQ_CAP_MAX_CONTACTS"] == FREQ_CAP_MAX_CONTACTS == 2
    assert c["FREQ_CAP_WINDOW_DAYS"] == FREQ_CAP_WINDOW_DAYS == 14
    assert c["SCORE_VALIDITY_DAYS"] == DEFAULT_SCORE_VALIDITY_DAYS == 30


def test_churn_label_window_is_90_days_forward():
    """Label churn = jendela 90 hari KE DEPAN (Panduan Minggu 1, business_events.md)."""
    c = _doc_constants()
    assert c["PREDICTION_HORIZON_DAYS"] == 90
    assert "CHURN_DEFINITION_DAYS" not in c  # 180 hari ke belakang dicabut (v1.1)
    text = TARGET_DEFS.read_text(encoding="utf-8")
    definition = text.split("### 1.1")[1].split("> **Sumber v1.1")[0]
    assert "90 hari ke depan" in definition
    # definisi v1.0 yang keliru (ke belakang + sirkular) tidak boleh kembali
    assert "ke belakang" not in definition
    assert "tidak diprediksi aktif" not in definition
    for event in (
        "transaksi POS",
        "Kunjungan fisik terverifikasi",
        "Perpanjangan keanggotaan",
    ):
        assert event in definition


def test_doc_lifecycle_and_clv_thresholds():
    c = _doc_constants()
    assert (c["CLV_TIER_PLATINUM"], c["CLV_TIER_GOLD"], c["CLV_TIER_SILVER"]) == (
        1_000_000,
        500_000,
        200_000,
    )
    assert (c["LIFECYCLE_AT_RISK_START"], c["LIFECYCLE_AT_RISK_END"]) == (91, 180)
    assert (c["LIFECYCLE_DORMANT_START"], c["LIFECYCLE_DORMANT_END"]) == (181, 365)


def test_doc_has_matrix_for_all_nine_segments():
    text = TARGET_DEFS.read_text(encoding="utf-8")
    matrix = text.split("### 3.1 Matriks Alokasi Perlakuan per Segmen")[1].split(
        "\n---\n"
    )[0]
    for seg in (
        "NEW",
        "ACTIVE",
        "LOYAL",
        "AT_RISK",
        "DORMANT",
        "CHURNED",
        "REACTIVATED",
        "OCCASIONAL",
        "NEVER_TRANSACTED",
    ):
        assert f"`{seg}`" in matrix, seg


# --------------------------- Catalogue.py vs K-06 -----------------------------


def test_catalogue_ids_match_k06_enum():
    from services.decision.nba.catalogue import ACTION_CATALOGUE

    enum = load("K-06_action_catalogue")["definitions"]["ActionDefinition"][
        "properties"
    ]["action_id"]["enum"]
    assert set(ACTION_CATALOGUE) == set(enum)


def test_exported_catalogue_validates_against_k06():
    """Seluruh 11 aksi di catalogue.py menghasilkan dokumen K-06 yang valid."""
    from services.decision.nba.catalogue import export_k06_catalogue

    doc = export_k06_catalogue()
    errors = [
        e.message
        for e in Draft7Validator(load("K-06_action_catalogue")).iter_errors(doc)
    ]
    assert errors == []
    assert doc["total_actions"] == 11 and doc["contract_version"] == "INTG-v1.0"


def test_each_exported_action_validates_individually():
    from services.decision.nba.catalogue import export_k06_catalogue

    v = k06_action_validator()
    for action in export_k06_catalogue()["actions"]:
        assert v.is_valid(action), action["action_id"]


def test_no_action_exported_without_channels_incentive_or_facts():
    from services.decision.nba.catalogue import ACTION_CATALOGUE

    na = ACTION_CATALOGUE["NO_ACTION"]
    assert na.allowed_channels == []
    assert na.incentive_band.value == "Tanpa Insentif"
    assert na.required_fact_package == []


# --------------------------- K-08: holdout (Panduan Minggu 9) -----------------


class TestK08Holdout:
    BASE = {
        "campaign_id": "CMP-1",
        "exposure_window": {
            "start_time": "2026-11-01T00:00:00Z",
            "end_time": "2026-11-30T00:00:00Z",
        },
        "conversion_window_days": 30,
        "adjustment_window_days": 14,
    }

    def validator(self):
        return Draft7Validator(load("K-08_campaign_identifier"))

    def test_existing_documents_stay_valid_backward_compatible(self):
        assert self.validator().is_valid(self.BASE)

    def test_exposure_window_field_is_not_renamed_and_still_required(self):
        k08 = load("K-08_campaign_identifier")
        assert "exposure_window" in k08["required"]
        assert "exposure_start_window" not in k08["properties"]

    def test_default_holdout_ratio_is_ten_percent(self):
        props = load("K-08_campaign_identifier")["properties"]
        assert props["control_holdout_ratio"]["default"] == 0.1
        assert props["ab_test_ratio"]["default"] == 90  # 100 - 10

    def test_holdout_requires_random_seed(self):
        v = self.validator()
        assert v.is_valid(
            {**self.BASE, "control_holdout_ratio": 0.1, "random_seed": 42}
        )
        assert not v.is_valid({**self.BASE, "control_holdout_ratio": 0.1})

    @pytest.mark.parametrize("ratio", [0, 1, -0.1, 1.5])
    def test_holdout_ratio_must_be_strictly_between_zero_and_one(self, ratio):
        assert not self.validator().is_valid(
            {**self.BASE, "control_holdout_ratio": ratio, "random_seed": 1}
        )

    def test_random_seed_must_be_integer(self):
        assert not self.validator().is_valid(
            {**self.BASE, "control_holdout_ratio": 0.1, "random_seed": "abc"}
        )

    def test_treatment_share_is_not_stored_separately(self):
        """Porsi treatment = 1 - holdout; tidak disimpan agar tidak bisa saling bertentangan."""
        assert "treatment_share" not in load("K-08_campaign_identifier")["properties"]

    def test_existing_status_field_kept(self):
        status = load("K-08_campaign_identifier")["properties"]["status"]["enum"]
        assert {"DRAFT", "APPROVED", "ACTIVE", "COMPLETED", "CANCELLED"} <= set(status)


def test_k07_no_action_reason_includes_below_min_ev():
    enum = load("K-07_decision_record")["properties"]["no_action_reason"]["enum"]
    assert set(enum) == {
        "OPT_OUT_SUPPRESSED",
        "FREQ_CAP_SUPPRESSED",
        "ALL_CANDIDATES_BLOCKED",
        "BELOW_MIN_EV",
        None,
    }


def test_team_decision_constants_match_code():
    """Keputusan tim di target_definitions v1.2 harus sama dengan konstanta di kode/kontrak."""
    from services.decision.nba.engine import DEFAULT_MIN_EV_THRESHOLD
    from services.decision.nba.evaluator import SERVICE_REMINDER_WINDOW_DAYS
    from services.decision.nudge.safety import MAX_DISCOUNT_PERCENT

    c = _doc_constants()
    assert c["MIN_EV_THRESHOLD_IDR"] == DEFAULT_MIN_EV_THRESHOLD == 1000.0
    assert c["MAX_DISCOUNT_PERCENT"] == MAX_DISCOUNT_PERCENT == 30.0
    assert c["SERVICE_REMINDER_WINDOW_DAYS"] == SERVICE_REMINDER_WINDOW_DAYS == 7
    k08 = load("K-08_campaign_identifier")["properties"]
    assert c["CONTROL_HOLDOUT_RATIO"] == k08["control_holdout_ratio"]["default"] == 0.1
