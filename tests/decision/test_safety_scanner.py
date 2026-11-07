"""
test_safety_scanner.py — Test Safety Scanner / Forbidden Claims Detector (Minggu 8).

Jalankan: python -m pytest tests/decision/test_safety_scanner.py -v
"""

import pytest

from services.decision.nudge import safety as safety_module
from services.decision.nudge.safety import (
    RULE_DISCOUNT,
    RULE_GUARANTEE,
    RULE_MEDICAL,
    RULE_PLACEHOLDER,
    STATUS_BLOCKED,
    STATUS_SAFE,
    scan_message,
)


class TestSafeMessages:
    @pytest.mark.parametrize(
        "text",
        [
            "Halo Budi, kami rindu melihat Anda di cabang Yogya.",
            "Saldo poin Anda 1200 poin dan berlaku sampai 31-12-2026.",
            "Kepuasan pelanggan naik 90% tahun ini.",
            "",
        ],
    )
    def test_safe(self, text):
        r = scan_message(text)
        assert r.is_safe is True
        assert r.status == STATUS_SAFE
        assert r.violations == []


class TestMedicalClaims:
    @pytest.mark.parametrize(
        "text",
        [
            "Produk ini menyembuhkan nyeri sendi.",
            "Terapi penyembuhan terbaik untuk Anda.",
            "Layanan kami dapat mencegah penyakit kanker.",
            "TERBUKTI SECARA KLINIS efektif.",
            "Bebas penyakit selamanya.",
        ],
    )
    def test_blocked(self, text):
        r = scan_message(text)
        assert not r.is_safe and r.status == STATUS_BLOCKED
        assert RULE_MEDICAL in r.rule_ids


class TestGuarantees:
    @pytest.mark.parametrize(
        "text",
        [
            "Hasil 100% dijamin!",
            "Garansi 100% untuk Anda.",
            "Pasti berhasil tanpa risiko.",
            "Dijamin berhasil.",
            "Seratus persen pasti aman.",
            "Result guaranteed",
            "100 % dijamin",
        ],
    )
    def test_blocked(self, text):
        r = scan_message(text)
        assert not r.is_safe
        assert RULE_GUARANTEE in r.rule_ids


class TestDiscountCap:
    """
    Pagu diskon TIDAK tertulis di Requirement_Capstone / target_definitions / K-06..K-11.
    Default = belum ditetapkan -> fail-closed (semua diskon persentase diblokir).
    """

    def test_default_cap_is_not_configured(self):
        assert safety_module.MAX_DISCOUNT_PERCENT is None

    @pytest.mark.parametrize("text", ["Diskon 5%", "Potongan 10 persen", "20% off"])
    def test_any_percentage_discount_blocked_when_cap_undefined(self, text):
        r = scan_message(text)
        assert not r.is_safe and RULE_DISCOUNT in r.rule_ids
        assert "belum ditetapkan" in r.violations[0].description

    def test_explicit_cap_equal_is_allowed(self):
        assert scan_message("Diskon 30% untuk Anda", max_discount_percent=30).is_safe

    @pytest.mark.parametrize(
        "text",
        [
            "Diskon 50% hari ini",
            "Potongan 70 persen",
            "Hemat 90%!",
            "Dapatkan 40% off",
            "Diskon hingga 80%",
            "diskon 99,5%",
            "DISKON 100%",
        ],
    )
    def test_above_explicit_cap_blocked(self, text):
        r = scan_message(text, max_discount_percent=30)
        assert not r.is_safe
        assert RULE_DISCOUNT in r.rule_ids
        assert "melebihi pagu" in r.violations[0].description

    def test_custom_cap_values(self):
        assert scan_message("Diskon 40%", max_discount_percent=50).is_safe
        assert not scan_message("Diskon 40%", max_discount_percent=20).is_safe

    def test_module_level_cap_is_used_when_set(self, monkeypatch):
        monkeypatch.setattr(safety_module, "MAX_DISCOUNT_PERCENT", 25.0)
        assert scan_message("Diskon 25%").is_safe
        assert not scan_message("Diskon 26%").is_safe

    def test_non_discount_percentage_is_ignored(self):
        assert scan_message("Kepuasan pelanggan naik 90% tahun ini.").is_safe


class TestPlaceholdersAndEvasion:
    def test_unresolved_placeholder_blocked(self):
        r = scan_message("Halo {first_name}, selamat datang")
        assert not r.is_safe and RULE_PLACEHOLDER in r.rule_ids

    def test_case_and_extra_whitespace_do_not_evade(self):
        assert not scan_message("PASTI    BERHASIL").is_safe
        assert not scan_message("dis\u200bkon 90%", max_discount_percent=30).is_safe
        assert not scan_message(
            "pasti\u00adberhasil".replace("\u00ad", " \u00ad")
        ).is_safe

    def test_multiple_violations_all_reported(self):
        r = scan_message(
            "Diskon 90%, 100% dijamin menyembuhkan!", max_discount_percent=30
        )
        assert set(r.rule_ids) >= {RULE_DISCOUNT, RULE_GUARANTEE, RULE_MEDICAL}

    def test_non_string_raises(self):
        with pytest.raises(TypeError):
            scan_message(None)  # type: ignore[arg-type]
