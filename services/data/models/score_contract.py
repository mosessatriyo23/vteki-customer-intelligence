"""Development-only validation of a proposed AI-to-decision score handoff.

No score producer is wired to this module. Passing validation does not authorize
training, deployment, customer selection, or use in the decision engine.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from services.decision.nba.engine import AIScores


@dataclass(frozen=True)
class ScoreContractResult:
    valid: bool
    errors: tuple[str, ...]


def _finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def validate_score_handoff(
    scores: AIScores, *, expected_customer_id: str, known_at: datetime
) -> ScoreContractResult:
    """Check the proposed handoff against an explicit customer and knowledge cutoff.

    The band/tier are checked for vocabulary only: numeric mapping thresholds
    have not been approved. Missing explanations are reported, never fabricated.
    """
    errors: list[str] = []
    if not isinstance(expected_customer_id, str) or not expected_customer_id.strip():
        errors.append("expected_customer_id_missing")
    if (
        not isinstance(scores.customer_id, str)
        or not scores.customer_id.strip()
        or scores.customer_id != expected_customer_id
    ):
        errors.append("customer_id_mismatch")
    if (
        not isinstance(known_at, datetime)
        or known_at.tzinfo is None
        or known_at.utcoffset() is None
    ):
        errors.append("known_at_not_aware")
    if (
        not isinstance(scores.score_generated_at, datetime)
        or scores.score_generated_at.tzinfo is None
        or scores.score_generated_at.utcoffset() is None
    ):
        errors.append("score_generated_at_not_aware")
    elif "known_at_not_aware" not in errors:
        if scores.score_generated_at > known_at:
            errors.append("score_generated_after_known_at")
    for field in ("churn_score", "propensity_purchase", "propensity_renew"):
        value = getattr(scores, field)
        if not _finite_number(value) or not 0 <= value <= 1:
            errors.append(f"{field}_invalid")
    if not _finite_number(scores.clv_amount) or scores.clv_amount < 0:
        errors.append("clv_amount_invalid")
    if scores.churn_risk_band not in ("LOW", "MEDIUM", "HIGH", "VERY_HIGH"):
        errors.append("churn_risk_band_unknown")
    if scores.clv_tier not in ("PLATINUM", "GOLD", "SILVER", "INSUFFICIENT_HISTORY"):
        errors.append("clv_tier_unknown")
    if not isinstance(scores.reason_codes, list) or not all(
        isinstance(code, str) and bool(code.strip()) for code in scores.reason_codes
    ):
        errors.append("reason_codes_invalid")
    elif len(set(scores.reason_codes)) < 3:
        errors.append("reason_codes_insufficient")
    return ScoreContractResult(valid=not errors, errors=tuple(errors))
