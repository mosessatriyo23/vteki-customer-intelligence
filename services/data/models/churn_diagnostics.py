"""Offline Moses churn evidence; synthetic, retrospective, non-serving diagnostics.

Consumes experiment artifacts, not inference-only scores (which have no outcomes).
No raw train/holdout features are available here, so no drift is estimated.
"""

import argparse
import json
import math
import random
import re
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from services.data.features.snapshot import VERSION as FEATURE_VERSION
from services.data.ingestion.validator import sha256
from services.data.models.churn_experiment import FEATURES, MODEL_VERSION
from services.data.models.evaluator import _auc, _average_precision, _aware_timestamp
from services.data.models.labels import CHRIST_VERSION

MODELS = ("logistic", "shallow_tree", "baseline")
OUTPUTS = ("evaluation.json", "holdout_predictions.json", "model_parameters.json")
VERSIONS = dict(
    model_version=MODEL_VERSION,
    feature_version=FEATURE_VERSION,
    label_version=CHRIST_VERSION,
)
LIMITATIONS = [
    "Synthetic development cohort only; not population or production performance",
    "Retrospective identity; no point-in-time (PIT) historical guarantee",
    "Observational evidence only; no causal or campaign-effect claims",
    "Raw probabilities are uncalibrated; reliability and ECE are descriptive, not calibration approval",
    "Fixed threshold 0.5 only; no holdout threshold tuning or serving authorization",
    "Customer-cluster percentile intervals describe resampling uncertainty only, not dataset bias or model refitting",
    "No raw train/holdout feature distributions available; no drift analysis performed",
]


def _identity(data, *, manifest=False):
    expected = {"model_version": MODEL_VERSION} if manifest else VERSIONS
    if any(data.get(key) != value for key, value in expected.items()):
        raise ValueError("Unexpected model/feature/label version")
    if (
        data.get("development_only") is not True
        or data.get("serving_ready") is not False
    ):
        raise ValueError("Development-only, non-serving evidence required")


