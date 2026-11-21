"""Plain-Indonesian descriptions of model log-odds contributions.

Translates the exact mathematical decomposition already produced by
``propensity_inference.predict_rows`` and ``churn_inference.predict_rows``
into sentences a non-technical reader can follow. This module does not
invent a business reason, a cause, or a customer-level claim: it only
restates which feature pushed the model's internal score up or down, and
discloses when that feature's value was missing and had to be imputed.

Not a reason-code taxonomy, not NBA input, not approved for serving.
"""

from __future__ import annotations

import math
from typing import Any, TypeGuard

EXPLANATION_VERSION = "score-explanation-id-1.0"
NOTICE = (
    "Kalimat ini menjelaskan arah pengaruh fitur pada perhitungan model, "
    "bukan penyebab bisnis atau perilaku pelanggan yang sebenarnya."
)

_TARGET_LABELS = {
    "retail_purchase30": "skor pembelian retail dalam 30 hari",
    "renewal60": "skor perpanjangan dalam 60 hari",
    "churn90": "skor churn dalam 90 hari",
}

_FEATURE_LABELS = {
    "recency_days": "lama sejak aktivitas terakhir",
    "tenure_days": "lama pelanggan tercatat",
    "purchase_count_365d": "jumlah pembelian 365 hari terakhir",
    "retained_revenue_365d": "pendapatan yang dipertahankan 365 hari terakhir",
    "purchase_count_60d": "jumlah pembelian 60 hari terakhir",
    "purchase_count_90d": "jumlah pembelian 90 hari terakhir",
    "retained_revenue_90d": "pendapatan yang dipertahankan 90 hari terakhir",
}


def _finite_number(value: Any) -> TypeGuard[int | float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def explain_contributions(
    contributions: list[dict[str, Any]], *, target: str
) -> dict[str, Any]:
    """Build one sentence per nonzero contribution, in input order.

    ``contributions`` must be the exact ``feature_contributions``/
    ``contributions`` records already produced by the propensity or churn
    inference modules: each item carries ``feature``, ``feature_value``,
    ``missing``, ``imputed_value`` and ``log_odds_contribution``. This
    function reads them; it never recomputes or overrides them.
    """
    if target not in _TARGET_LABELS:
        raise ValueError(f"Unsupported target: {target!r}")
    if not isinstance(contributions, list):
        raise ValueError("contributions must be a list")

    target_label = _TARGET_LABELS[target]
    sentences: list[str] = []
    seen: set[str] = set()
    for entry in contributions:
        if not isinstance(entry, dict):
            raise ValueError("Each contribution must be a mapping")
        required = {
            "feature",
            "feature_value",
            "missing",
            "imputed_value",
            "log_odds_contribution",
        }
        if not required.issubset(entry):
            raise ValueError("Contribution is missing required fields")
        feature = entry.get("feature")
        if feature not in _FEATURE_LABELS:
            raise ValueError(f"Unmapped feature: {feature!r}")
        if feature in seen:
            raise ValueError(f"Duplicate feature in contributions: {feature}")
        seen.add(feature)

        missing = entry.get("missing")
        if not isinstance(missing, bool):
            raise ValueError("missing must be a boolean")
        value = entry.get("feature_value")
        if missing:
            if value is not None:
                raise ValueError("missing feature must have no feature_value")
        else:
            if not _finite_number(value) or value < 0:
                raise ValueError(f"{feature} feature_value must be finite nonnegative")

        imputed = entry["imputed_value"]
        if not _finite_number(imputed) or imputed < 0:
            raise ValueError(f"{feature} imputed_value must be finite nonnegative")
        if not missing and imputed != value:
            raise ValueError(f"{feature} imputed_value differs from feature_value")

        contribution = entry.get("log_odds_contribution")
        if not _finite_number(contribution):
            raise ValueError(f"{feature} log_odds_contribution must be finite")

        if contribution == 0:
            continue

        direction = "naik" if contribution > 0 else "turun"
        sentence = (
            f"Dalam perhitungan model, {_FEATURE_LABELS[feature]} mendorong "
            f"{target_label} {direction}."
        )
        if missing:
            sentence += " Data fitur ini kosong; model memakai nilai pengganti."
        sentences.append(sentence)

    return {
        "sentences": sentences,
        "notice": NOTICE,
        "version": EXPLANATION_VERSION,
    }
