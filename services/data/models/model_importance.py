"""Holdout-only permutation reliance and segment diagnostics for fitted JSON logistic models.

Development-only evidence (FRD FR-MON-001 global importance, TRD 9.3 per-segment
performance). Nothing here refits, calibrates, tunes, or approves a model: the
JSON parameters are reloaded exactly as scored, raw feature columns are permuted
on the holdout fold only, and the drop in ROC-AUC (and rise in Brier) is reported
as model reliance, never as a causal effect. Segments are derived from feature
columns only; no ground truth, lifecycle, or CLV tier is read.
"""

import argparse
import csv
import json
import math
import random
import statistics
from collections.abc import Sequence
from pathlib import Path

from services.data.features.snapshot import VERSION as FEATURE_VERSION
from services.data.ingestion.validator import sha256
from services.data.models import renewal_membership_experiment as membership
from services.data.models.baseline import temporal_split
from services.data.models.churn_experiment import FEATURES, LOCAL_TIMEZONE
from services.data.models.churn_experiment import _validate as _validate_churn
from services.data.models.evaluator import _auc, _aware_timestamp, _binary
from services.data.models.labels import TRAINING_FIELDS as CHURN_TRAINING_FIELDS
from services.data.models.propensity_experiment import _read_features, _typed_labels
from services.data.models.propensity_experiment import _validate as _validate_propensity
from services.data.models.propensity_labels import (
    TARGETS,
    join_propensity_training_rows,
)

EXPLAINER_METHOD = "permutation_importance_auc_drop"
EXPLAINER_VERSION = "moses-permutation-importance-dev-1.1"
SEED = 42
REPEATS = 10
MIN_SEGMENT_N = 100
# Correlated by construction; single-column permutation understates the group.
CORRELATED_GROUP = ("purchase_count_60d", "purchase_count_90d", "purchase_count_365d")
KINDS = ("churn", "retail_purchase30", "renewal60", "renewal60_membership")
LABEL_KEYS = {
    "churn": "churn90",
    "retail_purchase30": "target_value",
    "renewal60": "target_value",
    "renewal60_membership": "target_value",
}
OUTPUTS = ("importance_report.json",)
LIMITATIONS = [
    "Synthetic development cohort only; not population or production performance",
    "Retrospective identity; features are not point-in-time (PIT) safe",
    "Permutation importance measures model reliance on a column, not causal effect",
    "Correlated features (purchase_count_60d/90d/365d) share reliance, so single-column "
    "permutation understates the grouped effect; the grouped permutation is reported separately",
    "Segments are feature-derived buckets only; no lifecycle, approved label, or CLV tier is used",
    "Model is never refitted, recalibrated, or threshold-tuned; raw probabilities only",
    "Observational evidence only; not serving-approved and not an I-04 handoff",
]
# recency/tenure/frequency buckets fixed before any holdout metric was read.
SEGMENT_BUCKETS = {
    "recency_days": (("<=30", 30), ("31-90", 90), ("91-180", 180), (">180", math.inf)),
    "tenure_days": (
        ("<=90", 90),
        ("91-180", 180),
        ("181-365", 365),
        (">365", math.inf),
    ),
    "purchase_count_365d": (
        ("0", 0),
        ("1-2", 2),
        ("3-5", 5),
        ("6-11", 11),
        (">=12", math.inf),
    ),
}


# Fixed, feature-derived buckets for exploratory post-holdout diagnostics; not
# pre-registered, not independent confirmation, and not lifecycle,
# renewal-vs-upgrade semantics, or CLV tiers. tier_upgraded_last_event is a flag
# and is not bucketed.
MEMBERSHIP_SEGMENT_BUCKETS = {
    "days_to_expiry": (("<=0", 0), ("1-30", 30), ("31-60", 60), (">60", math.inf)),
    "current_tier_ordinal": (("0", 0), ("1", 1), ("2", 2), ("3", math.inf)),
    "membership_tenure_days": (("<=90", 90), ("91-365", 365), (">365", math.inf)),
    "renewal_count_365d": (("0", 0), ("1", 1), (">=2", math.inf)),
}


