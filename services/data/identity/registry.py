"""Persistent Identity Registry implementation with Golden ID preservation and audit trail."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import (
    GoldenCustomer,
    MatchDecision,
    RegistryVersion,
    ReviewAuditLog,
    ReviewQueueItem,
    SourceIdentityMapping,
)


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
