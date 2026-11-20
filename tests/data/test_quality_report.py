"""Offline per-table data-quality report (FR-CDI-004 / T-CDI-04, development only)."""

import csv
import json
from pathlib import Path

import pytest

from services.data.ingestion.contracts import SCHEMA_VERSION, TABLES
from services.data.ingestion.quality_report import (
    QualityThresholds,
    build_quality_report,
    main,
    write_quality_report,
)
from services.data.ingestion.validator import sha256

THRESHOLDS = QualityThresholds(
    max_missing_rate=0.05,
    max_invalid_rate=0.05,
    max_duplicate_rate=0.05,
    max_untimely_rate=0.05,
    max_orphan_rate=0.05,
)
TS = "2026-08-01T10:00:00+07:00"


def _write(root: Path, name: str, rows: list[dict[str, str]]) -> None:
    with (root / name).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=TABLES[name].fields)
        writer.writeheader()
        writer.writerows(rows)


def _transaction(i: int) -> dict[str, str]:
    return {
        "source_transaction_id": f"T{i}",
        "source_customer_ref": "C1",
        "source_system": "POS",
        "branch_code": "B1",
        "channel_code": "STORE",
        "transaction_datetime": TS,
        "gross_amount": "1000",
        "discount_amount": "0",
        "net_amount": "1000",
        "refund_amount": "0",
        "actual_revenue": "1000",
        "status": "COMPLETED",
    }


def _batch(root: Path, transactions: list[dict[str, str]]) -> Path:
    inbound = root / "inbound"
    inbound.mkdir()
    (inbound / "generation_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "observation_period": {
                    "from": "2026-01-01T00:00:00+07:00",
                    "to": "2026-09-06T23:59:59+07:00",
                },
            }
        ),
        encoding="utf-8",
    )
    _write(
        inbound,
        "branches.csv",
        [
            {
                "branch_code": "B1",
                "branch_name": "Main",
                "city": "Yogyakarta",
                "region": "DIY",
                "active_flag": "True",
            }
        ],
    )
    _write(inbound, "transactions.csv", transactions)
    return inbound


def _metric(report: dict, table: str, metric: str, field: str | None = None) -> dict:
    found = [
        m
        for m in report["metrics"]
        if m["entity"] == table
        and m["metric_name"] == metric
        and m.get("field") == field
    ]
    assert len(found) == 1, (table, metric, field)
    return found[0]


def test_eight_percent_missing_amount_breaches_five_percent_threshold(tmp_path):
    rows = [_transaction(i) for i in range(100)]
    for row in rows[:8]:
        row["gross_amount"] = ""
    report = build_quality_report(_batch(tmp_path, rows), THRESHOLDS)

    completeness = _metric(report, "transactions.csv", "completeness")
    assert completeness["numerator"] == 8
    assert completeness["denominator"] == 100
    assert completeness["metric_value"] == 0.08
    assert completeness["threshold"] == 0.05
    assert completeness["status"] == "QUALITY_WARNING"
    assert completeness["offending_records"] == 8
    assert completeness["offending_row_numbers"][:2] == [2, 3]
    assert report["quality_warning"] is True
    assert "QUALITY_WARNING" in report["flags"]
    # empty required value is completeness, not double-counted as invalid
    assert _metric(report, "transactions.csv", "validity")["offending_records"] == 0


def test_clean_fixture_has_no_warning_and_states_scope_limits(tmp_path):
    rows = [_transaction(i) for i in range(20)]
    report = build_quality_report(_batch(tmp_path, rows), THRESHOLDS)

    assert report["quality_warning"] is False
    assert report["flags"] == []
    assert all(
        m["status"] in {"OK", "NOT_APPLICABLE", "NOT_EVALUABLE"}
        for m in report["metrics"]
    ), report["metrics"]
    assert report["development_only"] is True
    enforcement = report["enforcement"]
    assert enforcement["downstream_blocking_enforced"] is False
    assert enforcement["acknowledgement_enforced"] is False
    assert "James" in enforcement["note"]
    assert report["tables"]["transactions.csv"]["row_count"] == 20