def _buckets_for(field: str):
    return SEGMENT_BUCKETS.get(field) or MEMBERSHIP_SEGMENT_BUCKETS[field]


def _numbers(values: object, length: int) -> list[float]:
    if not isinstance(values, list) or len(values) != length:
        raise ValueError("Model parameter vector has the wrong shape")
    result = []
    for value in values:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError("Model parameter values must be finite numbers")
        result.append(float(value))
    return result


def _logistic(parameters: dict) -> tuple[tuple[str, ...], dict]:
    """Read the JSON-only logistic parameters exactly as the scorer sees them."""
    if not isinstance(parameters, dict):
        raise ValueError("Model parameters must be an object")
    if (
        parameters.get("development_only") is not True
        or parameters.get("serving_ready") is not False
    ):
        raise ValueError("Development-only, non-serving model parameters required")
    if "isotonic" in parameters:
        raise ValueError(
            "Importance for calibrated artifacts is not supported; do not score as raw logistic"
        )
    features = tuple(parameters.get("features") or ())
    if features == membership.FEATURES:
        _membership_contract(parameters)
    elif features != FEATURES:
        raise ValueError("Unexpected feature contract in model parameters")
    logistic = parameters.get("logistic")
    if not isinstance(logistic, dict):
        raise ValueError("Missing logistic model parameters")
    count = len(features)
    intercept = logistic.get("intercept")
    if not isinstance(intercept, list) or len(intercept) != 1:
        raise ValueError("Logistic intercept must be a single-value list")
    scale = _numbers(logistic.get("scaler_scale"), count)
    if any(value <= 0 for value in scale):
        raise ValueError("Scaler scale must be strictly positive")
    return features, {
        "intercept": _numbers(intercept, 1)[0],
        "coef": _numbers(logistic.get("coef"), count),
        "scaler_mean": _numbers(logistic.get("scaler_mean"), count),
        "scaler_scale": scale,
        "imputer_medians": _numbers(logistic.get("imputer_medians"), count),
    }


def _membership_contract(parameters: dict) -> None:
    if any(
        parameters.get(key) != value for key, value in membership.IDENTITY.items()
    ) or any(
        parameters.get(key) is not value for key, value in membership.STATUS.items()
    ):
        raise ValueError("Unexpected membership model contract")


def _raw(row: dict, field: str) -> float:
    value = row.get(field)
    if value is None or value == "":
        if field == "recency_days":
            return math.nan  # eligible event-only cohort; imputed by the train median
        raise ValueError(f"{field} must be finite numeric")
    if isinstance(value, bool):
        raise ValueError(f"{field} must be finite numeric")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be finite numeric") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{field} must be finite nonnegative numeric")
    return number


def _score(model: dict, values: list[float]) -> float:
    log_odds = model["intercept"]
    for index, raw in enumerate(values):
        imputed = model["imputer_medians"][index] if math.isnan(raw) else raw
        log_odds += (
            (imputed - model["scaler_mean"][index])
            / model["scaler_scale"][index]
            * model["coef"][index]
        )
    if not math.isfinite(log_odds):
        raise ValueError("log-odds score is not finite")
    if log_odds >= 0:
        return 1.0 / (1.0 + math.exp(-log_odds))
    exponent = math.exp(log_odds)
    return exponent / (1.0 + exponent)


def _scores(model: dict, matrix: list[list[float]]) -> list[float]:
    return [_score(model, values) for values in matrix]


def _brier(labels: list[int], scores: list[float]) -> float:
    return sum((score - label) ** 2 for label, score in zip(labels, scores)) / len(
        labels
    )


def _metrics(labels: list[int], scores: list[float]) -> dict:
    return {
        "roc_auc": _auc(list(zip(labels, scores))),
        "brier_score": _brier(labels, scores),
    }


