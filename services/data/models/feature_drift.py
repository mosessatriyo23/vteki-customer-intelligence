"""Offline, descriptive-only distribution comparison for the seven Moses features.

Compares the purged training (non-holdout) rows behind an existing development
model manifest against a current feature snapshot. Reports per-feature PSI,
decile histograms, missing rates, and current values outside the reference
range. This is diagnostic reading only: no alert thresholds, no retraining
recommendation, and no performance claim are produced.
"""

import argparse
import csv
import json
import math
from pathlib import Path

from services.data.features.snapshot import FIELDS as FEATURE_FIELDS
from services.data.features.snapshot import VERSION as FEATURE_VERSION
from services.data.ingestion.validator import sha256
from services.data.models.baseline import temporal_split
from services.data.models.churn_experiment import FEATURES
from services.data.models.labels import CHRIST_VERSION, TRAINING_FIELDS
from services.data.monitoring.drift import population_stability_index

EPSILON = 1e-6
DECILES = (10, 20, 30, 40, 50, 60, 70, 80, 90)


def _value(row: dict, field: str) -> float | None:
    """Finite, nonnegative numeric value; missing is allowed for recency only."""
    value = row.get(field)
    if value is None or value == "":
        if field == "recency_days":
            return None
        raise ValueError(f"{field} must be finite nonnegative numeric")
    if isinstance(value, bool):
        raise ValueError(f"{field} must be finite nonnegative numeric")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be finite nonnegative numeric") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{field} must be finite nonnegative numeric")
    return number


