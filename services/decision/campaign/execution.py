"""Pure transformation for a channel-simulator campaign result."""

from __future__ import annotations

from collections.abc import Iterable


def build_simulated_execution_result(
    *,
    customer_ids: Iterable[int],
    channel: str,
    ab_test_ratio: int,
    target_mode: str,
) -> dict[str, object]:
    """Summarize a worker-supplied audience without database or network access."""
    if not isinstance(channel, str) or not channel.endswith("_sim"):
        raise ValueError("Only simulator channels are supported")
    if isinstance(ab_test_ratio, bool) or not isinstance(ab_test_ratio, int):
        raise ValueError("A/B test ratio must be an integer")
    if not 0 <= ab_test_ratio <= 100:
        raise ValueError("A/B test ratio must be between 0 and 100")
    if target_mode not in {"segment", "single_customer"}:
        raise ValueError("Unknown campaign target mode")
    audience = tuple(customer_ids)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in audience):
        raise ValueError("Audience customer ids must be integers")
    if len(audience) != len(set(audience)):
        raise ValueError("Audience customer ids must be unique")
    variant_a = len(audience) * ab_test_ratio // 100
    return {
        "delivery_mode": "simulated",
        "external_delivery": False,
        "channel": channel,
        "target_mode": target_mode,
        "audience_size": len(audience),
        "variant_a_count": variant_a,
        "variant_b_count": len(audience) - variant_a,
        "customer_ids": list(audience),
    }
