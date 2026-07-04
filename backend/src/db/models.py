"""ORM mapped classes for all database tables.

Tables:
  - organizations      (W1, migration 0009)
  - teams              (W1, migration 0009 -- created but unused in v1 flows)
  - memberships        (W1, migration 0009)
  - users              (Phase 2, migration 0001; +current_org_id in 0009)
  - api_keys           (Phase 2, migration 0001; +org_id in 0009)
  - analyses           (Phase 3, migration 0002; +org_id in 0009)
  - cost_decisions     (Phase 2 gap, migration 0008; +org_id in 0009)
  - jobs               (Phase 3, migration 0002 -- schema only, populated in Phase 7; +org_id in 0009)
  - usage_events       (Phase 3, migration 0002; +org_id in 0009)
  - batches            (Phase 9, migration 0004; +org_id in 0009)
  - batch_items        (Phase 9, migration 0004; +org_id in 0009)
  - webhook_deliveries (Phase 9, migration 0004; +org_id in 0009)
  - audit_log          (Phase 12, migration 0006; +org_id in 0009)

W1 tenancy note (migration 0009): every user-scoped row carries ``org_id``
(FK -> organizations.id, a ULID string). The eight pure data tables have it
NOT NULL; ``users.current_org_id`` (the active-org pointer) and
``audit_log.org_id`` (system events have no user) are intentionally nullable.
Nothing filters by ``org_id`` yet -- this is a pure foundation layer (W1 step 1).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from ulid import ULID

from src.db.engine import Base


# ---------------------------------------------------------------------------
# W1 tenancy tables (migration 0009)
# ---------------------------------------------------------------------------


class Organization(Base):
    """A tenant. Every user-scoped row is owned by exactly one organization.

    In v1 each user gets a personal org at signup (or via the 0009 backfill for
    pre-existing users); multi-user orgs / invites arrive with RBAC (W1 step 2).
    ``id`` is a ULID string PK (matches the spec's ``id (ulid pk)``), so all
    ``org_id`` FK columns elsewhere are ``Text``.
    """

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(
        Text, primary_key=True, default=lambda: str(ULID())
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    # relationships
    teams: Mapped[List[Team]] = relationship(
        back_populates="organization", lazy="selectin"
    )
    memberships: Mapped[List[Membership]] = relationship(
        back_populates="organization", lazy="selectin"
    )


class Team(Base):
    """A sub-group within an org. Created in v1 but unused by any flow yet."""

    __tablename__ = "teams"
    __table_args__ = (Index("ix_teams_org_id", "org_id"),)

    id: Mapped[str] = mapped_column(
        Text, primary_key=True, default=lambda: str(ULID())
    )
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    # relationships
    organization: Mapped[Organization] = relationship(back_populates="teams")


class Membership(Base):
    """Binds a user to an org with an org-scoped role.

    ``(org_id, user_id)`` is unique. ``org_role`` is one of admin/member/viewer
    (a CHECK constraint, mirroring the platform ``users.role`` check from 0005).
    This is the row ``resolve_org()`` reads to answer "which org owns this user".
    """

    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_memberships_org_user"),
        Index("ix_memberships_user_id", "user_id"),
        Index("ix_memberships_org_id", "org_id"),
    )

    id: Mapped[str] = mapped_column(
        Text, primary_key=True, default=lambda: str(ULID())
    )
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    org_role: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="member"
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    # relationships
    organization: Mapped[Organization] = relationship(back_populates="memberships")


# ---------------------------------------------------------------------------
# Phase 2 tables (mirror 0001 migration)
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_current_org_id", "current_org_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    email_lower: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    google_sub: Mapped[Optional[str]] = mapped_column(Text, unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    disposable_flag: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False
    )
    auth_provider: Mapped[str] = mapped_column(
        Text, server_default="google", nullable=False
    )
    role: Mapped[str] = mapped_column(
        Text, server_default="analyst", nullable=False
    )
    password_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # W1: the user's active org (pointer). Intentionally NULLABLE — it breaks
    # the users<->organizations bootstrap cycle at signup, and accommodates the
    # future superadmin split (W1 step 2). Not the tenancy source of truth; the
    # ``memberships`` row is (see resolve_org).
    current_org_id: Mapped[Optional[str]] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )

    # relationships
    api_keys: Mapped[List[ApiKey]] = relationship(back_populates="user", lazy="selectin")
    analyses: Mapped[List[Analysis]] = relationship(back_populates="user", lazy="selectin")
    batches: Mapped[List[Batch]] = relationship(back_populates="user", lazy="selectin")
    cost_decisions: Mapped[List[CostDecision]] = relationship(
        back_populates="user", lazy="selectin"
    )


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (Index("ix_api_keys_org_id", "org_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, server_default="Default")
    prefix: Mapped[str] = mapped_column(Text, nullable=False)
    hmac_index: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    secret_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # relationships
    user: Mapped[User] = relationship(back_populates="api_keys")


# ---------------------------------------------------------------------------
# Phase 3 tables (migration 0002)
# ---------------------------------------------------------------------------


class Analysis(Base):
    __tablename__ = "analyses"
    __table_args__ = (
        Index("ix_analyses_user_created", "user_id", "created_at"),
        # W1 hot-table composite: org_id is the leading column so it also
        # serves org_id-only lookups (no separate single-column index needed).
        Index("ix_analyses_org_user", "org_id", "user_id"),
        UniqueConstraint(
            "user_id",
            "mesh_hash",
            "process_set_hash",
            "analysis_version",
            name="uq_analyses_dedup",
        ),
        Index(
            "ix_analyses_share",
            "share_short_id",
            unique=True,
            postgresql_where=text("share_short_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ulid: Mapped[str] = mapped_column(
        Text, unique=True, nullable=False, default=lambda: str(ULID())
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    api_key_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True
    )
    mesh_hash: Mapped[str] = mapped_column(Text, nullable=False)
    process_set_hash: Mapped[str] = mapped_column(Text, nullable=False)
    analysis_version: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[str] = mapped_column(Text, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    result_json: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    face_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
    is_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    share_short_id: Mapped[Optional[str]] = mapped_column(
        Text, unique=False, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    # relationships
    user: Mapped[User] = relationship(back_populates="analyses")
    jobs: Mapped[List[Job]] = relationship(back_populates="analysis", lazy="selectin")


class CostDecision(Base):
    """Persisted should-cost / make-vs-buy decision (Phase 2 gap #3).

    Mirrors ``Analysis`` for type-compatibility on both Postgres (JSONB) and the
    SQLite test DB: ``result_json`` stores the full ``report_to_dict(report)``
    glass-box artifact verbatim (geometry, per-process estimates with drivers +
    provenance + honest confidence band, routing, assumptions, and the
    make-vs-buy decision). A handful of columns are denormalized off that JSON
    (``make_now_process`` / ``crossover_qty`` / ``quantities``) purely for
    listing/filtering — the JSON stays the source of truth and carries the same
    honesty (never "validated") as the live decision.
    """

    __tablename__ = "cost_decisions"
    __table_args__ = (
        Index("ix_cost_decisions_user_created", "user_id", "created_at"),
        # W1 hot-table composite (org_id leading; see Analysis note).
        Index("ix_cost_decisions_org_user", "org_id", "user_id"),
        UniqueConstraint(
            "user_id",
            "mesh_hash",
            "params_hash",
            name="uq_cost_decisions_dedup",
        ),
        Index(
            "ix_cost_decisions_share",
            "share_short_id",
            unique=True,
            postgresql_where=text("share_short_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ulid: Mapped[str] = mapped_column(
        Text, unique=True, nullable=False, default=lambda: str(ULID())
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    api_key_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True
    )
    mesh_hash: Mapped[str] = mapped_column(Text, nullable=False)
    # SHA-256 of the canonical cost parameters (qty/region/cavities/complexity/
    # material_class/shop/overrides) — the second half of the dedup key.
    params_hash: Mapped[str] = mapped_column(Text, nullable=False)
    engine_version: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Denormalized off result_json for cheap listing / filtering only.
    make_now_process: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    crossover_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    quantities: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    label: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    share_short_id: Mapped[Optional[str]] = mapped_column(
        Text, unique=False, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    # relationships
    user: Mapped[User] = relationship(back_populates="cost_decisions")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        # W1 hot-table composite (org_id leading; see Analysis note).
        Index("ix_jobs_org_user", "org_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ulid: Mapped[str] = mapped_column(
        Text, unique=True, nullable=False, default=lambda: str(ULID())
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    analysis_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("analyses.id", ondelete="SET NULL"), nullable=True
    )
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="queued"
    )
    params_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    result_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # relationships
    analysis: Mapped[Optional[Analysis]] = relationship(back_populates="jobs")


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        Index("ix_usage_events_user_created", "user_id", "created_at"),
        Index("ix_usage_events_apikey_created", "api_key_id", "created_at"),
        Index("ix_usage_events_org_id", "org_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    api_key_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    analysis_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("analyses.id", ondelete="SET NULL"), nullable=True
    )
    mesh_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    face_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Phase 9 tables (migration 0004)
# ---------------------------------------------------------------------------


class Batch(Base):
    __tablename__ = "batches"
    __table_args__ = (
        Index("ix_batches_user_created", "user_id", "created_at"),
        # W1 hot-table composite (org_id leading; see Analysis note).
        Index("ix_batches_org_user", "org_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ulid: Mapped[str] = mapped_column(
        Text, unique=True, nullable=False, default=lambda: str(ULID())
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    api_key_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="pending"
    )
    # W3: 'dfm' (DFM-check every item, the original pipeline) | 'cost' (should-cost
    # every item). server_default keeps every pre-W3 row DFM with no backfill.
    job_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="dfm"
    )
    input_mode: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    webhook_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    webhook_secret: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    total_items: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    completed_items: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    failed_items: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    concurrency_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="10"
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # relationships
    items: Mapped[List[BatchItem]] = relationship(
        back_populates="batch", lazy="selectin"
    )
    webhook_deliveries: Mapped[List[WebhookDelivery]] = relationship(
        back_populates="batch", lazy="selectin"
    )
    user: Mapped[User] = relationship(back_populates="batches")


class BatchItem(Base):
    __tablename__ = "batch_items"
    __table_args__ = (
        Index("ix_batch_items_batch_status", "batch_id", "status"),
        Index("ix_batch_items_batch_created", "batch_id", "created_at"),
        Index("ix_batch_items_org_id", "org_id"),
        Index("ix_batch_items_cost_decision_id", "cost_decision_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ulid: Mapped[str] = mapped_column(
        Text, unique=True, nullable=False, default=lambda: str(ULID())
    )
    batch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("batches.id", ondelete="CASCADE"), nullable=False
    )
    # W1: no user_id on this table — org_id is derived from the parent batch
    # (in the 0009 backfill and in create_batch_items).
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="pending"
    )
    process_types: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rule_pack: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="normal"
    )
    analysis_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("analyses.id", ondelete="SET NULL"), nullable=True
    )
    # W3 cost-batch per-item params (nullable; DFM items leave them unset). The
    # worker mirrors POST /validate/cost when these are supplied and falls back
    # to the engine defaults otherwise. ``quantities`` is a semicolon-separated
    # int list (e.g. "1;100;1000").
    quantities: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    region: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    material_class: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    shop: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # The cost_decisions row a costed item produced (SET NULL on delete so a
    # pruned decision never orphans the item).
    cost_decision_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("cost_decisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )
    duration_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # relationships
    batch: Mapped[Batch] = relationship(back_populates="items")
    analysis: Mapped[Optional[Analysis]] = relationship()


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        Index("ix_webhook_deliveries_retry", "status", "next_retry_at"),
        Index("ix_webhook_deliveries_org_id", "org_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("batches.id", ondelete="CASCADE"), nullable=False
    )
    # W1: no user_id on this table — org_id is derived from the parent batch
    # (in the 0009 backfill and in create_webhook_delivery).
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    response_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    # relationships
    batch: Mapped[Batch] = relationship(back_populates="webhook_deliveries")


# ---------------------------------------------------------------------------
# Phase 12 tables (migration 0006)
# ---------------------------------------------------------------------------


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_timestamp", "timestamp"),
        Index("ix_audit_log_user_timestamp", "user_id", "timestamp"),
        Index("ix_audit_log_action_timestamp", "action", "timestamp"),
        Index("ix_audit_log_org_id", "org_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # W1: NULLABLE — system/unauthenticated audit events have no user, hence no
    # org. User-attributed rows are stamped (backfill + log_action). ondelete
    # SET NULL: audit history survives org deletion (mirrors user_id).
    org_id: Mapped[Optional[str]] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    user_email: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    detail_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class GroundTruthRecordRow(Base):
    """One persisted real cost/quote datum — the W5 flywheel's durable store.

    The ORG-SCOPED home for the ``GroundTruthRecord`` that the costing
    ground-truth loop (``src/costing/groundtruth.py``) consumes. This is what
    retires the Python-REPL requirement: real quotes land here via the ingest
    API, and recalibration reads them (``WHERE org_id = caller-org``) to fit the
    served Calibration / ResidualModel. ``stand_in`` defaults False — the API is
    for REAL data — but a True row can only shape a band's spread, it can NEVER
    flip ``validated`` True (that honesty rail is enforced in the costing layer,
    not here). One org's rows never enter another's calibration: every read is
    org-filtered (cross-tenant test asserts this by name).

    Mirrors the ``analyses``/``cost_decisions`` shape: ULID public id, org_id FK
    (CASCADE), nullable user_id (who ingested; SET NULL so history survives a
    user delete). Dedup (last write wins on part+process+qty+shop within an org)
    lives in the service, mirroring ``groundtruth.add_record``.
    """

    __tablename__ = "ground_truth_records"
    __table_args__ = (
        Index("ix_ground_truth_records_org", "org_id"),
        Index("ix_ground_truth_records_org_part", "org_id", "part_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ulid: Mapped[str] = mapped_column(
        Text, unique=True, nullable=False, default=lambda: str(ULID())
    )
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    part_id: Mapped[str] = mapped_column(Text, nullable=False)
    process: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_unit_cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    material_class: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="polymer"
    )
    shop: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    region: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="USD")
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    stand_in: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    part_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    # ── P1 analogy-to-quote k-NN geometry (migration 0018) — all NULLABLE. ──
    # The MEASURED cost-drivers (mirroring ``analogy_estimator.FEATURE_KEYS`` /
    # ``drivers.GeoDrivers``) a record carries so the analogy k-NN member can
    # measure geometric distance to the query part. Populated best-effort at
    # ingest when the part's mesh resolves; a record with no resolvable mesh (or
    # an older row) stays NULL and the analogy simply skips it. Never fabricated.
    volume_cm3: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    surface_area_cm2: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_bbox_mm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    face_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# W4 governed libraries (migration 0013): the versioned rate-card asset
# ---------------------------------------------------------------------------


class RateCardVersion(Base):
    """A governed rate-card asset — a versioned, effective-dated snapshot of an
    org's cost rate table (W4 governed libraries, slice 1).

    Replaces "the 487-line hardcoded ``RATE_CARD_V0`` dict with no API at all"
    (long-horizon-plan §W4 / arch audit) with a DB-backed asset an org admin can
    draft, review, and PUBLISH with an effective date. ``payload`` is a full
    ``RATE_CARD_V0``-shaped table; the costing engine reads the version *effective
    at the estimate time* as its base table instead of the hardcoded default.

    HONESTY (non-negotiable rule #1/#2): a governed rate card is still a table of
    DEFAULT assumptions — NOT a claim of measured truth. Adopting one changes
    which default numbers an org uses; it never flips a decision to ``validated``
    (that comes only from real ground-truth residuals, W5). Nothing here launders
    an assumption into a fact.

    Versioning / effective-dating (one non-overlapping timeline per org):
      * ``version`` is monotonic per org (1, 2, 3…), unique per org.
      * ``status`` is ``draft`` | ``published`` | ``archived``.
      * Publishing a version stamps ``effective_from`` (now, or a caller-supplied
        future instant) and closes the previously-open published version's
        ``effective_to`` to that instant — so at most one published version is in
        effect at any time. Resolution picks the published row with
        ``effective_from <= as_of`` and (``effective_to IS NULL`` or ``> as_of``).
    """

    __tablename__ = "rate_card_versions"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "version", name="uq_rate_card_versions_org_version"
        ),
        Index("ix_rate_card_versions_org_status", "org_id", "status"),
        Index("ix_rate_card_versions_org_effective", "org_id", "effective_from"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ulid: Mapped[str] = mapped_column(
        Text, unique=True, nullable=False, default=lambda: str(ULID())
    )
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="draft"
    )
    # Full RATE_CARD_V0-shaped rate table (validated on publish).
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    change_note: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=""
    )
    effective_from: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    effective_to: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )


# ---------------------------------------------------------------------------
# W3.5 rung-1 declared context (migration 0014): honest portfolio $/year
# ---------------------------------------------------------------------------


class PartContext(Base):
    """A part's USER-DECLARED business context (W3.5 rung-1).

    One optional row per part (a distinct ``mesh_hash`` within an org) carrying
    the demand/program facts the geometry can never tell you — which program the
    part belongs to, its parent assembly, how many go into each parent, and the
    annual build volume. It is what lets the portfolio roll-up state an honest
    ``$/year`` instead of only a per-unit price.

    HONESTY (non-negotiable): every field here is DECLARED by a user, never
    inferred or guessed from the mesh — provenance is always ``"user"``. Nothing
    is fabricated: an annualized figure is only ever computed when the user has
    actually declared an ``annual_volume`` (we NEVER invent a demand quantity),
    and a part with no context row behaves exactly as it did before this table
    existed. Adopting a context changes what business math we can show; it never
    flips a cost band to ``validated`` (that is still real ground truth only).
    """

    __tablename__ = "part_contexts"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "mesh_hash", name="uq_part_contexts_org_mesh"
        ),
        Index("ix_part_contexts_org_program", "org_id", "program"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ulid: Mapped[str] = mapped_column(
        Text, unique=True, nullable=False, default=lambda: str(ULID())
    )
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    mesh_hash: Mapped[str] = mapped_column(Text, nullable=False)
    program: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parent_assembly: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    units_per_parent: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    annual_volume: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


class PartSummary(Base):
    """Materialized per-part catalog projection (Aramco GAP 2 — scale to millions).

    ONE row per ``(org_id, mesh_hash)`` carrying the fully-derived catalog row
    (``row_json`` = the exact ``catalog_service.derive_row`` dict) plus the scalar
    columns needed to aggregate/paginate the whole inventory in SQL — the derived
    makeability ``triage_bucket``, the recommended ``route_process``, the two
    artifact-presence flags, and the row's derived recency (``updated_at`` =
    ``max(analysis, cost)`` created_at).

    Maintained on write at the two persist funnels (analysis + cost decision) so
    the whole-inventory triage COUNT and the catalog grid no longer scan the 2000
    newest raw rows and fold in Python. The legacy fold path
    (``catalog_service._fold_org_parts`` and friends) is untouched and remains the
    byte-identity oracle: ``row_json`` reproduces the grid row VERBATIM and
    ``triage_bucket`` equals ``catalog_service.triage_bucket(row_json)``.

    HONESTY: nothing is fabricated — every column is a projection of what the
    legacy derivation already computes from persisted engine output. A part with
    no artifact has no summary row (it never appears in the catalog either).
    """

    __tablename__ = "part_summaries"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "mesh_hash", name="uq_part_summaries_org_mesh"
        ),
        # Triage rollup: GROUP BY triage_bucket within an org.
        Index("ix_part_summaries_org_bucket", "org_id", "triage_bucket"),
        # Keyset pagination of the grid: (updated_at DESC, mesh_hash DESC).
        Index(
            "ix_part_summaries_org_keyset",
            "org_id",
            text("updated_at DESC"),
            text("mesh_hash DESC"),
        ),
        # by_process rollup: GROUP BY route_process within an org.
        Index("ix_part_summaries_org_route", "org_id", "route_process"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    mesh_hash: Mapped[str] = mapped_column(Text, nullable=False)
    # Derived makeability posture (makeable | needs_review | unknown) — the exact
    # output of catalog_service.triage_bucket(row_json).
    triage_bucket: Mapped[str] = mapped_column(Text, nullable=False)
    # Recommended-route process id (None when the part has no route). Fuels the
    # by_process rollup + the route facet.
    route_process: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    has_analysis: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    has_cost: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    # Derived recency = max(analysis, cost) created_at — the grid's sort key and
    # the keyset-pagination cursor axis. Kept in lock-step with row_json's
    # ``updated_at`` string (both parsed from the same value; never drifts).
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    # The full catalog row — catalog_service.derive_row(...) VERBATIM, so the
    # scaled grid hydrates a page byte-identically to the legacy grid.
    row_json: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)


# ---------------------------------------------------------------------------
# W4 governed libraries (migration 0015): the versioned shop-profile asset
# ---------------------------------------------------------------------------


class ShopProfileVersion(Base):
    """A governed shop-profile asset — a versioned, effective-dated, PER-SLUG
    snapshot of one shop's cost calibration (W4 governed libraries, slice 2).

    The DB-backed successor to the read-only ``backend/data/shop_profiles/*.json``
    flat files: an org admin drafts, reviews, and PUBLISHES a shop profile with an
    effective date, and the costing engine binds the version *effective at the
    estimate time* as that shop's SHOP-provenance overrides instead of loading the
    flat file. Mirrors ``RateCardVersion`` column-for-column, plus a ``slug`` (the
    shop identifier the cost API references, e.g. ``"midwest-precision-cnc"``).

    ``payload`` is the shop-overrides dict — the exact dotted-key form
    ``ShopProfile.to_shop_overrides`` produces and ``build_rate_card(shop_overrides=…)``
    consumes (``labor_rate``, ``machine_rate.SLS``, ``material_price.@polymer``,
    ``region_labor.MX`` …) — plus optional ``name``/``region`` metadata used for
    the shop label/region binding.

    HONESTY (non-negotiable rules #1/#2): a governed shop profile is the org's
    DECLARED shop calibration. ``build_rate_card`` already flips its keys to SHOP
    provenance (``shop_keys``); that is a declared assumption, NOT measured truth.
    Adopting one changes *which* shop numbers an org uses; it never flips a
    decision to ``validated`` (that comes only from real ground-truth residuals,
    W5). Nothing here launders a declared rate into a fact.

    Versioning / effective-dating is PER ``(org_id, slug)``: ``version`` is
    monotonic per org; publishing a version for a slug closes that slug's
    previously-open published version's ``effective_to`` so at most one published
    version per (org, slug) is in effect at any time.
    """

    __tablename__ = "shop_profile_versions"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "version", name="uq_shop_profile_versions_org_version"
        ),
        UniqueConstraint("ulid", name="uq_shop_profile_versions_ulid"),
        Index("ix_shop_profile_versions_org_status", "org_id", "status"),
        Index("ix_shop_profile_versions_org_slug", "org_id", "slug"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ulid: Mapped[str] = mapped_column(
        Text, nullable=False, default=lambda: str(ULID())
    )
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # The shop identifier the cost API references (?shop=<slug>). The effective
    # governed profile is resolved per (org_id, slug).
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="draft"
    )
    # Shop-overrides dict (validated on publish via a build_rate_card dry-run).
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    change_note: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=""
    )
    effective_from: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    effective_to: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )


# ---------------------------------------------------------------------------
# W4 governance (migration 0016): the change-request workflow over the
# governed rate-card / shop-profile libraries
# ---------------------------------------------------------------------------


class ChangeRequest(Base):
    """A governance change-request over a governed library asset version (W4).

    The org-scoped record that gates the "change request -> review -> publish"
    flow over the versioned rate-card and shop-profile libraries: a member
    PROPOSES a draft version for review, and an org admin either APPROVES it
    (which publishes the draft via the library's existing, tested
    ``publish_version`` path) or REJECTS it (the draft stays a draft).

    ``target_version_id`` + ``asset_type`` identify the DRAFT being proposed.
    They are deliberately NOT a single cross-table FK: a change request can
    target either a ``rate_card_versions`` row or a ``shop_profile_versions``
    row, so ``asset_type`` dispatches which library owns the id. Tenancy is by
    ``org_id`` (both the change request and its target live in the same org).

    HONESTY (non-negotiable): governance never launders an assumption into a
    fact. Approving a change request only triggers the existing publish path —
    it changes WHICH default/shop numbers an org uses and WHO may trigger the
    switch; it never flips a decision to ``validated`` (that is real
    ground-truth residuals only, W5).
    """

    __tablename__ = "change_requests"
    __table_args__ = (
        UniqueConstraint("ulid", name="uq_change_requests_ulid"),
        Index("ix_change_requests_org_status", "org_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ulid: Mapped[str] = mapped_column(
        Text, nullable=False, default=lambda: str(ULID())
    )
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # Which library owns ``target_version_id``: 'rate_card' | 'shop_profile'.
    asset_type: Mapped[str] = mapped_column(Text, nullable=False)
    # The DRAFT version being proposed (id within the asset_type's table — NOT a
    # cross-table FK; the owning table is chosen by asset_type).
    target_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="proposed"
    )
    title: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    proposed_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )


# ---------------------------------------------------------------------------
# W4 governed libraries (migration 0017): the versioned materials-catalog asset
# ---------------------------------------------------------------------------


class MaterialLibraryVersion(Base):
    """A governed materials-library asset — a versioned, effective-dated,
    org-scoped catalog of material prices/definitions (W4 governed libraries,
    slice 3).

    The DB-backed successor to the empty ``RATE_CARD_V0["material_prices"]``
    default (generic material-DB unit prices): an org admin drafts, reviews, and
    PUBLISHES a materials catalog with an effective date, and the costing engine
    overlays the version *effective at the estimate time* onto the base rate
    table's ``material_prices`` so the org's DECLARED lot prices override the
    generic per-kg defaults. Mirrors ``RateCardVersion`` column-for-column.

    ``payload`` is a materials catalog dict shaped exactly as the engine expects:
    ``{"material_prices": {<material>: <usd_per_kg>, ...},
        "materials": {<name>: {"family": ..., "density_g_cm3": ..., ...}}}``.
    ``material_prices`` maps an exact material name (e.g. ``"PA12 (Nylon 12)"``)
    or a class sentinel (``"@polymer"``) to a positive $/kg; ``materials`` is an
    optional bag of material definitions. Only ``material_prices`` is required.

    HONESTY (non-negotiable rules #1/#2): a governed materials catalog is the
    org's DECLARED default prices — NOT measured/negotiated truth. Adopting one
    changes *which* default per-kg numbers an org uses; it never flips a decision
    to ``validated`` (that comes only from real ground-truth residuals, W5).
    Nothing here launders a declared price into a fact.

    Versioning / effective-dating (one non-overlapping timeline per org):
    ``version`` is monotonic per org; publishing a version closes the previously
    open published version's ``effective_to`` so at most one is in effect at a time.
    """

    __tablename__ = "material_library_versions"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "version", name="uq_material_library_versions_org_version"
        ),
        UniqueConstraint("ulid", name="uq_material_library_versions_ulid"),
        Index("ix_material_library_versions_org_status", "org_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ulid: Mapped[str] = mapped_column(
        Text, nullable=False, default=lambda: str(ULID())
    )
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="draft"
    )
    # Materials catalog dict (validated on publish).
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    change_note: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=""
    )
    effective_from: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    effective_to: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
