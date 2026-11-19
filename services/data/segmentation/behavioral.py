"""Anonymous, non-serving behavioral clustering proposal on retrospective features.

Only the selected feature-snapshot cutoff is fitted; no labels or outcome data enter
this module. Current identity is applied retrospectively, so this is not PIT-safe.
"""

import argparse
import csv
import json
import math
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from services.data.features.snapshot import FIELDS, VERSION
from services.data.ingestion.validator import sha256

ALGORITHM_VERSION = "behavioral-proposal-dev-1.0"
FEATURES = (
    "recency_days",
    "tenure_days",
    "purchase_count_365d",
    "retained_revenue_365d",
    "purchase_count_60d",
    "purchase_count_90d",
    "retained_revenue_90d",
    "recency_missing",
)
LIMITATIONS = (
    "Synthetic data; current identity snapshot applied retrospectively, not point-in-time safe",
    "No ingestion/availability timestamps or historical transaction status/refund versions",
    "Feature snapshot omits category/channel mix, visit regularity, basket size, "
    "promotion response, app activity, complaints/service intensity and campaign exposure; "
    "do not infer those behaviors from these clusters",
    "Anonymous development proposal; human naming, description and approval required "
    "before any targeting; no serving or integration with segmentation lifecycle",
)


def _time(value):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid cutoff timestamp") from exc
    if parsed.utcoffset() != timedelta(hours=7):
        raise ValueError("Cutoff must have +07:00 timezone")
    return parsed


def _matrix(rows):
    data = []
    for row in rows:
        values = []
        missing = row["recency_days"] in (None, "")
        for field in FEATURES[:-1]:
            value = row[field]
            if field == "recency_days" and missing:
                value = 0  # Explicit indicator distinguishes missing recency from zero.
            if isinstance(value, bool) or value is None or value == "":
                raise ValueError(f"{field} must be finite nonnegative numeric")
            try:
                number = float(value)
            except (ValueError, TypeError, OverflowError) as exc:
                raise ValueError(f"{field} must be finite nonnegative numeric") from exc
            if not math.isfinite(number) or number < 0:
                raise ValueError(f"{field} must be finite nonnegative numeric")
            values.append(number)
        data.append([*values, float(missing)])
    return np.asarray(data, dtype=float)


def _gates():
    return dict(
        name=None,
        description=None,
        approved=False,
        targeting_allowed=False,
        serving_ready=False,
    )