def _spread(values: Sequence[float | None]) -> tuple[float | None, float | None]:
    usable = [value for value in values if value is not None]
    if len(usable) != len(values) or not usable:
        return None, None
    return statistics.fmean(usable), statistics.pstdev(usable)


def _importance_entry(
    model: dict,
    matrix: list[list[float]],
    labels: list[int],
    indexes: tuple[int, ...],
    name: str,
    baseline: dict,
    repeats: int,
    seed: int,
) -> dict:
    auc_drops: list[float | None] = []
    brier_rises: list[float] = []
    for repeat in range(repeats):
        order = list(range(len(matrix)))
        random.Random(f"{seed}:{name}:{repeat}").shuffle(order)
        permuted = [list(values) for values in matrix]
        for index in indexes:
            column = [matrix[row][index] for row in order]
            for row, value in enumerate(column):
                permuted[row][index] = value
        metrics = _metrics(labels, _scores(model, permuted))
        auc_drops.append(
            None
            if baseline["roc_auc"] is None or metrics["roc_auc"] is None
            else baseline["roc_auc"] - metrics["roc_auc"]
        )
        brier_rises.append(metrics["brier_score"] - baseline["brier_score"])
    auc_mean, auc_std = _spread(auc_drops)
    brier_mean, brier_std = _spread(brier_rises)
    return {
        "auc_drop_mean": auc_mean,
        "auc_drop_std": auc_std,
        "brier_increase_mean": brier_mean,
        "brier_increase_std": brier_std,
        "repeats": repeats,
    }


def _bucket(field: str, value: float) -> str:
    if math.isnan(value):
        return "missing"
    buckets = _buckets_for(field)
    for name, upper in buckets:
        if value <= upper:
            return name
    return buckets[-1][0]


def _segment(labels: list[int], scores: list[float], min_n: int) -> dict:
    positives = sum(labels)
    single_class = len(set(labels)) < 2
    small = len(labels) < min_n
    reason = None
    if small and single_class:
        reason = "n_below_min_n_and_single_class"
    elif small:
        reason = "n_below_min_n"
    elif single_class:
        reason = "single_class"
    return {
        "n": len(labels),
        "positives": positives,
        "base_rate": positives / len(labels),
        "roc_auc": None if reason else _auc(list(zip(labels, scores))),
        "auc_reason": reason,
        "brier_score": _brier(labels, scores),
        "small_segment": small,
    }


