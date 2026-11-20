"""Exploratory feature ablation for membership-only renewal60 (synthetic, dev only).

Post-holdout-inspection follow-up to renewal_membership_experiment: asks which
membership features carry the signal. Reuses that module's join, validation and
matrix helpers. Not independent confirmation, not an approved model, not serving.
Install requirements-models.txt in a development environment to run the fits.
"""

import argparse
import json
import math
from datetime import timedelta
from pathlib import Path

from services.data.ingestion.validator import sha256
from services.data.models.baseline import temporal_split
from services.data.models.churn_diagnostics import _metrics
from services.data.models.churn_experiment import _estimator_metadata
from services.data.models.evaluation_disclaimer import SYNTHETIC_DATA_DISCLAIMER
from services.data.models.evaluator import _aware_timestamp
from services.data.models.membership_features import FIELDS as MEMBERSHIP_FIELDS
from services.data.models.membership_features import MEMBERSHIP_FEATURE_VERSION
from services.data.models.propensity_labels import FIELDS as LABEL_FIELDS
from services.data.models.propensity_labels import RENEWAL_VERSION
from services.data.models.renewal_membership_experiment import (
    FEATURES,
    LOCAL_TIMEZONE,
    SEED,
    _binary,
    _cutoffs,
    _flag,
    _index,
    _matrix,
    _read_csv,
    join_rows,
)

MODEL_VERSION = "moses-renewal-ablation-exploratory-dev-1.0"
OUTPUTS = ("evaluation.json",)
STATUS = dict(
    development_only=True,
    training_ready=False,
    experiment_ready=False,
    final_model=False,
    serving_ready=False,
    exploratory=True,
    post_holdout_inspection=True,
    independent_confirmation=False,
    valid_until=None,
)
IDENTITY = dict(
    model_version=MODEL_VERSION,
    target="renewal60",
    target_version=RENEWAL_VERSION,
    feature_version=MEMBERSHIP_FEATURE_VERSION,
    horizon_days=60,
)
LIMITATIONS = [
    "Exploratory post-holdout-inspection ablation; not independent confirmation",
    "Synthetic development cohort only; not population or production performance",
    "Generator renewal probability appears near-random inside the eligible window",
    "Current-snapshot retrospective identity is not availability-time/PIT safe",
    "PROPOSED renewal60 target pending approval; renewal is not upgrade",
    "Features are correlated; drop-one and single-feature deltas are not additive",
    "Rule form is post-hoc and holdout-informed; logistic fits use training labels only",
    "Observational comparison only; no causal or campaign-effect claims",
    "Not I-04 compliant; no reason codes or serving authorization",
]
RULE_NOTE = (
    "Post-hoc rule suggested by earlier holdout inspection: score = 1 if "
    "days_to_expiry >= 0 else 0 (missing -> 0). No fitting; not pre-registered. "
    "Ranking reflects cohort/generator structure, not independent confirmation."
)
SINGLE_DAYS = "single_only:days_to_expiry"


def _variants():
    names = {"full": FEATURES}
    for name in FEATURES:
        names[f"drop_one:{name}"] = tuple(f for f in FEATURES if f != name)
    for name in FEATURES:
        names[f"single_only:{name}"] = (name,)
    return names


def _validate(rows):
    if not rows:
        raise ValueError("No eligible complete renewal60 rows")
    _index(rows)
    for row in rows:
        if row.get("feature_version") != MEMBERSHIP_FEATURE_VERSION:
            raise ValueError("Unexpected membership feature version")
        for name in ("eligible", "outcome_complete"):
            if _flag(row.get(name), name) is not True:
                raise ValueError(f"{name} must be True")
        if _flag(row.get("training_ready"), "training_ready"):
            raise ValueError("training_ready must be False")
        cutoff = _aware_timestamp(row["cutoff_at"], "cutoff_at")
        end = _aware_timestamp(row.get("outcome_end_at"), "outcome_end_at")
        if end != cutoff + timedelta(days=60):
            raise ValueError("Unexpected renewal60 outcome window")
        _binary(row.get("target_value"), "target_value")


def _structure(rows, y):
    """Descriptive cohort structure from already-joined rows; no new labels."""
    days = [m[0] for m in _matrix(rows)]
    groups = {
        "days_to_expiry_negative": lambda d: d < 0,
        "days_to_expiry_0_to_60": lambda d: 0 <= d <= 60,
        "days_to_expiry_above_60": lambda d: d > 60,
        "days_to_expiry_missing": math.isnan,
    }
    result = {"rows": len(rows)}
    for name, test in groups.items():
        labels = [t for d, t in zip(days, y) if test(d)]
        result[name] = dict(
            count=len(labels),
            positives=sum(labels),
            base_rate=sum(labels) / len(labels) if labels else None,
        )
    return result