def compute(rows: list[dict], cutoff_at: str) -> tuple[dict, list[dict]]:
    """Fit on the selected cutoff only; select k by bounded deterministic silhouette.

    The scaler and each KMeans fit only the same selected-cutoff population.
    Invalid/tiny/one-class solutions are excluded; equal scores choose smaller k.
    """
    _time(cutoff_at)
    selected = sorted(
        (r for r in rows if r["cutoff_at"] == cutoff_at),
        key=lambda r: r["golden_customer_id"],
    )
    if not selected:
        raise ValueError("No rows at selected cutoff")
    seen = set()
    for row in selected:
        customer = row["golden_customer_id"]
        if not customer or customer in seen:
            raise ValueError("Duplicate or missing golden_customer_id")
        seen.add(customer)
        if (
            row["feature_version"] != VERSION
            or row["identity_time_policy"] != "CURRENT_SNAPSHOT_RETROSPECTIVE"
            or row["training_ready"] not in (False, "False")
        ):
            raise ValueError("Unexpected feature version or readiness/identity policy")
    matrix = _matrix(selected)
    count = len(selected)
    minimum_size = max(2, math.ceil(count * 0.01))
    scaler = StandardScaler().fit(matrix)  # fit only the chosen as-of cutoff
    scaled = scaler.transform(matrix)
    # Select rows by fixed RNG rather than order; ≤1500 bounds silhouette O(n²).
    sample = np.sort(
        np.random.default_rng(42).choice(count, size=min(count, 1500), replace=False)
    )
    candidates = []
    best = None
    for k in range(3, min(8, count // minimum_size) + 1):
        if np.unique(scaled, axis=0).shape[0] < k:
            break
        model = KMeans(n_clusters=k, random_state=42, n_init=10).fit(scaled)
        labels = model.labels_
        sizes = np.bincount(labels, minlength=k)
        if np.any(sizes < minimum_size) or np.count_nonzero(sizes) != k:
            continue
        sampled_labels = labels[sample]
        if not 1 < len(set(sampled_labels)) < len(sample):
            continue
        score = float(silhouette_score(scaled[sample], sampled_labels))
        if not math.isfinite(score):
            continue
        candidates.append(
            dict(k=k, silhouette=score, minimum_cluster_size=int(sizes.min()))
        )
        if best is None or score > best[0]:  # ascending k resolves equal scores
            best = (score, k, labels)
    if best is None:
        raise ValueError("No nondegenerate cluster solution with minimum cluster size")
    score, k, labels = best
    profiles = []
    # Standardized delta from the entire population mean (zero in fitted space).
    for cluster_id in range(k):
        members = scaled[labels == cluster_id]
        delta = members.mean(axis=0) - scaled.mean(axis=0)
        top = sorted(
            range(len(FEATURES)), key=lambda idx: (-abs(delta[idx]), FEATURES[idx])
        )[:5]
        profiles.append(
            dict(
                cluster_id=cluster_id,
                size=len(members),
                top_feature_deltas=[
                    dict(feature=FEATURES[idx], standardized_delta=float(delta[idx]))
                    for idx in top
                ],
                **_gates(),
            )
        )
    membership = [
        dict(
            golden_customer_id=row["golden_customer_id"],
            cutoff_at=cutoff_at,
            feature_version=VERSION,
            algorithm_version=ALGORITHM_VERSION,
            cluster_id=int(label),
            **_gates(),
        )
        for row, label in zip(selected, labels)
    ]
    report = dict(
        cutoff_at=cutoff_at,
        feature_version=VERSION,
        algorithm_version=ALGORITHM_VERSION,
        selected_k=k,
        silhouette=score,
        sample_size=len(sample),
        minimum_cluster_size=minimum_size,
        rows=count,
        features=list(FEATURES),
        candidates=candidates,
        profiles=profiles,
        limitations=list(LIMITATIONS),
        **_gates(),
    )
    return report, membership


def _json(path, payload):
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def run(feature_dir: Path, output_dir: Path, cutoff_at: str) -> dict:
    """Verify feature artifact, compute one cutoff, publish immutable proposal."""
    feature_dir = Path(feature_dir).resolve()
    output_dir = Path(output_dir).resolve()
    if any(
        part.lower() == "ground_truth"
        for path in (feature_dir, output_dir)
        for part in path.parts
    ):
        raise ValueError("ground_truth is forbidden")
    if output_dir.exists():
        raise ValueError(
            "Use a new output directory; existing runs cannot be overwritten"
        )
    if (
        feature_dir == output_dir
        or feature_dir in output_dir.parents
        or output_dir in feature_dir.parents
    ):
        raise ValueError("Output directory must be separate from inputs")
    _time(cutoff_at)
    manifest_path = feature_dir / "feature_manifest.json"
    data_path = feature_dir / "features.csv"
    before = {p.name: sha256(p) for p in (manifest_path, data_path)}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("feature_version") != VERSION
        or manifest.get("training_ready") is not False
        or cutoff_at not in manifest.get("cutoffs", [])
        or manifest.get("output_sha256") != {"features.csv": before["features.csv"]}
    ):
        raise ValueError("Feature manifest version/cutoff/checksum mismatch")
    with data_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(FIELDS):
            raise ValueError("Unexpected feature columns (labels/outcomes forbidden)")
        rows = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Feature row field count differs from header")
            rows.append(row)
    if len(rows) != manifest.get("rows"):
        raise ValueError("Feature manifest row count mismatch")
    if {r["cutoff_at"] for r in rows} != set(manifest["cutoffs"]):
        raise ValueError("Feature manifest cutoff mismatch")
    report, membership = compute(rows, cutoff_at)
    if any(sha256(feature_dir / name) != digest for name, digest in before.items()):
        raise ValueError("Inputs changed during computation")
    output_dir.mkdir(parents=True)
    _json(output_dir / "memberships.json", membership)
    _json(output_dir / "profiles.json", report)
    result = dict(
        algorithm_version=ALGORITHM_VERSION,
        feature_version=VERSION,
        cutoff_at=cutoff_at,
        rows=len(membership),
        selected_k=report["selected_k"],
        silhouette=report["silhouette"],
        cluster_sizes=dict(Counter(str(m["cluster_id"]) for m in membership)),
        input_sha256=before,
        output_sha256={
            name: sha256(output_dir / name)
            for name in ("memberships.json", "profiles.json")
        },
        limitations=list(LIMITATIONS),
        **_gates(),
    )
    _json(output_dir / "manifest.json", result)  # completion marker
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cutoff-at", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.feature_dir, args.output_dir, args.cutoff_at),
            allow_nan=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
