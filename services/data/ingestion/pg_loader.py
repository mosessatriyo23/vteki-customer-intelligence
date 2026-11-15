"""Atomic PostgreSQL ingestion of ten validated CSVs into staging and typed source.

Business IDs are immutable in the baseline. Branches are shared reference
records: an existing branch is reused only when its business attributes match.
Catalogue items are versioned by source_batch_id.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Integer,
    SmallInteger,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from api.models import IngestionBatch, IngestionRawRow

from .contracts import LOAD_ORDER, TABLES
from .source_tables import SOURCE_TABLES
from .validator import BatchValidator, sha256

BATCH_CHUNK_SIZE = 500

BRANCH_BUSINESS_FIELDS = (
    "branch_name",
    "city",
    "region",
    "active_flag",
)


def _typed_value(value: str, column: Any, table_name: str) -> Any:
    """Converts validated CSV cells without using float for IDR amounts."""
    if value == "" and column.nullable:
        return None

    datatype = column.type

    if isinstance(datatype, Boolean):
        if value not in {"True", "False"}:
            raise ValueError(f"Invalid boolean {table_name}.{column.name}")
        return value == "True"

    if isinstance(datatype, (SmallInteger, Integer, BigInteger)):
        if (
            not value
            or value.strip() != value
            or any(char not in "-0123456789" for char in value)
        ):
            raise ValueError(f"Invalid integer {table_name}.{column.name}")
        return int(value)

    if isinstance(datatype, DateTime):
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() != timedelta(hours=7):
            raise ValueError(f"Expected +07:00 timezone for {table_name}.{column.name}")
        return parsed

    if isinstance(datatype, Date):
        return date.fromisoformat(value)

    if isinstance(datatype, JSON):
        return json.loads(value)

    return value


def _batch_lock(session: Session, batch_id: str) -> None:
    """Serialize concurrent repeats of one batch until the transaction ends."""
    if session.get_bind().dialect.name == "postgresql":
        lock_key = int(batch_id[:16], 16)
        if lock_key >= (1 << 63):
            lock_key -= 1 << 64

        session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": lock_key},
        )


def _validate_existing_branches(
    session: Session,
    table: sa.Table,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Reuse identical branches and reject conflicting branch definitions."""
    if not rows:
        return []

    branch_codes = list({row["branch_code"] for row in rows})

    existing_rows = session.execute(
        select(
            table.c.branch_code,
            table.c.branch_name,
            table.c.city,
            table.c.region,
            table.c.active_flag,
        ).where(table.c.branch_code.in_(branch_codes))
    ).mappings()

    existing_by_code = {row["branch_code"]: dict(row) for row in existing_rows}

    new_rows: list[dict[str, Any]] = []

    for incoming in rows:
        branch_code = incoming["branch_code"]
        existing = existing_by_code.get(branch_code)

        if existing is None:
            new_rows.append(incoming)
            continue

        differences = [
            field
            for field in BRANCH_BUSINESS_FIELDS
            if existing[field] != incoming[field]
        ]

        if differences:
            raise ValueError(
                "Conflicting branch definition for "
                f"{branch_code}; mismatched fields: {', '.join(differences)}"
            )

    return new_rows


def _insert_branch_rows(
    session: Session,
    table: sa.Table,
    rows: list[dict[str, Any]],
) -> None:
    """Insert shared branches without overwriting existing reference records."""
    if not rows:
        return

    dialect = session.get_bind().dialect.name

    if dialect == "postgresql":
        statement = (
            pg_insert(table)
            .values(rows)
            .on_conflict_do_nothing(index_elements=[table.c.branch_code])
        )
        session.execute(statement)

    elif dialect == "sqlite":
        statement = (
            sqlite_insert(table)
            .values(rows)
            .on_conflict_do_nothing(index_elements=[table.c.branch_code])
        )
        session.execute(statement)

    else:
        new_rows = _validate_existing_branches(session, table, rows)
        if new_rows:
            session.execute(table.insert(), new_rows)
        return

    # Verify after insertion as well. This catches an existing branch whose
    # code matched but whose business attributes differ from the incoming row.
    _validate_existing_branches(session, table, rows)


def _insert_typed_rows(
    session: Session,
    table: sa.Table,
    rows: list[dict[str, Any]],
    table_name: str,
) -> None:
    """Insert typed records, applying shared-reference rules where required."""
    if not rows:
        return

    if table_name == "branches":
        _insert_branch_rows(session, table, rows)
        return

    session.execute(table.insert(), rows)


