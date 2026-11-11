"""
timeutil.py — Helper waktu bersama modul Decisioning (Fase 3)
=============================================================
Seluruh modul Fase 3 (simulator, holdout, uplift, atribusi, forecasting) memakai
konvensi yang sama dengan `policy/fatigue.py`: datetime NAIF dalam UTC.

Kontrak K-08 / K-09 mengirim waktu sebagai string ISO-8601 (mis. "2026-11-01T10:00:00Z").
`to_naive_utc` menerima `datetime` (naif atau beraksesoris zona waktu) maupun string ISO-8601
dan selalu mengembalikan datetime naif UTC, sehingga perbandingan antar-modul tidak pernah
gagal karena "can't compare offset-naive and offset-aware datetimes".
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Union


def utc_now() -> datetime:
    """Waktu sekarang sebagai datetime naif UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive_utc(value: Union[datetime, str]) -> datetime:
    """
    Mengubah `datetime` atau string ISO-8601 menjadi datetime naif UTC.

    - String berakhiran "Z" dianggap UTC.
    - datetime beraksesoris zona waktu dikonversi ke UTC lalu zona waktunya dibuang.
    - datetime naif dianggap sudah UTC.

    Raises:
        TypeError: tipe selain datetime / str.
        ValueError: string bukan ISO-8601 yang valid.
    """
    if isinstance(value, str):
        text = value.strip()
        if text[-1:] in ("Z", "z"):
            text = text[:-1] + "+00:00"
        value = datetime.fromisoformat(text)
    if not isinstance(value, datetime):
        raise TypeError(
            f"Nilai waktu harus datetime atau string ISO-8601, bukan {type(value).__name__}."
        )
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value
