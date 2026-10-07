from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.database import Base

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column(
        "user_id", ForeignKey("core.users.id", ondelete="CASCADE"), primary_key=True
    ),
    Column(
        "role_id", ForeignKey("core.roles.id", ondelete="CASCADE"), primary_key=True
    ),
    schema="core",
)


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = {"schema": "core"}

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    users: Mapped[list["User"]] = relationship(
        secondary=user_roles, back_populates="roles"
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    roles: Mapped[list[Role]] = relationship(
        secondary=user_roles, back_populates="users"
    )


class AuditEvent(Base):
    __tablename__ = "audit_event"
    __table_args__ = {"schema": "gov"}

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    correlation_id: Mapped[str] = mapped_column(String(128), index=True)
    actor_id: Mapped[int | None]
    event_type: Mapped[str] = mapped_column(String(64), default="http.request")
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(512))
    status_code: Mapped[int]
    client_ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class BatchJob(Base):
    __tablename__ = "batch_jobs"
    __table_args__ = {"schema": "act"}

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    created_by: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = {"schema": "core"}

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(128))
    email: Mapped[str] = mapped_column(String(320))
    segment: Mapped[str] = mapped_column(String(64), index=True)
    ltv: Mapped[float] = mapped_column(default=0.0)
    churn_risk: Mapped[str] = mapped_column(
        String(16), default="Low"
    )  # Low, Medium, High
    next_best_action: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class Campaign(Base):
    __tablename__ = "campaigns"
    __table_args__ = {"schema": "act"}

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    target_segment: Mapped[str] = mapped_column(String(64))
    channel: Mapped[str] = mapped_column(String(32))  # email_sim, sms_sim, push_sim
    ab_test_ratio: Mapped[int] = mapped_column(Integer, default=50)
    status: Mapped[str] = mapped_column(
        String(32), default="Draft"
    )  # Draft, Active, Completed, Paused
    message_draft: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    approved_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    correlation_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class IdentityReview(Base):
    __tablename__ = "identity_reviews"
    __table_args__ = {"schema": "core"}

    id: Mapped[int] = mapped_column(primary_key=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    customer_code: Mapped[str] = mapped_column(String(32))
    full_name: Mapped[str] = mapped_column(String(128))
    flagged_reason: Mapped[str] = mapped_column(String(256))
    match_confidence: Mapped[float] = mapped_column()
    subject_reference: Mapped[str] = mapped_column(String(128), index=True)
    candidate_references: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column()
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    decision: Mapped[str | None] = mapped_column(String(24), nullable=True)
    reviewer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CustomerFeature(Base):
    __tablename__ = "customer_features"
    __table_args__ = {"schema": "feat"}

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(Integer, index=True)
    feature_name: Mapped[str] = mapped_column(String(100))
    feature_value: Mapped[dict] = mapped_column(JSON, default=dict)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class ModelDriftMetric(Base):
    __tablename__ = "model_drift_metrics"
    __table_args__ = {"schema": "ml"}

    id: Mapped[int] = mapped_column(primary_key=True)
    model_name: Mapped[str] = mapped_column(String(100), index=True)
    metric_name: Mapped[str] = mapped_column(String(100))
    metric_value: Mapped[float] = mapped_column()
    threshold: Mapped[float] = mapped_column()
    status: Mapped[str] = mapped_column(String(16), default="healthy", index=True)
    measured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class NBADecision(Base):
    __tablename__ = "nba_decisions"
    __table_args__ = {"schema": "dec"}

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(Integer, index=True)
    correlation_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    recommended_action: Mapped[str] = mapped_column(String(256))
    rationale: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="proposed", index=True)
    selected_action: Mapped[str | None] = mapped_column(String(256), nullable=True)
    overridden_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    override_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class HumanOverride(Base):
    __tablename__ = "human_overrides"
    __table_args__ = {"schema": "dec"}

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(Integer, index=True)
    original_nba: Mapped[str] = mapped_column(String(256))
    override_nba: Mapped[str] = mapped_column(String(256))
    reason: Mapped[str] = mapped_column(String(512))
    overridden_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class DecisionTrace(Base):
    __tablename__ = "decision_traces"
    __table_args__ = {"schema": "gov"}

    id: Mapped[int] = mapped_column(primary_key=True)
    correlation_id: Mapped[str] = mapped_column(String(128), index=True)
    customer_code: Mapped[str] = mapped_column(String(32), index=True)
    trigger_event: Mapped[str] = mapped_column(String(128))
    decision_output: Mapped[str] = mapped_column(String(256))
    step_logs: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class CampaignMeasurement(Base):
    __tablename__ = "campaign_measurements"
    __table_args__ = {"schema": "msr"}

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(Integer, index=True)
    metric_name: Mapped[str] = mapped_column(String(100))
    observed_value: Mapped[float] = mapped_column()
    incremental_value: Mapped[float] = mapped_column()
    measured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = {"schema": "stg"}

    id: Mapped[int] = mapped_column(primary_key=True)
    source_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    records_seen: Mapped[int] = mapped_column(Integer, default=0)
    error_summary: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    __table_args__ = {"schema": "stg"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    step_results: Mapped[dict] = mapped_column(JSON, default=dict)
    error_summary: Mapped[str | None] = mapped_column(String(1000), nullable=True)