def evaluate(
    parameters: dict,
    holdout_rows: list[dict],
    label_key: str,
    *,
    repeats: int = REPEATS,
    seed: int = SEED,
    min_n: int = MIN_SEGMENT_N,
) -> dict:
    """Permute holdout feature columns against the reloaded model; never refit."""
    if type(repeats) is not int or repeats < 1:
        raise ValueError("repeats must be a positive integer")
    if type(min_n) is not int or min_n < 1:
        raise ValueError("min_n must be a positive integer")
    if not holdout_rows:
        raise ValueError("Nonempty holdout rows required")
    features, model = _logistic(parameters)
    if label_key in features:
        raise ValueError(
            "Unexpected feature contract: label_key must not be a feature column"
        )
    # Read-only snapshot of the holdout; the caller's rows are never mutated.
    is_membership = features == membership.FEATURES
    matrix = (
        membership._matrix(holdout_rows)
        if is_membership
        else [[_raw(row, field) for field in features] for row in holdout_rows]
    )
    labels = [_binary(row.get(label_key), label_key) for row in holdout_rows]
    baseline = _metrics(labels, _scores(model, matrix))
    importance = [
        {
            "feature": field,
            **_importance_entry(
                model, matrix, labels, (index,), field, baseline, repeats, seed
            ),
        }
        for index, field in enumerate(features)
    ]

    def order(entry):
        value = entry["auc_drop_mean"]
        return (
            -value if value is not None else 0.0,
            -entry["brier_increase_mean"],
            entry["feature"],
        )

    for rank, entry in enumerate(sorted(importance, key=order), start=1):
        entry["rank"] = rank
    grouped = []
    group = tuple(field for field in CORRELATED_GROUP if field in features)
    if len(group) > 1:
        indexes = tuple(features.index(field) for field in group)
        grouped.append(
            {
                "features": list(group),
                **_importance_entry(
                    model,
                    matrix,
                    labels,
                    indexes,
                    "|".join(group),
                    baseline,
                    repeats,
                    seed,
                ),
                "note": "Joint permutation of correlated columns; compare against the sum of single-column drops",
            }
        )
    segments = {}
    bucket_fields = MEMBERSHIP_SEGMENT_BUCKETS if is_membership else SEGMENT_BUCKETS
    for field in bucket_fields:
        if field not in features:
            continue
        index = features.index(field)
        groups: dict[str, list[int]] = {}
        for row, values in enumerate(matrix):
            groups.setdefault(_bucket(field, values[index]), []).append(row)
        names = [name for name, _ in _buckets_for(field)] + ["missing"]
        scores = _scores(model, matrix)
        segments[field] = [
            {
                "bucket": name,
                **_segment(
                    [labels[row] for row in groups[name]],
                    [scores[row] for row in groups[name]],
                    min_n,
                ),
            }
            for name in names
            if name in groups
        ]
    return {
        "explainer_method": EXPLAINER_METHOD,
        "explainer_version": EXPLAINER_VERSION,
        "seed": seed,
        "repeats": repeats,
        "min_segment_n": min_n,
        "features": list(features),
        "label_key": label_key,
        "holdout_rows": len(holdout_rows),
        "holdout_positives": sum(labels),
        "refitted": False,
        "development_only": True,
        "serving_ready": False,
        "final_model": False,
        "training_ready": False,
        "experiment_ready": False,
        "baseline": baseline,
        "global_importance": importance,
        "grouped_importance": grouped,
        **(membership.STATUS if is_membership else {}),
        "segment_definition": {
            field: [name for name, _ in buckets] + ["missing"]
            for field, buckets in bucket_fields.items()
            if field in features
        },
        "segments": segments,
        "limitations": list(LIMITATIONS)
        + (
            membership.LIMITATIONS
            + [
                "Membership segments are fixed feature-derived buckets for exploratory post-holdout "
                "diagnostics; not pre-registered, and no lifecycle, renewal-vs-upgrade semantics "
                "or CLV tier is implied"
            ]
            if is_membership
            else []
        ),
    }


def _normalized(rows: list[dict]) -> list[dict]:
    """Reproduce the experiment's normalization so the same holdout fold is rebuilt."""
    return sorted(
        [
            {
                **row,
                "cutoff_at": _aware_timestamp(row["cutoff_at"], "cutoff_at")
                .astimezone(LOCAL_TIMEZONE)
                .isoformat(),
                "outcome_end_at": _aware_timestamp(
                    row["outcome_end_at"], "outcome_end_at"
                )
                .astimezone(LOCAL_TIMEZONE)
                .isoformat(),
            }
            for row in rows
        ],
        key=lambda row: (row["cutoff_at"], row["golden_customer_id"]),
    )


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _check_paths(model_dir: Path, output_dir: Path, sources: list[Path]) -> None:
    if output_dir.exists():
        raise ValueError("Use a new output directory")
    inputs = [model_dir, *sources]
    for path in inputs + [output_dir]:
        if any(part.lower() == "ground_truth" for part in path.parts):
            raise ValueError("ground_truth paths are not allowed")
    for path in inputs:
        if (
            path == output_dir
            or path in output_dir.parents
            or output_dir in path.parents
        ):
            raise ValueError("Keep input and output directories separate")


