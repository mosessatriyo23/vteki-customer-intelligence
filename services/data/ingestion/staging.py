"""SQLite development staging; NOT a PostgreSQL production loader."""

from __future__ import annotations

import csv
from contextlib import closing
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .contracts import LOAD_ORDER, TABLES
from .validator import BatchValidator


class IngestionStaging:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def ingest(self, inbound: str | Path) -> dict:
        root = Path(inbound).resolve()
        report = BatchValidator().validate(root)
        if not report.valid:
            return {"status": "REJECTED", "validation": report.to_dict()}
        manifest = json.loads((root / "generation_manifest.json").read_text(encoding="utf-8"))
        identity = {key: manifest[key] for key in ("schema_version", "seed", "as_of_date", "tables")}
        batch_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(str(self.db_path))) as db:
            db.execute("CREATE TABLE IF NOT EXISTS batches (id TEXT PRIMARY KEY, loaded_at TEXT NOT NULL, manifest TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS raw_rows (batch_id TEXT NOT NULL REFERENCES batches(id), table_name TEXT NOT NULL, source_id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(batch_id,table_name,source_id))")
            db.commit()
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            try:
                if db.execute("SELECT 1 FROM batches WHERE id=?", (batch_id,)).fetchone():
                    db.rollback()
                    return {"status": "ALREADY_LOADED", "batch_id": batch_id}
                db.execute("INSERT INTO batches VALUES (?,?,?)", (batch_id, datetime.now(timezone.utc).isoformat(), json.dumps(identity, sort_keys=True)))
                for name in LOAD_ORDER:
                    with (root / name).open(newline="", encoding="utf-8") as stream:
                        for row in csv.DictReader(stream):
                            db.execute("INSERT INTO raw_rows VALUES (?,?,?,?)", (batch_id, name, row[TABLES[name].pk], json.dumps(row, ensure_ascii=False)))
                # Detect modifications between validation and loading; rollback the whole batch.
                from .validator import sha256
                for name in LOAD_ORDER:
                    if sha256(root / name) != manifest["tables"][name]["sha256"]:
                        raise ValueError(f"File changed during ingestion: {name}")
            except Exception:
                db.rollback()
                raise
            db.commit()
        return {"status": "LOADED", "batch_id": batch_id, "row_counts": report.row_counts}
