"""Tests for PostgreSQL persistence layer: Ingestion loader, Identity registry, and Snapshots."""

import argparse
import json
import tempfile
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.database import SQLITE_SCHEMA_TRANSLATE_MAP, Base
from api.models import (
    GoldenCustomer,
    IdentityHistoryCoverage,
    IdentityMappingHistory,
    IdentityReviewDecisionHistory,
    IngestionBatch,
    IngestionRawRow,
    ProfileSnapshot,
    RegistryVersion,
    ReviewAuditLog,
    ReviewQueueItem,
    RFMLifecycleSnapshot,
    Role,
    SourceIdentityMapping,
    User,
)
from generator.generate import run
from services.data.customer360.persistence import save_profile_snapshots
from services.data.identity.registry import (
    IdentityHistoryCoverageError,
    PersistentIdentityRegistry,
)
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

    def test_registry_sequential_replay_preserves_decisions(self):
        from copy import deepcopy

        from api.models import MatchDecision

        result = {
            "mapping": [
                {"source_customer_id": "a", "golden_customer_id": "golden-a"},
                {"source_customer_id": "b", "golden_customer_id": "golden-b"},
            ],
            "decisions": [
                {
                    "left_source_id": "a",
                    "right_source_id": "b",
                    "decision": "REVIEW",
                    "heuristic_score": 0.6,
                    "reason": "single identifier",
                }
            ],
        }
        with self.SessionLocal() as session:
            registry = PersistentIdentityRegistry(session)
            registry.apply_resolution_batch("replay-batch", "replay-v1", result)
            first_mapping = registry.get_existing_mapping()
            original = session.scalars(select(MatchDecision)).one()
            original_id, original_time = original.id, original.created_at
            registry.apply_resolution_batch("replay-batch", "replay-v1", result)
            decisions = session.scalars(select(MatchDecision)).all()
            self.assertEqual(len(decisions), 1)
            self.assertEqual(
                (decisions[0].id, decisions[0].created_at), (original_id, original_time)
            )
            self.assertEqual(registry.get_existing_mapping(), first_mapping)
            history = session.scalars(
                select(IdentityMappingHistory).where(
                    IdentityMappingHistory.source_batch_id == "replay-batch"
                )
            ).all()
            self.assertEqual(len(history), 2)
            self.assertEqual({row.source_customer_id for row in history}, {"a", "b"})
            self.assertEqual(len(session.scalars(select(ReviewQueueItem)).all()), 1)
            changed = deepcopy(result)
            changed["decisions"][0]["reason"] = "changed evidence"
            with self.assertRaisesRegex(ValueError, "differs from replay"):
                registry.apply_resolution_batch("replay-batch", "replay-v1", changed)
            session.rollback()
            self.assertEqual(
                session.scalars(select(MatchDecision)).one().reason, "single identifier"
            )

    def test_identity_mapping_as_of_preserves_history(self):
        initial_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        merge_time = datetime(2026, 2, 1, tzinfo=timezone.utc)

        with self.SessionLocal() as session:
            session.add(
                RegistryVersion(
                    version_tag="asof-v1",
                    algorithm="test",
                    parameters={},
                    status="ACTIVE",
                    description="Identity as-of test",
                    created_at=initial_time,
                )
            )
            session.add_all(
                [
                    GoldenCustomer(
                        golden_customer_id="asof-old",
                        first_source_batch_id="asof-batch-1",
                        anchor_source_id="source-asof",
                        status="APPROVED",
                        created_at=initial_time,
                        updated_at=initial_time,
                    ),
                    GoldenCustomer(
                        golden_customer_id="asof-new",
                        first_source_batch_id="asof-batch-2",
                        anchor_source_id="source-asof",
                        status="APPROVED",
                        created_at=merge_time,
                        updated_at=merge_time,
                    ),
                ]
            )
            session.flush()

            session.add_all(
                [
                    IdentityMappingHistory(
                        source_customer_id="source-asof",
                        golden_customer_id="asof-old",
                        registry_version="asof-v1",
                        source_batch_id="asof-batch-1",
                        assignment_type="PROVISIONAL",
                        event_type="BASELINE",
                        effective_at=initial_time,
                        recorded_at=initial_time,
                    ),
                    IdentityMappingHistory(
                        source_customer_id="source-asof",
                        golden_customer_id="asof-new",
                        registry_version="asof-v1",
                        source_batch_id="asof-batch-2",
                        assignment_type="MANUAL_OVERRIDE",
                        event_type="MANUAL_MERGE",
                        effective_at=merge_time,
                        recorded_at=merge_time,
                    ),
                ]
            )
            session.commit()

            registry = PersistentIdentityRegistry(session)

            before_merge = registry.get_mapping_as_of(
                effective_at=merge_time - timedelta(seconds=1),
                recorded_at=merge_time + timedelta(days=1),
            )
            self.assertEqual(before_merge, {"source-asof": "asof-old"})

            after_merge = registry.get_mapping_as_of(
                effective_at=merge_time + timedelta(seconds=1),
                recorded_at=merge_time + timedelta(days=1),
            )
            self.assertEqual(after_merge, {"source-asof": "asof-new"})

            old_knowledge = registry.get_mapping_as_of(
                effective_at=merge_time + timedelta(days=1),
                recorded_at=merge_time - timedelta(seconds=1),
            )
            self.assertEqual(old_knowledge, {"source-asof": "asof-old"})

    def test_migration_baseline_does_not_claim_pre_migration_identity_history(self):
        baseline_time = datetime(2026, 3, 1, tzinfo=timezone.utc)
        prior_assignment_time = datetime(2025, 12, 1, tzinfo=timezone.utc)

        with self.SessionLocal() as session:
            session.add(
                RegistryVersion(
                    version_tag="migration-baseline-v1",
                    algorithm="test",
                    parameters={},
                    status="ACTIVE",
                    description="Migration baseline boundary test",
                    created_at=baseline_time,
                )
            )
            session.add(
                GoldenCustomer(
                    golden_customer_id="migration-baseline-golden",
                    first_source_batch_id="migration-baseline-batch",
                    anchor_source_id="migration-baseline-source",
                    status="PROVISIONAL",
                    created_at=prior_assignment_time,
                    updated_at=baseline_time,
                )
            )
            session.flush()
            session.add(
                IdentityMappingHistory(
                    source_customer_id="migration-baseline-source",
                    golden_customer_id="migration-baseline-golden",
                    registry_version="migration-baseline-v1",
                    source_batch_id="migration-baseline-batch",
                    assignment_type="PROVISIONAL",
                    event_type="BASELINE",
                    effective_at=prior_assignment_time,
                    recorded_at=baseline_time,
                    change_reason=("Initial baseline captured during migration 0013"),
                )
            )
            session.commit()

            registry = PersistentIdentityRegistry(session)
            before_coverage = registry.get_mapping_as_of_result(
                effective_at=baseline_time - timedelta(seconds=1),
                recorded_at=baseline_time + timedelta(days=1),
            )
            assert before_coverage.status == "BLOCKED"
            assert before_coverage.mapping == {}

            with self.assertRaisesRegex(IdentityHistoryCoverageError, "BLOCKED"):
                registry.get_mapping_as_of(
                    effective_at=baseline_time - timedelta(seconds=1),
                    recorded_at=baseline_time + timedelta(days=1),
                )

            at_coverage = registry.get_mapping_as_of_result(
                effective_at=baseline_time + timedelta(seconds=1),
                recorded_at=baseline_time + timedelta(days=1),
            )
            assert at_coverage.status == "AVAILABLE"
            assert at_coverage.mapping == {
                "migration-baseline-source": "migration-baseline-golden"
            }

    def test_identity_coverage_marker_blocks_even_when_baseline_table_is_empty(self):
        coverage_time = datetime(2026, 11, 1, tzinfo=timezone.utc)
        with self.SessionLocal() as session:
            session.add(
                IdentityHistoryCoverage(
                    singleton_id=1,
                    coverage_started_at=coverage_time,
                    recorded_at=coverage_time,
                )
            )
            session.commit()
            result = PersistentIdentityRegistry(session).get_mapping_as_of_result(
                effective_at=coverage_time - timedelta(seconds=1),
                recorded_at=coverage_time + timedelta(minutes=1),
            )
            self.assertEqual(result.status, "BLOCKED")
            self.assertEqual(result.mapping, {})
            self.assertEqual(result.coverage_started_at, coverage_time)
            unknown_to_old_knowledge = PersistentIdentityRegistry(
                session
            ).get_mapping_as_of_result(
                effective_at=coverage_time + timedelta(seconds=1),
                recorded_at=coverage_time - timedelta(seconds=1),
            )
            self.assertEqual(unknown_to_old_knowledge.status, "UNKNOWN")
            self.assertIsNone(unknown_to_old_knowledge.coverage_started_at)

    def test_identity_split_as_of_preserves_prior_mapping_without_forcing_unknowns(
        self,
    ):
        baseline_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        split_time = datetime(2026, 2, 1, tzinfo=timezone.utc)

        with self.SessionLocal() as session:
            session.add(
                RegistryVersion(
                    version_tag="split-asof-v1",
                    algorithm="test",
                    parameters={},
                    status="ACTIVE",
                    description="Identity split as-of test",
                    created_at=baseline_time,
                )
            )
            session.add_all(
                [
                    GoldenCustomer(
                        golden_customer_id="split-old",
                        first_source_batch_id="split-batch-1",
                        anchor_source_id="split-source",
                        status="PROVISIONAL",
                        created_at=baseline_time,
                        updated_at=baseline_time,
                    ),
                    GoldenCustomer(
                        golden_customer_id="split-new",
                        first_source_batch_id="split-batch-2",
                        anchor_source_id="split-source",
                        status="PROVISIONAL",
                        created_at=split_time,
                        updated_at=split_time,
                    ),
                ]
            )
            session.flush()
            session.add_all(
                [
                    IdentityMappingHistory(
                        source_customer_id="split-source",
                        golden_customer_id="split-old",
                        registry_version="split-asof-v1",
                        source_batch_id="split-batch-1",
                        assignment_type="PROVISIONAL",
                        event_type="BASELINE",
                        effective_at=baseline_time,
                        recorded_at=baseline_time,
                    ),
                    IdentityMappingHistory(
                        source_customer_id="split-source",
                        golden_customer_id="split-new",
                        registry_version="split-asof-v1",
                        source_batch_id="split-batch-2",
                        assignment_type="MANUAL_OVERRIDE",
                        event_type="MANUAL_SPLIT",
                        effective_at=split_time,
                        recorded_at=split_time,
                    ),
                ]
            )
            session.commit()

            registry = PersistentIdentityRegistry(session)
            before_split = registry.get_mapping_as_of_result(
                effective_at=split_time - timedelta(seconds=1),
                recorded_at=split_time + timedelta(days=1),
            )
            after_split = registry.get_mapping_as_of_result(
                effective_at=split_time + timedelta(seconds=1),
                recorded_at=split_time + timedelta(days=1),
            )
            unknown_source = registry.get_mapping_as_of_result(
                effective_at=split_time + timedelta(seconds=1),
                recorded_at=split_time - timedelta(seconds=1),
            )

            assert before_split.mapping == {"split-source": "split-old"}
            assert after_split.mapping == {"split-source": "split-new"}
            assert "unresolved-source" not in after_split.mapping
            assert unknown_source.mapping == {"split-source": "split-old"}

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
            initial_time = datetime.now(timezone.utc) - timedelta(minutes=1)
            session.add(
                RegistryVersion(
                    version_tag="v1",
                    algorithm="test",
                    parameters={},
                    status="ACTIVE",
                    description="Identity merge as-of test",
                    created_at=initial_time,
                )
            )
            session.add_all([g1, g2, m1, m2, q_item])
            session.flush()
            session.add_all(
                [
                    IdentityMappingHistory(
                        source_customer_id="s1",
                        golden_customer_id="g-101",
                        registry_version="v1",
                        source_batch_id="b1",
                        assignment_type="PROVISIONAL",
                        event_type="BASELINE",
                        effective_at=initial_time,
                        recorded_at=initial_time,
                    ),
                    IdentityMappingHistory(
                        source_customer_id="s2",
                        golden_customer_id="g-102",
                        registry_version="v1",
                        source_batch_id="b1",
                        assignment_type="PROVISIONAL",
                        event_type="BASELINE",
                        effective_at=initial_time,
                        recorded_at=initial_time,
                    ),
                ]
            )
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

            decision_event = session.scalars(
                select(IdentityReviewDecisionHistory).where(
                    IdentityReviewDecisionHistory.review_queue_id == queue_id,
                    IdentityReviewDecisionHistory.event_type == "DECISION",
                )
            ).one()
            self.assertEqual(decision_event.action, "APPROVE_MERGE")
            self.assertEqual(decision_event.reviewer_id, self.user_id)
            self.assertEqual(decision_event.correlation_id, "corr-test-12345")

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

            history = session.scalars(
                select(IdentityMappingHistory).where(
                    IdentityMappingHistory.event_type == "MANUAL_MERGE"
                )
            ).all()
            self.assertEqual(len(history), 1)
            self.assertEqual({row.source_customer_id for row in history}, {"s2"})
            self.assertEqual(
                {row.correlation_id for row in history}, {"corr-test-12345"}
            )
            self.assertEqual({row.reviewer_id for row in history}, {self.user_id})
            # Verify bitemporal identity mapping using the real merge event.
            merge_event = next(row for row in history if row.source_customer_id == "s2")
            merge_effective_at = merge_event.effective_at
            merge_recorded_at = merge_event.recorded_at

            # SQLite may return timezone-aware columns as naive datetimes.
            if merge_effective_at.tzinfo is None:
                merge_effective_at = merge_effective_at.replace(tzinfo=timezone.utc)
            if merge_recorded_at.tzinfo is None:
                merge_recorded_at = merge_recorded_at.replace(tzinfo=timezone.utc)

            before_effective_time = merge_effective_at - timedelta(microseconds=1)
            after_recorded_time = merge_recorded_at + timedelta(seconds=1)

            before_merge = reg.get_mapping_as_of(
                effective_at=before_effective_time,
                recorded_at=after_recorded_time,
            )
            self.assertEqual(before_merge, {"s1": "g-101", "s2": "g-102"})

            after_merge = reg.get_mapping_as_of(
                effective_at=merge_effective_at + timedelta(seconds=1),
                recorded_at=after_recorded_time,
            )
            self.assertEqual(after_merge, {"s1": "g-101", "s2": "g-101"})

            old_knowledge = reg.get_mapping_as_of(
                effective_at=merge_effective_at + timedelta(seconds=1),
                recorded_at=merge_recorded_at - timedelta(microseconds=1),
            )
            self.assertEqual(old_knowledge, {"s1": "g-101", "s2": "g-102"})

    def test_review_decision_history_is_bitemporal_and_correctable(self):
        now = datetime.now(timezone.utc)
        with self.SessionLocal() as session:
            version = RegistryVersion(
                version_tag="review-history-v1",
                algorithm="test",
                parameters={},
                status="ACTIVE",
                description="Review history test",
                created_at=now,
            )
            queue = ReviewQueueItem(
                source_batch_id="review-history-batch",
                registry_version=version.version_tag,
                left_source_id="review-left",
                right_source_id="review-right",
                left_golden_id=None,
                right_golden_id=None,
                heuristic_score=0.5,
                reason="test",
                status="PENDING",
                created_at=now,
            )
            session.add_all([version, queue])
            session.flush()
            initial = IdentityReviewDecisionHistory(
                review_queue_id=queue.id,
                event_type="DECISION",
                action="REJECT_KEEP_SEPARATE",
                occurred_at=now - timedelta(minutes=30),
                available_at=now - timedelta(minutes=30),
                recorded_at=now - timedelta(minutes=30),
                source_batch_id=queue.source_batch_id,
                source_event_id="review-history:initial-event",
                source_version="identity-review-v1",
                idempotency_key="review-history:initial",
                reviewer_id=self.user_id,
                correlation_id="review-history-initial",
                rationale="Initial reviewed decision",
            )
            session.add(initial)
            session.commit()
            queue_id, initial_id = queue.id, initial.event_id

            registry = PersistentIdentityRegistry(session)
            before_correction = now - timedelta(seconds=1)
            with self.assertRaisesRegex(ValueError, "cannot predate"):
                registry.append_review_decision_revision(
                    queue_id=queue_id,
                    supersedes_event_id=initial_id,
                    event_type="CORRECTION",
                    action="APPROVE_MERGE",
                    actor_id=self.user_id,
                    rationale="Invalid early correction",
                    correlation_id="review-history-early-correction",
                    occurred_at=now - timedelta(hours=1),
                )
            correction = registry.append_review_decision_revision(
                queue_id=queue_id,
                supersedes_event_id=initial_id,
                event_type="CORRECTION",
                action="APPROVE_MERGE",
                actor_id=self.user_id,
                rationale="Corrected after evidence review",
                correlation_id="review-history-correction",
            )
            session.commit()
            replay = registry.append_review_decision_revision(
                queue_id=queue_id,
                supersedes_event_id=initial_id,
                event_type="CORRECTION",
                action="APPROVE_MERGE",
                actor_id=self.user_id,
                rationale="Corrected after evidence review",
                correlation_id="review-history-correction",
            )
            self.assertEqual(replay.event_id, correction.event_id)
            with self.assertRaisesRegex(ValueError, "conflicts with payload"):
                registry.append_review_decision_revision(
                    queue_id=queue_id,
                    supersedes_event_id=initial_id,
                    event_type="CORRECTION",
                    action="REJECT_KEEP_SEPARATE",
                    actor_id=self.user_id,
                    rationale="Conflicting retry",
                    correlation_id="review-history-correction",
                )

            effective_after = now + timedelta(minutes=1)
            knowledge_before = registry.get_review_decision_as_of(
                queue_id, effective_after, before_correction
            )
            self.assertEqual(knowledge_before.action, "REJECT_KEEP_SEPARATE")
            knowledge_after = registry.get_review_decision_as_of(
                queue_id, effective_after, now + timedelta(minutes=1)
            )
            self.assertEqual(knowledge_after.action, "APPROVE_MERGE")
            status_by_golden = registry.get_review_status_by_golden_as_of(
                {
                    "review-left": "gold-review-left",
                    "review-right": "gold-review-right",
                },
                effective_after,
                now + timedelta(minutes=1),
            )
            self.assertEqual(
                set(status_by_golden.values()),
                {"UNKNOWN"},
            )
            merged_status = registry.get_review_status_by_golden_as_of(
                {"review-left": "gold-review-left", "review-right": "gold-review-left"},
                effective_after,
                now + timedelta(minutes=1),
            )
            self.assertEqual(
                merged_status,
                {"gold-review-left": "APPROVED"},
            )

            revoke = registry.append_review_decision_revision(
                queue_id=queue_id,
                supersedes_event_id=correction.event_id,
                event_type="REVOCATION",
                action=None,
                actor_id=self.user_id,
                rationale="Revoked pending new evidence",
                correlation_id="review-history-revocation",
            )
            session.commit()
            revoked = registry.get_review_decision_as_of(
                queue_id, now + timedelta(minutes=2), now + timedelta(minutes=2)
            )
            self.assertEqual(revoked.event_id, revoke.event_id)
            self.assertIsNone(revoked.action)
            revoked_status = registry.get_review_status_by_golden_as_of(
                {
                    "review-left": "gold-review-left",
                    "review-right": "gold-review-right",
                },
                now + timedelta(minutes=2),
                now + timedelta(minutes=2),
            )
            self.assertEqual(set(revoked_status.values()), {"REVIEW_REQUIRED"})

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
            unknown_status_golden = GoldenCustomer(
                golden_customer_id="gold-unknown",
                first_source_batch_id="b1",
                anchor_source_id="s2",
                status="PROVISIONAL",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add_all([g, unknown_status_golden])
            session.commit()

            c360_saved = save_profile_snapshots(
                profiles=mock_c360,
                batch_id="batch_01",
                registry_version="v1.1",
                session=session,
            )
            self.assertEqual(c360_saved, 1)

            unknown_status_profile = {
                **mock_c360[0],
                "golden_customer_id": "gold-unknown",
                "identity_status": "UNKNOWN",
            }
            unknown_status_saved = save_profile_snapshots(
                profiles=[unknown_status_profile],
                batch_id="batch_01",
                registry_version="v1.1",
                session=session,
            )
            self.assertEqual(unknown_status_saved, 1)

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
            unknown_status_snapshot = session.scalars(
                select(ProfileSnapshot).where(
                    ProfileSnapshot.golden_customer_id == "gold-unknown"
                )
            ).one()
            self.assertEqual(unknown_status_snapshot.identity_status, "UNKNOWN")

            seg_snap = session.scalars(select(RFMLifecycleSnapshot)).first()
            self.assertIsNotNone(seg_snap)
            self.assertEqual(seg_snap.rfm_code, "533")
            self.assertEqual(seg_snap.lifecycle, "LOYAL")


if __name__ == "__main__":
    unittest.main()