def _validate(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError("Nonempty holdout predictions required")
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Prediction must be an object")
        _identity(row)
        customer = row.get("golden_customer_id")
        if not isinstance(customer, str) or not customer.strip():
            raise ValueError("Missing golden_customer_id")
        cutoff = _aware_timestamp(row.get("cutoff_at"), "cutoff_at")
        if _aware_timestamp(
            row.get("outcome_end_at"), "outcome_end_at"
        ) != cutoff + timedelta(days=90):
            raise ValueError("Outcome window must be 90 days")
        key = (customer, cutoff)
        if key in seen:
            raise ValueError("Duplicate customer/cutoff")
        seen.add(key)
        if type(row.get("churn90")) is not int or row["churn90"] not in (0, 1):
            raise ValueError("churn90 must be binary integer")
        for model in MODELS:
            score = row.get(model + "_probability")
            if (
                type(score) not in (int, float)
                or not math.isfinite(score)
                or not 0 <= score <= 1
            ):
                raise ValueError("Probabilities must be finite numbers in [0, 1]")


def _metrics(scored):
    return dict(
        roc_auc=_auc(scored),
        average_precision=_average_precision(scored),
        brier_score=sum((p - y) ** 2 for y, p in scored) / len(scored),
    )


def _operating(scored):
    tp = sum(y == 1 and p >= 0.5 for y, p in scored)
    tn = sum(y == 0 and p < 0.5 for y, p in scored)
    fp = sum(y == 0 and p >= 0.5 for y, p in scored)
    fn = sum(y == 1 and p < 0.5 for y, p in scored)

    def ratio(a, b):
        return a / b if b else None

    return dict(
        threshold=0.5,
        tp=tp,
        tn=tn,
        fp=fp,
        fn=fn,
        precision=ratio(tp, tp + fp),
        recall=ratio(tp, tp + fn),
        f1=ratio(2 * tp, 2 * tp + fp + fn),
        specificity=ratio(tn, tn + fp),
    )


def _reliability(scored):
    bins = [[] for _ in range(10)]
    for y, p in scored:
        bins[min(int(p * 10), 9)].append((y, p))
    table = []
    ece = 0.0
    for i, bucket in enumerate(bins):
        count = len(bucket)
        mean = sum(p for _, p in bucket) / count if count else None
        observed = sum(y for y, _ in bucket) / count if count else None
        if count:
            ece += count / len(scored) * abs(mean - observed)
        table.append(
            dict(
                lower=i / 10,
                upper=(i + 1) / 10,
                upper_inclusive=i == 9,
                count=count,
                mean_score=mean,
                observed_event_rate=observed,
            )
        )
    return table, ece


def _percentile(values, q):
    values = sorted(values)
    index = (len(values) - 1) * q
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (index - lower)


def summarize(rows: list[dict], *, repeats: int = 200) -> dict:
    """Resample Golden IDs with replacement, retaining every cutoff per draw.

    Single-class draws are excluded from ROC-AUC/AP intervals. At least two
    independent customers and 20 valid draws are required for any interval.
    Missing either class in the original cohort yields null ROC-AUC/AP CIs.
    """
    if type(repeats) is not int or repeats < 20:
        raise ValueError("repeats must be an integer >=20")
    _validate(rows)
    rows = sorted(rows, key=lambda r: (r["golden_customer_id"], r["cutoff_at"]))
    groups = defaultdict(list)
    for row in rows:
        groups[row["golden_customer_id"]].append(row)
    customers = sorted(groups)
    samples = {
        model: {
            metric: [] for metric in ("roc_auc", "average_precision", "brier_score")
        }
        for model in MODELS
    }
    rng = random.Random(42)
    if len(customers) >= 2:
        for _ in range(repeats):
            draw = [row for _ in customers for row in groups[rng.choice(customers)]]
            two_classes = len({row["churn90"] for row in draw}) == 2
            for model in MODELS:
                values = _metrics(
                    [(r["churn90"], r[model + "_probability"]) for r in draw]
                )
                for metric, value in values.items():
                    if value is not None and (metric == "brier_score" or two_classes):
                        samples[model][metric].append(value)
    models = {}
    for model in MODELS:
        scored = [(r["churn90"], r[model + "_probability"]) for r in rows]
        table, ece = _reliability(scored)
        intervals = {}
        for metric, values in samples[model].items():
            enough = len(values) >= 20
            intervals[metric] = dict(
                lower=_percentile(values, 0.025) if enough else None,
                upper=_percentile(values, 0.975) if enough else None,
                valid_repeats=len(values),
                invalid_repeats=repeats - len(values),
                note=(
                    None
                    if enough
                    else "Insufficient independent customers or valid two-class draws"
                ),
            )
        models[model] = dict(
            metrics=_metrics(scored),
            bootstrap_ci95=intervals,
            operating_metrics=_operating(scored),
            reliability=table,
            descriptive_ece=ece,
        )
    return dict(
        **VERSIONS,
        development_only=True,
        training_ready=False,
        experiment_ready=False,
        final_model=False,
        serving_ready=False,
        bootstrap=dict(
            seed=42,
            repeats=repeats,
            unit="golden_customer_id",
            method="percentile",
            confidence=0.95,
            minimum_valid_repeats=20,
        ),
        cohort_coverage=dict(
            rows=len(rows),
            unique_customers=len(customers),
            positives=sum(r["churn90"] for r in rows),
            by_cutoff={
                c: sum(r["cutoff_at"] == c for r in rows)
                for c in sorted({r["cutoff_at"] for r in rows})
            },
            scope="Complete eligible experiment holdout only; full population denominator unavailable",
        ),
        models=models,
        limitations=LIMITATIONS,
    )


def _provenance(data):
    before = data.get("input_sha256")
    if (
        not isinstance(before, dict)
        or not before
        or before != data.get("input_sha256_after")
    ):
        raise ValueError("Experiment input-before/input-after integrity mismatch")
    if any(
        not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v)
        for v in before.values()
    ):
        raise ValueError("Invalid input checksum")
    return before