def _summary(y_test, scores):
    scored = list(zip(y_test, scores))
    return dict(
        rows=len(y_test),
        positives=sum(y_test),
        negatives=len(y_test) - sum(y_test),
        metrics=_metrics(scored),
    )


def ablate(rows: list[dict]) -> dict:
    """Fit every variant on the (purged) March fold; score the June holdout once."""
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    _validate(rows)
    rows = [
        dict(
            row,
            cutoff_at=_aware_timestamp(row["cutoff_at"], "cutoff_at")
            .astimezone(LOCAL_TIMEZONE)
            .isoformat(),
        )
        for row in rows
    ]
    cutoffs = sorted({_aware_timestamp(r["cutoff_at"], "cutoff_at") for r in rows})
    if (
        len(cutoffs) != 2
        or [c.month for c in cutoffs] != [3, 6]
        or cutoffs[0].year != cutoffs[1].year
    ):
        raise ValueError("Exactly March and June cutoffs in the same year required")
    train, test, train_cutoffs, test_cutoffs = temporal_split(rows)
    y_train = [_binary(r["target_value"], "target_value") for r in train]
    y_test = [_binary(r["target_value"], "target_value") for r in test]
    if len(set(y_train)) != 2:
        raise ValueError("Training fold requires two classes")
    x_train, x_test = _matrix(train), _matrix(test)

    variants, fitted = {}, {}
    for name, features in _variants().items():
        cols = [FEATURES.index(f) for f in features]
        model = make_pipeline(
            SimpleImputer(strategy="median", keep_empty_features=True),
            StandardScaler(),
            LogisticRegression(random_state=SEED, max_iter=1000),
        )
        model.fit([[r[c] for c in cols] for r in x_train], y_train)
        scores = model.predict_proba([[r[c] for c in cols] for r in x_test])[:, 1]
        logistic = model.named_steps["logisticregression"]
        fitted[name] = dict(
            features=list(features),
            imputer_medians=model.named_steps["simpleimputer"].statistics_.tolist(),
            scaler_mean=model.named_steps["standardscaler"].mean_.tolist(),
            scaler_scale=model.named_steps["standardscaler"].scale_.tolist(),
            coef=logistic.coef_[0].tolist(),
            intercept=logistic.intercept_.tolist(),
        )
        variants[name] = dict(
            **_estimator_metadata(logistic),
            kind="logistic",
            features=list(features),
            **_summary(y_test, [float(p) for p in scores]),
        )
    # Fixed rule: no fit, reads no labels; NaN >= 0 is False so missing -> 0.
    rule = [1.0 if r[0] >= 0 else 0.0 for r in x_test]
    variants["baseline:fixed_rule_days_to_expiry_nonnegative"] = dict(
        kind="fixed_rule",
        fitted=False,
        pre_registered=False,
        rule=RULE_NOTE,
        features=["days_to_expiry"],
        **_summary(y_test, rule),
    )
    # Train-only logistic on days_to_expiry equals the single-feature variant.
    variants["baseline:logistic_days_to_expiry_only"] = dict(
        variants[SINGLE_DAYS],
        note=f"Same fit as {SINGLE_DAYS}; listed as the declared baseline",
    )
    fitted["baseline:logistic_days_to_expiry_only"] = fitted[SINGLE_DAYS]
    base_rate = sum(y_train) / len(y_train)
    comparator = dict(
        kind="constant",
        features=[],
        **_summary(y_test, [base_rate] * len(y_test)),
    )
    full = variants["full"]["metrics"]
    for variant in (*variants.values(), comparator):
        variant["delta_vs_full"] = {
            k: None if v is None or full[k] is None else v - full[k]
            for k, v in variant["metrics"].items()
        }
    report = {
        "algorithm": variants["full"]["algorithm"],
        "hyperparameters": variants["full"]["hyperparameters"],
        **IDENTITY,
        **STATUS,
        "synthetic_data_disclaimer": SYNTHETIC_DATA_DISCLAIMER,
        "features": list(FEATURES),
        "seed": SEED,
        "train_rows": len(train),
        "test_rows": len(test),
        "purged_rows": len(rows) - len(train) - len(test),
        "train_cutoffs": train_cutoffs,
        "test_cutoffs": test_cutoffs,
        "train_base_rate": base_rate,
        "test_base_rate": sum(y_test) / len(y_test),
        "cohort_structure": {
            "training_fold": _structure(train, y_train),
            "holdout": _structure(test, y_test),
            "note": "Read-only descriptive counts from the same joined rows",
        },
        "variants": variants,
        "train_base_rate_comparator": comparator,
        "fitted_parameters": fitted,
        "limitations": LIMITATIONS,
    }
    return report


