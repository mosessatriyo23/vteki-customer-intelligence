"""
test_demo_script.py — Menjaga skrip demo (docs/christ_business/demo/run_demo.py) tetap
jalan dan tetap jujur: setiap bagian berlabel data sintetis, control = 0 paparan, dan
angka lift tidak muncul sebelum hasil konversi ada.

Jalankan: python -m pytest tests/decision/test_demo_script.py -v
"""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "docs" / "christ_business" / "demo" / "run_demo.py"


def _load():
    spec = importlib.util.spec_from_file_location("christ_run_demo", DEMO)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_demo_runs_offline_and_labels_everything_as_synthetic():
    demo = _load()
    buffer = io.StringIO()
    result = demo.main(buffer)
    text = buffer.getvalue()

    assert text.count(demo.SYNTHETIC_LABEL) >= 3  # awal, bagian hasil, akhir
    assert result.control_exposure_count == 0
    assert result.sent_count > 0
    assert "AWAITING_OUTCOMES" in text
    assert "TIDAK ditampilkan" in text
    assert "Rp 5.000.000" in text  # format Rupiah Indonesia pada bagian sintetis


def test_demo_first_section_shows_lift_numbers_only_after_outcomes_exist():
    demo = _load()
    buffer = io.StringIO()
    demo.main(buffer)
    text = buffer.getvalue()
    before_outcomes = text.split("[3]")[0]
    assert "Incremental revenue" not in before_outcomes
    assert "Lift conversion rate" not in before_outcomes