def run(source: Path, output_dir: Path, *, repeats: int = 200) -> dict:
    source, output_dir = Path(source).resolve(), Path(output_dir).resolve()
    if any(p.lower() == "ground_truth" for p in source.parts + output_dir.parts):
        raise ValueError("ground_truth paths are not allowed")
    if (
        source == output_dir
        or source in output_dir.parents
        or output_dir in source.parents
    ):
        raise ValueError("Keep input and output separate")
    if output_dir.exists():
        raise ValueError("Use a new output directory")
    manifest_path = source / "experiment_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _identity(manifest, manifest=True)
    provenance = _provenance(manifest)
    hashes = manifest.get("output_sha256")
    if not isinstance(hashes, dict) or not set(OUTPUTS).issubset(hashes):
        raise ValueError("Missing experiment output checksums")
    for name in hashes:
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or "\\" in name
            or "/" in name
            or name.lower() == "ground_truth"
        ):
            raise ValueError("Unsafe output checksum path")
        path = source / name
        if path.resolve().parent != source or path.is_symlink():
            raise ValueError("Output artifacts must stay inside experiment directory")
    before = {
        name: sha256(source / name) for name in (*hashes, "experiment_manifest.json")
    }
    for name, expected in hashes.items():
        if before[name] != expected:
            raise ValueError(f"{name} checksum mismatch")
    evaluation = json.loads((source / "evaluation.json").read_text(encoding="utf-8"))
    parameters = json.loads(
        (source / "model_parameters.json").read_text(encoding="utf-8")
    )
    rows = json.loads((source / "holdout_predictions.json").read_text(encoding="utf-8"))
    for data in (evaluation, parameters):
        _identity(data)
        if data.get("features") != list(FEATURES):
            raise ValueError("Unexpected feature contract")
    if _provenance(evaluation) != provenance:
        raise ValueError("Evaluation provenance mismatch")
    if any(
        evaluation.get(flag) is not False
        for flag in ("training_ready", "experiment_ready", "final_model")
    ):
        raise ValueError("Evaluation readiness mismatch")
    report = summarize(rows, repeats=repeats)
    positives = sum(r["churn90"] for r in rows)
    if type(evaluation.get("test_rows")) is not int or evaluation["test_rows"] != len(
        rows
    ):
        raise ValueError("Holdout prediction count mismatch")
    for model in MODELS:
        expected = dict(
            rows=len(rows), positives=positives, negatives=len(rows) - positives
        )
        if any(
            type(evaluation.get(model, {}).get(k)) is not int
            or evaluation[model][k] != v
            for k, v in expected.items()
        ):
            raise ValueError("Model holdout counts mismatch")
    train = [
        _aware_timestamp(c, "train_cutoffs")
        for c in evaluation.get("train_cutoffs", [])
    ]
    test = {
        _aware_timestamp(c, "test_cutoffs") for c in evaluation.get("test_cutoffs", [])
    }
    actual = {_aware_timestamp(r["cutoff_at"], "cutoff_at") for r in rows}
    if not train or test != actual or max(train) + timedelta(days=90) > min(test):
        raise ValueError("Invalid purged train/holdout cutoff boundary")
    report["cohort_coverage"].update(
        train_rows=evaluation.get("train_rows"),
        purged_rows=evaluation.get("purged_rows"),
    )
    after = {name: sha256(source / name) for name in before}
    if after != before:
        raise ValueError("Input changed during diagnostics")
    output_dir.mkdir(parents=True)
    (output_dir / "diagnostics.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    result = dict(
        **VERSIONS,
        development_only=True,
        serving_ready=False,
        input_sha256=before,
        input_sha256_after=after,
        output_sha256={"diagnostics.json": sha256(output_dir / "diagnostics.json")},
    )
    (output_dir / "diagnostics_manifest.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.source, args.output_dir)
    print(
        json.dumps(
            {"serving_ready": report["serving_ready"], "output": str(args.output_dir)}
        )
    )


if __name__ == "__main__":
    main()
