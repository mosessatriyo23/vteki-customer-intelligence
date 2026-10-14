"""Streaming, source-only validation for VTEKI ingestion batches."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .contracts import LOAD_ORDER, SCHEMA_VERSION, TABLES, TableContract


GROUND_TRUTH_FILES = frozenset({
    "identity_mapping.csv", "customer_latent_trajectories.csv",
    "transaction_duplicates.csv", "injected_campaign_effects.json",
})


@dataclass(frozen=True)
class Rejection:
    file_name: str
    row_number: int
    code: str
    detail: str


@dataclass
class ValidationReport:
    valid: bool
    schema_version: str | None
    row_counts: dict[str, int]
    errors: dict[str, int]
    rejections: list[Rejection]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["rejections"] = [asdict(item) for item in self.rejections]
        return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _parse_integer(value: str) -> int:
    if value.strip() != value or not value or any(char not in "-0123456789" for char in value):
        raise ValueError(value)
    return int(value)


class BatchValidator:
    """Validate one generated inbound directory without loading evaluation truth."""

    def __init__(self, max_rejection_examples: int = 100) -> None:
        self.max_rejection_examples = max_rejection_examples

    def validate(self, inbound: str | Path) -> ValidationReport:
        root = Path(inbound).resolve()
        errors: Counter[str] = Counter()
        examples: list[Rejection] = []
        counts: dict[str, int] = {}

        def reject(file_name: str, row_number: int, code: str, detail: object) -> None:
            errors[code] += 1
            if len(examples) < self.max_rejection_examples:
                examples.append(Rejection(file_name, row_number, code, str(detail)))

        manifest_path = root / "generation_manifest.json"
        if not manifest_path.is_file():
            reject("generation_manifest.json", 0, "missing_manifest", manifest_path)
            return ValidationReport(False, None, counts, dict(errors), examples)
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            reject("generation_manifest.json", 0, "invalid_manifest", exc)
            return ValidationReport(False, None, counts, dict(errors), examples)
        if not isinstance(manifest, dict):
            reject("generation_manifest.json", 0, "invalid_manifest", "Expected object")
            return ValidationReport(False, None, counts, dict(errors), examples)
        schema_version = manifest.get("schema_version")
        if schema_version != SCHEMA_VERSION:
            reject("generation_manifest.json", 0, "unsupported_schema", schema_version)
            return ValidationReport(False, schema_version, counts, dict(errors), examples)
        table_meta = manifest.get("tables")
        if not isinstance(table_meta, dict):
            reject("generation_manifest.json", 0, "missing_table_metadata", "tables")
            return ValidationReport(False, schema_version, counts, dict(errors), examples)
        declared = set(table_meta)
        expected = set(TABLES)
        for name in sorted(expected - declared):
            reject("generation_manifest.json", 0, "missing_manifest_table", name)
        for name in sorted(declared - expected):
            reject("generation_manifest.json", 0, "unexpected_manifest_table", name)
        for forbidden in sorted(GROUND_TRUTH_FILES & declared):
            reject("generation_manifest.json", 0, "ground_truth_forbidden", forbidden)
        for forbidden in sorted(GROUND_TRUTH_FILES & {p.name for p in root.iterdir() if p.is_file()}):
            reject(forbidden, 0, "ground_truth_forbidden", "Evaluation-only file present in inbound")
        for unexpected in sorted({p.name for p in root.glob("*.csv")} - expected):
            if unexpected not in GROUND_TRUTH_FILES:
                reject(unexpected, 0, "unexpected_source_file", unexpected)
        try:
            start = datetime.fromisoformat(manifest["observation_period"]["from"])
            end = datetime.fromisoformat(manifest["observation_period"]["to"])
            if start.utcoffset() != timedelta(hours=7) or end.utcoffset() != timedelta(hours=7) or start > end:
                raise ValueError("Observation bounds must be ordered and timezone +07:00")
        except (KeyError, TypeError, ValueError) as exc:
            reject("generation_manifest.json", 0, "invalid_observation_period", exc)
            return ValidationReport(False, schema_version, counts, dict(errors), examples)

        with tempfile.TemporaryDirectory(prefix="vteki-ingest-validation-") as temporary:
            db = sqlite3.connect(str(Path(temporary) / "keys.sqlite"))
            try:
                db.execute("CREATE TABLE keys (file_name TEXT, value TEXT, PRIMARY KEY(file_name,value))")
                db.execute("CREATE TABLE tx_sums (value TEXT PRIMARY KEY, amount INTEGER NOT NULL)")
                for file_name in LOAD_ORDER:
                    contract = TABLES[file_name]
                    path = root / file_name
                    metadata = table_meta.get(file_name, {})
                    if not isinstance(metadata, dict):
                        reject(file_name, 0, "invalid_table_metadata", metadata)
                        continue
                    if metadata.get("schema_version") != SCHEMA_VERSION:
                        reject(file_name, 0, "unsupported_table_schema", metadata.get("schema_version"))
                    if not path.is_file():
                        reject(file_name, 0, "missing_file", path)
                        continue
                    expected_hash = metadata.get("sha256")
                    if not expected_hash or sha256(path) != expected_hash:
                        reject(file_name, 0, "checksum_mismatch", expected_hash)
                        continue
                    count = self._validate_file(path, contract, db, start, end, reject)
                    counts[file_name] = count
                    if metadata.get("row_count") != count:
                        reject(file_name, 0, "row_count_mismatch", f"manifest={metadata.get('row_count')} actual={count}")
                if not errors:
                    self._validate_references(root, db, reject)
                    if not errors:
                        self._validate_semantics(root, db, reject)
                        self._validate_membership(root, db, reject)
                        self._validate_visits(root, db, reject)
                        self._validate_chronology(root, reject)
            finally:
                db.close()
        return ValidationReport(not errors, schema_version, counts, dict(sorted(errors.items())), examples)

    def _validate_file(self, path: Path, contract: TableContract, db: sqlite3.Connection,
                       start: datetime, end: datetime, reject: Any) -> int:
        count = 0
        with path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != contract.fields:
                reject(path.name, 0, "header_mismatch", reader.fieldnames)
                return 0
            enum_map = dict(contract.enums)
            for row_number, row in enumerate(reader, 2):
                count += 1
                if None in row or None in row.values():
                    reject(path.name, row_number, "csv_shape", row)
                    continue
                key = row[contract.pk]
                if not key:
                    reject(path.name, row_number, "missing_primary_key", contract.pk)
                else:
                    try:
                        db.execute("INSERT INTO keys VALUES (?,?)", (path.name, key))
                    except sqlite3.IntegrityError:
                        reject(path.name, row_number, "duplicate_primary_key", key)
                for field in contract.fields:
                    if not row[field] and field not in contract.nullable:
                        reject(path.name, row_number, "required_value", field)
                for field in contract.dates:
                    try:
                        parsed = date.fromisoformat(row[field])
                        if not start.date() <= parsed <= end.date():
                            reject(path.name, row_number, "date_outside_window", field)
                    except ValueError:
                        reject(path.name, row_number, "invalid_date", field)
                for field in contract.timestamps:
                    if not row[field] and field in contract.nullable:
                        continue
                    try:
                        parsed = datetime.fromisoformat(row[field])
                        if parsed.utcoffset() != timedelta(hours=7):
                            reject(path.name, row_number, "invalid_timezone", field)
                        # Contract expiration may be known beyond observation end.
                        if field not in {"expires_at"} and not start <= parsed <= end:
                            reject(path.name, row_number, "timestamp_outside_window", field)
                    except (TypeError, ValueError):
                        reject(path.name, row_number, "invalid_timestamp", field)
                for field in contract.nonnegative:
                    try:
                        if _parse_integer(row[field]) < 0:
                            reject(path.name, row_number, "negative_value", field)
                    except ValueError:
                        reject(path.name, row_number, "invalid_integer", field)
                for field in contract.positive:
                    try:
                        if _parse_integer(row[field]) <= 0:
                            reject(path.name, row_number, "nonpositive_value", field)
                    except ValueError:
                        reject(path.name, row_number, "invalid_integer", field)
                if path.name == 'crm_customers.csv':
                    try:
                        if not 1 <= _parse_integer(row['birth_month']) <= 12:
                            reject(path.name, row_number, 'invalid_birth_month', row['birth_month'])
                    except ValueError:
                        pass  # already reported as invalid_integer
                    has_member = bool(row['member_code'])
                    if has_member != bool(row['membership_tier']):
                        reject(path.name, row_number, 'membership_mismatch', row['crm_customer_id'])
                    if has_member and row['membership_tier'] not in {'BRONZE', 'SILVER', 'GOLD', 'PLATINUM'}:
                        reject(path.name, row_number, 'invalid_enum', 'membership_tier')
                for field, values in enum_map.items():
                    if row[field] not in values:
                        reject(path.name, row_number, "invalid_enum", f"{field}={row[field]}")
        db.commit()
        return count

    def _validate_references(self, root: Path, db: sqlite3.Connection, reject: Any) -> None:
        for file_name, contract in TABLES.items():
            with (root / file_name).open(newline="", encoding="utf-8") as stream:
                for row_number, row in enumerate(csv.DictReader(stream), 2):
                    for field, target, _target_field in contract.references:
                        value = row[field]
                        if not value and field in contract.nullable:
                            continue
                        found = db.execute("SELECT 1 FROM keys WHERE file_name=? AND value=?", (target, value)).fetchone()
                        if not found:
                            reject(file_name, row_number, "foreign_key", f"{field}->{target}:{value}")

    def _validate_semantics(self, root: Path, db: sqlite3.Connection, reject: Any) -> None:
        with (root / "transaction_items.csv").open(newline="", encoding="utf-8") as stream:
            for row_number, row in enumerate(csv.DictReader(stream), 2):
                qty, price, amount = (int(row[field]) for field in ("qty", "unit_price", "line_amount"))
                if amount != qty * price:
                    reject("transaction_items.csv", row_number, "line_accounting", row["source_item_id"])
                db.execute(
                    "INSERT INTO tx_sums VALUES (?,?) ON CONFLICT(value) DO UPDATE SET amount=amount+excluded.amount",
                    (row["source_transaction_id"], amount),
                )
        with (root / "transactions.csv").open(newline="", encoding="utf-8") as stream:
            for row_number, row in enumerate(csv.DictReader(stream), 2):
                gross, discount, net, refund, revenue = (
                    int(row[field]) for field in
                    ("gross_amount", "discount_amount", "net_amount", "refund_amount", "actual_revenue")
                )
                total = db.execute("SELECT amount FROM tx_sums WHERE value=?", (row["source_transaction_id"],)).fetchone()
                if not total or total[0] != gross:
                    reject("transactions.csv", row_number, "gross_item_sum", row["source_transaction_id"])
                if net != gross - discount or not 0 <= refund <= net:
                    reject("transactions.csv", row_number, "transaction_accounting", row["source_transaction_id"])
                expected = 0 if row["status"] in {"CANCELLED", "REFUNDED"} else net - refund
                if revenue != expected:
                    reject("transactions.csv", row_number, "actual_revenue", row["source_transaction_id"])
                valid_refund = (
                    (row["status"] == "REFUNDED" and refund == net)
                    or (row["status"] == "PARTIAL_REFUND" and 0 < refund < net)
                    or (row["status"] in {"COMPLETED", "CANCELLED"} and refund == 0)
                )
                if not valid_refund:
                    reject("transactions.csv", row_number, "refund_status", row["source_transaction_id"])

    def _validate_membership(self, root: Path, db: sqlite3.Connection, reject: Any) -> None:
        members: dict[str, str] = {}
        with (root / 'crm_customers.csv').open(newline='', encoding='utf-8') as stream:
            for row in csv.DictReader(stream):
                if row['member_code']:
                    members[row['crm_customer_id']] = row['member_code']
        chains: dict[str, list[dict[str, str]]] = {}
        with (root / 'membership_events.csv').open(newline='', encoding='utf-8') as stream:
            for row_number, row in enumerate(csv.DictReader(stream), 2):
                chains.setdefault(row['source_customer_ref'], []).append({**row, '_line': str(row_number)})
        for customer, events in chains.items():
            if customer not in members:
                reject('membership_events.csv', int(events[0]['_line']), 'nonmember_event', customer)
                continue
            if members[customer] != events[0]['member_code'] or not events[0]['member_code']:
                reject('membership_events.csv', int(events[0]['_line']), 'membership_code_mismatch', customer)
            ordered = sorted(events, key=lambda item: item['occurred_at'])
            previous = ''
            previous_expiry: datetime | None = None
            previous_tier = 0
            tiers = ['BRONZE', 'SILVER', 'GOLD', 'PLATINUM']
            for position, event in enumerate(ordered):
                line = int(event['_line'])
                if event['member_code'] != members[customer]:
                    reject('membership_events.csv', line, 'membership_code_mismatch', customer)
                if event['event_type'] == 'JOIN':
                    if position != 0 or event['previous_event_id']:
                        reject('membership_events.csv', line, 'membership_chain', customer)
                elif event['previous_event_id'] != previous:
                    reject('membership_events.csv', line, 'membership_chain', customer)
                if event['membership_tier'] not in tiers:
                    reject('membership_events.csv', line, 'invalid_enum', event['membership_tier'])
                elif previous and not 0 <= tiers.index(event['membership_tier']) - previous_tier <= 1:
                    reject('membership_events.csv', line, 'membership_tier', customer)
                try:
                    occurred = datetime.fromisoformat(event['occurred_at'])
                    period = datetime.fromisoformat(event['period_start'])
                    expiry = datetime.fromisoformat(event['expires_at'])
                except ValueError:
                    reject('membership_events.csv', line, 'invalid_timestamp', customer)
                    continue
                if occurred != period or expiry != period + timedelta(days=180):
                    reject('membership_events.csv', line, 'membership_period', customer)
                if previous_expiry and occurred != previous_expiry + timedelta(days=1):
                    reject('membership_events.csv', line, 'membership_chain', customer)
                previous, previous_expiry = event['event_id'], expiry
                if event['membership_tier'] in tiers:
                    previous_tier = tiers.index(event['membership_tier'])

    def _validate_visits(self, root: Path, db: sqlite3.Connection, reject: Any) -> None:
        transactions: dict[str, dict[str, str]] = {}
        with (root / 'transactions.csv').open(newline='', encoding='utf-8') as stream:
            for row in csv.DictReader(stream):
                transactions[row['source_transaction_id']] = row
        seen: set[str] = set()
        with (root / 'customer_visits.csv').open(newline='', encoding='utf-8') as stream:
            for row_number, row in enumerate(csv.DictReader(stream), 2):
                transaction = transactions.get(row['source_transaction_id'])
                if not transaction:
                    reject('customer_visits.csv', row_number, 'foreign_key', row['source_transaction_id'])
                    continue
                eligible = (
                    transaction['source_system'] == 'POS'
                    and transaction['status'] in {'COMPLETED', 'PARTIAL_REFUND'}
                    and bool(transaction['source_customer_ref'])
                )
                if not eligible:
                    reject('customer_visits.csv', row_number, 'visit_transaction', row['source_transaction_id'])
                elif any(row[field] != transaction[source] for field, source in (
                    ('source_customer_ref', 'source_customer_ref'),
                    ('branch_code', 'branch_code'),
                    ('visit_datetime', 'transaction_datetime'),
                )):
                    reject('customer_visits.csv', row_number, 'visit_transaction', row['source_transaction_id'])
                if row['source_transaction_id'] in seen:
                    reject('customer_visits.csv', row_number, 'visit_replay', row['source_transaction_id'])
                seen.add(row['source_transaction_id'])
        fingerprint_fields = (
            'source_customer_ref', 'source_system', 'branch_code', 'channel_code',
            'transaction_datetime', 'gross_amount', 'discount_amount', 'net_amount', 'status')
        visited_fingerprints = {
            tuple(transactions[key][field] for field in fingerprint_fields) for key in seen
        }
        for transaction_id, transaction in transactions.items():
            if (transaction['source_system'] == 'POS'
                    and transaction['status'] in {'COMPLETED', 'PARTIAL_REFUND'}
                    and transaction['source_customer_ref']
                    and tuple(transaction[field] for field in fingerprint_fields) not in visited_fingerprints):
                reject('customer_visits.csv', 0, 'missing_visit', transaction_id)

    def _validate_chronology(self, root: Path, reject: Any) -> None:
        customers: dict[str, date] = {}
        with (root / 'crm_customers.csv').open(newline='', encoding='utf-8') as stream:
            for row_number, row in enumerate(csv.DictReader(stream), 2):
                joined = date.fromisoformat(row['join_date'])
                customers[row['crm_customer_id']] = joined
                if datetime.fromisoformat(row['source_updated_at']).date() < joined:
                    reject('crm_customers.csv', row_number, 'update_before_join', row['crm_customer_id'])
        sources = (
            ('transactions.csv', 'source_customer_ref', 'transaction_datetime'),
            ('app_events.csv', 'source_customer_id', 'occurred_at'),
            ('service_cases.csv', 'source_customer_ref', 'opened_at'),
            ('consent_events.csv', 'source_customer_ref', 'captured_at'),
            ('membership_events.csv', 'source_customer_ref', 'occurred_at'),
            ('customer_visits.csv', 'source_customer_ref', 'visit_datetime'),
        )
        for file_name, reference, timestamp in sources:
            with (root / file_name).open(newline='', encoding='utf-8') as stream:
                for row_number, row in enumerate(csv.DictReader(stream), 2):
                    if not row[reference]:
                        continue
                    if datetime.fromisoformat(row[timestamp]).date() < customers[row[reference]]:
                        reject(file_name, row_number, 'before_join', row[reference])
        with (root / 'service_cases.csv').open(newline='', encoding='utf-8') as stream:
            for row_number, row in enumerate(csv.DictReader(stream), 2):
                if row['closed_at'] and datetime.fromisoformat(row['closed_at']) < datetime.fromisoformat(row['opened_at']):
                    reject('service_cases.csv', row_number, 'closed_before_opened', row['source_case_id'])
        with (root / 'consent_events.csv').open(newline='', encoding='utf-8') as stream:
            for row_number, row in enumerate(csv.DictReader(stream), 2):
                if datetime.fromisoformat(row['expires_at']) <= datetime.fromisoformat(row['captured_at']):
                    reject('consent_events.csv', row_number, 'invalid_expiry', row['source_consent_id'])