def _column(rows: list[dict], field: str) -> list[float | None]:
    return [_value(row, field) for row in rows]


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Linear-interpolation percentile; numpy is used if present, not required."""
    try:
        import numpy as np  # optional model dependency (requirements-models.txt)
    except ImportError:
        np = None
    if np is not None:
        return float(np.percentile(sorted_values, pct))
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100) * (len(sorted_values) - 1)
    lower, upper = math.floor(rank), math.ceil(rank)
    if lower == upper:
        return sorted_values[lower]
    weight = rank - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _bin_edges(present_train: list[float]) -> tuple[float, ...]:
    """Fixed-decile boundaries from train-only values; safe for constant/empty."""
    if not present_train:
        return ()
    ordered = sorted(present_train)
    edges: list[float] = []
    for pct in DECILES:
        edge = _percentile(ordered, pct)
        if not edges or edge > edges[-1]:
            edges.append(edge)
    return tuple(edges)


def _out_of_reference_range(
    train_values: list[float | None], current_values: list[float | None]
) -> int:
    present_train = [v for v in train_values if v is not None]
    present_current = [v for v in current_values if v is not None]
    if not present_train:
        return len(present_current)
    low, high = min(present_train), max(present_train)
    return sum(1 for value in present_current if value < low or value > high)


def _feature_report(
    train_values: list[float | None], current_values: list[float | None]
) -> dict:
    present_train = [v for v in train_values if v is not None]
    # The shared helper requires a nonempty edge set. With no observed train
    # recency, zero is a synthetic boundary, not an estimated quantile.
    edges = _bin_edges(present_train) or (0.0,)
    distribution = population_stability_index(
        train_values, current_values, edges, epsilon=EPSILON
    )
    train_total, current_total = len(train_values), len(current_values)
    bins_report = [
        {
            "lower": bin_["lower"],
            "upper": bin_["upper"],
            "missing": bin_["missing"],
            "reference_count": bin_["baseline_count"],
            "current_count": bin_["current_count"],
            "reference_fraction": bin_["baseline_share"],
            "current_fraction": bin_["current_share"],
            "contribution": bin_["contribution"],
        }
        for bin_ in distribution["bins"]
    ]
    return {
        "psi": distribution["value"],
        "epsilon": EPSILON,
        "bin_edges": edges,
        "bins": bins_report,
        "reference_count": train_total,
        "current_count": current_total,
        "reference_missing_rate": (train_total - len(present_train)) / train_total,
        "current_missing_rate": (
            current_total - sum(1 for v in current_values if v is not None)
        )
        / current_total,
        "reference_range": (
            None if not present_train else [min(present_train), max(present_train)]
        ),
        "current_out_of_reference_range_count": _out_of_reference_range(
            train_values, current_values
        ),
        "descriptive_only": True,
        "readiness": False,
    }


def _disjoint(*directories: Path) -> None:
    for i, a in enumerate(directories):
        for b in directories[i + 1 :]:
            if a == b or a in b.parents or b in a.parents:
                raise ValueError(
                    "Reference, current, and output directories must be disjoint"
                )


def run(reference_dir: Path, current_dir: Path, output_dir: Path) -> dict:
    """Compare purged reference training rows against a current feature snapshot."""
    if output_dir.exists():
        raise ValueError("Use a new output directory")
    reference_dir, current_dir, output_dir = (
        Path(reference_dir).resolve(),
        Path(current_dir).resolve(),
        Path(output_dir).resolve(),
    )
    parts = reference_dir.parts + current_dir.parts + output_dir.parts
    if any(part.lower() == "ground_truth" for part in parts):
        raise ValueError("ground_truth paths are not allowed")
    _disjoint(reference_dir, current_dir, output_dir)

    reference_paths = {
        name: reference_dir / name
        for name in ("model_manifest.json", "training_rows.csv")
    }
    current_paths = {
        name: current_dir / name for name in ("feature_manifest.json", "features.csv")
    }
    before = {
        "reference": {name: sha256(path) for name, path in reference_paths.items()},
        "current": {name: sha256(path) for name, path in current_paths.items()},
    }

    reference_manifest = json.loads(
        reference_paths["model_manifest.json"].read_text(encoding="utf-8")
    )
    if (
        reference_manifest.get("experiment_ready") is not False
        or reference_manifest.get("final_model") is not False
    ):
        raise ValueError("Development-only reference manifest required")
    if (
        tuple(reference_manifest.get("feature_fields", ())) != FEATURE_FIELDS
        or reference_manifest.get("label_version") != CHRIST_VERSION
        or reference_manifest.get("horizon_days") != 90
    ):
        raise ValueError("Unexpected reference contract")
    if (
        reference_manifest.get("output_sha256", {}).get("training_rows.csv")
        != before["reference"]["training_rows.csv"]
    ):
        raise ValueError("Reference training row checksum mismatch")
    with reference_paths["training_rows.csv"].open(
        newline="", encoding="utf-8"
    ) as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != TRAINING_FIELDS:
            raise ValueError("Unexpected training row columns")
        training_rows = list(reader)
    if len(training_rows) != reference_manifest.get("training_rows"):
        raise ValueError("Reference training row count mismatch")

    current_manifest = json.loads(
        current_paths["feature_manifest.json"].read_text(encoding="utf-8")
    )
    if current_manifest.get("training_ready") is not False:
        raise ValueError("Current feature manifest must be training_ready=False")
    if current_manifest.get("feature_version") != FEATURE_VERSION:
        raise ValueError("Unexpected current feature version")
    if (
        current_manifest.get("output_sha256", {}).get("features.csv")
        != before["current"]["features.csv"]
    ):
        raise ValueError("Current features checksum mismatch")
    with current_paths["features.csv"].open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != FEATURE_FIELDS:
            raise ValueError("Unexpected current feature columns")
        current_rows = list(reader)
    if len(current_rows) != current_manifest.get("rows"):
        raise ValueError("Current feature row count mismatch")

    normalized = sorted(
        training_rows, key=lambda row: (row["cutoff_at"], row["golden_customer_id"])
    )
    train_rows, holdout_rows, _train_cutoffs, _test_cutoffs = temporal_split(normalized)

    report = {
        "feature_version": FEATURE_VERSION,
        "label_version": CHRIST_VERSION,
        "epsilon": EPSILON,
        "training_ready": False,
        "experiment_ready": False,
        "serving_ready": False,
        "development_only": True,
        "train_rows": len(train_rows),
        "holdout_rows": len(holdout_rows),
        "purged_rows": len(normalized) - len(train_rows) - len(holdout_rows),
        "reference_rows": len(normalized),
        "current_rows": len(current_rows),
        "features": {
            feature: _feature_report(
                _column(train_rows, feature), _column(current_rows, feature)
            )
            for feature in FEATURES
        },
        "limitations": [
            "Descriptive distribution comparison only; no alert thresholds set",
            "No retraining recommendation or performance claim is made",
            "Reference boundaries use purged chronological train rows only, never holdout",
        ],
    }

    after = {
        "reference": {name: sha256(path) for name, path in reference_paths.items()},
        "current": {name: sha256(path) for name, path in current_paths.items()},
    }
    if after != before:
        raise ValueError("Input changed during diagnostic")
    report["input_sha256"] = before
    report["input_sha256_after"] = after

    output_dir.mkdir(parents=True)
    (output_dir / "feature_drift.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "development_only": True,
        "training_ready": False,
        "experiment_ready": False,
        "serving_ready": False,
        "input_sha256": before,
        "input_sha256_after": after,
        "output_sha256": {
            "feature_drift.json": sha256(output_dir / "feature_drift.json")
        },
    }
    (output_dir / "feature_drift_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.reference, args.current, args.output_dir)
    print(
        json.dumps(
            {"training_ready": result["training_ready"], "output": str(args.output_dir)}
        )
    )


if __name__ == "__main__":
    main()
