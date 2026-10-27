"""
conftest.py — Shared pytest configuration untuk test suite Christ Business.
============================================================================
Menyediakan fixtures yang dapat digunakan di seluruh file test.
"""

import sys
from pathlib import Path

# Pastikan root proyek ada di sys.path agar import relatif berjalan
PROJECT_ROOT = Path(__file__).resolve().parents[4]  # 4 level naik dari test/ ke project root
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
