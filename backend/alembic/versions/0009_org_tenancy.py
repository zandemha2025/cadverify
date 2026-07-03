"""add org tenancy: organizations/teams/memberships + org_id on ten user-scoped tables

Three-phase, additive (W1 step 1):
  (1) create org tables + add NULLABLE org_id columns to the ten user-scoped
      tables (``users`` gets ``current_org_id``);
  (2) backfill: per existing user create a personal org + an admin membership,
      point ``users.current_org_id`` at it, and stamp ``org_id`` on every one of
      their rows. ``batch_items`` / ``webhook_deliveries`` derive their org from
      the parent batch via ``batch_id``; ``audit_log`` rows with a NULL user_id
      (system events) are legitimately left NULL;
  (3) set NOT NULL on the eight pure data tables, add all FK constraints, and
      create the org_id indexes (composite ``(org_id, user_id)`` on the four hot
      tables, single-column elsewhere).

Downgrade reverses cleanly (drop indexes -> drop FKs -> drop columns -> drop
tables), leaving the pre-0009 schema byte-equivalent. Proven up -> down -> up on
real Postgres with seeded multi-user data.

Revision ID: 0009_org_tenancy
Revises: 0008_create_cost_decisions
Create Date: 2026-07-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from ulid import ULID

from src.auth.org_context import personal_org_name, personal_org_slug

revision = "0009_org_tenancy"
down_revision = "0008_create_cost_decisions"
branch_labels = None
depends_on = None

# The eight pure data tables whose org_id becomes NOT NULL after backfill.
_NOT_NULL_ORG_TABLES = [
    "api_keys",
    "analyses",
    "cost_decisions",
    "jobs",
    "usage_events",
    "batches",
    "batch_items",
    "webhook_deliveries",
]
# Tables whose org_id is derived directly from their own user_id column.
_USER_OWNED_TABLES = [
    "api_keys",
    "analyses",
    "cost_decisions",
    "jobs",
    "usage_events",
    "batches",
]
# (index_name, table, columns) — composite for the four hot tables, single else.
_ORG_INDEXES = [
    ("ix_analyses_org_user", "analyses", ["org_id", "user_id"]),
    ("ix_cost_decisions_org_user", "cost_decisions", ["org_id", "user_id"]),
    ("ix_batches_org_user", "batches", ["org_id", "user_id"]),
    ("ix_jobs_org_user", "jobs", ["org_id", "user_id"]),
    ("ix_api_keys_org_id", "api_keys", ["org_id"]),
    ("ix_usage_events_org_id", "usage_events", ["org_id"]),
    ("ix_batch_items_org_id", "batch_items", ["org_id"]),
    ("ix_webhook_deliveries_org_id", "webhook_deliveries", ["org_id"]),
    ("ix_audit_log_org_id", "audit_log", ["org_id"]),
]


def upgrade() -> None:
    op.execute("SET statement_timeout = '30000'")
    conn = op.get_bind()

    # ---- Phase 1: new tables + nullable org_id columns ----------------------
    op.create_table(
        "organizations",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("slug", sa.Text, nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "teams",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column(
            "org_id",
            sa.Text,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_teams_org_id", "teams", ["org_id"])
    op.create_table(
        "memberships",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column(
            "org_id",
            sa.Text,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("org_role", sa.Text, nullable=False, server_default="member"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_memberships_org_role",
        "memberships",
        "org_role IN ('admin', 'member', 'viewer')",
    )
    op.execute(
        "ALTER TABLE memberships ADD CONSTRAINT uq_memberships_org_user "
        "UNIQUE (org_id, user_id)"
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    op.create_index("ix_memberships_org_id", "memberships", ["org_id"])

    # nullable org_id on the ten user-scoped tables (users -> current_org_id)
    op.add_column("users", sa.Column("current_org_id", sa.Text, nullable=True))
    for tbl in _NOT_NULL_ORG_TABLES + ["audit_log"]:
        op.add_column(tbl, sa.Column("org_id", sa.Text, nullable=True))

    # ---- Phase 2: backfill --------------------------------------------------
    users = conn.execute(
        sa.text("SELECT id, email FROM users ORDER BY id")
    ).fetchall()
    for uid, email in users:
        org_id = str(ULID())
        conn.execute(
            sa.text(
                "INSERT INTO organizations (id, name, slug, created_at) "
                "VALUES (:id, :n, :s, now())"
            ),
            {"id": org_id, "n": personal_org_name(email), "s": personal_org_slug(email)},
        )
        conn.execute(
            sa.text(
                "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
                "VALUES (:id, :o, :u, 'admin', now())"
            ),
            {"id": str(ULID()), "o": org_id, "u": uid},
        )
        conn.execute(
            sa.text("UPDATE users SET current_org_id = :o WHERE id = :u"),
            {"o": org_id, "u": uid},
        )
        for tbl in _USER_OWNED_TABLES:
            conn.execute(
                sa.text(
                    f"UPDATE {tbl} SET org_id = :o "
                    "WHERE user_id = :u AND org_id IS NULL"
                ),
                {"o": org_id, "u": uid},
            )
        # audit_log rows with a NULL user_id (system events) stay NULL.
        conn.execute(
            sa.text(
                "UPDATE audit_log SET org_id = :o "
                "WHERE user_id = :u AND org_id IS NULL"
            ),
            {"o": org_id, "u": uid},
        )

    # child tables inherit org from their parent batch
    conn.execute(
        sa.text(
            "UPDATE batch_items bi SET org_id = b.org_id "
            "FROM batches b WHERE bi.batch_id = b.id AND bi.org_id IS NULL"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE webhook_deliveries wd SET org_id = b.org_id "
            "FROM batches b WHERE wd.batch_id = b.id AND wd.org_id IS NULL"
        )
    )

    # ---- Phase 3: NOT NULL + FK constraints + indexes -----------------------
    # users.current_org_id stays NULLABLE (bootstrap pointer); just add its FK.
    op.create_foreign_key(
        "fk_users_current_org",
        "users",
        "organizations",
        ["current_org_id"],
        ["id"],
        ondelete="SET NULL",
    )
    for tbl in _NOT_NULL_ORG_TABLES:
        op.alter_column(tbl, "org_id", existing_type=sa.Text, nullable=False)
        op.create_foreign_key(
            f"fk_{tbl}_org",
            tbl,
            "organizations",
            ["org_id"],
            ["id"],
            ondelete="CASCADE",
        )
    # audit_log.org_id stays NULLABLE; FK is SET NULL so history survives.
    op.create_foreign_key(
        "fk_audit_log_org",
        "audit_log",
        "organizations",
        ["org_id"],
        ["id"],
        ondelete="SET NULL",
    )
    for idx_name, tbl, cols in _ORG_INDEXES:
        op.create_index(idx_name, tbl, cols)


def downgrade() -> None:
    op.execute("SET statement_timeout = '30000'")

    for idx_name, tbl, _cols in _ORG_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {idx_name}")

    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS fk_users_current_org")
    op.execute("ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS fk_audit_log_org")
    for tbl in _NOT_NULL_ORG_TABLES:
        op.execute(f"ALTER TABLE {tbl} DROP CONSTRAINT IF EXISTS fk_{tbl}_org")

    op.drop_column("users", "current_org_id")
    for tbl in _NOT_NULL_ORG_TABLES + ["audit_log"]:
        op.drop_column(tbl, "org_id")

    op.drop_index("ix_memberships_org_id", table_name="memberships")
    op.drop_index("ix_memberships_user_id", table_name="memberships")
    op.drop_table("memberships")
    op.drop_index("ix_teams_org_id", table_name="teams")
    op.drop_table("teams")
    op.drop_table("organizations")
