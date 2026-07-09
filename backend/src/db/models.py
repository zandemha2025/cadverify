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

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
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
    saml_group_mappings: Mapped[List[SamlGroupMapping]] = relationship(
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


class SamlGroupMapping(Base):
    """Maps a SAML assertion attribute value to an org-scoped role.

    This is intentionally a JIT assignment rule, not SCIM: on SAML login a
    matching group can grant/promote membership and select the active org, but
    absence from a group does not deprovision or demote a manual admin.
    """

    __tablename__ = "saml_group_mappings"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "attribute_name",
            "group_value",
            name="uq_saml_group_mappings_org_attr_value",
        ),
        CheckConstraint(
            "org_role IN ('viewer','member','admin')",
            name="ck_saml_group_mappings_org_role",
        ),
        Index("ix_saml_group_mappings_org", "org_id"),
        Index("ix_saml_group_mappings_attr_value", "attribute_name", "group_value"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    attribute_name: Mapped[str] = mapped_column(Text, nullable=False)
    group_value: Mapped[str] = mapped_column(Text, nullable=False)
    org_role: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="viewer"
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    organization: Mapped[Organization] = relationship(
        back_populates="saml_group_mappings"
    )


class OrgInvite(Base):
    """A single-use, hashed, expiring invitation to join an org (0024).

    The membership-LIFECYCLE seam on top of 0009's tenancy isolation: an org
    admin issues an invite for an ``email`` + ``role``; the raw token is emailed
    (or returned to the admin) exactly once and NEVER persisted — only its
    SHA-256 ``token_hash`` is stored, so a DB leak cannot be replayed. Accepting
    (an authenticated user presenting the raw token) creates a ``memberships``
    row. Single-use + expiry are enforced by the accept path: an invite is
    redeemable only while ``accepted_at IS NULL AND revoked_at IS NULL AND
    expires_at > now()``. ``role`` is checked to admin/member/viewer (mirrors
    the memberships CHECK) and may never exceed the inviter's own org role.
    """

    __tablename__ = "org_invites"
    __table_args__ = (
        Index("ix_org_invites_token_hash", "token_hash", unique=True),
        Index("ix_org_invites_org", "org_id"),
        Index("ix_org_invites_org_email", "org_id", "email"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="member"
    )
    # SHA-256 hex of the raw token — the raw token is NEVER stored.
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # The account this invite was minted for, resolved by an EXACT ``email_lower``
    # match at creation (the real, unique row identity — never a normalise-
    # collision). Acceptance requires ``accepting.id == invited_user_id``, which
    # defeats BOTH directions of the normalize_email collision. NULLABLE: an
    # invite for an email with no account yet resolves to NULL and acceptance
    # falls back to a collision-safe email check.
    invited_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    accepted_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    accepted_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


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
    # Org-membership beat (§39): account-level deactivation. ``is_active`` is a
    # security control (no feature flag) — false blocks EVERY auth path (login,
    # Google/SAML/magic re-provision, existing sessions, and API keys the user
    # owns). Server-default true so every pre-existing row is active and the
    # platform is byte-identical until an admin (superadmin) deactivates.
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default="true", nullable=False
    )
    deactivated_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    session_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
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
        back_populates="user",
        lazy="selectin",
        foreign_keys="CostDecision.user_id",
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
# P8 (migration 0034): SCIM org-scoped identity lifecycle ledger
# ---------------------------------------------------------------------------


class ScimIdentity(Base):
    """Org-scoped SCIM resource state for IdP-managed users.

    Membership is the access-control truth. This row is the identity-lifecycle
    truth: it persists the SCIM resource after ``active=false`` removes the user's
    org membership, so Okta/Entra-style providers can still read/update the
    inactive resource without granting app access.
    """

    __tablename__ = "scim_identities"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_scim_identities_org_user"),
        UniqueConstraint(
            "org_id", "external_id", name="uq_scim_identities_org_external"
        ),
        CheckConstraint(
            "org_role IN ('viewer','member','admin')",
            name="ck_scim_identities_org_role",
        ),
        Index("ix_scim_identities_org_active", "org_id", "active"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    org_role: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="viewer"
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# P8 (migration 0035): encrypted connector credential profiles
# ---------------------------------------------------------------------------


class ConnectorCredentialProfile(Base):
    """Org-scoped encrypted credentials for sandbox/live connector probes.

    API responses expose only the profile ULID, connector id, label, base URL,
    auth type, fingerprint, and revocation status. The encrypted secret blob is
    used only server-side and must never be serialized.
    """

    __tablename__ = "connector_credential_profiles"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "connector_id",
            "label",
            name="uq_connector_credentials_org_connector_label",
        ),
        Index(
            "ix_connector_credentials_org_connector",
            "org_id",
            "connector_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ulid: Mapped[str] = mapped_column(
        Text, unique=True, nullable=False, default=lambda: str(ULID())
    )
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    connector_id: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    auth_type: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_secret_json: Mapped[str] = mapped_column(Text, nullable=False)
    secret_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


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
    approval_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="unreviewed"
    )
    approved_by_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    approval_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stale_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    stale_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
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
    user: Mapped[User] = relationship(
        back_populates="cost_decisions", foreign_keys=[user_id]
    )


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


