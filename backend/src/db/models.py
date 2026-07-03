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
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
