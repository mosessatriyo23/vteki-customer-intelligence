"""Exploratory membership-only renewal60 fit after inspection of the POS holdout.

Consumes propensity_labels and membership_features CLI outputs only. This is not
independent confirmation, an approved model, PIT-safe evidence, or serving code.
Install requirements-models.txt in a development environment to run the fit.
"""

import argparse
import csv
import json
import math
import re
from datetime import timedelta, timezone
from pathlib import Path

from services.data.ingestion.validator import sha256
from services.data.models.baseline import temporal_split
from services.data.models.churn_diagnostics import _metrics, _operating
from services.data.models.evaluator import _aware_timestamp
from services.data.models.membership_features import FIELDS as MEMBERSHIP_FIELDS
from services.data.models.membership_features import MEMBERSHIP_FEATURE_VERSION
from services.data.models.propensity_labels import FIELDS as LABEL_FIELDS
from services.data.models.propensity_labels import RENEWAL_VERSION

MODEL_VERSION = "moses-renewal-membership-exploratory-dev-1.0"
FEATURES = (
    "days_to_expiry",
    "current_tier_ordinal",
    "membership_tenure_days",
    "renewal_count_365d",
    "tier_upgraded_last_event",
    "days_since_last_membership_event",
)
SEED = 42
LOCAL_TIMEZONE = timezone(timedelta(hours=7))
OUTPUTS = ("evaluation.json", "holdout_predictions.json", "model_parameters.json")
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
    "Exploratory post-holdout-inspection follow-up; not independent confirmation",
    "Synthetic development cohort only; not population or production performance",
    "Current-snapshot retrospective identity is not availability-time/PIT safe",
    "PROPOSED renewal60 target pending approval; renewal is not upgrade",
    "Membership-only predictors; no POS predictors or combined model",
    "Raw probabilities are uncalibrated; fixed threshold 0.5, no holdout tuning",
    "Observational comparison only; no causal or campaign-effect claims",
    "Not I-04 compliant; no reason codes or serving authorization",
]
COMPARISON_NOTE = (
    "Own train-fold base-rate comparator only. Compare the original POS-only result "
    "in a separate report after verifying its manifest, hashes, versions and cohort; "
    "no unverified evaluation.json is read or compared here."
)


def _flag(value, field):
    if value is True or (type(value) is str and value == "True"):
        return True
    if value is False or (type(value) is str and value == "False"):
        return False
    raise ValueError(f"{field} must be True or False")


def _binary(value, field):
    if type(value) is int and value in (0, 1):
        return value
    if type(value) is str and value in ("0", "1"):
        return int(value)
    raise ValueError(f"{field} must be a binary integer")


