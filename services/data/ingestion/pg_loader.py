"""PostgreSQL Ingestion Loader with Atomic Batch Transactions, Rollback, and Idempotency."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from api.models import IngestionBatch, IngestionRawRow

from .contracts import LOAD_ORDER, TABLES
from .validator import BatchValidator, sha256


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
                k: manifest["tables"][k]["sha256"]
                for k in sorted(manifest["tables"])
                if k in TABLES
            },
        }
        return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()

    def ingest(self, inbound_dir: str | Path) -> dict[str, Any]:
        root = Path(inbound_dir).resolve()

        # 1. Entire-batch validation before loading
        report = BatchValidator().validate(root)
        if not report.valid:
            return {"status": "REJECTED", "validation": report.to_dict()}

        manifest = json.loads(
            (root / "generation_manifest.json").read_text(encoding="utf-8")
        )
        batch_id = self.compute_batch_id(manifest)
        as_of_date = datetime.fromisoformat(manifest["as_of_date"]).date()

        # 2. Check Idempotency
        with self.session_factory() as session:
            stmt = select(IngestionBatch).where(IngestionBatch.batch_id == batch_id)
            existing = session.scalars(stmt).first()
            if existing and existing.status == "PUBLISHED":
                return {
                    "status": "ALREADY_LOADED",
                    "batch_id": batch_id,
                    "published_at": (
                        existing.published_at.isoformat()
                        if existing.published_at
                        else None
                    ),
                }

        # 3. Transactional All-or-Nothing Loading
        with self.session_factory() as session:
            try:
                # Stage batch record
                batch_obj = session.get(IngestionBatch, batch_id)
                if not batch_obj:
                    batch_obj = IngestionBatch(
                        batch_id=batch_id,
                        schema_version=manifest.get("schema_version", "2.0.0"),
                        seed=manifest.get("seed"),
                        as_of_date=as_of_date,
                        manifest_payload=manifest,
                        table_checksums=manifest.get("tables", {}),
                        status="STAGED",
                        row_counts=report.row_counts,
                        loaded_at=datetime.now(timezone.utc),
                    )
                    session.add(batch_obj)
                else:
                    batch_obj.status = "STAGED"
                    batch_obj.rejection_reasons = None
                    batch_obj.loaded_at = datetime.now(timezone.utc)
                session.flush()

                # Stream raw rows into stg.ingestion_raw_rows
                for table_name in LOAD_ORDER:
                    contract = TABLES[table_name]
                    file_path = root / table_name
                    with file_path.open(newline="", encoding="utf-8") as stream:
                        for row in csv.DictReader(stream):
                            pk_val = row[contract.pk]
                            raw_row = IngestionRawRow(
                                batch_id=batch_id,
                                table_name=table_name,
                                source_id=str(pk_val),
                                payload=row,
                                created_at=datetime.now(timezone.utc),
                            )
                            session.merge(raw_row)

                # Post-load hash verification (guard against file modification during ingestion)
                for table_name in LOAD_ORDER:
                    if (
                        sha256(root / table_name)
                        != manifest["tables"][table_name]["sha256"]
                    ):
                        raise ValueError(
                            f"Integrity violation: {table_name} altered during loading"
                        )

                # Mark batch published
                batch_obj.status = "PUBLISHED"
                batch_obj.published_at = datetime.now(timezone.utc)
                session.commit()

                return {
                    "status": "LOADED",
                    "batch_id": batch_id,
                    "row_counts": report.row_counts,
                    "published_at": batch_obj.published_at.isoformat(),
                }

            except Exception as exc:
                session.rollback()
                # Autonomous error logging
                with self.session_factory() as err_session:
                    failed_batch = err_session.get(IngestionBatch, batch_id)
                    if not failed_batch:
                        failed_batch = IngestionBatch(
                            batch_id=batch_id,
                            schema_version=manifest.get("schema_version", "2.0.0"),
                            seed=manifest.get("seed"),
                            as_of_date=as_of_date,
                            manifest_payload=manifest,
                            table_checksums=manifest.get("tables", {}),
                            status="REJECTED",
                            rejection_reasons={"error": str(exc)},
                            row_counts=report.row_counts,
                            loaded_at=datetime.now(timezone.utc),
                        )
                        err_session.add(failed_batch)
                    else:
                        failed_batch.status = "REJECTED"
                        failed_batch.rejection_reasons = {"error": str(exc)}
                    err_session.commit()
                raise
