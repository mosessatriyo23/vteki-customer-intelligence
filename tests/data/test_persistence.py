"""Tests for PostgreSQL persistence layer: Ingestion loader, Identity registry, and Snapshots."""

import argparse
import json
import tempfile
import unittest
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.database import SQLITE_SCHEMA_TRANSLATE_MAP, Base
from api.models import (
    GoldenCustomer,
    IngestionBatch,
    IngestionRawRow,
    ProfileSnapshot,
    ReviewAuditLog,
    ReviewQueueItem,
    RFMLifecycleSnapshot,
    Role,
    SourceIdentityMapping,
    User,
)
from generator.generate import run
from services.data.customer360.persistence import save_profile_snapshots
from services.data.identity.registry import PersistentIdentityRegistry
from services.data.identity.resolver import resolve_csv
from services.data.ingestion.pg_loader import PostgresIngestionLoader
from services.data.segmentation.persistence import save_segmentation_snapshots


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        ).execution_options(schema_translate_map=SQLITE_SCHEMA_TRANSLATE_MAP)
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)

        # Seed test user for audit logs
        with self.SessionLocal() as session:
            admin_role = Role(name="admin")
            session.add(admin_role)
            session.flush()
            self.test_user = User(
                email="reviewer@example.com",
                password_hash="fakehash",
                roles=[admin_role],
            )
            session.add(self.test_user)
            session.commit()
            self.user_id = self.test_user.id

    def generate_batch(self, root: Path, customers: int = 20) -> Path:
        inbound = root / "inbound"
        run(
            argparse.Namespace(
                seed=20260906,
                customers=customers,
                as_of_date=date(2026, 9, 6),
                output_dir=inbound,
                ground_truth_dir=root / "truth",
            )
        )
        return inbound

    def test_pg_loader_valid_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbound = self.generate_batch(root)

            loader = PostgresIngestionLoader(self.SessionLocal)
            result = loader.ingest(inbound)
            self.assertEqual(result["status"], "LOADED")
            batch_id = result["batch_id"]

            # Verify rows in DB
            with self.SessionLocal() as session:
                batch = session.get(IngestionBatch, batch_id)
                self.assertIsNotNone(batch)
                self.assertEqual(batch.status, "PUBLISHED")

                raw_rows_count = session.scalars(
                    select(IngestionRawRow).where(IngestionRawRow.batch_id == batch_id)
                ).all()
                self.assertGreater(len(raw_rows_count), 0)

            # Replay should be idempotent
            second_result = loader.ingest(inbound)
            self.assertEqual(second_result["status"], "ALREADY_LOADED")
            self.assertEqual(second_result["batch_id"], batch_id)

    def test_pg_loader_rejection_no_partial_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbound = self.generate_batch(root)

            # Corrupt manifest to fail validation
            manifest_path = inbound / "generation_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["schema_version"] = "1.0.0"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            loader = PostgresIngestionLoader(self.SessionLocal)
            result = loader.ingest(inbound)
            self.assertEqual(result["status"], "REJECTED")

            # Check no batch marked published
            with self.SessionLocal() as session:
                batches = session.scalars(
                    select(IngestionBatch).where(IngestionBatch.status == "PUBLISHED")
                ).all()
                self.assertEqual(len(batches), 0)

    def test_persistent_identity_registry_preservation_and_anti_silent_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbound = self.generate_batch(root)
            resolution = resolve_csv(inbound / "crm_customers.csv")

            with self.SessionLocal() as session:
                registry = PersistentIdentityRegistry(session)
                applied = registry.apply_resolution_batch(
                    batch_id="batch_001",
                    version_tag="identity-v1.1",
                    resolution_result=resolution,
                )
                self.assertEqual(applied["status"], "APPLIED")

                # Verify golden customers created
                goldens = session.scalars(select(GoldenCustomer)).all()
                self.assertGreater(len(goldens), 0)

                mappings = session.scalars(select(SourceIdentityMapping)).all()
                self.assertEqual(len(mappings), len(resolution["mapping"]))

                # Save published mapping for second test run
                prior = registry.get_existing_mapping()
                sample_sources = list(prior.keys())
                self.assertGreater(len(sample_sources), 1)

            # Test Silent Merge Violation: force two distinct published Golden IDs to merge
            source_a, source_b = sample_sources[0], sample_sources[1]
            golden_a, golden_b = prior[source_a], prior[source_b]
            if golden_a != golden_b:
                corrupted_resolution = {
                    "mapping": [
                        {
                            "source_customer_id": s,
                            "golden_customer_id": (
                                golden_a if s in (source_a, source_b) else g
                            ),
                        }
                        for s, g in prior.items()
                    ],
                    "decisions": [],
                }
                with self.SessionLocal() as session:
                    reg = PersistentIdentityRegistry(session)
                    with self.assertRaises(ValueError) as ctx:
                        reg.apply_resolution_batch(
                            batch_id="batch_002",
                            version_tag="identity-v1.1",
                            resolution_result=corrupted_resolution,
                        )
                    self.assertIn("Silent merge violation", str(ctx.exception))

            # Test Silent Split Violation: split one cluster into two
            cluster_with_multiple = None
            by_golden = {}
            for s, g in prior.items():
                by_golden.setdefault(g, []).append(s)
                if len(by_golden[g]) > 1:
                    cluster_with_multiple = g
                    break

            if cluster_with_multiple:
                sources_in_cluster = by_golden[cluster_with_multiple]
                split_res = {
                    "mapping": [
                        {
                            "source_customer_id": s,
                            "golden_customer_id": (
                                str(uuid.uuid4()) if s == sources_in_cluster[0] else g
                            ),
                        }
                        for s, g in prior.items()
                    ],
                    "decisions": [],
                }
                with self.SessionLocal() as session:
                    reg = PersistentIdentityRegistry(session)
                    with self.assertRaises(ValueError) as ctx:
                        reg.apply_resolution_batch(
                            batch_id="batch_003",
                            version_tag="identity-v1.1",
                            resolution_result=split_res,
                        )
                    self.assertIn("Silent split violation", str(ctx.exception))

    def test_identity_review_workflow_and_audit_trail(self):
        with self.SessionLocal() as session:
            # Seed a review queue item
            g1 = GoldenCustomer(
                golden_customer_id="g-101",
                first_source_batch_id="b1",
                anchor_source_id="s1",
                status="REVIEW_REQUIRED",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            g2 = GoldenCustomer(
                golden_customer_id="g-102",
                first_source_batch_id="b1",
                anchor_source_id="s2",
                status="REVIEW_REQUIRED",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            m1 = SourceIdentityMapping(
                source_customer_id="s1",
                golden_customer_id="g-101",
                registry_version="v1",
                source_batch_id="b1",
                assignment_type="PROVISIONAL",
                assigned_at=datetime.now(timezone.utc),
            )
            m2 = SourceIdentityMapping(
                source_customer_id="s2",
                golden_customer_id="g-102",
                registry_version="v1",
                source_batch_id="b1",
                assignment_type="PROVISIONAL",
                assigned_at=datetime.now(timezone.utc),
            )
            q_item = ReviewQueueItem(
                source_batch_id="b1",
                registry_version="v1",
                left_source_id="s1",
                right_source_id="s2",
                left_golden_id="g-101",
                right_golden_id="g-102",
                heuristic_score=0.60,
                reason="phone_match:insufficient_corroboration",
                status="PENDING",
                created_at=datetime.now(timezone.utc),
            )
            session.add_all([g1, g2, m1, m2, q_item])
            session.commit()
            queue_id = q_item.id

            reg = PersistentIdentityRegistry(session)
            result = reg.decide_review_queue_item(
                queue_id=queue_id,
                actor_id=self.user_id,
                action="APPROVE_MERGE",
                rationale="Reviewed customer IDs manually - verified same individual",
                correlation_id="corr-test-12345",
            )
            self.assertEqual(result["status"], "APPROVED_MERGE")

            # Check audit trail created
            audit = session.scalars(
                select(ReviewAuditLog).where(ReviewAuditLog.review_queue_id == queue_id)
            ).first()
            self.assertIsNotNone(audit)
            self.assertEqual(audit.action, "APPROVE_MERGE")
            self.assertEqual(audit.correlation_id, "corr-test-12345")
            self.assertEqual(audit.actor_id, self.user_id)

            # Check mapping updated
            m2_updated = session.get(SourceIdentityMapping, "s2")
            self.assertEqual(m2_updated.golden_customer_id, "g-101")
            self.assertEqual(m2_updated.assignment_type, "MANUAL_OVERRIDE")

    def test_customer360_and_segmentation_snapshot_persistence(self):
        cutoff = datetime(2026, 9, 6, 23, 59, 59, tzinfo=timezone.utc)
        mock_c360 = [
            {
                "golden_customer_id": "gold-1",
                "cutoff_at": cutoff.isoformat(),
                "identity_status": "PROVISIONAL",
                "source_identity_count": 1,
                "first_join_date": "2026-01-01",
                "transaction_count": 5,
                "retained_revenue": 1500000,
                "last_transaction_at": "2026-09-01T12:00:00+07:00",
                "visit_count": 2,
                "renewal_count": 0,
            }
        ]

        mock_seg = [
            {
                "golden_customer_id": "gold-1",
                "cutoff_at": cutoff.isoformat(),
                "identity_status": "PROVISIONAL",
                "recency_days": 5,
                "frequency": 5,
                "monetary": 1500000,
                "rfm_window_days": 365,
                "r_score": 5,
                "f_score": 3,
                "m_score": 3,
                "rfm_code": "533",
                "tenure_days": 248,
                "transactions_60d": 3,
                "transactions_90d": 5,
                "revenue_90d": 1500000,
                "lifecycle": "LOYAL",
                "rule_version": "lifecycle-proposed-1.0",
            }
        ]

        with self.SessionLocal() as session:
            # Seed golden customer
            g = GoldenCustomer(
                golden_customer_id="gold-1",
                first_source_batch_id="b1",
                anchor_source_id="s1",
                status="PROVISIONAL",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(g)
            session.commit()

            c360_saved = save_profile_snapshots(
                profiles=mock_c360,
                batch_id="batch_01",
                registry_version="v1.1",
                session=session,
            )
            self.assertEqual(c360_saved, 1)

            seg_saved = save_segmentation_snapshots(
                segments=mock_seg,
                batch_id="batch_01",
                registry_version="v1.1",
                session=session,
            )
            self.assertEqual(seg_saved, 1)

            # Query persisted snapshots
            c360_snap = session.scalars(select(ProfileSnapshot)).first()
            self.assertIsNotNone(c360_snap)
            self.assertEqual(c360_snap.retained_revenue, 1500000)

            seg_snap = session.scalars(select(RFMLifecycleSnapshot)).first()
            self.assertIsNotNone(seg_snap)
            self.assertEqual(seg_snap.rfm_code, "533")
            self.assertEqual(seg_snap.lifecycle, "LOYAL")


if __name__ == "__main__":
    unittest.main()