def _number(value, field):
    if value is None or value == "":
        if field == "renewal_count_365d":
            raise ValueError(f"{field} is required")
        return math.nan
    if type(value) is int:
        number = value
    elif type(value) is str and re.fullmatch(r"-?[0-9]+", value):
        number = int(value)
    else:
        raise ValueError(f"{field} must be an integer or missing")
    if field != "days_to_expiry" and number < 0:
        raise ValueError(f"{field} must be nonnegative")
    if field == "current_tier_ordinal" and number not in range(4):
        raise ValueError("current_tier_ordinal must be 0..3 or missing")
    try:
        result = float(number)
    except OverflowError as exc:
        raise ValueError(f"{field} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _matrix(rows):
    return [
        [
            (
                float(_flag(row.get(name), name))
                if name == "tier_upgraded_last_event"
                else _number(row.get(name), name)
            )
            for name in FEATURES
        ]
        for row in rows
    ]


def _index(rows):
    result = {}
    for row in rows:
        customer = row.get("golden_customer_id")
        cutoff = _aware_timestamp(row.get("cutoff_at"), "cutoff_at")
        if not isinstance(customer, str) or not customer.strip():
            raise ValueError("Missing golden_customer_id")
        key = customer, cutoff
        if key in result:
            raise ValueError("Duplicate customer/cutoff key")
        result[key] = row
    return result


def join_rows(membership_rows: list[dict], labels: list[dict]) -> list[dict]:
    """Validate every input row before selecting eligible, complete renewal60."""
    members, outcomes = _index(membership_rows), _index(labels)
    if members.keys() != outcomes.keys():
        raise ValueError("Membership/label keys must exactly match")
    rows = []
    for key, member in members.items():
        label = outcomes[key]
        if member.get("feature_version") != MEMBERSHIP_FEATURE_VERSION:
            raise ValueError("Unexpected membership feature version")
        if label.get("renewal_label_version") != RENEWAL_VERSION:
            raise ValueError("Unexpected renewal label version")
        if _flag(member.get("training_ready"), "training_ready"):
            raise ValueError("training_ready must be False")
        if _flag(label.get("experiment_ready"), "experiment_ready"):
            raise ValueError("experiment_ready must be False")
        _flag(member.get("has_membership_history"), "has_membership_history")
        _matrix([member])
        eligible = _flag(label.get("renewal60_eligible"), "renewal60_eligible")
        complete = _flag(
            label.get("renewal60_outcome_complete"), "renewal60_outcome_complete"
        )
        end = _aware_timestamp(label.get("renewal60_outcome_end_at"), "outcome_end_at")
        if end != key[1] + timedelta(days=60):
            raise ValueError("Unexpected renewal60 outcome window")
        value = label.get("renewal60")
        if value not in (None, ""):
            _binary(value, "renewal60")
        if eligible and complete:
            rows.append(
                dict(
                    member,
                    cutoff_at=key[1].astimezone(LOCAL_TIMEZONE).isoformat(),
                    outcome_end_at=end.astimezone(LOCAL_TIMEZONE).isoformat(),
                    target_value=_binary(value, "renewal60"),
                    eligible=True,
                    outcome_complete=True,
                )
            )
    return sorted(rows, key=lambda r: (r["cutoff_at"], r["golden_customer_id"]))


def evaluate(rows: list[dict]) -> tuple[dict, list[dict], dict]:
    """Fit train-only transforms and logistic on March; test once on June."""
    import sklearn
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

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
    model = make_pipeline(
        SimpleImputer(strategy="median", keep_empty_features=True),
        StandardScaler(),
        LogisticRegression(random_state=SEED, max_iter=1000),
    )
    model.fit(_matrix(train), y_train)
    base_rate = sum(y_train) / len(y_train)
    scores = {
        "logistic": [float(p) for p in model.predict_proba(_matrix(test))[:, 1]],
        "base_rate": [base_rate] * len(test),
    }
    summaries = {}
    for name, values in scores.items():
        scored = list(zip(y_test, values))
        summaries[name] = dict(
            rows=len(test),
            positives=sum(y_test),
            negatives=len(test) - sum(y_test),
            metrics=_metrics(scored),
            operating_metrics=_operating(scored),
        )
    report = {
        **IDENTITY,
        **STATUS,
        "features": list(FEATURES),
        "seed": SEED,
        "train_rows": len(train),
        "test_rows": len(test),
        "purged_rows": len(rows) - len(train) - len(test),
        "train_cutoffs": train_cutoffs,
        "test_cutoffs": test_cutoffs,
        "train_base_rate": base_rate,
        "test_base_rate": sum(y_test) / len(y_test),
        "models": summaries,
        "limitations": LIMITATIONS,
        "comparison_note": COMPARISON_NOTE,
    }
    predictions = [
        {
            **IDENTITY,
            **STATUS,
            "golden_customer_id": row["golden_customer_id"],
            "cutoff_at": row["cutoff_at"],
            "outcome_end_at": row["outcome_end_at"],
            "target_value": y_test[i],
            **{name + "_probability": values[i] for name, values in scores.items()},
        }
        for i, row in enumerate(test)
    ]
    logistic = model.named_steps["logisticregression"]
    parameters = {
        **IDENTITY,
        **STATUS,
        "features": list(FEATURES),
        "seed": SEED,
        "sklearn_version": sklearn.__version__,
        "serialization_note": "JSON inspection only, not a loadable or serving model",
        "logistic": {
            "imputer_medians": model.named_steps["simpleimputer"].statistics_.tolist(),
            "scaler_mean": model.named_steps["standardscaler"].mean_.tolist(),
            "scaler_scale": model.named_steps["standardscaler"].scale_.tolist(),
            "coef": logistic.coef_[0].tolist(),
            "intercept": logistic.intercept_.tolist(),
        },
        "base_rate": {"train_base_rate": base_rate},
    }
    return report, predictions, parameters


def _read_csv(path, fields):
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != fields:
            raise ValueError("Unexpected CSV columns")
        rows = list(reader)
    if any(None in r or any(v is None for v in r.values()) for r in rows):
        raise ValueError("Malformed CSV row")
    return rows


def _cutoffs(manifest):
    values = manifest.get("cutoffs")
    if not isinstance(values, list) or not values:
        raise ValueError("Missing manifest cutoffs")
    parsed = [_aware_timestamp(v, "cutoff") for v in values]
    if len(set(parsed)) != len(parsed):
        raise ValueError("Duplicate manifest cutoffs")
    return set(parsed)


def run(labels_dir: Path, membership_dir: Path, output_dir: Path) -> dict:
    labels_dir, membership_dir, output_dir = map(
        Path, (labels_dir, membership_dir, output_dir)
    )
    if output_dir.exists():
        raise ValueError("Use a new output directory")
    paths = [labels_dir, membership_dir, output_dir]
    if any(part.lower() == "ground_truth" for p in paths for part in p.parts):
        raise ValueError("ground_truth paths are not allowed")
    labels_dir, membership_dir, output_dir = (p.resolve() for p in paths)
    if any(
        part.lower() == "ground_truth"
        for p in (labels_dir, membership_dir, output_dir)
        for part in p.parts
    ):
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
    report, predictions, parameters = evaluate(join_rows(members, labels))
    after = {name: sha256(path) for name, path in paths.items()}
    if before != after:
        raise ValueError("Input changed during experiment")
    report.update(input_sha256=before, input_sha256_after=after)
    # Serialize before creating anything, so invalid/nonfinite output fails closed.
    serialized = [
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
        for value in (report, predictions, parameters)
    ]
    output_dir.mkdir(parents=True)
    for name, content in zip(OUTPUTS, serialized):
        with (output_dir / name).open("x", encoding="utf-8") as stream:
            stream.write(content)
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
        stream.write(
            json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n"
        )
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
