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
    Pagu diskon global 30% adalah keputusan tim (tidak tertulis di Requirement_Capstone).
    Jika pagu di-set None, scanner kembali ke mode fail-closed.
    """

    def test_default_global_cap_is_thirty_percent(self):
        assert safety_module.MAX_DISCOUNT_PERCENT == 30.0

    @pytest.mark.parametrize("text", ["Diskon 5%", "Potongan 10 persen", "30% off"])
    def test_discount_within_default_cap_is_allowed(self, text):
        assert scan_message(text).is_safe

    @pytest.mark.parametrize("text", ["Diskon 31%", "Potongan 50 persen", "90% off"])
    def test_discount_above_default_cap_is_blocked(self, text):
        r = scan_message(text)
        assert not r.is_safe and RULE_DISCOUNT in r.rule_ids
        assert "melebihi pagu" in r.violations[0].description

    @pytest.mark.parametrize("text", ["Diskon 5%", "Potongan 10 persen", "20% off"])
    def test_any_discount_blocked_when_cap_is_none_fail_closed(self, text, monkeypatch):
        monkeypatch.setattr(safety_module, "MAX_DISCOUNT_PERCENT", None)
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

    def test_module_level_cap_is_used_when_changed(self, monkeypatch):
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


class TestForbiddenTerms:
    """Daftar kata terlarang dari tim; pencocokan kata utuh, tidak peka huruf besar/kecil."""

    @pytest.mark.parametrize("term", safety_module.FORBIDDEN_TERMS)
    def test_each_term_is_blocked(self, term):
        r = scan_message(f"Halo, kami punya {term} untuk Anda.")
        assert not r.is_safe and safety_module.RULE_FORBIDDEN_TERM in r.rule_ids

    @pytest.mark.parametrize(
        "text", ["MEDIS", "Terapeutik", "BEBAS   KOMEDO   SELAMANYA", "Klaim Obat"]
    )
    def test_case_and_spacing_insensitive(self, text):
        assert not scan_message(text).is_safe

    def test_term_list_is_exactly_the_team_decision(self):
        assert safety_module.FORBIDDEN_TERMS == [
            "garansi 100%",
            "pasti sembuh",
            "bebas komedo selamanya",
            "medis",
            "terapeutik",
            "klinis",
            "klaim obat",
        ]

    def test_whole_word_only(self):
        """'medisinal' / 'klinisi' bukan kata terlarang (kata utuh saja)."""
        assert scan_message("Layanan medisinal dan klinisi").is_safe

    def test_known_false_positive_non_medis_is_blocked(self):
        """Diketahui: 'non-medis' mengandung kata 'medis' sehingga ikut diblokir."""
        assert not scan_message("Perawatan non-medis").is_safe


class TestEscalation:
    def test_discount_violation_requires_escalation(self):
        r = scan_message("Diskon 50%")
        assert r.requires_escalation is True
        assert safety_module.ESCALATION_CODE == "INCENTIVE_ESCALATED"

    def test_other_violations_do_not_require_escalation(self):
        for text in ("pasti sembuh", "Halo {nama}", "klinis"):
            r = scan_message(text)
            assert not r.is_safe and r.requires_escalation is False

    def test_safe_message_does_not_require_escalation(self):
        assert scan_message("Halo Budi").requires_escalation is False
