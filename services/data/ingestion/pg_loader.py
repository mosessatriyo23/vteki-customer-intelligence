"""Atomic PostgreSQL ingestion of ten validated CSVs into staging and typed source.

Business IDs are immutable in the baseline: conflicting IDs in another batch fail
rather than silently overwrite an earlier published snapshot. Source schema and
foreign keys are owned by Alembic revision 0009.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Integer,
    SmallInteger,
    text,
)
from sqlalchemy.orm import Session

from api.models import IngestionBatch, IngestionRawRow

from .contracts import LOAD_ORDER, TABLES
from .source_tables import SOURCE_TABLES
from .validator import BatchValidator, sha256

BATCH_CHUNK_SIZE = 500


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
    """Serialize concurrent repeats of one batch until the enclosing transaction ends."""
    if session.get_bind().dialect.name == "postgresql":
        lock_key = int(batch_id[:16], 16)
        if lock_key >= (1 << 63):
            lock_key -= 1 << 64
        session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": lock_key},
        )


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
            return {"status": "REJECTED", "validation": report.to_dict()}

        manifest = json.loads(
            (root / "generation_manifest.json").read_text(encoding="utf-8")
        )
        batch_id = self.compute_batch_id(manifest)
        as_of_date = date.fromisoformat(manifest["as_of_date"])
        published_at = datetime.now(timezone.utc)
        created_at = datetime.now(timezone.utc)

        # One transaction for raw, typed tables, consistency verification & publication.
        # No external transaction or intermediate commit is permitted in this loader.
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
                        "Batch ID collision or previous incomplete batch; manual investigation required"
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
                    table = SOURCE_TABLES[file_name.removesuffix(".csv")]
                    raw_rows: list[IngestionRawRow] = []
                    typed_rows: list[dict[str, Any]] = []
                    actual_count = 0
                    with (root / file_name).open(
                        newline="", encoding="utf-8"
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
                                    row[column.name], column, file_name
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
                                session.execute(table.insert(), typed_rows)
                                raw_rows.clear()
                                typed_rows.clear()
                    if typed_rows:
                        session.add_all(raw_rows)
                        session.flush()
                        session.execute(table.insert(), typed_rows)
                    if actual_count != report.row_counts[file_name]:
                        raise ValueError(
                            f"Row count changed during ingestion for {file_name}"
                        )
                    if (
                        sha256(root / file_name)
                        != manifest["tables"][file_name]["sha256"]
                    ):
                        raise ValueError(
                            f"Checksum changed during ingestion for {file_name}"
                        )

                batch.status = "PUBLISHED"
                batch.published_at = published_at

        return {
            "status": "LOADED",
            "batch_id": batch_id,
            "row_counts": report.row_counts,
            "published_at": published_at.isoformat(),
        }
