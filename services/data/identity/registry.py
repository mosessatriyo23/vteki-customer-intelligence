"""Persistent Identity Registry implementation with Golden ID preservation and audit trail."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from api.models import (
    GoldenCustomer,
    IdentityHistoryCoverage,
    IdentityMappingHistory,
    IdentityReviewDecisionHistory,
    MatchDecision,
    RegistryVersion,
    ReviewAuditLog,
    ReviewQueueItem,
    SourceIdentityMapping,
)

MIGRATION_BASELINE_REASON = "Initial baseline captured during migration 0013"


@dataclass(frozen=True)
class IdentityMappingAsOf:
    status: Literal["AVAILABLE", "BLOCKED", "UNKNOWN"]
    mapping: dict[str, str]
    coverage_started_at: datetime | None


@dataclass(frozen=True)
class IdentityReviewDecisionAsOf:
    status: Literal["AVAILABLE", "UNKNOWN"]
    event_type: str | None
    action: str | None
    event_id: int | None
    occurred_at: datetime | None
    available_at: datetime | None
    recorded_at: datetime | None


class IdentityHistoryCoverageError(ValueError):
    """Raised when an identity cutoff predates the recorded history coverage."""


class PersistentIdentityRegistry:
    """Manages persistent Golden Customer registry with anti-silent-merge/split guarantees."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def register_version_if_absent(
        self,
        version_tag: str,
        algorithm: str = "conservative_heuristic_v1.1",
        parameters: dict[str, Any] | None = None,
        description: str | None = None,
    ) -> RegistryVersion:
        version = self.session.get(RegistryVersion, version_tag)
        if not version:
            version = RegistryVersion(
                version_tag=version_tag,
                algorithm=algorithm,
                parameters=parameters or {},
                status="ACTIVE",
                description=description or "Production Identity Registry version",
                created_at=datetime.now(timezone.utc),
            )
            self.session.add(version)
            self.session.flush()
        return version

    def get_existing_mapping(self) -> dict[str, str]:
        """Returns dict of {source_customer_id: golden_customer_id} from persistent storage."""
        stmt = select(
            SourceIdentityMapping.source_customer_id,
            SourceIdentityMapping.golden_customer_id,
        )
        return dict(self.session.execute(stmt).all())

    def get_mapping_as_of(
        self,
        effective_at: datetime,
        recorded_at: datetime | None = None,
    ) -> dict[str, str]:
        """Return source-to-Golden mappings as known at a bitemporal cutoff.

        effective_at limits when a mapping was valid in the business domain.
        recorded_at limits what the system had recorded by that point in time.
        """
        snapshot = self.get_mapping_as_of_result(effective_at, recorded_at)
        if snapshot.status == "BLOCKED":
            raise IdentityHistoryCoverageError(
                "BLOCKED: effective_at predates recorded identity-history coverage"
            )
        return snapshot.mapping

    def get_mapping_as_of_result(
        self,
        effective_at: datetime,
        recorded_at: datetime | None = None,
    ) -> IdentityMappingAsOf:
        """Return mappings with an explicit identity-history coverage status."""
        self._validate_cutoffs(effective_at, recorded_at)
        knowledge_cutoff = recorded_at or datetime.now(timezone.utc)
        coverage_marker = self.session.get(IdentityHistoryCoverage, 1)
        independent_coverage = (
            coverage_marker.coverage_started_at if coverage_marker is not None else None
        )
        if coverage_marker is not None and _as_utc(knowledge_cutoff) < _as_utc(
            coverage_marker.recorded_at
        ):
            return IdentityMappingAsOf(
                status="UNKNOWN",
                mapping={},
                coverage_started_at=None,
            )
        migration_baseline = self.session.scalar(
            select(func.min(IdentityMappingHistory.recorded_at)).where(
                IdentityMappingHistory.event_type == "BASELINE",
                IdentityMappingHistory.change_reason == MIGRATION_BASELINE_REASON,
            )
        )
        if independent_coverage is not None:
            coverage_started_at = _as_utc(independent_coverage)
            if _as_utc(effective_at) < coverage_started_at:
                return IdentityMappingAsOf(
                    status="BLOCKED",
                    mapping={},
                    coverage_started_at=coverage_started_at,
                )
        elif migration_baseline is not None:
            coverage_started_at = _as_utc(migration_baseline)
            if _as_utc(effective_at) < coverage_started_at:
                return IdentityMappingAsOf(
                    status="BLOCKED",
                    mapping={},
                    coverage_started_at=coverage_started_at,
                )
        else:
            first_history = self.session.scalar(
                select(func.min(IdentityMappingHistory.effective_at))
            )
            if first_history is None:
                return IdentityMappingAsOf(
                    status="UNKNOWN",
                    mapping={},
                    coverage_started_at=None,
                )
            coverage_started_at = _as_utc(first_history)
            if _as_utc(effective_at) < coverage_started_at:
                return IdentityMappingAsOf(
                    status="BLOCKED",
                    mapping={},
                    coverage_started_at=coverage_started_at,
                )

        effective_time = case(
            (
                and_(
                    IdentityMappingHistory.event_type == "BASELINE",
                    IdentityMappingHistory.change_reason == MIGRATION_BASELINE_REASON,
                ),
                IdentityMappingHistory.recorded_at,
            ),
            else_=IdentityMappingHistory.effective_at,
        )
        stmt = (
            select(IdentityMappingHistory)
            .where(
                effective_time <= effective_at,
                IdentityMappingHistory.recorded_at <= knowledge_cutoff,
            )
            .order_by(
                IdentityMappingHistory.source_customer_id,
                effective_time.desc(),
                IdentityMappingHistory.recorded_at.desc(),
                IdentityMappingHistory.id.desc(),
            )
        )

        result: dict[str, str] = {}
        for row in self.session.scalars(stmt):
            if row.source_customer_id not in result:
                result[row.source_customer_id] = row.golden_customer_id

        return IdentityMappingAsOf(
            status="AVAILABLE" if result else "UNKNOWN",
            mapping=result,
            coverage_started_at=coverage_started_at,
        )

    def get_review_decision_as_of(
        self,
        queue_id: int,
        effective_at: datetime,
        known_at: datetime,
    ) -> IdentityReviewDecisionAsOf:
        """Return a review decision using only events effective and known by cutoffs."""
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in (effective_at, known_at)
        ):
            raise ValueError("effective_at and known_at must be timezone-aware")
        rows = list(
            self.session.scalars(
                select(IdentityReviewDecisionHistory)
                .where(
                    IdentityReviewDecisionHistory.review_queue_id == queue_id,
                    IdentityReviewDecisionHistory.occurred_at <= effective_at,
                    IdentityReviewDecisionHistory.available_at <= known_at,
                    IdentityReviewDecisionHistory.recorded_at <= known_at,
                )
                .order_by(
                    IdentityReviewDecisionHistory.occurred_at,
                    IdentityReviewDecisionHistory.available_at,
                    IdentityReviewDecisionHistory.recorded_at,
                    IdentityReviewDecisionHistory.event_id,
                )
            ).all()
        )
        if not rows:
            return IdentityReviewDecisionAsOf(
                "UNKNOWN", None, None, None, None, None, None
            )

        visible_ids = {row.event_id for row in rows}
        superseded: set[int] = set()
        children: dict[int, int] = {}
        for row in rows:
            parent_id = row.supersedes_event_id
            if parent_id is None:
                continue
            if parent_id not in visible_ids:
                raise ValueError("Visible review correction has no visible parent")
            if parent_id in children:
                raise ValueError(
                    "Identity review decision correction branches are invalid"
                )
            children[parent_id] = row.event_id
            superseded.add(parent_id)

        heads = [row for row in rows if row.event_id not in superseded]
        if len(heads) != 1:
            raise ValueError("Identity review decision history must form one chain")
        head = heads[0]
        return IdentityReviewDecisionAsOf(
            status="AVAILABLE",
            event_type=head.event_type,
            action=head.action,
            event_id=head.event_id,
            occurred_at=head.occurred_at,
            available_at=head.available_at,
            recorded_at=head.recorded_at,
        )

    def get_review_status_by_golden_as_of(
        self,
        mapping: dict[str, str],
        effective_at: datetime,
        known_at: datetime,
    ) -> dict[str, str]:
        """Project review status without consulting mutable queue status fields."""
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in (effective_at, known_at)
        ):
            raise ValueError("effective_at and known_at must be timezone-aware")
        queues = self.session.scalars(
            select(ReviewQueueItem).where(
                ReviewQueueItem.created_at <= effective_at,
                ReviewQueueItem.created_at <= known_at,
            )
        ).all()
        statuses: dict[str, set[str]] = defaultdict(set)
        for queue in queues:
            goldens = {
                mapping[source]
                for source in (queue.left_source_id, queue.right_source_id)
                if source in mapping
            }
            if not goldens:
                continue
            decision = self.get_review_decision_as_of(queue.id, effective_at, known_at)
            if decision.status == "UNKNOWN":
                if queue.decided_at is not None and queue.decided_at <= effective_at:
                    status = "UNKNOWN"
                else:
                    status = "REVIEW_REQUIRED"
            elif decision.event_type == "REVOCATION":
                status = "REVIEW_REQUIRED" if len(goldens) == 2 else "UNKNOWN"
            elif decision.action == "APPROVE_MERGE":
                status = "APPROVED" if len(goldens) == 1 else "UNKNOWN"
            elif decision.action == "REJECT_KEEP_SEPARATE":
                status = "REJECTED" if len(goldens) == 2 else "UNKNOWN"
            else:
                status = "UNKNOWN"
            for golden in goldens:
                statuses[golden].add(status)
        return {
            golden: next(iter(values)) if len(values) == 1 else "UNKNOWN"
            for golden, values in statuses.items()
        }

    def append_review_decision_revision(
        self,
        *,
        queue_id: int,
        supersedes_event_id: int,
        event_type: Literal["CORRECTION", "REVOCATION"],
        action: str | None,
        actor_id: int,
        rationale: str,
        correlation_id: str,
        occurred_at: datetime | None = None,
    ) -> IdentityReviewDecisionHistory:
        """Append a linear correction/revocation without rewriting prior decisions.

        This revises the decision ledger. It deliberately does not rewrite existing
        identity mappings; a merge correction must use the identity mapping review
        workflow and publish corresponding mapping history as a separate decision.
        """
        if event_type not in {"CORRECTION", "REVOCATION"}:
            raise ValueError("event_type must be CORRECTION or REVOCATION")
        if event_type == "CORRECTION" and action not in {
            "APPROVE_MERGE",
            "REJECT_KEEP_SEPARATE",
        }:
            raise ValueError("CORRECTION requires a supported review action")
        if event_type == "REVOCATION" and action is not None:
            raise ValueError("REVOCATION action must be null")
        event_time = occurred_at or datetime.now(timezone.utc)
        if event_time.tzinfo is None or event_time.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        queue_item = self.session.scalars(
            select(ReviewQueueItem)
            .where(ReviewQueueItem.id == queue_id)
            .with_for_update()
        ).first()
        if queue_item is None:
            raise ValueError(f"Review queue item {queue_id} not found")
        target = self.session.get(IdentityReviewDecisionHistory, supersedes_event_id)
        if target is None or target.review_queue_id != queue_id:
            raise ValueError("supersedes_event_id must belong to the same review queue")
        if _as_utc(event_time) < _as_utc(target.occurred_at):
            raise ValueError(
                "A review correction cannot predate the decision it revises"
            )
        key = (
            f"identity-review:{queue_id}:{event_type}:"
            f"{supersedes_event_id}:{correlation_id}"
        )
        existing = self.session.scalar(
            select(IdentityReviewDecisionHistory).where(
                IdentityReviewDecisionHistory.idempotency_key == key
            )
        )
        if existing is not None:
            if (
                existing.action != action
                or existing.rationale != rationale
                or existing.reviewer_id != actor_id
            ):
                raise ValueError(
                    "Review decision idempotency key conflicts with payload"
                )
            return existing
        latest = self.session.scalar(
            select(IdentityReviewDecisionHistory)
            .where(IdentityReviewDecisionHistory.review_queue_id == queue_id)
            .order_by(
                IdentityReviewDecisionHistory.occurred_at.desc(),
                IdentityReviewDecisionHistory.recorded_at.desc(),
                IdentityReviewDecisionHistory.event_id.desc(),
            )
            .limit(1)
        )
        if latest is None or latest.event_id != supersedes_event_id:
            raise ValueError(
                "Only the current review-decision chain head may be revised"
            )
        event = IdentityReviewDecisionHistory(
            review_queue_id=queue_id,
            event_type=event_type,
            action=action,
            supersedes_event_id=supersedes_event_id,
            occurred_at=event_time,
            source_batch_id=queue_item.source_batch_id,
            source_event_id=key,
            source_version="identity-review-v1",
            idempotency_key=key,
            reviewer_id=actor_id,
            correlation_id=correlation_id,
            rationale=rationale,
        )
        self.session.add(event)
        self.session.add(
            ReviewAuditLog(
                review_queue_id=queue_id,
                actor_id=actor_id,
                action=event_type,
                previous_golden_id=queue_item.right_golden_id,
                new_golden_id=None,
                rationale=rationale,
                correlation_id=correlation_id,
                performed_at=event_time,
            )
        )
        self.session.flush()
        return event

    @staticmethod
    def _validate_cutoffs(
        effective_at: datetime,
        recorded_at: datetime | None,
    ) -> None:
        if effective_at.tzinfo is None or effective_at.utcoffset() is None:
            raise ValueError("effective_at must be timezone-aware")
        if recorded_at is not None and (
            recorded_at.tzinfo is None or recorded_at.utcoffset() is None
        ):
            raise ValueError("recorded_at must be timezone-aware")

    def apply_resolution_batch(
        self,
        batch_id: str,
        version_tag: str,
        resolution_result: dict[str, Any],
        allow_new_clusters: bool = True,
    ) -> dict[str, Any]:
        """Applies a resolver run onto persistent registry.

        Strictly enforces:
        1. Published Golden IDs are preserved.
        2. Silent merge of two distinct published Golden IDs is rejected & enqueued for review.
        3. Silent split of one published Golden ID cluster is rejected.
        4. Decisions and review queue are persisted with full auditability.
        """
        # merge() matches primary keys, not the natural unique pair key. Check
        # existing decisions before any writes so sequential replay is safe and
        # changed evidence cannot silently overwrite published provenance.
        existing_decisions = {
            (row.left_source_id, row.right_source_id): row
            for row in self.session.scalars(
                select(MatchDecision).where(MatchDecision.source_batch_id == batch_id)
            ).all()
        }
        for decision in resolution_result.get("decisions", []):
            existing = existing_decisions.get(
                (decision["left_source_id"], decision["right_source_id"])
            )
            if existing and (
                existing.registry_version != version_tag
                or existing.decision != decision["decision"]
                or existing.heuristic_score != decision["heuristic_score"]
                or existing.reason != decision["reason"]
            ):
                raise ValueError(
                    "Published match decision differs from replay; review required"
                )
        self.register_version_if_absent(version_tag)
        prior_mapping = self.get_existing_mapping()
        proposed_mapping = resolution_result["mapping"]

        # 1. Check for silent merge / silent split if prior records exist
        current = {
            r["source_customer_id"]: r["golden_customer_id"] for r in proposed_mapping
        }

        if prior_mapping:
            # Check disappeared sources
            if not set(prior_mapping).issubset(set(current)):
                disappeared = set(prior_mapping) - set(current)
                raise ValueError(
                    f"Integrity violation: previously published source records disappeared: {disappeared}"
                )

            old_to_new: dict[str, set[str]] = defaultdict(set)
            new_to_old: dict[str, set[str]] = defaultdict(set)
            for source, old_golden in prior_mapping.items():
                new_predicted = current[source]
                old_to_new[old_golden].add(new_predicted)
                new_to_old[new_predicted].add(old_golden)

            # Detect Silent Split
            for old_golden, predicted_clusters in old_to_new.items():
                if len(predicted_clusters) > 1:
                    # An existing published cluster split into multiple clusters
                    raise ValueError(
                        f"Silent split violation: published Golden ID {old_golden} was partitioned into multiple clusters: {predicted_clusters}"
                    )

            # Detect Silent Merge
            for new_cluster, old_goldens in new_to_old.items():
                if len(old_goldens) > 1:
                    conflicting_sources = [
                        s for s in prior_mapping if prior_mapping[s] in old_goldens
                    ]
                    raise ValueError(
                        f"Silent merge violation: published Golden IDs {old_goldens} would silently merge in cluster {new_cluster} (sources: {conflicting_sources}). Human review required."
                    )

        # 2. Map replacement: existing sources retain their published Golden ID
        replacements: dict[str, str] = {}
        if prior_mapping:
            for source, old_golden in prior_mapping.items():
                predicted = current[source]
                replacements[predicted] = old_golden

        # 3. Persist Golden Customers and Mappings
        now = datetime.now(timezone.utc)
        for row in proposed_mapping:
            predicted_cluster = row["golden_customer_id"]
            final_golden_id = replacements.get(predicted_cluster, predicted_cluster)
            source_id = row["source_customer_id"]

            # Ensure Golden Customer exists
            golden_obj = self.session.get(GoldenCustomer, final_golden_id)
            if not golden_obj:
                golden_obj = GoldenCustomer(
                    golden_customer_id=final_golden_id,
                    first_source_batch_id=batch_id,
                    anchor_source_id=source_id,
                    status="PROVISIONAL",
                    created_at=now,
                    updated_at=now,
                )
                self.session.add(golden_obj)
                self.session.flush()

            # Upsert Source Mapping
            mapping_obj = self.session.get(SourceIdentityMapping, source_id)
            if not mapping_obj:
                mapping_obj = SourceIdentityMapping(
                    source_customer_id=source_id,
                    golden_customer_id=final_golden_id,
                    registry_version=version_tag,
                    source_batch_id=batch_id,
                    assignment_type=(
                        "AUTO_MATCH"
                        if predicted_cluster in replacements
                        else "PROVISIONAL"
                    ),
                    assigned_at=now,
                )
                self.session.add(mapping_obj)
            else:
                mapping_obj.registry_version = version_tag
                mapping_obj.source_batch_id = batch_id
                mapping_obj.assigned_at = now

            existing_history = self.session.scalar(
                select(IdentityMappingHistory.id)
                .where(
                    IdentityMappingHistory.source_customer_id == source_id,
                    IdentityMappingHistory.source_batch_id == batch_id,
                    IdentityMappingHistory.registry_version == version_tag,
                    IdentityMappingHistory.golden_customer_id == final_golden_id,
                    IdentityMappingHistory.event_type == "BATCH_ASSIGNMENT",
                )
                .limit(1)
            )
            if existing_history is None:
                self.session.add(
                    IdentityMappingHistory(
                        source_customer_id=source_id,
                        golden_customer_id=final_golden_id,
                        registry_version=version_tag,
                        source_batch_id=batch_id,
                        assignment_type=mapping_obj.assignment_type,
                        event_type="BATCH_ASSIGNMENT",
                        effective_at=now,
                        recorded_at=now,
                        change_reason="Identity assignment recorded from resolution batch",
                    )
                )

        # 4. Persist Match Decisions
        for dec in resolution_result.get("decisions", []):
            decision_obj = MatchDecision(
                source_batch_id=batch_id,
                registry_version=version_tag,
                left_source_id=dec["left_source_id"],
                right_source_id=dec["right_source_id"],
                decision=dec["decision"],
                heuristic_score=dec["heuristic_score"],
                reason=dec["reason"],
                created_at=now,
            )
            pair = (dec["left_source_id"], dec["right_source_id"])
            if pair not in existing_decisions:
                self.session.add(decision_obj)
                existing_decisions[pair] = decision_obj

            # 5. Populate Review Queue for REVIEW decisions
            if dec["decision"] == "REVIEW":
                left_current = current.get(dec["left_source_id"])
                right_current = current.get(dec["right_source_id"])

                left_golden = (
                    replacements.get(left_current, left_current)
                    if left_current is not None
                    else None
                )
                right_golden = (
                    replacements.get(right_current, right_current)
                    if right_current is not None
                    else None
                )

                stmt = select(ReviewQueueItem).where(
                    ReviewQueueItem.registry_version == version_tag,
                    ReviewQueueItem.left_source_id == dec["left_source_id"],
                    ReviewQueueItem.right_source_id == dec["right_source_id"],
                )
                existing_q = self.session.scalars(stmt).first()
                if not existing_q:
                    q_item = ReviewQueueItem(
                        source_batch_id=batch_id,
                        registry_version=version_tag,
                        left_source_id=dec["left_source_id"],
                        right_source_id=dec["right_source_id"],
                        left_golden_id=left_golden,
                        right_golden_id=right_golden,
                        heuristic_score=dec["heuristic_score"],
                        reason=dec["reason"],
                        status="PENDING",
                        created_at=now,
                    )
                    self.session.add(q_item)

                    # Mark Golden Customers as REVIEW_REQUIRED
                    for gid in (left_golden, right_golden):
                        if gid:
                            g_ent = self.session.get(GoldenCustomer, gid)
                            if g_ent and g_ent.status == "PROVISIONAL":
                                g_ent.status = "REVIEW_REQUIRED"
                                g_ent.updated_at = now

        self.session.commit()
        return {
            "status": "APPLIED",
            "mapped_sources": len(proposed_mapping),
            "registry_version": version_tag,
            "batch_id": batch_id,
        }

    def decide_review_queue_item(
        self,
        queue_id: int,
        actor_id: int,
        action: str,  # 'APPROVE_MERGE' or 'REJECT_KEEP_SEPARATE'
        rationale: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """Executes a human review decision with mandatory audit trail."""
        stmt = (
            select(ReviewQueueItem)
            .where(ReviewQueueItem.id == queue_id)
            .with_for_update()
        )
        item = self.session.scalars(stmt).first()
        if not item:
            raise ValueError(f"Review queue item {queue_id} not found")
        decision_key = f"identity-review:{item.id}:DECISION:{correlation_id}"
        existing_event = self.session.scalar(
            select(IdentityReviewDecisionHistory).where(
                IdentityReviewDecisionHistory.idempotency_key == decision_key
            )
        )
        if existing_event is not None:
            if (
                existing_event.action != action
                or existing_event.reviewer_id != actor_id
                or existing_event.rationale != rationale
            ):
                raise ValueError(
                    "Review decision idempotency key conflicts with payload"
                )
            return {
                "queue_id": item.id,
                "status": item.status,
                "decision": existing_event.action,
                "correlation_id": existing_event.correlation_id,
            }
        if item.status != "PENDING":
            raise ValueError(
                f"Review queue item {queue_id} is already decided ({item.status})"
            )

        now = datetime.now(timezone.utc)
        prev_golden = item.right_golden_id
        new_golden = item.left_golden_id

        if action == "APPROVE_MERGE":
            item.status = "APPROVED_MERGE"
            # A Golden ID represents an entire published cluster. Reassign all
            # members atomically, not just one reviewed source (silent partial
            # merge would corrupt the registry).
            if not item.left_golden_id or not item.right_golden_id:
                raise ValueError("Both published Golden IDs are required for merge")
            if item.left_golden_id == item.right_golden_id:
                raise ValueError("Cannot merge a Golden ID with itself")
            affected = self.session.scalars(
                select(SourceIdentityMapping).where(
                    SourceIdentityMapping.golden_customer_id == item.right_golden_id
                )
            ).all()
            if not affected:
                raise ValueError("Reviewed right Golden ID has no source mappings")
            for mapping in affected:
                mapping.golden_customer_id = item.left_golden_id
                mapping.assignment_type = "MANUAL_OVERRIDE"
                mapping.assigned_at = now
                self.session.add(
                    IdentityMappingHistory(
                        source_customer_id=mapping.source_customer_id,
                        golden_customer_id=item.left_golden_id,
                        registry_version=mapping.registry_version,
                        source_batch_id=mapping.source_batch_id,
                        assignment_type="MANUAL_OVERRIDE",
                        event_type="MANUAL_MERGE",
                        effective_at=now,
                        recorded_at=now,
                        reviewer_id=actor_id,
                        correlation_id=correlation_id,
                        change_reason=rationale,
                    )
                )

            # Mark right golden customer as merged if applicable
            if item.right_golden_id and item.right_golden_id != item.left_golden_id:
                right_g = self.session.get(GoldenCustomer, item.right_golden_id)
                if right_g:
                    right_g.status = "APPROVED"
                    right_g.merged_into_golden_id = item.left_golden_id
                    right_g.updated_at = now
            if item.left_golden_id:
                left_g = self.session.get(GoldenCustomer, item.left_golden_id)
                if left_g:
                    left_g.status = "APPROVED"
                    left_g.updated_at = now

        elif action == "REJECT_KEEP_SEPARATE":
            item.status = "REJECTED_KEEP_SEPARATE"
        else:
            raise ValueError(f"Invalid review action: {action}")

        item.reviewer_id = actor_id
        item.reviewer_note = rationale
        item.decided_at = now

        self.session.add(
            IdentityReviewDecisionHistory(
                review_queue_id=item.id,
                event_type="DECISION",
                action=action,
                occurred_at=now,
                available_at=now,
                recorded_at=now,
                source_batch_id=item.source_batch_id,
                source_event_id=decision_key,
                source_version="identity-review-v1",
                idempotency_key=decision_key,
                reviewer_id=actor_id,
                correlation_id=correlation_id,
                rationale=rationale,
            )
        )

        # Create Immutable Audit Trail
        audit_log = ReviewAuditLog(
            review_queue_id=item.id,
            actor_id=actor_id,
            action=action,
            previous_golden_id=prev_golden,
            new_golden_id=new_golden if action == "APPROVE_MERGE" else None,
            rationale=rationale,
            correlation_id=correlation_id,
            performed_at=now,
        )
        self.session.add(audit_log)
        self.session.commit()

        return {
            "queue_id": item.id,
            "status": item.status,
            "decision": action,
            "correlation_id": correlation_id,
        }


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
