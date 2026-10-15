"""Platform contract tests for the James-scoped typed loader and persistent registry."""

import argparse
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.database import SQLITE_SCHEMA_TRANSLATE_MAP, Base
from api.models import (
    GoldenCustomer,
    IngestionBatch,
    IngestionRawRow,
    ProfileSnapshot,
    RegistryVersion,
    ReviewQueueItem,
    SourceIdentityMapping,
)
from generator.generate import run
from services.data.customer360.persistence import save_profile_snapshots
from services.data.identity.registry import PersistentIdentityRegistry
from services.data.ingestion.pg_loader import PostgresIngestionLoader
from services.data.ingestion.source_tables import SOURCE_TABLES


class JamesIngestionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        ).execution_options(schema_translate_map=SQLITE_SCHEMA_TRANSLATE_MAP)
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)

    def inbound(self, tmp: str) -> Path:
        dest = Path(tmp) / "inbound"
        run(
            argparse.Namespace(
                seed=20260906,
                customers=20,
                as_of_date=date(2026, 9, 6),
                output_dir=dest,
                ground_truth_dir=Path(tmp) / "evaluation",
            )
        )
        return dest

    def test_typed_source_publish_and_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbound = self.inbound(tmp)
            loader = PostgresIngestionLoader(self.SessionLocal)
            result = loader.ingest(inbound)
            self.assertEqual(result["status"], "LOADED")
            with self.SessionLocal() as session:
                for csv_name, count in result["row_counts"].items():
                    table = SOURCE_TABLES[csv_name.removesuffix(".csv")]
                    actual = session.scalar(select(func.count()).select_from(table))
                    self.assertEqual(actual, count, csv_name)
                transaction = session.execute(
                    select(SOURCE_TABLES["transactions"].c.gross_amount).limit(1)
                ).scalar_one()
                self.assertIsInstance(transaction, int)
            self.assertEqual(loader.ingest(inbound)["status"], "ALREADY_LOADED")

    def test_rollback_all_tables_on_typed_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbound = self.inbound(tmp)
            table = SOURCE_TABLES["branches"]
            from csv import DictReader

            with (inbound / "branches.csv").open(newline="", encoding="utf-8") as f:
                first = next(DictReader(f))
            with self.SessionLocal.begin() as session:
                session.execute(
                    table.insert(),
                    [
                        {
                            **first,
                            "active_flag": True,
                            "source_batch_id": "preexisting",
                            "created_at": datetime.now(timezone.utc),
                        }
                    ],
                )
            with self.assertRaises(Exception):
                PostgresIngestionLoader(self.SessionLocal).ingest(inbound)
            with self.SessionLocal() as session:
                self.assertEqual(
                    session.scalar(select(func.count()).select_from(IngestionBatch)), 0
                )
                self.assertEqual(
                    session.scalar(select(func.count()).select_from(IngestionRawRow)), 0
                )
                self.assertEqual(
                    session.scalar(
                        select(func.count()).select_from(SOURCE_TABLES["crm_customers"])
                    ),
                    0,
                )


class JamesGovernanceTests(unittest.TestCase):
    def setUp(self):
        JamesIngestionTests.setUp(self)

    def test_review_merge_moves_entire_published_cluster(self):
        with self.SessionLocal() as session:
            session.add(RegistryVersion(version_tag="v1", algorithm="test"))
            session.add_all(
                [
                    GoldenCustomer(
                        golden_customer_id="g-left",
                        first_source_batch_id="batch",
                        anchor_source_id="left",
                    ),
                    GoldenCustomer(
                        golden_customer_id="g-right",
                        first_source_batch_id="batch",
                        anchor_source_id="right",
                    ),
                ]
            )
            session.flush()
            session.add_all(
                [
                    SourceIdentityMapping(
                        source_customer_id="left",
                        golden_customer_id="g-left",
                        registry_version="v1",
                        source_batch_id="batch",
                        assignment_type="AUTO",
                    ),
                    SourceIdentityMapping(
                        source_customer_id="right",
                        golden_customer_id="g-right",
                        registry_version="v1",
                        source_batch_id="batch",
                        assignment_type="AUTO",
                    ),
                    SourceIdentityMapping(
                        source_customer_id="right-2",
                        golden_customer_id="g-right",
                        registry_version="v1",
                        source_batch_id="batch",
                        assignment_type="AUTO",
                    ),
                ]
            )
            session.add(
                ReviewQueueItem(
                    source_batch_id="batch",
                    registry_version="v1",
                    left_source_id="left",
                    right_source_id="right",
                    left_golden_id="g-left",
                    right_golden_id="g-right",
                    heuristic_score=0.5,
                    reason="manual-test",
                    status="PENDING",
                )
            )
            session.commit()
            queue_id = session.scalar(select(ReviewQueueItem.id))
            registry = PersistentIdentityRegistry(session)
            registry.decide_review_queue_item(
                queue_id, 1, "APPROVE_MERGE", "Checked", "test-correlation"
            )
            assigned = session.scalars(select(SourceIdentityMapping)).all()
            self.assertEqual({x.golden_customer_id for x in assigned}, {"g-left"})
            self.assertEqual(
                session.get(GoldenCustomer, "g-right").merged_into_golden_id, "g-left"
            )

    def test_c360_rule_versions_and_integer_idr(self):
        sample = {
            "golden_customer_id": "g1",
            "cutoff_at": "2026-09-06T00:00:00+07:00",
            "identity_status": "PROVISIONAL",
            "source_identity_count": 1,
            "first_join_date": "2026-02-01",
            "transaction_count": 1,
            "retained_revenue": 10000,
            "last_transaction_at": None,
            "visit_count": 1,
            "renewal_count": 0,
        }
        with self.SessionLocal() as session:
            save_profile_snapshots([sample], "batch", "v1", session, rule_version="r1")
            save_profile_snapshots([sample], "batch", "v1", session, rule_version="r2")
            self.assertEqual(
                session.scalar(select(func.count()).select_from(ProfileSnapshot)), 2
            )
            with self.assertRaises(ValueError):
                save_profile_snapshots(
                    [dict(sample, retained_revenue=10000.5)],
                    "batch",
                    "v1",
                    session,
                    rule_version="r3",
                )


if __name__ == "__main__":
    unittest.main()
