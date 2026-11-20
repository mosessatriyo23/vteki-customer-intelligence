"""Read-only development model inventory (TRD §9.6 metadata, not a registry).

This module inspects existing, already-produced model experiment directories
and reports what their own manifests already declare: version identifiers,
output checksums (re-verified here, not trusted blindly), reported
limitations, and which TRD §9.6 promotion fields are present or absent.

It never writes to an artifact, never sets ``validated_by``, never marks a
model ``ACTIVE``/promoted, and never invents a trained_by/validated_by
identity, a calibration reference, or a leakage-check result that the source
manifest does not already carry. A real registry (persistent storage, a
promotion workflow, an author != validator check enforced in code, and a
one-ACTIVE-per-type constraint) is a separate, larger piece of work that
belongs with the platform/validator handoff; this is a read-only inventory
of what Moses's own dev experiments currently contain.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path

_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _read_verified(path: Path) -> bytes:
    """Reject link/replacement artifacts before reading from a single handle.

    POSIX uses O_NOFOLLOW. On Windows, where that flag is absent, compare
    lstat identity with the opened handle before reading any bytes. Reject
    reparse points and non-regular files. Artifact directories are trusted;
    this does not sandbox concurrent replacement of ancestor directories.
    """
    before = path.lstat()
    if stat.S_ISLNK(before.st_mode) or getattr(before, "st_file_attributes", 0) & 0x400:
        raise ValueError("Symlink/reparse artifacts are not allowed")
    flags = os.O_RDONLY | _NOFOLLOW | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"{path.name}: cannot open artifact") from exc
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError(f"{path.name}: artifact must be a regular file")
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("Symlink or file changed before artifact read")
        chunks = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


# TRD 9.6: "Setiap baris model_version memuat algoritma, hyperparameter,
# jendela train/validation/test, feature_set_version, metrik, referensi
# calibration, referensi explainability, hasil pemeriksaan leakage, state,
# trained_by, validated_by ...". None of Moses's dev experiment manifests
# currently populate these promotion-governance fields; they are listed here
# so every inventory row states exactly what a validator would still need.
PROMOTION_REQUIREMENTS = (
    "trained_by",
    "validated_by",
    "calibration_ref",
    "explainability_ref",
    "leakage_check_result",
)

EVALUATION_DISCLAIMER = (
    "Metrik ini dihitung atas data sintetis yang dihasilkan oleh proyek ini. "
    "Metrik tersebut mencirikan generator, bukan populasi pelanggan nyata "
    "mana pun, dan tidak memprediksi kinerja produksi."
)


EVIDENCE_FIELDS = (
    "features",
    "train_cutoffs",
    "test_cutoffs",
    "train_rows",
    "test_rows",
    "seed",
    "sklearn_version",
    "serialization",
    "algorithm",
    "hyperparameters",
)


def _valid_metadata(field: str, value: object) -> bool:
    if field in {"features", "train_cutoffs", "test_cutoffs"}:
        return isinstance(value, list) and all(isinstance(v, str) for v in value)
    if field in {"train_rows", "test_rows", "seed"}:
        return type(value) is int and (field == "seed" or value >= 0)
    if field == "hyperparameters":
        return isinstance(value, dict)
    return isinstance(value, str) and bool(value.strip())


def _evidence_metadata(verified: dict[str, bytes]) -> dict:
    """Extract only explicitly named declarations from checksum-verified bytes.

    These are source-reported facts, not independent validation of training.
    A ``logistic`` key, fitted coefficients, or library defaults never establish
    an algorithm/hyperparameter declaration. Conflicts stay unknown rather than
    silently selecting one source. Existing artifacts lack explicit algorithm
    and complete hyperparameter declarations; that remains a metadata gap.
    """
    documents = {}
    for name in ("evaluation.json", "model_parameters.json"):
        if name in verified:
            document = json.loads(verified[name].decode("utf-8"))
            if isinstance(document, dict):
                documents[name] = document
    values = {}
    sources: dict[str, dict[str, str] | None] = {}
    conflicts = []
    for field in EVIDENCE_FIELDS:
        candidates = []
        for name, document in documents.items():
            keys = (
                (field, "serialization_note") if field == "serialization" else (field,)
            )
            for key in keys:
                value = document.get(key)
                if _valid_metadata(field, value):
                    candidates.append((name, value))
        if candidates and all(value == candidates[0][1] for _, value in candidates):
            name, value = candidates[0]
            values[field] = value
            sources[field] = {
                "file": name,
                "sha256": hashlib.sha256(verified[name]).hexdigest(),
            }
        else:
            values[field] = None
            sources[field] = None
            if candidates:
                conflicts.append(field)
    return {
        "values": values,
        "sources": sources,
        "missing_metadata": [
            field for field in EVIDENCE_FIELDS if values[field] is None
        ],
        "conflicting_metadata": conflicts,
    }


def _inspect(directory: Path) -> dict:
    manifest_path = directory / "experiment_manifest.json"
    if not manifest_path.exists():
        raise ValueError(f"{directory}: missing experiment_manifest.json")
    if manifest_path.is_symlink():
        raise ValueError("Symlink artifacts are not allowed")
    manifest_bytes = _read_verified(manifest_path)
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if (
        manifest.get("development_only") is not True
        or manifest.get("serving_ready") is not False
    ):
        raise ValueError(
            f"{directory}: only development-only, non-serving manifests may be"
            " inventoried"
        )
    expected = manifest.get("output_sha256")
    if not isinstance(expected, dict) or not expected:
        raise ValueError("output_sha256 must be a nonempty checksum mapping")
    mismatches = []
    verified: dict[str, bytes] = {}
    for name, digest in expected.items():
        if (
            not isinstance(name, str)
            or not name
            or "/" in name
            or "\\" in name
            or name in {".", ".."}
            or ":" in name
        ):
            raise ValueError("Artifact names must be simple filenames")
        if not isinstance(digest, str):
            raise ValueError("Artifact checksums must be strings")
        path = directory / name
        if path.is_symlink():
            raise ValueError("Symlink artifacts are not allowed")
        if not path.exists():
            mismatches.append(name)
            continue
        data = _read_verified(path)
        if path.is_symlink():
            raise ValueError("Artifact changed during inventory")
        if hashlib.sha256(data).hexdigest() != digest:
            mismatches.append(name)
        else:
            verified[name] = data
    mismatches.sort()

    evaluation = None
    raw_limitations = manifest.get("limitations", [])
    if not isinstance(raw_limitations, list) or not all(
        isinstance(item, str) for item in raw_limitations
    ):
        raise ValueError("limitations must be a list of strings")
    limitations = list(raw_limitations)
    if "evaluation.json" in verified:
        evaluation = json.loads(verified["evaluation.json"].decode("utf-8"))
        report_limitations = (
            evaluation.get("limitations", []) if isinstance(evaluation, dict) else []
        )
        if not isinstance(report_limitations, list) or not all(
            isinstance(item, str) for item in report_limitations
        ):
            raise ValueError("evaluation limitations must be a list of strings")
        for item in report_limitations:
            if item not in limitations:
                limitations.append(item)

    return {
        "artifact_dir": directory.name,
        "model_version": manifest.get("model_version"),
        "feature_version": manifest.get("feature_version"),
        "target": manifest.get("target"),
        "limitations": limitations,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "artifact_sha256": dict(expected),
        "checksums_verified": not mismatches,
        "checksum_mismatches": mismatches,
        "evaluation": evaluation,
        "evidence_metadata": _evidence_metadata(verified),
        "trained_by": manifest.get("trained_by"),
        "validated_by": manifest.get("validated_by"),
        "calibration_ref": manifest.get("calibration_ref"),
        "explainability_ref": manifest.get("explainability_ref"),
        "leakage_check_result": manifest.get("leakage_check_result"),
        "missing_for_promotion": [
            field for field in PROMOTION_REQUIREMENTS if not manifest.get(field)
        ],
        "state": "UNREGISTERED_DEV_ONLY",
        "promotable": False,
    }


def build_inventory(directories: list[Path]) -> dict:
    """Return a read-only inventory of development model experiment directories.

    Raises on any non-development or serving-ready manifest rather than
    silently including it. Checksum mismatches are reported, not hidden.
    Output is a deterministic function of the manifests' own content,
    independent of input order.
    """
    entries = sorted(
        (_inspect(Path(directory)) for directory in directories),
        key=lambda entry: entry["artifact_dir"],
    )
    names = [entry["artifact_dir"] for entry in entries]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate artifact_dir names in inventory input")
    return {
        "models": entries,
        "registry_authoritative": False,
        "serving_ready": False,
        "evaluation_disclaimer": EVALUATION_DISCLAIMER,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Use a new output file")
    report = build_inventory(args.model_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"inventoried={len(report['models'])} registry_authoritative=False")


if __name__ == "__main__":
    main()
