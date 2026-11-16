"""Development-only numeric distribution drift; no retraining or I/O.

Bins use fixed shared edges: (-inf, edge[0]), [edge[0], edge[1]),
..., [edge[-1], inf). None is always counted in a separate missing bin.
Each bin is smoothed with epsilon pseudo-observations in *both* populations:
(count + epsilon) / (population_size + epsilon * number_of_bins).
"""

import math
from bisect import bisect_right
from decimal import Decimal
from numbers import Real


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (Real, Decimal)):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def classify_drift(value: float) -> str:
    """Apply the fixed PSI/CSI thresholds (0.10 and 0.25)."""
    score = _finite(value, "drift")
    if Decimal(str(score)) >= Decimal("0.25"):
        return "RETRAIN_RECOMMENDED"
    if Decimal(str(score)) >= Decimal("0.10"):
        return "WARNING"
    if score < 0:
        raise ValueError("drift must be nonnegative")
    return "STABLE"


def _distribution(baseline, current, bin_edges, epsilon: float, metric: str) -> dict:
    edges = tuple(_finite(edge, "bin edge") for edge in bin_edges)
    if not edges or any(left >= right for left, right in zip(edges, edges[1:])):
        raise ValueError("bin_edges must be nonempty and strictly increasing")
    smoothing = _finite(epsilon, "epsilon")
    if smoothing <= 0:
        raise ValueError("epsilon must be positive")

    counts = []
    for name, population in (("baseline", baseline), ("current", current)):
        bins = [0] * (len(edges) + 2)
        for value in population:
            index = (
                len(bins) - 1
                if value is None
                else bisect_right(edges, _finite(value, name))
            )
            bins[index] += 1
        if not sum(bins):
            raise ValueError(f"{name} population must be nonempty")
        counts.append(bins)

    base, now = counts
    labels = [
        {
            "lower": None if i == 0 else edges[i - 1],
            "upper": None if i == len(edges) else edges[i],
            "missing": False,
        }
        for i in range(len(edges) + 1)
    ]
    labels.append({"lower": None, "upper": None, "missing": True})
    bins_report = []
    for label, base_count, now_count in zip(labels, base, now):
        base_share = (base_count + smoothing) / (sum(base) + smoothing * len(base))
        now_share = (now_count + smoothing) / (sum(now) + smoothing * len(now))
        contribution = (now_share - base_share) * math.log(now_share / base_share)
        bins_report.append(
            {
                **label,
                "baseline_count": base_count,
                "current_count": now_count,
                "baseline_share": base_share,
                "current_share": now_share,
                "contribution": contribution,
            }
        )
    value = math.fsum(bin_["contribution"] for bin_ in bins_report)
    return {
        "metric": metric,
        "value": value,
        "status": classify_drift(value),
        "bin_edges": edges,
        "epsilon": smoothing,
        "baseline_count": sum(base),
        "current_count": sum(now),
        "bins": bins_report,
        "training_ready": False,
        "experiment_ready": False,
        "final_model": False,
    }


def population_stability_index(
    baseline, current, bin_edges, epsilon: float = 1e-6
) -> dict:
    """Report PSI over numeric values and an explicit missing bin."""
    return _distribution(baseline, current, bin_edges, epsilon, "PSI")


def characteristic_stability_index(
    baseline, current, bin_edges, epsilon: float = 1e-6
) -> dict:
    """Report CSI for one feature using the identical fixed-bin algorithm."""
    return _distribution(baseline, current, bin_edges, epsilon, "CSI")


def auc_drop(baseline_auc: float | None, current_auc: float | None) -> dict:
    """Flag a strictly greater than 0.05 ROC AUC drop; None means unavailable."""
    baseline = None if baseline_auc is None else _finite(baseline_auc, "baseline_auc")
    current = None if current_auc is None else _finite(current_auc, "current_auc")
    if any(value is not None and not 0 <= value <= 1 for value in (baseline, current)):
        raise ValueError("ROC AUC must be between 0 and 1")
    drop = (
        None
        if baseline is None or current is None
        else Decimal(str(baseline)) - Decimal(str(current))
    )
    flagged = drop is not None and drop > Decimal("0.05")
    return {
        "metric": "ROC_AUC_DROP",
        "baseline_auc": baseline,
        "current_auc": current,
        "drop": None if drop is None else float(drop),
        "status": (
            "UNAVAILABLE"
            if drop is None
            else ("RETRAIN_RECOMMENDED" if flagged else "STABLE")
        ),
        "retrain_recommended": flagged,
        "training_ready": False,
        "experiment_ready": False,
        "final_model": False,
    }
