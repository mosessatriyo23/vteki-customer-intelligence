"""Read-only, stdlib audit of generated CSVs (disk-backed indexes, bounded RAM).

python generator/audit_generated.py --inbound DIR --ground-truth DIR
Exit status is 0 for a clean audit, 1 for invariant violations, 2 for unreadable data.
Contractual consent/membership expiries may exceed the observation end.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

PRIMARY_KEYS = {
    "crm_customers.csv": "crm_customer_id", "branches.csv": "branch_code",
    "catalogue_items.csv": "item_code", "transactions.csv": "source_transaction_id",
    "transaction_items.csv": "source_item_id", "app_events.csv": "event_id",
    "service_cases.csv": "source_case_id", "consent_events.csv": "source_consent_id",
    "identity_mapping.csv": "source_customer_id",
    "customer_latent_trajectories.csv": "golden_customer_id",
    "transaction_duplicates.csv": "source_transaction_id",
    "membership_events.csv": "event_id", "customer_visits.csv": "visit_id",
}
REQUIRED = tuple(name for name in PRIMARY_KEYS if name not in
                 ("membership_events.csv", "customer_visits.csv"))
TIERS = ("BRONZE", "SILVER", "GOLD", "PLATINUM")


def rows(path):
    with Path(path).open(newline="", encoding="utf-8") as stream:
        yield from csv.DictReader(stream)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def normalize_phone(value):
    digits = re.sub(r"\D", "", value)
    return "62" + digits[1:] if digits.startswith("0") else digits


def normalize_email(value):
    value = value.strip().lower()
    if "@" not in value:
        return value
    local, domain = value.split("@", 1)
    return local.split("+", 1)[0] + "@" + domain


def fingerprint(row):
    return tuple(row.get(key, "").strip() for key in (
        "source_customer_ref", "source_system", "branch_code", "channel_code",
        "transaction_datetime", "gross_amount", "discount_amount", "net_amount", "status"))


def audit(inbound, truth):
    inbound, truth = Path(inbound), Path(truth)
    manifest = json.loads((inbound / "generation_manifest.json").read_text(encoding="utf-8"))
    start = datetime.fromisoformat(manifest["observation_period"]["from"])
    end = datetime.fromisoformat(manifest["observation_period"]["to"])
    errors, examples, counts = Counter(), {}, {}
    statuses, scenarios, trajectories = Counter(), Counter(), Counter()

    def check(condition, kind, detail):
        if not condition:
            errors[kind] += 1
            if len(examples.setdefault(kind, [])) < 5:
                examples[kind].append(str(detail))

    with tempfile.TemporaryDirectory(prefix="vteki-audit-") as temporary:
        db = sqlite3.connect(str(Path(temporary) / "indexes.sqlite"))
        try:
            db.execute("CREATE TABLE records (name TEXT, id TEXT, data TEXT, PRIMARY KEY(name,id))")
            db.execute("CREATE TABLE sums (id TEXT PRIMARY KEY, amount INTEGER, lines INTEGER)")
            db.execute("CREATE TABLE identities (kind TEXT, value TEXT, golden TEXT, scenario TEXT)")
            db.execute("CREATE TABLE visit_keys (key TEXT PRIMARY KEY)")
            paths = {}
            for folder, section, legacy in ((inbound, "tables", "checksums_sha256"),
                                             (truth, "ground_truth_tables", "ground_truth_checksums_sha256")):
                entries = manifest.get(section, {})
                filenames = set(entries) | set(manifest.get(legacy, {}))
                filenames |= {p.name for p in folder.glob("*.csv")}
                for name in sorted(filenames):
                    path = folder / name
                    paths[name] = path
                    check(path.is_file(), "missing_file", name)
                    if not path.is_file():
                        continue
                    metadata = entries.get(name, {})
                    expected = metadata.get("sha256", manifest.get(legacy, {}).get(name))
                    check(expected is not None, "missing_manifest_entry", name)
                    actual = digest(path)
                    check(actual == expected, "checksum", name)
                    if name in manifest.get(legacy, {}):
                        check(actual == manifest[legacy][name], "legacy_checksum", name)
                    if "schema_version" in metadata:
                        check(metadata["schema_version"] == manifest["schema_version"], "schema_version", name)
                    if path.suffix != ".csv":
                        continue
                    count = 0
                    with path.open(newline="", encoding="utf-8") as stream:
                        reader = csv.DictReader(stream)
                        fields = reader.fieldnames or []
                        check(bool(fields) and len(fields) == len(set(fields)), "csv_header", name)
                        key = PRIMARY_KEYS.get(name)
                        check(not key or key in fields, "pk_header", name)
                        for row in reader:
                            count += 1
                            check(None not in row and None not in row.values(), "csv_shape", f"{name}:{count}")
                            if key:
                                identity = row.get(key, "")
                                check(bool(identity), "empty_pk", f"{name}:{count}")
                                try:
                                    db.execute("INSERT INTO records VALUES (?,?,?)", (name, identity, json.dumps(row)))
                                except sqlite3.IntegrityError:
                                    check(False, "duplicate_pk", f"{name}:{identity}")
                    counts[name] = count
                    if metadata.get("row_count") is not None:
                        check(count == metadata["row_count"], "manifest_count", name)
                    if name[:-4] in manifest.get("volumes", {}):
                        check(count == manifest["volumes"][name[:-4]], "manifest_volume", name)
            for name in REQUIRED:
                check(name in paths and paths[name].is_file(), "required_table", name)
            db.commit()

            def records(name):
                for (data,) in db.execute("SELECT data FROM records WHERE name=?", (name,)):
                    yield json.loads(data)

            def get(name, identity):
                result = db.execute("SELECT data FROM records WHERE name=? AND id=?", (name, identity)).fetchone()
                return json.loads(result[0]) if result else None

            def fk(name, identity, detail, optional=False):
                result = get(name, identity) if identity else None
                check(bool(result) or (optional and not identity), "foreign_key", detail)
                return result

            def moment(value, detail, lower=start, upper=end):
                try:
                    result = datetime.fromisoformat(value)
                    check(result.utcoffset() == timedelta(hours=7), "timezone", detail)
                    check((lower is None or result >= lower) and (upper is None or result <= upper), "temporal", detail)
                    return result
                except (ValueError, TypeError):
                    check(False, "invalid_timestamp", detail)
                    return None

            def customer_time(row, field, customer_field="source_customer_ref"):
                occurred = moment(row[field], row)
                customer = fk("crm_customers.csv", row[customer_field], row, optional=customer_field == "source_customer_ref" and "source_transaction_id" in row)
                if customer and occurred:
                    check(occurred.date().isoformat() >= customer["join_date"], "before_join", row)
                return occurred

            for row in records("identity_mapping.csv"):
                fk("crm_customers.csv", row["source_customer_id"], row)
                fk("customer_latent_trajectories.csv", row["golden_customer_id"], row)
                scenarios[row["identity_scenario"]] += 1
                check(row["identity_scenario"] in ("GOLDEN_SOURCE", "DUPLICATE_VARIANT", "SHARED_PHONE_TRAP"), "identity_scenario", row)
                check(row["source_system"] in ("CRM", "POS", "APP"), "identity_source", row)
            for row in records("customer_latent_trajectories.csv"):
                trajectories[row["trajectory"]] += 1
                check(row["trajectory"] in ("LOYAL_STABLE", "DECLINING", "ONE_TIME", "SEASONAL", "NEW", "DORMANT"), "trajectory", row)
                check(row["observed_from"] == start.date().isoformat() and row["observed_to"] == end.date().isoformat(), "trajectory_window", row)
            check(dict(trajectories) == manifest["trajectory_distribution"], "trajectory_distribution", trajectories)
            check(sum(trajectories.values()) == manifest["golden_customers"], "golden_count", trajectories)
            check(counts.get("crm_customers.csv") == manifest["golden_customers"] + manifest["duplicate_source_records"], "source_count", counts)
            for row in records("crm_customers.csv"):
                mapping = fk("identity_mapping.csv", row["crm_customer_id"], row)
                fk("branches.csv", row["preferred_branch_code"], row)
                updated = moment(row["source_updated_at"], row)
                check(start.date().isoformat() <= row["join_date"] <= end.date().isoformat(), "join_window", row)
                check(not updated or updated.date().isoformat() >= row["join_date"], "update_before_join", row)
                check(row["status"] in ("ACTIVE", "INACTIVE", "CLOSED"), "customer_status", row)
                check(row["gender"] in ("F", "M", "U") and 1 <= int(row["birth_month"]) <= 12, "customer_demographics", row)
                check((bool(row["member_code"]) and row["membership_tier"] in TIERS) or (not row["member_code"] and not row["membership_tier"]), "customer_membership", row)
                if mapping:
                    for kind, value in (("phone", normalize_phone(row["phone_raw"])), ("email", normalize_email(row["email_raw"])), ("member", row["member_code"])):
                        if value:
                            db.execute("INSERT INTO identities VALUES (?,?,?,?)", (kind, value, mapping["golden_customer_id"], mapping["identity_scenario"]))
            db.execute("CREATE INDEX identity_values ON identities(kind,value)")
            collisions = Counter()
            for kind, value, size, unmarked in db.execute("SELECT kind,value,COUNT(DISTINCT golden), SUM(scenario != 'SHARED_PHONE_TRAP') FROM identities GROUP BY kind,value HAVING COUNT(DISTINCT golden)>1"):
                collisions[kind] += 1
                check(kind == "phone" and unmarked == 0, "identity_collision", f"{kind}:{value}:{size}")

            for row in records("transactions.csv"):
                identity = row["source_transaction_id"]
                customer_time(row, "transaction_datetime")
                statuses[row["status"]] += 1
                check(row["status"] in ("COMPLETED", "CANCELLED", "REFUNDED", "PARTIAL_REFUND"), "transaction_status", row)
                check((row["source_system"] == "POS" and row["channel_code"] == "POS_STORE" and bool(fk("branches.csv", row["branch_code"], row))) or (row["source_system"] == "ECOM" and row["channel_code"] in ("MOBILE_APP", "WEB_STORE") and not row["branch_code"]), "transaction_channel", row)
                gross, discount, net, refund, revenue = (int(row[k]) for k in ("gross_amount", "discount_amount", "net_amount", "refund_amount", "actual_revenue"))
                check(gross > 0 and 0 <= discount <= gross and net == gross - discount and 0 <= refund <= net, "accounting", row)
                expected = 0 if row["status"] in ("CANCELLED", "REFUNDED") else net - refund
                check(revenue == expected, "actual_revenue", row)
                check((row["status"] == "REFUNDED" and refund == net) or (row["status"] == "PARTIAL_REFUND" and 0 < refund < net) or (row["status"] in ("COMPLETED", "CANCELLED") and refund == 0), "refund_status", row)
                mapping = fk("transaction_duplicates.csv", identity, row)
                if mapping:
                    canonical = fk("transactions.csv", mapping["duplicate_group_id"], mapping)
                    fk("customer_latent_trajectories.csv", mapping["golden_customer_id"], mapping)
                    if row["source_customer_ref"]:
                        owner = get("identity_mapping.csv", row["source_customer_ref"])
                        check(owner and owner["golden_customer_id"] == mapping["golden_customer_id"], "transaction_identity", row)
                    check(mapping["event_kind"] == ("BUSINESS_TRANSACTION" if identity == mapping["duplicate_group_id"] else "DUPLICATE_BUSINESS_EVENT"), "duplicate_kind", mapping)
                    if canonical:
                        check({k: v for k, v in row.items() if k != "source_transaction_id"} == {k: v for k, v in canonical.items() if k != "source_transaction_id"}, "duplicate_payload", identity)
            for row in records("transaction_duplicates.csv"):
                fk("transactions.csv", row["source_transaction_id"], row)
            for row in records("transaction_items.csv"):
                fk("transactions.csv", row["source_transaction_id"], row)
                item = fk("catalogue_items.csv", row["item_code"], row)
                qty, price, amount = (int(row[k]) for k in ("qty", "unit_price", "line_amount"))
                check(qty > 0 and price > 0 and amount == qty * price, "line_accounting", row)
                check(item and row["item_type"] == item["item_type"] and price == int(item["list_price"]), "catalogue_line", row)
                db.execute("INSERT INTO sums VALUES (?,?,1) ON CONFLICT(id) DO UPDATE SET amount=amount+excluded.amount, lines=lines+1", (row["source_transaction_id"], amount))
            for row in records("transactions.csv"):
                total = db.execute("SELECT amount FROM sums WHERE id=?", (row["source_transaction_id"],)).fetchone()
                check(total and total[0] == int(row["gross_amount"]), "gross_line_sum", row)
            for row in records("app_events.csv"):
                customer_time(row, "occurred_at", "source_customer_id")
                check(row["event_type"] in ("APP_OPEN", "PRODUCT_VIEW", "SEARCH", "CART_ADD") and row["channel"] == "APP", "app_status", row)
                item = fk("catalogue_items.csv", row["item_id"], row, optional=row["event_type"] in ("APP_OPEN", "SEARCH"))
                check(not item or item["item_type"] == "PRODUCT", "app_item", row)
            for row in records("service_cases.csv"):
                opened = customer_time(row, "opened_at")
                check(row["status"] in ("OPEN", "IN_PROGRESS", "RESOLVED"), "case_status", row)
                if row["status"] == "RESOLVED":
                    moment(row["closed_at"], row, lower=opened or start)
                    check(bool(row["resolution_code"]), "case_resolution", row)
                else:
                    check(not row["closed_at"] and not row["resolution_code"], "case_resolution", row)
            for row in records("consent_events.csv"):
                captured = customer_time(row, "captured_at")
                moment(row["expires_at"], row, lower=captured or start, upper=None)
                check(row["state"] in ("OPT_IN", "OPT_OUT", "UNKNOWN") and row["purpose"] in ("MARKETING", "SERVICE") and row["channel_code"] in ("EMAIL", "PUSH"), "consent_status", row)

            for row in records("membership_events.csv"):
                customer = fk("crm_customers.csv", row["source_customer_ref"], row)
                occurred = moment(row["occurred_at"], row, lower=None)
                period = moment(row["period_start"], row, lower=None)
                expiry = moment(row["expires_at"], row, lower=period, upper=None)
                check(occurred == period and period and expiry == period + timedelta(days=180), "membership_period", row)
                check(customer and row["member_code"] == customer["member_code"] and bool(row["member_code"]) and row["membership_tier"] in TIERS, "membership_customer", row)
                if row["event_type"] == "JOIN":
                    check(not row["previous_event_id"] and customer and occurred and occurred.date().isoformat() == customer["join_date"], "membership_join", row)
                else:
                    previous = fk("membership_events.csv", row["previous_event_id"], row)
                    check(row["event_type"] == "RENEWAL" and previous and previous["source_customer_ref"] == row["source_customer_ref"] and occurred == datetime.fromisoformat(previous["expires_at"]) + timedelta(days=1), "membership_chain", row)
                    if previous and row["membership_tier"] in TIERS and previous["membership_tier"] in TIERS:
                        check(0 <= TIERS.index(row["membership_tier"]) - TIERS.index(previous["membership_tier"]) <= 1, "membership_tier", row)
            for row in records("customer_visits.csv"):
                customer_time(row, "visit_datetime")
                transaction = fk("transactions.csv", row["source_transaction_id"], row)
                fk("branches.csv", row["branch_code"], row)
                check(row["status"] == "COMPLETED" and transaction and transaction["source_system"] == "POS" and transaction["status"] in ("COMPLETED", "PARTIAL_REFUND") and all(row[a] == transaction[b] for a, b in (("source_customer_ref", "source_customer_ref"), ("branch_code", "branch_code"), ("visit_datetime", "transaction_datetime"))), "visit_transaction", row)
                if transaction:
                    try:
                        db.execute("INSERT INTO visit_keys VALUES (?)", (json.dumps(fingerprint(transaction)),))
                    except sqlite3.IntegrityError:
                        check(False, "visit_replay", row)
            if "customer_visits.csv" in paths:
                for row in records("transactions.csv"):
                    if row["source_system"] == "POS" and row["status"] in ("COMPLETED", "PARTIAL_REFUND") and row["source_customer_ref"]:
                        check(db.execute("SELECT 1 FROM visit_keys WHERE key=?", (json.dumps(fingerprint(row)),)).fetchone(), "missing_visit", row)
            db.commit()
        finally:
            db.close()
    return {"ok": not errors, "counts": counts, "errors": dict(sorted(errors.items())),
            "examples": examples, "identity_collisions": dict(collisions),
            "identity_scenarios": dict(scenarios), "trajectories": dict(trajectories),
            "transaction_statuses": dict(statuses),
            "optional_tables_present": [name for name in ("membership_events.csv", "customer_visits.csv") if name in paths]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inbound", "--output-dir", type=Path, default=Path("inbound/2026-09-06"))
    parser.add_argument("--ground-truth", "--ground-truth-dir", type=Path, default=Path("generator/ground_truth"))
    args = parser.parse_args()
    try:
        report = audit(args.inbound, args.ground_truth)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        print(json.dumps({"ok": False, "fatal_error": str(exc)}, indent=2))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
