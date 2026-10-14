import argparse
import csv
import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from generator.generate import run
from services.data.ingestion.staging import IngestionStaging
from services.data.ingestion.validator import BatchValidator


class IngestionTests(unittest.TestCase):
    def batch(self, root):
        inbound = root / "inbound"
        run(
            argparse.Namespace(
                seed=20260906,
                customers=20,
                as_of_date=date(2026, 9, 6),
                output_dir=inbound,
                ground_truth_dir=root / "truth",
            )
        )
        return inbound

    def test_valid_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbound = self.batch(root)
            store = IngestionStaging(root / "stage.sqlite")
            self.assertTrue(BatchValidator().validate(inbound).valid)
            self.assertEqual(store.ingest(inbound)["status"], "LOADED")
            self.assertEqual(store.ingest(inbound)["status"], "ALREADY_LOADED")

    def test_reject_corruption_and_unsupported_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbound = self.batch(Path(tmp))
            manifest_path = inbound / "generation_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["schema_version"] = "1.0.0"
            manifest_path.write_text(json.dumps(manifest))
            self.assertIn(
                "unsupported_schema", BatchValidator().validate(inbound).errors
            )
            manifest["schema_version"] = "2.0.0"
            manifest_path.write_text(json.dumps(manifest))
            path = inbound / "transactions.csv"
            path.write_bytes(path.read_bytes() + b"\n")
            self.assertIn(
                "checksum_mismatch", BatchValidator().validate(inbound).errors
            )

    def test_ground_truth_rejected_missing_ref_allowed_and_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbound = self.batch(root)
            with (inbound / "transactions.csv").open() as stream:
                self.assertTrue(
                    any(not r["source_customer_ref"] for r in csv.DictReader(stream))
                )
            self.assertTrue(BatchValidator().validate(inbound).valid)
            manifest_path = inbound / "generation_manifest.json"
            original = manifest_path.read_text()
            manifest = json.loads(original)
            manifest["tables"]["identity_mapping.csv"] = {}
            manifest_path.write_text(json.dumps(manifest))
            self.assertIn(
                "ground_truth_forbidden", BatchValidator().validate(inbound).errors
            )
            manifest_path.write_text(original)
            store = IngestionStaging(root / "stage.sqlite")
            # Force a post-load hash failure: transaction must roll back all rows.
            from services.data.ingestion import validator

            original_sha = validator.sha256
            calls = 0

            def changed(path):
                nonlocal calls
                calls += 1
                return original_sha(path) if calls <= 10 else "modified"

            with patch("services.data.ingestion.validator.sha256", side_effect=changed):
                with self.assertRaises(ValueError):
                    store.ingest(inbound)
            db = sqlite3.connect(root / "stage.sqlite")
            try:
                self.assertEqual(
                    db.execute("SELECT count(*) FROM batches").fetchone()[0], 0
                )
                self.assertEqual(
                    db.execute("SELECT count(*) FROM raw_rows").fetchone()[0], 0
                )
            finally:
                db.close()