def _dump(value):
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"


def run(labels_dir: Path, membership_dir: Path, output_dir: Path) -> dict:
    labels_dir, membership_dir, output_dir = map(
        Path, (labels_dir, membership_dir, output_dir)
    )
    if output_dir.exists():
        raise ValueError("Use a new output directory")
    labels_dir, membership_dir, output_dir = (
        p.resolve() for p in (labels_dir, membership_dir, output_dir)
    )
    for p in (labels_dir, membership_dir, output_dir):
        if any(part.lower() == "ground_truth" for part in p.parts):
            raise ValueError("ground_truth paths are not allowed")
    for source in (labels_dir, membership_dir):
        if (
            source == output_dir
            or source in output_dir.parents
            or output_dir in source.parents
        ):
            raise ValueError("Keep inputs and output separate")
    paths = {
        "propensity_manifest.json": labels_dir / "propensity_manifest.json",
        "propensity_labels.csv": labels_dir / "propensity_labels.csv",
        "membership_manifest.json": membership_dir / "membership_manifest.json",
        "membership_features.csv": membership_dir / "membership_features.csv",
    }
    before = {name: sha256(path) for name, path in paths.items()}
    label_manifest = json.loads(paths["propensity_manifest.json"].read_text("utf-8"))
    member_manifest = json.loads(paths["membership_manifest.json"].read_text("utf-8"))
    for manifest in (label_manifest, member_manifest):
        if (
            manifest.get("development_only") is not True
            or manifest.get("training_ready") is not False
        ):
            raise ValueError("Development-only manifests required")
    if (
        label_manifest.get("experiment_ready") is not False
        or label_manifest.get("final_model") is not False
    ):
        raise ValueError("Development-only label manifest required")
    if label_manifest.get("target_versions", {}).get("renewal60") != RENEWAL_VERSION:
        raise ValueError("Unexpected label version")
    if member_manifest.get("feature_version") != MEMBERSHIP_FEATURE_VERSION:
        raise ValueError("Unexpected membership feature version")
    if member_manifest.get("identity_time_policy") != "CURRENT_SNAPSHOT_RETROSPECTIVE":
        raise ValueError("Unexpected identity time policy")
    for manifest, filename in (
        (label_manifest, "propensity_labels.csv"),
        (member_manifest, "membership_features.csv"),
    ):
        if manifest.get("output_sha256") != {filename: before[filename]}:
            raise ValueError("Input checksum mismatch")
    expected_cutoffs = _cutoffs(label_manifest)
    if expected_cutoffs != _cutoffs(member_manifest):
        raise ValueError("Membership and label cutoffs must match")
    members = _read_csv(paths["membership_features.csv"], MEMBERSHIP_FIELDS)
    labels = _read_csv(paths["propensity_labels.csv"], LABEL_FIELDS)
    if (
        type(member_manifest.get("row_count")) is not int
        or len(members) != member_manifest["row_count"]
    ):
        raise ValueError("Membership row count mismatch")
    for data in (members, labels):
        if {key[1] for key in _index(data)} != expected_cutoffs:
            raise ValueError("CSV and manifest cutoffs must match")
    report = ablate(join_rows(members, labels))
    after = {name: sha256(path) for name, path in paths.items()}
    if before != after:
        raise ValueError("Input changed during experiment")
    report.update(input_sha256=before, input_sha256_after=after)
    serialized = _dump(report)  # fail closed on nonfinite values before writing
    output_dir.mkdir(parents=True)
    with (output_dir / "evaluation.json").open("x", encoding="utf-8") as stream:
        stream.write(serialized)
    manifest = {
        **IDENTITY,
        **STATUS,
        "limitations": LIMITATIONS,
        "input_sha256": before,
        "input_sha256_after": after,
        "output_sha256": {name: sha256(output_dir / name) for name in OUTPUTS},
    }
    with (output_dir / "experiment_manifest.json").open(
        "x", encoding="utf-8"
    ) as stream:
        stream.write(_dump(manifest))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels-dir", type=Path, required=True)
    parser.add_argument("--membership-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.labels_dir, args.membership_dir, args.output_dir)
    print(
        json.dumps(
            {"model_version": MODEL_VERSION, "serving_ready": result["serving_ready"]}
        )
    )


if __name__ == "__main__":
    main()