def test_duplicate_keys_counted_beyond_first_occurrence(tmp_path):
    rows = [_transaction(i) for i in range(10)]
    rows[5]["source_transaction_id"] = "T1"
    rows[9]["source_transaction_id"] = "T1"
    report = build_quality_report(_batch(tmp_path, rows), THRESHOLDS)

    uniqueness = _metric(report, "transactions.csv", "uniqueness")
    assert uniqueness["numerator"] == 2
    assert uniqueness["denominator"] == 10
    assert uniqueness["offending_row_numbers"] == [7, 11]
    assert uniqueness["status"] == "QUALITY_WARNING"


def test_orphan_foreign_key_reported_per_reference(tmp_path):
    rows = [_transaction(i) for i in range(10)]
    rows[3]["branch_code"] = "B404"
    rows[4]["branch_code"] = ""  # nullable and empty: excluded from denominator
    report = build_quality_report(_batch(tmp_path, rows), THRESHOLDS)

    branch = _metric(report, "transactions.csv", "referential_integrity", "branch_code")
    assert branch["numerator"] == 1
    assert branch["denominator"] == 9
    assert branch["status"] == "QUALITY_WARNING"
    assert branch["target"] == "branches.csv.branch_code"
    # crm_customers.csv absent: reference cannot be evaluated, not silently OK
    customer = _metric(
        report, "transactions.csv", "referential_integrity", "source_customer_ref"
    )
    assert customer["status"] == "NOT_EVALUABLE"
    assert "crm_customers.csv" in report["missing_tables"]


def test_validity_and_timeliness_use_manifest_window(tmp_path):
    rows = [_transaction(i) for i in range(10)]
    rows[0]["status"] = "BOGUS"
    rows[1]["transaction_datetime"] = "2027-01-01T00:00:00+07:00"
    rows[2]["gross_amount"] = "abc"
    report = build_quality_report(_batch(tmp_path, rows), THRESHOLDS)

    assert _metric(report, "transactions.csv", "validity")["numerator"] == 2
    timeliness = _metric(report, "transactions.csv", "timeliness")
    assert timeliness["numerator"] == 1
    assert timeliness["denominator"] == 10
    branches = _metric(report, "branches.csv", "timeliness")
    assert branches["status"] == "NOT_APPLICABLE"


def test_threshold_comparison_uses_exact_fraction_not_rounded_display(tmp_path):
    rows = [_transaction(i) for i in range(7)]
    rows[0]["gross_amount"] = ""
    thresholds = QualityThresholds(0.142857, 1, 1, 1, 1)
    metric = _metric(
        build_quality_report(_batch(tmp_path, rows), thresholds),
        "transactions.csv",
        "completeness",
    )
    assert metric["metric_value"] == 0.142857
    assert metric["status"] == "QUALITY_WARNING"


def test_thresholds_are_required_and_bounded():
    with pytest.raises(TypeError):
        QualityThresholds()  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        QualityThresholds(1.5, 0.05, 0.05, 0.05, 0.05)


def test_report_is_deterministic_and_inputs_untouched(tmp_path):
    inbound = _batch(tmp_path, [_transaction(i) for i in range(5)])
    before = {p.name: p.read_bytes() for p in inbound.iterdir()}
    first = build_quality_report(inbound, THRESHOLDS)
    second = build_quality_report(inbound, THRESHOLDS)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert before == {p.name: p.read_bytes() for p in inbound.iterdir()}

    out = tmp_path / "out"
    path = write_quality_report(first, out, inbound=inbound)
    assert (
        path.read_text(encoding="utf-8")
        == json.dumps(first, indent=2, sort_keys=True) + "\n"
    )
    with pytest.raises(FileExistsError):
        write_quality_report(first, out, inbound=inbound)
    with pytest.raises(ValueError):
        write_quality_report(first, inbound / "nested", inbound=inbound)


def test_cli_writes_new_directory(tmp_path):
    inbound = _batch(tmp_path, [_transaction(i) for i in range(5)])
    out = tmp_path / "cli_out"
    code = main(
        [
            "--inbound",
            str(inbound),
            "--output-dir",
            str(out),
            "--max-missing-rate",
            "0.05",
            "--max-invalid-rate",
            "0.05",
            "--max-duplicate-rate",
            "0.05",
            "--max-untimely-rate",
            "0.05",
            "--max-orphan-rate",
            "0.05",
        ]
    )
    assert code == 0
    assert (
        json.loads((out / "quality_report.json").read_text())["development_only"]
        is True
    )