def _churn_holdout(source_dir: Path) -> tuple[dict, list[dict]]:
    paths = {
        name: source_dir / name for name in ("model_manifest.json", "training_rows.csv")
    }
    manifest = _load(paths["model_manifest.json"])
    if (
        manifest.get("experiment_ready") is not False
        or manifest.get("final_model") is not False
    ):
        raise ValueError("Development-only source manifest required")
    if manifest.get("output_sha256", {}).get("training_rows.csv") != sha256(
        paths["training_rows.csv"]
    ):
        raise ValueError("Training row checksum mismatch")
    with paths["training_rows.csv"].open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != CHURN_TRAINING_FIELDS:
            raise ValueError("Unexpected training row columns")
        rows = list(reader)
    if len(rows) != manifest.get("training_rows"):
        raise ValueError("Training row count mismatch")
    _validate_churn(rows)
    _, holdout, _, _ = temporal_split(_normalized(rows))
    return paths, holdout


def _propensity_holdout(
    labels_dir: Path, features_dir: Path, kind: str
) -> tuple[dict, list[dict]]:
    version, _ = TARGETS[kind]
    paths = {
        "propensity_manifest.json": labels_dir / "propensity_manifest.json",
        "propensity_labels.csv": labels_dir / "propensity_labels.csv",
        "feature_manifest.json": features_dir / "feature_manifest.json",
        "features.csv": features_dir / "features.csv",
    }
    label_manifest = _load(paths["propensity_manifest.json"])
    feature_manifest = _load(paths["feature_manifest.json"])
    if (
        label_manifest.get("development_only") is not True
        or label_manifest.get("experiment_ready") is not False
        or feature_manifest.get("training_ready") is not False
    ):
        raise ValueError("Development-only source manifests required")
    if label_manifest.get("target_versions", {}).get(kind) != version:
        raise ValueError("Unexpected label version for target")
    if feature_manifest.get("feature_version") != FEATURE_VERSION:
        raise ValueError("Unexpected feature version")
    if label_manifest.get("output_sha256", {}).get("propensity_labels.csv") != sha256(
        paths["propensity_labels.csv"]
    ) or feature_manifest.get("output_sha256", {}).get("features.csv") != sha256(
        paths["features.csv"]
    ):
        raise ValueError("Input checksum mismatch")
    features = _read_features(paths["features.csv"])
    if len(features) != feature_manifest.get("rows"):
        raise ValueError("Feature row count mismatch")
    labels = _typed_labels(paths["propensity_labels.csv"], kind, version)
    rows = join_propensity_training_rows(features, labels, kind)
    _validate_propensity(rows, kind)
    _, holdout, _, _ = temporal_split(_normalized(rows))
    return paths, holdout


