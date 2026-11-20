import pytest

from services.decision.campaign.execution import build_simulated_execution_result


def test_campaign_execution_returns_a_simulation_without_external_delivery():
    result = build_simulated_execution_result(
        customer_ids=[10, 12, 13],
        channel="email_sim",
        ab_test_ratio=50,
        target_mode="segment",
    )

    assert result == {
        "delivery_mode": "simulated",
        "external_delivery": False,
        "channel": "email_sim",
        "target_mode": "segment",
        "audience_size": 3,
        "variant_a_count": 1,
        "variant_b_count": 2,
        "customer_ids": [10, 12, 13],
    }


@pytest.mark.parametrize(
    ("channel", "ratio", "ids", "mode"),
    [
        ("email", 50, [1], "segment"),
        ("email_sim", True, [1], "segment"),
        ("email_sim", 50, [1, 1], "segment"),
        ("email_sim", 50, [1], "unsupported"),
    ],
)
def test_campaign_execution_rejects_invalid_or_non_simulated_inputs(
    channel, ratio, ids, mode
):
    with pytest.raises(ValueError):
        build_simulated_execution_result(
            customer_ids=ids,
            channel=channel,
            ab_test_ratio=ratio,
            target_mode=mode,
        )