def _set_period(inbound: Path, start: object, end: object) -> None:
    path = inbound / "generation_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["observation_period"] = {"from": start, "to": end}
    path.write_text(json.dumps(manifest), encoding="utf-8")


def _bind_tables(inbound: Path) -> None:
    path = inbound / "generation_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["tables"] = {}
    for table in ("branches.csv", "transactions.csv"):
        file = inbound / table
        with file.open(newline="", encoding="utf-8") as stream:
            count = sum(1 for _ in csv.DictReader(stream))
        manifest["tables"][table] = {
            "schema_version": SCHEMA_VERSION,
            "sha256": sha256(file),
            "row_count": count,
        }
    path.write_text(json.dumps(manifest), encoding="utf-8")


def _customer(i: int, **override: str) -> dict[str, str]:
    row = {
        "crm_customer_id": f"C{i}",
        "full_name": "A",
        "phone_raw": "",
        "email_raw": "",
        "birth_month": "6",
        "gender": "F",
        "city": "Yogyakarta",
        "member_code": "M1",
        "membership_tier": "GOLD",
        "join_date": "2026-02-01",
        "preferred_branch_code": "B1",
        "status": "ACTIVE",
        "source_updated_at": TS,
    }
    row.update(override)
    return row


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-01-01T00:00:00+00:00", "2026-09-06T23:59:59+07:00"),
        ("2026-01-01T00:00:00", "2026-09-06T23:59:59+07:00"),
        ("2026-09-06T23:59:59+07:00", "2026-01-01T00:00:00+07:00"),
        ("2026-01-01T00:00:00+07:00", "2026-09-06T23:59:59+00:00"),
    ],
)
def test_invalid_manifest_window_is_not_evaluable_with_error(tmp_path, start, end):
    inbound = _batch(tmp_path, [_transaction(i) for i in range(5)])
    _set_period(inbound, start, end)
    report = build_quality_report(inbound, THRESHOLDS)

    timeliness = _metric(report, "transactions.csv", "timeliness")
    assert timeliness["status"] == "NOT_EVALUABLE"
    assert isinstance(report["window_error"], str) and report["window_error"]
    assert report["observation_period"] is None
    assert "transactions.csv:timeliness:None" in report["not_evaluable_metrics"]


def test_valid_window_has_no_window_error(tmp_path):
    report = build_quality_report(_batch(tmp_path, [_transaction(0)]), THRESHOLDS)
    assert report["window_error"] is None
    assert "transactions.csv:timeliness:None" not in report["not_evaluable_metrics"]


def test_window_error_states_reason_for_missing_unparseable_wrong_shape(tmp_path):
    inbound = _batch(tmp_path, [_transaction(0)])
    manifest = inbound / "generation_manifest.json"

    manifest.write_text("{not json", encoding="utf-8")
    assert "unparseable" in build_quality_report(inbound, THRESHOLDS)["window_error"]

    manifest.write_text(json.dumps({"observation_period": "x"}), encoding="utf-8")
    assert "shape" in build_quality_report(inbound, THRESHOLDS)["window_error"]

    manifest.write_text(json.dumps([1]), encoding="utf-8")
    assert "shape" in build_quality_report(inbound, THRESHOLDS)["window_error"]

    manifest.write_text(
        json.dumps({"observation_period": {"from": "garbage", "to": "x"}}),
        encoding="utf-8",
    )
    assert "unparseable" in build_quality_report(inbound, THRESHOLDS)["window_error"]

    manifest.unlink()
    report = build_quality_report(inbound, THRESHOLDS)
    assert "missing manifest" in report["window_error"]
    assert "transactions.csv:timeliness:None" in report["not_evaluable_metrics"]


def test_not_evaluable_metrics_lists_unevaluable_references(tmp_path):
    report = build_quality_report(
        _batch(tmp_path, [_transaction(i) for i in range(3)]), THRESHOLDS
    )
    assert (
        "transactions.csv:referential_integrity:source_customer_ref"
        in report["not_evaluable_metrics"]
    )