class Notification(Base):
    """Durable org inbox row.

    Unlike the older client-derived notification surface, this is a first-class
    workflow row emitted next to the domain mutation that needs attention. Audit
    stays compliance history; notifications are operator workflow state.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_org_status_created", "org_id", "status", "created_at"),
        UniqueConstraint(
            "org_id",
            "kind",
            "source_type",
            "source_id",
            name="uq_notifications_source",
        ),
        Index("ix_notifications_org_kind_source", "org_id", "kind", "source_type", "source_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ulid: Mapped[str] = mapped_column(
        Text, unique=True, nullable=False, default=lambda: str(ULID())
    )
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False, server_default="info")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    audience_role: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    dest: Mapped[str] = mapped_column(Text, nullable=False, server_default="verify")
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )


class NotificationRead(Base):
    """Per-user read marker for a durable org notification."""

    __tablename__ = "notification_reads"
    __table_args__ = (
        UniqueConstraint(
            "notification_id",
            "user_id",
            name="uq_notification_reads_notification_user",
        ),
        Index("ix_notification_reads_user_read", "user_id", "read_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    notification_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    read_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


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
    source_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="actual")
    vendor_quote_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    invoice_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    actual_machine_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    actual_setup_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    actual_labor_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    actual_inspection_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    actual_cycle_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    evidence_sha256: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
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
    # Declared service environment (machine-inventory §6): USER-declared, never
    # inferred. {max_temp_c, min_temp_c, pressure_bar, corrosive, sour_service,
    # medium, standard}. NULL → no environment declared (gate is a no-op).
    service_environment: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


class MachineInstance(Base):
    """One USER-DECLARED owned machine (or identical group) in an org's inventory.

    The machine-inventory model (verification-thesis crux, spec §3): turns the
    process-level owned-equipment seam into a machine-level capability-matching
    surface. One row per owned machine or identical group; ``count`` is capacity
    (N identical machines), never a fit axis. Every makeability check reduces to a
    scalar comparison ``part_requirement ⩿ machine_capability``; the small set of
    universal typed columns is queried/indexed and the per-process-family
    ``capabilities`` JSONB carries the process-appropriate scalars (validated on
    write against a per-family schema in ``machine_inventory_service``).

    HONESTY (non-negotiable, spec §2): every capability here is DECLARED by the
    org — provenance is always ``"user"``, NEVER measured. A machine's
    envelope/rate/material qualification is the org's declaration; a later "fits"
    verdict on the *envelope* is a MEASURED-geometry × USER-capability comparison,
    while tolerance/secondary-op capability is USER-declared, never a measurement
    of the machine. Malformed inputs are reported by the service, never coerced.
    No inventory declared → the platform is byte-identical (this feature is purely
    additive). Org-scoped: cross-tenant isolation on every query.

    Mirrors the ``manifest_parts`` / ``part_contexts`` column style: BigInt PK,
    ULID public id, org_id FK (CASCADE), nullable ``created_by`` (SET NULL so
    history survives a user delete). CRUD + keyset list + CSV import live in the
    service.
    """

    __tablename__ = "machine_instances"
    __table_args__ = (
        Index("ix_machine_instances_org", "org_id"),
        Index("ix_machine_instances_org_process", "org_id", "process"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ulid: Mapped[str] = mapped_column(
        Text, unique=True, nullable=False, default=lambda: str(ULID())
    )
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # Display name, e.g. "Haas VF-2 #3".
    name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # ProcessType.value — which process family (indexed).
    process: Mapped[str] = mapped_column(Text, nullable=False)
    # N identical machines (capacity, NOT a fit axis).
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Universal mass gate: max workpiece mass this machine handles (kg).
    max_workpiece_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # This machine's OWN rate ($/hr) — overrides the rate-card default for cost.
    hourly_rate_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Per-machine sunk-capital fraction [0,1]; NULL → rate-card default.
    capital_frac: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Per-process-family fit-gate scalars (envelope/force/reach/resolution).
    capabilities: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    # Material names/classes QUALIFIED on THIS machine (material-qualification gate).
    materials: Mapped[Optional[List[Any]]] = mapped_column(JSONB, nullable=True)
    # {material: max_mm} (laser/EDM/sheet power×material×thickness gate).
    material_thickness_map: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


class ShopCapabilities(Base):
    """An org's SHOP-LEVEL secondary-op capabilities (spec §3.1).

    Secondary ops are shop-level, NOT per-machine (a foundry has one HIP vessel,
    not one per press). ONE row per org: ``ops`` is a JSONB map
    ``{op: True | {size/temp limits}}`` (heat_treat, stress_relief, hip, sinter,
    grinding, plating, cmm, ct_inspection, …). The matcher consumes this as the
    org's available-secondary-ops set; a part that REQUIRES an op the org lacks is
    a real gap (spec §0).

    HONESTY: every entry is USER-declared (provenance ``"user"``), never inferred.
    No row → the org has declared no secondary ops (byte-identical / no-op).
    Org-scoped, one row per org (unique ``org_id``).
    """

    __tablename__ = "shop_capabilities"
    __table_args__ = (
        UniqueConstraint("org_id", name="uq_shop_capabilities_org"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # {op: True | {size/temp limits}} — the org's available secondary ops.
    ops: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
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
        # Phase D — scaled makeability rollup: GROUP BY (org_id,
        # makeability_bucket) + per-bucket keyset drill-down.
        Index(
            "ix_part_summaries_org_mkbucket",
            "org_id",
            "makeability_bucket",
            text("updated_at DESC"),
            text("mesh_hash DESC"),
        ),
        # Phase D — capability-investment ranking: GROUP BY (org_id,
        # unlock_process, unlock_gate) + per-acquisition drill-down.
        Index(
            "ix_part_summaries_org_unlock",
            "org_id",
            "unlock_process",
            "unlock_gate",
        ),
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

    # ── Phase D — machine-inventory makeability projection (spec §10 Phase D) ──
    # The §0 lattice verdict last computed for this part from the Phase-C
    # verification block on the cost decision (NULL = costed with no declared
    # inventory/env → "not evaluated", never a fabricated verdict).
    makeability_verdict: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # True iff verdict ∈ {makeable_in_house, makeable_with_secondary_op}; NULL when
    # unknown/unevaluated (never fabricated True).
    in_house_makeable: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True
    )
    # The D3 triage bucket (makeable_in_house | makeable_outside |
    # needs_capability | not_makeable | unknown | geometry_invalid) — the single
    # GROUP-BY key for the scaled makeability rollup. Always present.
    makeability_bucket: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="unknown"
    )
    # Set true (in bulk) when the org's machine inventory changes, so a verdict
    # computed against the OLD inventory is never served as fresh; cleared when the
    # part is re-costed against current inventory. Visible in rollups/rankings.
    makeability_stale: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    # ── D4 capability-investment ranking keys (the single primary acquisition
    # that would unlock a currently-blocked part), derived from the REAL stored
    # FitFailure gap data — never invented. ──
    # Process to acquire (outsource_only) or upgrade (not_on_owned).
    unlock_process: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Binding gate for an upgrade (envelope|material|tolerance|axes|...); NULL for
    # a pure acquire (owns none of the process family).
    unlock_gate: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # True when ONE acquisition suffices (single binding gate, or acquire); False
    # when multiple constraints block (no single acquisition unlocks it); NULL when
    # not blocked/applicable.
    unlock_single: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    # The numeric requirement the acquisition must meet for a numeric gate
    # (envelope mm / mass kg / IT grade / axes / thickness / force). NULL for a
    # categorical gate (material) or a pure acquire.
    unlock_need_num: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # The categorical requirement (e.g. the material name to qualify). NULL for a
    # numeric gate or a pure acquire.
    unlock_need_label: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Full per-part gap detail for the D4 drill-down: {kind, process, gate, single,
    # gap:[{gate,axis,need,have,human}, ...]}. NULL when the part is not blocked.
    makeability_gap: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )


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


# ---------------------------------------------------------------------------
# Aramco GAP 3 (migration 0020): declared parts-manifest bulk onboarding
# ---------------------------------------------------------------------------


class ManifestPart(Base):
    """One USER-DECLARED inventory line from a parts-manifest import (Aramco GAP 3).

    A THIRD kind of part identity, distinct from the two we already store: it is
    NOT a ``mesh_hash``-keyed catalog part (that is geometry-derived) and NOT a
    ``ground_truth_records`` cost datum — it is a DECLARED inventory line keyed by
    the customer's own ``part_id``. Aramco's parts live in SAP/PLM; the pilot
    bridge is a manifest upload (CSV exported from SAP/Excel) of part numbers plus
    demand/program/material metadata, usually WITHOUT geometry. This table is that
    registry, so an org can see its inventory ORGANIZED immediately and get an
    honest "how much of it can we even assess (has geometry)" coverage number.

    HONESTY (non-negotiable): every column here is DECLARED by the customer, never
    inferred and never a makeability/cost claim. A declared row never creates an
    analysis / cost decision / part summary, never touches the catalog or triage
    numbers (those stay geometry-derived), and NEVER flips a band to validated.
    Coverage's geometry match is a BEST-EFFORT normalized-stem convention against
    uploaded analyses in the SAME org — an unmatched declared part is honestly
    ``without_geometry``, never fabricated as covered.

    Mirrors the ``part_contexts`` / ``ground_truth_records`` column style: BigInt
    PK, ULID public id, org_id FK (CASCADE), nullable ``created_by`` (SET NULL so
    history survives a user delete). Upsert (last write wins) on
    ``(org_id, part_id)`` lives in the service.
    """

    __tablename__ = "manifest_parts"
    __table_args__ = (
        UniqueConstraint("org_id", "part_id", name="uq_manifest_parts_org_part"),
        Index("ix_manifest_parts_org_program", "org_id", "program"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ulid: Mapped[str] = mapped_column(
        Text, unique=True, nullable=False, default=lambda: str(ULID())
    )
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # The customer's own part number — the declared identity (NOT a mesh_hash).
    part_id: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    material_class: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    program: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parent_assembly: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    units_per_parent: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    annual_volume: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    region: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Customer-context layer Slice 1 (migration 0036): org-scoped shape-signature
# store — the retrieval corpus for part IDENTITY.
# ---------------------------------------------------------------------------


class PartSignature(Base):
    """One org-scoped geometry SIGNATURE + its (optional) DECLARED identity.

    The corpus behind the customer-context identity-retrieval engine (Slice 1).
    Geometry alone can never say "this is a Camry LE door handle" — that identity
    lives in the CUSTOMER's world. So as an org uses CadVerify, each part it sees
    lands here as an 18-dim shape signature (``src.eval.similarity.feature_vector``)
    keyed by ``mesh_hash``, together with whatever declared identity the customer
    gave (their own part number / name / program). On a NEW part we RETRIEVE the
    closest prior signatures IN THE SAME ORG and surface a provenance-tagged,
    user-confirmable identity — retrieval GROUNDS identity in their data; we never
    hallucinate it, and never let a near-miss masquerade as a confident match.

    HONESTY (non-negotiable): the ``signature`` is a MEASURED geometry vector; the
    declared_* fields are USER/file-declared identity, never inferred from the
    mesh. A row is a *suggestion source*, never a verified-identity assertion — the
    retrieval engine always returns a confidence + provenance, and abstains
    (``grounded=False``) below its stated bar rather than fabricate an identity.

    Mirrors the ``part_contexts`` / ``manifest_parts`` column style: BigInt PK,
    org_id FK (CASCADE — a corpus is deleted with its org, so cross-tenant
    isolation holds by construction), ``(org_id, mesh_hash)`` unique. The idempotent
    upsert (last write wins on the latest declared identity) lives in the service.
    """

    __tablename__ = "part_signatures"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "mesh_hash", name="uq_part_signatures_org_mesh"
        ),
        # Retrieval loads the whole org matrix; the org index scopes that scan.
        Index("ix_part_signatures_org", "org_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # sha256 of the normalized mesh — the SAME geometry-part key the catalog /
    # part_context / part_summary stores use (``analysis_service.compute_mesh_hash``).
    mesh_hash: Mapped[str] = mapped_column(Text, nullable=False)
    # The 18-dim MEASURED shape signature (similarity.feature_vector order). Stored
    # as a JSONB float array — pure numpy, zero-egress to compute and to compare.
    signature: Mapped[List[float]] = mapped_column(JSONB, nullable=False)
    # DECLARED identity (nullable — the customer may not have given one yet).
    declared_part_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    declared_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    program: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Where the signature entered the corpus: 'upload' | 'catalog' | 'manifest'.
    source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# P6/P8 (migrations 0030, 0033): connector-run evidence ledger
# ---------------------------------------------------------------------------


class IntegrationRun(Base):
    """One connector/dry-run/import attempt for an org feed.

    The first version was offline CSV only. The expanded ledger preserves that
    boundary and adds promotion-level evidence for sandbox/live connectors so
    simulated SAP/PLM/RFQ proof cannot be mislabeled as a live integration.
    """

    __tablename__ = "integration_runs"
    __table_args__ = (
        Index("ix_integration_runs_org_created", "org_id", "created_at"),
        Index("ix_integration_runs_org_connector", "org_id", "connector_id"),
        Index("ix_integration_runs_org_status", "org_id", "status"),
        Index("ix_integration_runs_org_boundary", "org_id", "boundary_label"),
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
    connector_id: Mapped[str] = mapped_column(Text, nullable=False)
    connector_mode: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="offline_csv"
    )
    boundary_label: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="exported_fixture"
    )
    source_system: Mapped[str] = mapped_column(Text, nullable=False)
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)
    api_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    api_version: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    external_tenant_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    correlation_ids_json: Mapped[Optional[List[str]]] = mapped_column(
        JSONB, nullable=True
    )
    watermark: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mode: Mapped[str] = mapped_column(Text, nullable=False, server_default="dry_run")
    status: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_record_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    normalized_record_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    rows_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    rows_valid: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    rows_invalid: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    imported_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    raw_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    errors_json: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSONB, nullable=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )


# ---------------------------------------------------------------------------
# P5/P6 (migration 0032): RFQ / supplier evidence package ledger
# ---------------------------------------------------------------------------


class RfqPackage(Base):
    """A durable supplier/RFQ evidence package assembled from approved decisions.

    This is an export workflow, not a supplier network. The package snapshots
    selected cost-decision evidence, manifest/context enrichment, and warning
    flags while explicitly recording that raw CAD is not included and no live
    supplier send happened.
    """

    __tablename__ = "rfq_packages"
    __table_args__ = (
        Index("ix_rfq_packages_org_created", "org_id", "created_at"),
        Index("ix_rfq_packages_org_status", "org_id", "status"),
        CheckConstraint(
            "status IN ('generated','archived')",
            name="ck_rfq_packages_status",
        ),
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
    title: Mapped[str] = mapped_column(Text, nullable=False)
    supplier_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="generated"
    )
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    approved_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    stale_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    unvalidated_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    raw_cad_included: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    live_supplier_send: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    items_json: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    warnings_json: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
