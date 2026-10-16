"""Aggregate diagnostics for the known retrospective synthetic baseline contract."""

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from services.data.features.snapshot import FIELDS as FEATURE_FIELDS
from services.data.ingestion.validator import sha256
from services.data.models.baseline import evaluate, predict_churn, temporal_split

FILES = ("labels.csv", "training_rows.csv", "metrics.json")


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def confusion(rows: list[dict], always_nonchurn: bool = False) -> dict:
    counts: Counter[str] = Counter()
    for row in rows:
        actual = int(row["churn90"])
        predicted = 0 if always_nonchurn else predict_churn(row["recency_days"])
        counts[("t" if actual == predicted else "f") + ("p" if predicted else "n")] += 1
    n = len(rows)
    positive = counts["tp"] + counts["fn"]
    negative = counts["tn"] + counts["fp"]
    sensitivity = counts["tp"] / positive if positive else None
    specificity = counts["tn"] / negative if negative else None
    return dict(
        rows=n,
        positives=positive,
        negatives=negative,
        prevalence=positive / n if n else None,
        **{key: counts[key] for key in ("tp", "tn", "fp", "fn")},
        accuracy=(counts["tp"] + counts["tn"]) / n if n else None,
        sensitivity=sensitivity,
        specificity=specificity,
        balanced_accuracy=(
            (sensitivity + specificity) / 2
            if sensitivity is not None and specificity is not None
            else None
        ),
    )


def summarize(rows: list[dict], labels: list[dict]) -> dict:
    keys = [(r["golden_customer_id"], r["cutoff_at"]) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate training customer/cutoff")
    for r in rows:
        if r["eligible"] != "True" or r["outcome_complete"] != "True":
            raise ValueError("Training rows must be complete and eligible")
        if r["churn90"] not in {"0", "1"} or int(r["clv90"]) < 0:
            raise ValueError("Invalid outcome")
        if datetime.fromisoformat(r["outcome_end_at"]) <= datetime.fromisoformat(
            r["cutoff_at"]
        ):
            raise ValueError("Invalid future outcome window")
    train, test, train_times, test_times = temporal_split(rows)
    metrics = evaluate(rows)
    median = metrics["clv_train_median"]
    return dict(
        training_ready=False,
        experiment_ready=False,
        readiness_blockers=[
            "SYNTHETIC_DATA",
            "RETROSPECTIVE_IDENTITY",
            "UNVERSIONED_REFUND_STATUS",
            "NO_AVAILABLE_AT",
            "PROPOSED_BUSINESS_TARGETS",
        ],
        readiness_scope="Fixed blockers for this development pipeline; not an approval service",
        train_cutoffs=train_times,
        test_cutoffs=test_times,
        purged_rows=len(rows) - len(train) - len(test),
        incomplete_label_rows=sum(r["outcome_complete"] != "True" for r in labels),
        label_counts_by_cutoff={
            c: dict(
                Counter(
                    (
                        "incomplete"
                        if r["outcome_complete"] != "True"
                        else (
                            "ineligible"
                            if r["eligible"] != "True"
                            else "churn_" + r["churn90"]
                        )
                    )
                    for r in labels
                    if r["cutoff_at"] == c
                )
            )
            for c in sorted({r["cutoff_at"] for r in labels})
        },
        holdout=dict(rule=confusion(test), always_nonchurn=confusion(test, True)),
        by_identity_status={
            status: confusion([r for r in test if r["identity_status"] == status])
            for status in sorted({r["identity_status"] for r in test})
        },
        revenue=dict(
            test_rows=len(test),
            actual_min=min(int(r["clv90"]) for r in test),
            actual_max=max(int(r["clv90"]) for r in test),
            zero_outcomes=sum(int(r["clv90"]) == 0 for r in test),
            train_median=median,
            median_mae=metrics["clv"]["mae"],
            train_mean=metrics["clv_train_mean"],
            mean_mae=metrics["clv"]["mae_mean_baseline"],
        ),
    )


def run(source: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError("Use a new diagnostics directory")
    if (
        source.resolve() == output.resolve()
        or source.resolve() in output.resolve().parents
        or output.resolve() in source.resolve().parents
    ):
        raise ValueError("Keep inputs and output separate")
    manifest_path = source / "model_manifest.json"
    before = {name: sha256(source / name) for name in (*FILES, "model_manifest.json")}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("experiment_ready") is not False
        or manifest.get("final_model") is not False
    ):
        raise ValueError("Only development baseline runs are supported")
    if tuple(manifest["feature_fields"]) != FEATURE_FIELDS:
        raise ValueError(
            "Unexpected feature contract or label leakage in feature allowlist"
        )
    if any(manifest["output_sha256"].get(name) != before[name] for name in FILES):
        raise ValueError("Model output checksum mismatch")
    rows, labels = read_csv(source / "training_rows.csv"), read_csv(
        source / "labels.csv"
    )
    if len(rows) != manifest["training_rows"] or len(labels) != manifest["label_rows"]:
        raise ValueError("Model row counts mismatch")
    report = summarize(rows, labels)
    if before != {name: sha256(source / name) for name in before}:
        raise ValueError("Model inputs changed")
    output.mkdir(parents=True)
    (output / "diagnostics.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "report.md").write_text(
        "# Development baseline diagnostics\n\nSynthetic retrospective diagnostics only. "
        "Not production performance. Readiness: BLOCKED.\n\n```json\n"
        + json.dumps(report, indent=2)
        + "\n```\n",
        encoding="utf-8",
    )
    (output / "diagnostics_manifest.json").write_text(
        json.dumps(
            dict(
                input_sha256=before,
                training_ready=False,
                output_sha256={
                    name: sha256(output / name)
                    for name in ("diagnostics.json", "report.md")
                },
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return report


def main():
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
