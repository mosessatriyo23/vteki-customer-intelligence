"""Development-only churn evaluation with leakage-safe temporal metrics."""

import argparse
import csv
import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path

from services.data.features.snapshot import FIELDS as FEATURE_FIELDS
from services.data.ingestion.validator import sha256
from services.data.models.baseline import predict_churn, temporal_split
from services.data.models.labels import CHRIST_VERSION

_HORIZON_DAYS = 90
_INTEGER = re.compile(r"^[0-9]+$")


def _binary(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be 0 or 1")
    if value in ("0", 0):
        return 0
    if value in ("1", 1):
        return 1
    raise ValueError(f"{field} must be 0 or 1")


def _flag(value: object, field: str) -> bool:
    if value is True or value == "True":
        return True
    raise ValueError(f"{field} must be True")


def _recency(value: object) -> int:
    if isinstance(value, bool) or value is None:
        raise ValueError("recency_days must be a finite nonnegative integer")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and _INTEGER.fullmatch(value):
        result = int(value)
    else:
        raise ValueError("recency_days must be a finite nonnegative integer")
    if result < 0 or not math.isfinite(result):
        raise ValueError("recency_days must be a finite nonnegative integer")
    return result


def _aware_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an aware timestamp")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be an aware timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{field} must be an aware timestamp")
    return result


def _validate_rows(rows: list[dict]) -> None:
    seen: set[tuple[str, str]] = set()
    for row in rows:
        customer = row.get("golden_customer_id")
        cutoff_text = row.get("cutoff_at")
        cutoff = _aware_timestamp(cutoff_text, "cutoff_at")
        key = (str(customer), cutoff.isoformat())
        if customer in (None, "") or key in seen:
            raise ValueError("Duplicate customer/cutoff or missing customer")
        seen.add(key)
        if row.get("label_version") != CHRIST_VERSION:
            raise ValueError("Each row must use the Christ label version")
        try:
            horizon = int(row.get("horizon_days"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Each row must have horizon_days=90") from exc
        if isinstance(row.get("horizon_days"), bool) or horizon != _HORIZON_DAYS:
            raise ValueError("Each row must have horizon_days=90")
        outcome_end = _aware_timestamp(row.get("outcome_end_at"), "outcome_end_at")
        if outcome_end != cutoff + timedelta(days=_HORIZON_DAYS):
            raise ValueError("outcome_end_at must equal cutoff_at plus 90 days")
        _flag(row.get("eligible"), "eligible")
        _flag(row.get("outcome_complete"), "outcome_complete")
        _binary(row.get("churn90"), "churn90")
        _recency(row.get("recency_days"))


def _auc(rows: list[tuple[int, float]]) -> float | None:
    positives = sum(label for label, _ in rows)
    negatives = len(rows) - positives
    if not positives or not negatives:
        return None
    ordered = sorted(rows, key=lambda item: item[1])
    rank_sum = 0.0
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        average_rank = (index + 1 + end) / 2
        rank_sum += sum(label for label, _ in ordered[index:end]) * average_rank
        index = end
    return (rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


def _average_precision(rows: list[tuple[int, float]]) -> float | None:
    """Average precision at score groups; this is not trapezoidal PR AUC."""
    positives = sum(label for label, _ in rows)
    if not positives:
        return None
    ordered = sorted(rows, key=lambda item: item[1], reverse=True)
    true_positive = false_positive = 0
    total = 0.0
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        group = ordered[index:end]
        true_positive += sum(label for label, _ in group)
        false_positive += len(group) - sum(label for label, _ in group)
        total += sum(label for label, _ in group) * (
            true_positive / (true_positive + false_positive)
        )
        index = end
    return total / positives


def _evaluate_rows(rows: list[dict]) -> dict[str, object]:
    if not rows:
        raise ValueError("Cannot evaluate an empty fold")
    scored = [
        (
            _binary(row["churn90"], "churn90"),
            float(predict_churn(_recency(row["recency_days"]))),
        )
        for row in rows
    ]
    brier = sum((score - label) ** 2 for label, score in scored) / len(scored)
    positives = sum(label for label, _ in scored)
    return {
        "rows": len(rows),
        "positive_rate": positives / len(rows),
        "roc_auc": _auc(scored),
        "average_precision": _average_precision(scored),
        "brier_score": brier,
        "top_decile_rows": None,
        "top_decile_lift": None,
        "top_decile_note": "Not reported: binary baseline creates arbitrary score ties",
        "score_definition": "fixed recency > 90 days; binary development baseline",
        "average_precision_note": "Average precision, not trapezoidal PR AUC",
    }


def evaluate(rows: list[dict]) -> dict[str, object]:
    """Evaluate complete, eligible rows using the existing purged temporal split."""
    if not rows:
        raise ValueError("No rows supplied")
    _validate_rows(rows)
    train, test, train_cutoffs, test_cutoffs = temporal_split(rows)
    return {
        "training_ready": False,
        "experiment_ready": False,
        "final_model": False,
        "train": _evaluate_rows(train),
        "holdout": _evaluate_rows(test),
        "train_cutoffs": train_cutoffs,
        "test_cutoffs": test_cutoffs,
        "limitations": [
            "Synthetic development data only",
            "Fixed recency rule, not a fitted probabilistic model",
            "Retrospective identity and unavailable historical event timing",
            "No production threshold or campaign decision is authorized",
        ],
    }


def run(source: Path, output_dir: Path) -> dict[str, object]:
    if output_dir.exists():
        raise ValueError("Use a new evaluator directory")
    source = source.resolve()
    output_dir = output_dir.resolve()
    if any(part.lower() == "ground_truth" for part in source.parts + output_dir.parts):
        raise ValueError("ground_truth paths are not allowed")
    if (
        source == output_dir
        or source in output_dir.parents
        or output_dir in source.parents
    ):
        raise ValueError("Keep input and output separate")
    manifest_path = source / "model_manifest.json"
    input_path = source / "training_rows.csv"
    before = {
        "model_manifest.json": sha256(manifest_path),
        "training_rows.csv": sha256(input_path),
    }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("experiment_ready") is not False
        or manifest.get("final_model") is not False
    ):
        raise ValueError("Only development baseline runs are supported")
    if manifest.get("label_version") != CHRIST_VERSION:
        raise ValueError("Evaluator requires the Christ development label version")
    if tuple(manifest.get("feature_fields", ())) != FEATURE_FIELDS:
        raise ValueError("Unexpected feature contract or label leakage in allowlist")
    if (
        manifest.get("output_sha256", {}).get("training_rows.csv")
        != before["training_rows.csv"]
    ):
        raise ValueError("Training row checksum mismatch")
    with input_path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != manifest.get("training_rows"):
        raise ValueError("Training row count mismatch")
    report = evaluate(rows)
    after = {name: sha256(source / name) for name in before}
    if after != before:
        raise ValueError("Input changed during evaluation")
    output_dir.mkdir(parents=True)
    (output_dir / "evaluation.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "evaluation_manifest.json").write_text(
        json.dumps(
            {
                "training_ready": False,
                "experiment_ready": False,
                "final_model": False,
                "input_sha256": before,
                "input_sha256_after": after,
                "training_rows": len(rows),
                "output_sha256": {
                    "evaluation.json": sha256(output_dir / "evaluation.json")
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.source, args.output_dir)
    print(
        json.dumps(
            {"training_ready": report["training_ready"], "output": str(args.output_dir)}
        )
    )


if __name__ == "__main__":
    main()