@pytest.mark.parametrize(
    "stamp",
    ["2026-08-01T10:00:00", "2026-08-01T10:00:00+00:00", "2026-08-01T10:00:00Z"],
)
def test_naive_or_non_plus7_timestamp_is_invalid_and_not_timely(tmp_path, stamp):
    rows = [_transaction(i) for i in range(10)]
    rows[0]["transaction_datetime"] = stamp
    report = build_quality_report(_batch(tmp_path, rows), THRESHOLDS)

    assert _metric(report, "transactions.csv", "validity")["numerator"] == 1
    assert _metric(report, "transactions.csv", "timeliness")["numerator"] == 1


def test_crm_validator_rules_count_as_invalid(tmp_path):
    inbound = _batch(tmp_path, [_transaction(0)])
    _write(
        inbound,
        "crm_customers.csv",
        [
            _customer(0),
            _customer(1, birth_month="13"),
            _customer(2, member_code="", membership_tier="GOLD"),
            _customer(3, member_code="M3", membership_tier=""),
            _customer(4, membership_tier="DIAMOND"),
            _customer(5, member_code="", membership_tier=""),
        ],
    )
    report = build_quality_report(inbound, THRESHOLDS)
    validity = _metric(report, "crm_customers.csv", "validity")
    assert validity["numerator"] == 4
    assert validity["offending_row_numbers"] == [3, 4, 5, 6]


def test_non_utf8_csv_raises_value_error_naming_table(tmp_path):
    inbound = _batch(tmp_path, [_transaction(0)])
    (inbound / "branches.csv").write_bytes(
        b"branch_code,branch_name,city,region,active_flag\nB1,Caf\xe9,Y,D,True\n"
    )
    with pytest.raises(ValueError, match="branches.csv"):
        build_quality_report(inbound, THRESHOLDS)


def test_matching_manifest_binding_is_verified(tmp_path):
    inbound = _batch(tmp_path, [_transaction(i) for i in range(3)])
    _bind_tables(inbound)
    report = build_quality_report(inbound, THRESHOLDS)
    assert report["manifest_verified"] is True
    assert report["manifest_mismatches"] == []
    assert report["schema_version"] == SCHEMA_VERSION


def test_hash_and_row_count_mismatch_reported_not_hidden(tmp_path):
    inbound = _batch(tmp_path, [_transaction(i) for i in range(3)])
    _bind_tables(inbound)
    path = inbound / "generation_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["tables"]["transactions.csv"]["sha256"] = "0" * 64
    manifest["tables"]["transactions.csv"]["row_count"] = 99
    path.write_text(json.dumps(manifest), encoding="utf-8")
    report = build_quality_report(inbound, THRESHOLDS)

    assert report["manifest_verified"] is False
    text = " ".join(report["manifest_mismatches"])
    assert "transactions.csv" in text and "sha256" in text and "row_count" in text
    assert not any("branches.csv" in m for m in report["manifest_mismatches"])


def test_schema_version_is_manifest_declared_and_mismatch_flagged(tmp_path):
    inbound = _batch(tmp_path, [_transaction(0)])
    _bind_tables(inbound)
    path = inbound / "generation_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["schema_version"] = "9.9.9"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    report = build_quality_report(inbound, THRESHOLDS)

    assert report["schema_version"] == "9.9.9"
    assert report["manifest_verified"] is False
    assert any("schema_version" in m for m in report["manifest_mismatches"])


def test_missing_manifest_is_unverified_with_reason(tmp_path):
    inbound = _batch(tmp_path, [_transaction(0)])
    (inbound / "generation_manifest.json").unlink()
    report = build_quality_report(inbound, THRESHOLDS)
    assert report["manifest_verified"] is False
    assert report["schema_version"] is None
    assert any("manifest" in m for m in report["manifest_mismatches"])


def test_write_rejects_report_for_different_inbound(tmp_path):
    inbound = _batch(tmp_path, [_transaction(0)])
    other = tmp_path / "other"
    other.mkdir()
    report = build_quality_report(inbound, THRESHOLDS)
    with pytest.raises(ValueError, match="inbound_dir"):
        write_quality_report(report, tmp_path / "out2", inbound=other)
    assert not (tmp_path / "out2").exists()
