"""ORM mapped classes for all database tables.

Tables:
  - users              (Phase 2, migration 0001)
  - api_keys           (Phase 2, migration 0001)
  - analyses           (Phase 3, migration 0002)
  - jobs               (Phase 3, migration 0002 -- schema only, populated in Phase 7)
  - usage_events       (Phase 3, migration 0002)
  - batches            (Phase 9, migration 0004)
  - batch_items        (Phase 9, migration 0004)
  - webhook_deliveries (Phase 9, migration 0004)
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
# Phase 2 tables (mirror 0001 migration)
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

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

    # relationships
    api_keys: Mapped[List[ApiKey]] = relationship(back_populates="user", lazy="selectin")
    analyses: Mapped[List[Analysis]] = relationship(back_populates="user", lazy="selectin")
    batches: Mapped[List[Batch]] = relationship(back_populates="user", lazy="selectin")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
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


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ulid: Mapped[str] = mapped_column(
        Text, unique=True, nullable=False, default=lambda: str(ULID())
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
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
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
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
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ulid: Mapped[str] = mapped_column(
        Text, unique=True, nullable=False, default=lambda: str(ULID())
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    api_key_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="pending"
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
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ulid: Mapped[str] = mapped_column(
        Text, unique=True, nullable=False, default=lambda: str(ULID())
    )
    batch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("batches.id", ondelete="CASCADE"), nullable=False
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
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("batches.id", ondelete="CASCADE"), nullable=False
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