class PostgresIngestionLoader:
    def __init__(self, session_factory: Any) -> None:
        self.session_factory = session_factory

    @staticmethod
    def compute_batch_id(manifest: dict[str, Any]) -> str:
        identity = {
            "schema_version": manifest.get("schema_version", "2.0.0"),
            "seed": manifest.get("seed"),
            "as_of_date": manifest["as_of_date"],
            "tables": {
                key: manifest["tables"][key]["sha256"]
                for key in sorted(manifest["tables"])
                if key in TABLES
            },
        }

        return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()

    def ingest(self, inbound_dir: str | Path) -> dict[str, Any]:
        root = Path(inbound_dir).resolve()
        report = BatchValidator().validate(root)

        if not report.valid:
            return {
                "status": "REJECTED",
                "validation": report.to_dict(),
            }

        manifest = json.loads(
            (root / "generation_manifest.json").read_text(encoding="utf-8")
        )

        batch_id = self.compute_batch_id(manifest)
        as_of_date = date.fromisoformat(manifest["as_of_date"])
        published_at = datetime.now(timezone.utc)
        created_at = datetime.now(timezone.utc)

        # One transaction for raw rows, typed rows, consistency checks,
        # transaction history and publication. No intermediate commit.
        with self.session_factory() as session:
            with session.begin():
                _batch_lock(session, batch_id)

                existing = session.get(IngestionBatch, batch_id)

                if existing is not None:
                    if (
                        existing.status == "PUBLISHED"
                        and existing.table_checksums == manifest.get("tables", {})
                    ):
                        return {
                            "status": "ALREADY_LOADED",
                            "batch_id": batch_id,
                            "published_at": (
                                existing.published_at.isoformat()
                                if existing.published_at
                                else None
                            ),
                        }

                    raise ValueError(
                        "Batch ID collision or previous incomplete batch; "
                        "manual investigation required"
                    )

                batch = IngestionBatch(
                    batch_id=batch_id,
                    schema_version=manifest.get("schema_version", "2.0.0"),
                    seed=manifest.get("seed"),
                    as_of_date=as_of_date,
                    manifest_payload=manifest,
                    table_checksums=manifest.get("tables", {}),
                    status="STAGED",
                    row_counts=report.row_counts,
                    loaded_at=created_at,
                )

                session.add(batch)
                session.flush()

                for file_name in LOAD_ORDER:
                    contract = TABLES[file_name]
                    table_name = file_name.removesuffix(".csv")
                    table = SOURCE_TABLES[table_name]

                    raw_rows: list[IngestionRawRow] = []
                    typed_rows: list[dict[str, Any]] = []
                    actual_count = 0

                    with (root / file_name).open(
                        newline="",
                        encoding="utf-8",
                    ) as stream:
                        for row in csv.DictReader(stream):
                            if set(row) != set(contract.fields):
                                raise ValueError(f"Unexpected fields in {file_name}")

                            source_id = str(row[contract.pk])

                            raw_rows.append(
                                IngestionRawRow(
                                    batch_id=batch_id,
                                    table_name=file_name,
                                    source_id=source_id,
                                    payload=row,
                                    created_at=created_at,
                                )
                            )

                            typed = {
                                column.name: _typed_value(
                                    row[column.name],
                                    column,
                                    file_name,
                                )
                                for column in table.columns
                                if column.name in row
                            }

                            typed["source_batch_id"] = batch_id
                            typed["created_at"] = created_at

                            typed_rows.append(typed)
                            actual_count += 1

                            if len(typed_rows) >= BATCH_CHUNK_SIZE:
                                session.add_all(raw_rows)
                                session.flush()

                                _insert_typed_rows(
                                    session,
                                    table,
                                    typed_rows,
                                    table_name,
                                )

                                raw_rows.clear()
                                typed_rows.clear()

                    if typed_rows:
                        session.add_all(raw_rows)
                        session.flush()

                        _insert_typed_rows(
                            session,
                            table,
                            typed_rows,
                            table_name,
                        )

                    if actual_count != report.row_counts[file_name]:
                        raise ValueError(
                            "Row count changed during ingestion for " f"{file_name}"
                        )

                    if (
                        sha256(root / file_name)
                        != manifest["tables"][file_name]["sha256"]
                    ):
                        raise ValueError(
                            f"Checksum changed during ingestion for {file_name}"
                        )

                if session.get_bind().dialect.name == "postgresql":
                    # Publish an immutable initial event for every transaction.
                    session.execute(
                        text(
                            """
                            INSERT INTO source.transaction_event_history (
                                source_transaction_id,
                                event_type,
                                occurred_at,
                                available_at,
                                source_batch_id,
                                idempotency_key,
                                payload
                            )
                            SELECT
                                t.source_transaction_id,
                                'TRANSACTION_RECORDED',
                                t.transaction_datetime,
                                t.created_at,
                                t.source_batch_id,
                                t.source_batch_id || ':' ||
                                    t.source_transaction_id ||
                                    chr(58) || 'TRANSACTION_RECORDED',
                                json_build_object(
                                    'source_system', t.source_system,
                                    'status', t.status,
                                    'gross_amount', t.gross_amount,
                                    'discount_amount', t.discount_amount,
                                    'net_amount', t.net_amount,
                                    'refund_amount', t.refund_amount,
                                    'actual_revenue', t.actual_revenue
                                )
                            FROM source.transactions AS t
                            WHERE t.source_batch_id = :batch_id
                            ON CONFLICT (idempotency_key) DO NOTHING
                            """
                        ),
                        {"batch_id": batch_id},
                    )

                batch.status = "PUBLISHED"
                batch.published_at = published_at

        return {
            "status": "LOADED",
            "batch_id": batch_id,
            "row_counts": report.row_counts,
            "published_at": published_at.isoformat(),
        }