def _membership_holdout(
    labels_dir: Path, membership_dir: Path
) -> tuple[dict, list[dict]]:
    """Rebuild the exact membership experiment cohort, without calling its fitter."""
    paths = {
        "propensity_manifest.json": labels_dir / "propensity_manifest.json",
        "propensity_labels.csv": labels_dir / "propensity_labels.csv",
        "membership_manifest.json": membership_dir / "membership_manifest.json",
        "membership_features.csv": membership_dir / "membership_features.csv",
    }
    labels_manifest = _load(paths["propensity_manifest.json"])
    member_manifest = _load(paths["membership_manifest.json"])
    for manifest in (labels_manifest, member_manifest):
        if (
            manifest.get("development_only") is not True
            or manifest.get("training_ready") is not False
        ):
            raise ValueError("Development-only manifests required")
    if (
        labels_manifest.get("experiment_ready") is not False
        or labels_manifest.get("final_model") is not False
    ):
        raise ValueError("Development-only label manifest required")
    if (
        labels_manifest.get("target_versions", {}).get("renewal60")
        != membership.RENEWAL_VERSION
    ):
        raise ValueError("Unexpected label version")
    if member_manifest.get("feature_version") != membership.MEMBERSHIP_FEATURE_VERSION:
        raise ValueError("Unexpected membership feature version")
    if member_manifest.get("identity_time_policy") != "CURRENT_SNAPSHOT_RETROSPECTIVE":
        raise ValueError("Unexpected identity time policy")
    for manifest, filename in (
        (labels_manifest, "propensity_labels.csv"),
        (member_manifest, "membership_features.csv"),
    ):
        if manifest.get("output_sha256") != {filename: sha256(paths[filename])}:
            raise ValueError("Input checksum mismatch")
    cutoffs = membership._cutoffs(labels_manifest)
    if cutoffs != membership._cutoffs(member_manifest):
        raise ValueError("Membership and label cutoffs must match")
    members = membership._read_csv(
        paths["membership_features.csv"], membership.MEMBERSHIP_FIELDS
    )
    labels = membership._read_csv(
        paths["propensity_labels.csv"], membership.LABEL_FIELDS
    )
    if (
        type(member_manifest.get("row_count")) is not int
        or len(members) != member_manifest["row_count"]
    ):
        raise ValueError("Membership row count mismatch")
    for rows in (members, labels):
        if {key[1] for key in membership._index(rows)} != cutoffs:
            raise ValueError("CSV and manifest cutoffs must match")
    rows = membership.join_rows(members, labels)
    eligible_cutoffs = sorted(
        {_aware_timestamp(row["cutoff_at"], "cutoff_at") for row in rows}
    )
    if (
        len(eligible_cutoffs) != 2
        or [c.month for c in eligible_cutoffs] != [3, 6]
        or eligible_cutoffs[0].year != eligible_cutoffs[1].year
    ):
        raise ValueError("Exactly March and June cutoffs in the same year required")
    _, holdout, _, _ = temporal_split(rows)
    return paths, holdout


