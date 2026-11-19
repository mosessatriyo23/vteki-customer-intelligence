"""Isolated behavioral proposal contract tests."""

import csv
import json

import pytest

from services.data.features.snapshot import FIELDS, VERSION
from services.data.ingestion.validator import sha256
from services.data.segmentation import behavioral as b

JUNE = "2026-06-01T00:00:00+07:00"
MARCH = "2026-03-01T00:00:00+07:00"


def rows(n=60):
    return [
        dict(
            zip(
                FIELDS,
                [
                    f"id{i:04}",
                    JUNE,
                    "PROVISIONAL",
                    VERSION,
                    False,
                    "CURRENT_SNAPSHOT_RETROSPECTIVE",
                    i % 10,
                    100 + i,
                    2 + i % 7,
                    100 + (i // (n // 2)) * 100000 + i,
                    i % 3,
                    i % 5,
                    100 + i * 10,
                ],
            )
        )
        for i in range(n)
    ]


def source(tmp_path, data):
    folder = tmp_path / "features"
    folder.mkdir()
    with (folder / "features.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(data)
    (folder / "feature_manifest.json").write_text(
        json.dumps(
            dict(
                feature_version=VERSION,
                rows=len(data),
                training_ready=False,
                cutoffs=sorted({r["cutoff_at"] for r in data}),
                input_sha256={},
                output_sha256={"features.csv": sha256(folder / "features.csv")},
            )
        )
    )
    return folder


def test_deterministic_proposal_and_profiles():
    report, members = b.compute(rows(), JUNE)
    assert (report, members) == b.compute(list(reversed(rows())), JUNE)
    assert 3 <= report["selected_k"] <= 8
    assert sum(p["size"] for p in report["profiles"]) == 60
    assert len({m["cluster_id"] for m in members}) == report["selected_k"]
    for item in members + report["profiles"]:
        assert item["name"] is None and item["description"] is None
        assert not any(
            item[k] for k in ("approved", "targeting_allowed", "serving_ready")
        )
    assert all(len(p["top_feature_deltas"]) == 5 for p in report["profiles"])
    json.dumps(report, allow_nan=False)


def test_one_cutoff_only_and_train_statistics():
    data = rows()
    other = [{**r, "cutoff_at": MARCH, "tenure_days": 999999} for r in data]
    assert b.compute(data + other, JUNE) == b.compute(data, JUNE)


def test_small_k_bound_and_no_degenerate_clusters():
    report, _ = b.compute(rows(8), JUNE)
    assert max(c["k"] for c in report["candidates"]) <= 4
    flat = [{**rows()[0], "golden_customer_id": str(i)} for i in range(20)]
    with pytest.raises(ValueError, match="cluster"):
        b.compute(flat, JUNE)


def test_two_distinct_groups_cannot_be_faked_into_three_clusters():
    data = rows()
    for i, row in enumerate(data):
        for field in b.FEATURES[:-1]:
            row[field] = 1 if i < 30 else 1000
    with pytest.raises(ValueError, match="cluster"):
        b.compute(data, JUNE)


def test_duplicate_and_nonfinite_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        b.compute(rows() + [rows()[0]], JUNE)
    data = rows()
    data[0]["tenure_days"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        b.compute(data, JUNE)


def test_full_snapshot_hashes_and_no_overwrite(tmp_path):
    data = rows() + [{**r, "cutoff_at": MARCH} for r in rows()]
    src = source(tmp_path, data)
    out = tmp_path / "output"
    manifest = b.run(src, out, JUNE)
    members = json.loads((out / "memberships.json").read_text())
    assert len(members) == manifest["rows"] == 60
    assert {r["cutoff_at"] for r in members} == {JUNE}
    for name, digest in manifest["output_sha256"].items():
        assert sha256(out / name) == digest
    with pytest.raises(ValueError, match="existing"):
        b.run(src, out, JUNE)
    with (src / "features.csv").open("a") as f:
        f.write("\n")
    with pytest.raises(ValueError, match="checksum"):
        b.run(src, tmp_path / "out2", JUNE)


@pytest.mark.parametrize("surplus", [True, False])
def test_checksum_valid_malformed_row_rejected_before_compute(
    tmp_path, monkeypatch, surplus
):
    src = source(tmp_path, rows())
    path = src / "features.csv"
    with path.open(newline="") as stream:
        content = list(csv.reader(stream))
    if surplus:
        content[1].append("OUTCOME_LABEL")
    else:
        content[1].pop()
    with path.open("w", newline="") as stream:
        csv.writer(stream).writerows(content)
    manifest_path = src / "feature_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["output_sha256"]["features.csv"] = sha256(path)
    manifest_path.write_text(json.dumps(manifest))

    def forbidden(*args, **kwargs):
        pytest.fail("Malformed CSV reached compute")

    monkeypatch.setattr(b, "compute", forbidden)
    with pytest.raises(ValueError, match="field count"):
        b.run(src, tmp_path / "output", JUNE)
    assert not (tmp_path / "output").exists()


def test_input_changes_during_compute_rejected(tmp_path, monkeypatch):
    src = source(tmp_path, rows())
    original = b.compute

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        with (src / "feature_manifest.json").open("a") as f:
            f.write(" ")
        return result

    monkeypatch.setattr(b, "compute", changed)
    with pytest.raises(ValueError, match="changed"):
        b.run(src, tmp_path / "output", JUNE)
    assert not (tmp_path / "output").exists()


def test_overlap_and_ground_truth_rejected(tmp_path):
    src = source(tmp_path, rows())
    with pytest.raises(ValueError, match="separate"):
        b.run(src, src / "output", JUNE)
    with pytest.raises(ValueError, match="ground_truth"):
        b.run(tmp_path / "ground_truth", tmp_path / "output", JUNE)


def test_ground_truth_parent_rejected(tmp_path):
    with pytest.raises(ValueError, match="ground_truth"):
        b.run(tmp_path / "ground_truth" / "features", tmp_path / "out", JUNE)


def test_missing_recency_retains_every_customer():
    data = rows()
    for row in data[:10]:
        row["recency_days"] = None
    report, members = b.compute(data, JUNE)
    assert len(members) == len(data)
    assert "recency_missing" in report["features"]
    with pytest.raises(TypeError):
        b.compute(data, JUNE, targeting_allowed=True)
