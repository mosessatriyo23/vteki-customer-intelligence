"""Descriptive 90-day retention-by-lifecycle-segment diagnostic.

This is a retrospective aggregate over the *existing* development churn
label (``christ-churn90-three-events-dev-1.1``, ``horizon_days=90``). It
does not fit a model, estimate a 12-month CLV retention factor, or widen
the label's own eligible cohort (currently POS-transaction-based 365-day
history; see ``services.data.models.labels``). Any consumer that treats
this output as the 12-month CLV retention estimand, or as covering
visit/renewal-only customers, is misusing it.

No ``ground_truth`` field is read or required by this module.
"""

from __future__ import annotations

from collections import defaultdict

VALID_LABEL_VERSION = "christ-churn90-three-events-dev-1.1"
VALID_HORIZON_DAYS = 90


def _validate_label(row: dict) -> None:
    if row.get("label_version") != VALID_LABEL_VERSION:
        raise ValueError(
            "Only the christ-churn90-three-events-dev-1.1 label is accepted"
        )
    if row.get("horizon_days") != VALID_HORIZON_DAYS:
        raise ValueError("Only horizon_days=90 is accepted")
    eligible = row.get("eligible")
    if not isinstance(eligible, bool):
        raise ValueError("eligible must be an explicit boolean")
    complete = row.get("outcome_complete")
    if not isinstance(complete, bool):
        raise ValueError("outcome_complete must be an explicit boolean")
    churn90 = row.get("churn90")
    if complete and eligible:
        if (
            not isinstance(churn90, int)
            or isinstance(churn90, bool)
            or churn90 not in (0, 1)
        ):
            raise ValueError("churn90 must be 0 or 1 when complete and eligible")
    elif churn90 is not None:
        raise ValueError("churn90 must be null when incomplete or ineligible")


def summarize_retention90(labels: list[dict], segments: list[dict]) -> list[dict]:
    """Join labels to lifecycle segments by (golden_customer_id, cutoff_at).

    Returns one descriptive row per (lifecycle, cutoff_at, rule_version)
    group actually present in the join. Does not pool across cutoffs or
    segmentation rule versions, and never fabricates a rate when the
    eligible-and-complete denominator is zero.
    """
    for row in labels:
        _validate_label(row)

    label_index: dict[tuple[str, str], dict] = {}
    for row in labels:
        key = (row["golden_customer_id"], row["cutoff_at"])
        if key in label_index:
            raise ValueError("Duplicate (golden_customer_id, cutoff_at) in labels")
        label_index[key] = row

    segment_index: dict[tuple[str, str], dict] = {}
    for row in segments:
        key = (row["golden_customer_id"], row["cutoff_at"])
        if key in segment_index:
            raise ValueError("Duplicate (golden_customer_id, cutoff_at) in segments")
        segment_index[key] = row

    if label_index.keys() != segment_index.keys():
        raise ValueError("Label and segment keys must exactly match")

    groups: dict[tuple[str, str, str], dict] = defaultdict(
        lambda: {
            "eligible_complete_count": 0,
            "retained_count": 0,
            "excluded_incomplete_count": 0,
            "excluded_ineligible_count": 0,
        }
    )
    for key, label in label_index.items():
        segment = segment_index[key]
        group_key = (segment["lifecycle"], label["cutoff_at"], segment["rule_version"])
        bucket = groups[group_key]
        if not label["outcome_complete"]:
            bucket["excluded_incomplete_count"] += 1
            continue
        if not label["eligible"]:
            bucket["excluded_ineligible_count"] += 1
            continue
        bucket["eligible_complete_count"] += 1
        if label["churn90"] == 0:
            bucket["retained_count"] += 1

    output = []
    for (lifecycle, cutoff_at, rule_version), bucket in sorted(groups.items()):
        denominator = bucket["eligible_complete_count"]
        output.append(
            {
                "label_version": VALID_LABEL_VERSION,
                "horizon_days": VALID_HORIZON_DAYS,
                "cutoff_at": cutoff_at,
                "lifecycle": lifecycle,
                "rule_version": rule_version,
                "eligible_complete_count": denominator,
                "retained_count": bucket["retained_count"],
                "retention90_rate": (
                    bucket["retained_count"] / denominator if denominator > 0 else None
                ),
                "excluded_incomplete_count": bucket["excluded_incomplete_count"],
                "excluded_ineligible_count": bucket["excluded_ineligible_count"],
                "cohort_scope": "existing_pos_365d_eligible_subset",
                "clv_factor_ready": False,
            }
        )
    return output