def run(
    kind: str,
    model_dir: Path,
    output_dir: Path,
    *,
    source_dir: Path | None = None,
    labels_dir: Path | None = None,
    features_dir: Path | None = None,
    membership_dir: Path | None = None,
    repeats: int = REPEATS,
    seed: int = SEED,
    min_n: int = MIN_SEGMENT_N,
) -> dict:
    """Score the rebuilt holdout fold of one fitted experiment and write one JSON report."""
    if kind not in KINDS:
        raise ValueError(f"Unknown kind: {kind!r}")
    model_dir, output_dir = Path(model_dir), Path(output_dir)
    sources = [
        Path(p)
        for p in (
            (source_dir,)
            if kind == "churn"
            else (
                (labels_dir, membership_dir)
                if kind == "renewal60_membership"
                else (labels_dir, features_dir)
            )
        )
        if p
    ]
    _check_paths(
        model_dir.resolve(), output_dir.resolve(), [p.resolve() for p in sources]
    )
    source_names = (
        (("model_manifest.json", "training_rows.csv"),)
        if kind == "churn"
        else (
            ("propensity_manifest.json", "propensity_labels.csv"),
            (
                ("membership_manifest.json", "membership_features.csv")
                if kind == "renewal60_membership"
                else ("feature_manifest.json", "features.csv")
            ),
        )
    )
    source_before = {
        name: sha256(directory / name)
        for directory, names in zip(sources, source_names)
        for name in names
    }
    if kind == "churn":
        if source_dir is None:
            raise ValueError(
                "churn requires --source-dir with the labelled training rows"
            )
        source_paths, holdout = _churn_holdout(Path(source_dir))
    elif kind == "renewal60_membership":
        if labels_dir is None or membership_dir is None:
            raise ValueError(
                "membership renewal requires --labels-dir and --membership-dir"
            )
        source_paths, holdout = _membership_holdout(
            Path(labels_dir), Path(membership_dir)
        )
    else:
        if labels_dir is None or features_dir is None:
            raise ValueError("propensity kinds require --labels-dir and --features-dir")
        source_paths, holdout = _propensity_holdout(
            Path(labels_dir), Path(features_dir), kind
        )
    model_paths = {
        name: model_dir / name
        for name in (
            "experiment_manifest.json",
            "model_parameters.json",
            "evaluation.json",
        )
    }
    paths = {**{f"model/{k}": v for k, v in model_paths.items()}, **source_paths}
    before = {name: sha256(path) for name, path in paths.items()}
    if any(before[name] != digest for name, digest in source_before.items()):
        raise ValueError("Input changed while rebuilding holdout")
    experiment = _load(model_paths["experiment_manifest.json"])
    if (
        experiment.get("development_only") is not True
        or experiment.get("serving_ready") is not False
    ):
        raise ValueError("Development-only, non-serving experiment manifest required")
    if (
        experiment.get("output_sha256", {}).get("model_parameters.json")
        != before["model/model_parameters.json"]
    ):
        raise ValueError(
            "model_parameters.json checksum mismatch against experiment_manifest"
        )
    evaluation = _load(model_paths["evaluation.json"])
    if (
        experiment.get("output_sha256", {}).get("evaluation.json")
        != before["model/evaluation.json"]
    ):
        raise ValueError(
            "evaluation.json checksum mismatch against experiment_manifest"
        )
    if len(holdout) != evaluation.get("test_rows") or sorted(
        {r["cutoff_at"] for r in holdout}
    ) != evaluation.get("test_cutoffs"):
        raise ValueError("Rebuilt holdout does not match the fitted experiment")
    for name, path in source_paths.items():
        if experiment.get("input_sha256", {}).get(name) != before[name]:
            raise ValueError(f"{name} differs from the fitted experiment input")
    parameters = _load(model_paths["model_parameters.json"])
    if (
        kind != "renewal60_membership"
        and tuple(parameters.get("features") or ()) == membership.FEATURES
    ):
        raise ValueError("Membership parameters require renewal60_membership kind")
    if kind == "renewal60_membership":
        _membership_contract(parameters)
        _membership_contract(experiment)
        _membership_contract(evaluation)
    if kind != "churn" and parameters.get("target") != (
        "renewal60" if kind == "renewal60_membership" else kind
    ):
        raise ValueError("Model parameters target does not match the requested kind")
    report = evaluate(
        parameters, holdout, LABEL_KEYS[kind], repeats=repeats, seed=seed, min_n=min_n
    )
    after = {name: sha256(path) for name, path in paths.items()}
    if after != before:
        raise ValueError("Input changed during importance run")
    report["kind"] = kind
    report["model_version"] = parameters.get("model_version")
    report["model_parameters_sha256"] = before["model/model_parameters.json"]
    report["input_sha256"] = before
    report["input_sha256_after"] = after
    output_dir.mkdir(parents=True)
    (output_dir / "importance_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (output_dir / "importance_manifest.json").write_text(
        json.dumps(
            {
                "kind": kind,
                "explainer_method": EXPLAINER_METHOD,
                "explainer_version": EXPLAINER_VERSION,
                "seed": seed,
                "repeats": repeats,
                "development_only": True,
                "serving_ready": False,
                "final_model": False,
                "refitted": False,
                "input_sha256": before,
                "input_sha256_after": after,
                **(membership.STATUS if kind == "renewal60_membership" else {}),
                "limitations": report["limitations"],
                "output_sha256": {name: sha256(output_dir / name) for name in OUTPUTS},
            },
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, choices=KINDS)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--labels-dir", type=Path)
    parser.add_argument("--features-dir", type=Path)
    parser.add_argument("--membership-dir", type=Path)
    parser.add_argument("--repeats", type=int, default=REPEATS)
    parser.add_argument("--min-n", type=int, default=MIN_SEGMENT_N)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = run(
        args.kind,
        args.model_dir,
        args.output_dir,
        source_dir=args.source_dir,
        labels_dir=args.labels_dir,
        features_dir=args.features_dir,
        membership_dir=args.membership_dir,
        repeats=args.repeats,
        min_n=args.min_n,
    )
    print(
        json.dumps(
            {
                "kind": report["kind"],
                "holdout_rows": report["holdout_rows"],
                "serving_ready": report["serving_ready"],
                "output": str(args.output_dir),
            }
        )
    )


if __name__ == "__main__":
    main()
