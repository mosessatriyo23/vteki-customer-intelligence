"""Offline per-table data-quality report for synthetic inbound batches.

Implements the metric computation part of FRD FR-CDI-004 / TRD 6.2 / T-CDI-04:
completeness, validity, uniqueness, timeliness and referential integrity per
table, each with numerator, denominator and offending-record counts.

Thresholds are caller-supplied; this module defines no business defaults. A
metric breaches when its offending fraction is strictly greater than its
threshold (FRD example: 8% missing against a 5% threshold is a breach).

Scope limit: this report only *flags* ``QUALITY_WARNING``. Blocking downstream
feature refresh, acknowledgement with actor/reason, and the
QUALITY_THRESHOLD_BREACH / QUALITY_ACKNOWLEDGED audit events belong to the
platform (James) and are NOT enforced here. Development only, synthetic data.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .contracts import SCHEMA_VERSION, TABLES, TableContract
from .validator import _parse_integer, sha256

MAX_ROW_EXAMPLES = 100
REPORT_FILE = "quality_report.json"
ENFORCEMENT_NOTE = (
    "This offline report only flags QUALITY_WARNING. It does not block "
    "downstream feature refresh, record acknowledged_by/acknowledged_reason, "
    "or emit QUALITY_THRESHOLD_BREACH / QUALITY_ACKNOWLEDGED audit events; "
    "that enforcement belongs to the platform (James) and is NOT implemented here."
)


@dataclass(frozen=True)
class QualityThresholds:
    """Maximum tolerated offending fraction (0..1) per metric; no defaults."""

    max_missing_rate: float
    max_invalid_rate: float
    max_duplicate_rate: float
    max_untimely_rate: float
    max_orphan_rate: float

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be within [0, 1]: {value}")


def _metric(
    table: str,
    name: str,
    threshold: float,
    offenders: list[int],
    count: int,
    denominator: int,
    field: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    if denominator == 0:
        value, status = None, "NOT_EVALUABLE"
    else:
        value = round(count / denominator, 6)
        status = "QUALITY_WARNING" if count / denominator > threshold else "OK"
    return {
        "metric_name": name,
        "entity": table,
        "field": field,
        "numerator": count,
        "denominator": denominator,
        "metric_value": value,
        "threshold": threshold,
        "status": status,
        "offending_records": count,
        "offending_row_numbers": offenders[:MAX_ROW_EXAMPLES],
        **extra,
    }


def _inapplicable(table: str, name: str, status: str, reason: str) -> dict[str, Any]:
    return {
        "metric_name": name,
        "entity": table,
        "field": None,
        "numerator": 0,
        "denominator": 0,
        "metric_value": None,
        "threshold": None,
        "status": status,
        "offending_records": 0,
        "offending_row_numbers": [],
        "reason": reason,
    }


def _read_manifest(root: Path) -> tuple[dict[str, Any] | None, str | None]:
    path = root / "generation_manifest.json"
    if not path.is_file():
        return None, "missing manifest: generation_manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        return None, f"unparseable manifest: {exc}"
    if not isinstance(manifest, dict):
        return None, "wrong shape: manifest must be an object"
    return manifest, None


def _read_window(
    manifest: dict[str, Any] | None, manifest_error: str | None
) -> tuple[tuple[datetime, datetime] | None, str | None]:
    if manifest is None:
        return None, manifest_error
    period = manifest.get("observation_period")
    if not isinstance(period, dict) or not all(
        isinstance(period.get(bound), str) for bound in ("from", "to")
    ):
        return None, "wrong shape: observation_period requires string from and to"
    try:
        start = datetime.fromisoformat(period["from"])
        end = datetime.fromisoformat(period["to"])
    except ValueError as exc:
        return None, f"unparseable observation_period: {exc}"
    if (
        start.utcoffset() != timedelta(hours=7)
        or end.utcoffset() != timedelta(hours=7)
        or start > end
    ):
        return (
            None,
            "invalid observation_period: bounds must be ordered and timezone +07:00",
        )
    return (start, end), None


def _manifest_mismatches(
    manifest: dict[str, Any] | None,
    manifest_error: str | None,
    tables: dict[str, dict[str, Any]],
) -> list[str]:
    if manifest is None:
        return [manifest_error or "missing manifest"]
    mismatches = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        mismatches.append(
            f"schema_version: manifest={manifest.get('schema_version')!r} expected={SCHEMA_VERSION!r}"
        )
    declared = manifest.get("tables")
    if not isinstance(declared, dict):
        return [*mismatches, "tables: missing or malformed manifest metadata"]
    for name in sorted(set(tables) - set(declared)):
        mismatches.append(f"{name}: missing manifest table metadata")
    for name in sorted(set(declared) - set(tables)):
        mismatches.append(f"{name}: declared table file absent")
    for name in sorted(set(declared) - set(TABLES)):
        mismatches.append(f"{name}: unexpected manifest table metadata")
    for name, actual in tables.items():
        metadata = declared.get(name)
        if not isinstance(metadata, dict):
            if name in declared:
                mismatches.append(f"{name}: malformed manifest table metadata")
            continue
        for field in ("schema_version", "sha256", "row_count"):
            expected = SCHEMA_VERSION if field == "schema_version" else actual[field]
            if metadata.get(field) != expected:
                mismatches.append(
                    f"{name}.{field}: manifest={metadata.get(field)!r} actual={expected!r}"
                )
    return mismatches


MEMBERSHIP_TIERS = dict(TABLES["membership_events.csv"].enums)["membership_tier"]
SOURCE_UTC_OFFSET = timedelta(hours=7)


def _keys(path: Path, pk: str) -> set[str]:
    try:
        with path.open(newline="", encoding="utf-8") as stream:
            return {row[pk] for row in csv.DictReader(stream) if row.get(pk)}
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path.name}: not valid UTF-8 ({exc.reason})") from exc


def _valid_value(
    contract: TableContract, row: dict[str, str]
) -> bool:  # empty values are completeness, not validity
    enums = dict(contract.enums)
    for field, allowed in enums.items():
        if row[field] and row[field] not in allowed:
            return False
    for field in (*contract.positive, *contract.nonnegative):
        if not row[field]:
            continue
        try:
            number = _parse_integer(row[field])
        except ValueError:
            return False
        if number <= 0 and field in contract.positive:
            return False
        if number < 0:
            return False
    for field in contract.dates:
        if row[field]:
            try:
                date.fromisoformat(row[field])
            except ValueError:
                return False
    for field in contract.timestamps:
        if row[field]:
            try:
                parsed = datetime.fromisoformat(row[field])
            except ValueError:
                return False
            if parsed.utcoffset() != SOURCE_UTC_OFFSET:
                return False  # naive or non-+07:00, as validator invalid_timezone
    if contract is TABLES["crm_customers.csv"]:
        return _valid_crm(row)
    return True


def _valid_crm(row: dict[str, str]) -> bool:
    if row["birth_month"]:
        try:
            if not 1 <= _parse_integer(row["birth_month"]) <= 12:
                return False
        except ValueError:
            pass  # non-integer already invalid via the positive rule
    has_member = bool(row["member_code"])
    if has_member != bool(row["membership_tier"]):
        return False
    return not has_member or row["membership_tier"] in MEMBERSHIP_TIERS


def _rows(name: str, reader: Any) -> Any:
    try:
        yield from enumerate(reader, 2)
    except UnicodeDecodeError as exc:
        raise ValueError(f"{name}: not valid UTF-8 ({exc.reason})") from exc


def _untimely(
    contract: TableContract,
    row: dict[str, str],
    window: tuple[datetime, datetime],
) -> bool:
    start, end = window
    for field in contract.timestamps:
        if field == "expires_at" or not row[field]:
            continue  # contract expiry may legitimately be after observation end
        try:
            parsed = datetime.fromisoformat(row[field])
        except ValueError:
            continue  # counted by validity
        if parsed.utcoffset() != SOURCE_UTC_OFFSET:
            return True  # never scored timely; also counted invalid
        if not start <= parsed <= end:
            return True
    for field in contract.dates:
        if not row[field]:
            continue
        try:
            parsed_date = date.fromisoformat(row[field])
        except ValueError:
            continue
        if not start.date() <= parsed_date <= end.date():
            return True
    return False


def _table_metrics(
    name: str,
    root: Path,
    thresholds: QualityThresholds,
    window: tuple[datetime, datetime] | None,
    window_error: str | None,
    target_keys: dict[str, set[str] | None],
) -> tuple[list[dict[str, Any]], int, bool]:
    contract = TABLES[name]
    required = [f for f in contract.fields if f not in contract.nullable]
    refs = contract.references
    missing_rows: list[int] = []
    missing_by_field = dict.fromkeys(required, 0)
    invalid_rows: list[int] = []
    duplicate_rows: list[int] = []
    untimely_rows: list[int] = []
    orphan_rows: dict[str, list[int]] = {ref[0]: [] for ref in refs}
    orphan_count = dict.fromkeys(orphan_rows, 0)
    ref_denominator = dict.fromkeys(orphan_rows, 0)
    seen: set[str] = set()
    rows = pk_rows = 0
    counts = {"missing": 0, "invalid": 0, "duplicate": 0, "untimely": 0}
    with (root / name).open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != contract.fields:
            raise ValueError(f"{name}: header does not match source contract")
        for row_number, row in _rows(name, reader):
            if None in row or None in row.values():
                raise ValueError(f"{name}:{row_number}: csv shape mismatch")
            rows += 1
            absent = [f for f in required if not row[f]]
            if absent:
                counts["missing"] += 1
                missing_rows.append(row_number)
                for field in absent:
                    missing_by_field[field] += 1
            if not _valid_value(contract, row):
                counts["invalid"] += 1
                invalid_rows.append(row_number)
            key = row[contract.pk]
            if key:
                pk_rows += 1
                if key in seen:
                    counts["duplicate"] += 1
                    duplicate_rows.append(row_number)
                seen.add(key)
            if window and _untimely(contract, row, window):
                counts["untimely"] += 1
                untimely_rows.append(row_number)
            for field, target, _target_field in refs:
                value = row[field]
                keys = target_keys.get(target)
                if not value or keys is None:
                    continue
                ref_denominator[field] += 1
                if value not in keys:
                    orphan_count[field] += 1
                    orphan_rows[field].append(row_number)
    metrics = [
        _metric(
            name,
            "completeness",
            thresholds.max_missing_rate,
            missing_rows,
            counts["missing"],
            rows,
            required_fields=required,
            missing_by_field=missing_by_field,
        ),
        _metric(
            name,
            "validity",
            thresholds.max_invalid_rate,
            invalid_rows,
            counts["invalid"],
            rows,
        ),
        _metric(
            name,
            "uniqueness",
            thresholds.max_duplicate_rate,
            duplicate_rows,
            counts["duplicate"],
            pk_rows,
            primary_key=contract.pk,
        ),
    ]
    has_time = bool(contract.timestamps or contract.dates)
    if not has_time:
        metrics.append(
            _inapplicable(name, "timeliness", "NOT_APPLICABLE", "no time fields")
        )
    elif window is None:
        metrics.append(
            _inapplicable(
                name,
                "timeliness",
                "NOT_EVALUABLE",
                f"observation window unusable: {window_error}",
            )
        )
    else:
        metrics.append(
            _metric(
                name,
                "timeliness",
                thresholds.max_untimely_rate,
                untimely_rows,
                counts["untimely"],
                rows,
                basis="inside manifest observation_period (expires_at excluded)",
            )
        )
    for field, target, target_field in refs:
        label = f"{target}.{target_field}"
        if target_keys.get(target) is None:
            item = _inapplicable(
                name, "referential_integrity", "NOT_EVALUABLE", f"{target} absent"
            )
            item.update(field=field, target=label)
            metrics.append(item)
            continue
        metrics.append(
            _metric(
                name,
                "referential_integrity",
                thresholds.max_orphan_rate,
                orphan_rows[field],
                orphan_count[field],
                ref_denominator[field],
                field=field,
                target=label,
            )
        )
    return metrics, rows, True


def build_quality_report(
    inbound: str | Path, thresholds: QualityThresholds
) -> dict[str, Any]:
    """Compute the report for one inbound directory; inputs are read-only."""
    root = Path(inbound).resolve()
    manifest, manifest_error = _read_manifest(root)
    window, window_error = _read_window(manifest, manifest_error)
    present = [name for name in TABLES if (root / name).is_file()]
    missing_tables = sorted(set(TABLES) - set(present))
    target_keys: dict[str, set[str] | None] = {
        name: (_keys(root / name, TABLES[name].pk) if name in present else None)
        for name in TABLES
    }
    metrics: list[dict[str, Any]] = []
    tables: dict[str, dict[str, Any]] = {}
    for name in present:
        table_metrics, rows, _ = _table_metrics(
            name, root, thresholds, window, window_error, target_keys
        )
        metrics.extend(table_metrics)
        tables[name] = {"row_count": rows, "sha256": sha256(root / name)}
    mismatches = _manifest_mismatches(manifest, manifest_error, tables)
    declared_version = manifest.get("schema_version") if manifest else None
    not_evaluable = [
        f"{m['entity']}:{m['metric_name']}:{m['field']}"
        for m in metrics
        if m["status"] == "NOT_EVALUABLE"
    ]
    warnings = [
        f"{m['entity']}:{m['metric_name']}:{m['field']}"
        for m in metrics
        if m["status"] == "QUALITY_WARNING"
    ]
    return {
        "report_type": "offline_data_quality",
        "requirement": "FRD FR-CDI-004; TRD 6.2; T-CDI-04",
        "schema_version": declared_version,
        "expected_schema_version": SCHEMA_VERSION,
        "manifest_verified": not mismatches,
        "manifest_mismatches": mismatches,
        "window_error": window_error,
        "not_evaluable_metrics": not_evaluable,
        "development_only": True,
        "synthetic_data_only": True,
        "inbound_dir": str(root),
        "observation_period": (
            None
            if window is None
            else {"from": window[0].isoformat(), "to": window[1].isoformat()}
        ),
        "thresholds": {
            "max_missing_rate": thresholds.max_missing_rate,
            "max_invalid_rate": thresholds.max_invalid_rate,
            "max_duplicate_rate": thresholds.max_duplicate_rate,
            "max_untimely_rate": thresholds.max_untimely_rate,
            "max_orphan_rate": thresholds.max_orphan_rate,
            "comparison": "QUALITY_WARNING when offending_fraction > threshold",
        },
        "enforcement": {
            "downstream_blocking_enforced": False,
            "acknowledgement_enforced": False,
            "audit_events_emitted": False,
            "note": ENFORCEMENT_NOTE,
        },
        "missing_tables": missing_tables,
        "tables": tables,
        "metrics": metrics,
        "quality_warning": bool(warnings),
        "flags": ["QUALITY_WARNING"] if warnings else [],
        "warning_metrics": warnings,
    }


def write_quality_report(
    report: dict[str, Any], output_dir: str | Path, inbound: str | Path
) -> Path:
    """Write deterministic JSON into a NEW directory outside the inbound batch."""
    out = Path(output_dir).resolve()
    source = Path(inbound).resolve()
    if report.get("inbound_dir") != str(source):
        raise ValueError(
            f"report inbound_dir {report.get('inbound_dir')!r} does not match "
            f"inbound argument {str(source)!r}"
        )
    if out == source or source in out.parents:
        raise ValueError("output directory must be outside the inbound batch")
    out.mkdir(parents=True, exist_ok=False)
    path = out / REPORT_FILE
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inbound", required=True)
    parser.add_argument("--output-dir", required=True)
    for flag in ("missing", "invalid", "duplicate", "untimely", "orphan"):
        parser.add_argument(f"--max-{flag}-rate", type=float, required=True)
    args = parser.parse_args(argv)
    thresholds = QualityThresholds(
        args.max_missing_rate,
        args.max_invalid_rate,
        args.max_duplicate_rate,
        args.max_untimely_rate,
        args.max_orphan_rate,
    )
    report = build_quality_report(args.inbound, thresholds)
    path = write_quality_report(report, args.output_dir, args.inbound)
    print(f"{path} quality_warning={report['quality_warning']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
