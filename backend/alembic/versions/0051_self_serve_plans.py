"""Self-serve plans: email-tier allowances, Pro billing, verified phones.

Existing accounts keep their original 10-check grant (a work-email account
gets the larger work tier). New accounts derive the grant from their email
domain at check time.

Revision ID: 0051_self_serve_plans
Revises: 0050_customer_profiles
Create Date: 2026-10-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP

revision = "0051_self_serve_plans"
down_revision = "0050_customer_profiles"
branch_labels = None
depends_on = None


def _timeouts() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5000'")
        op.execute("SET LOCAL statement_timeout = '30000'")


def upgrade():
    _timeouts()
    op.add_column("users", sa.Column("free_check_grant", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("verified_phone", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("phone_verified_at", TIMESTAMP(timezone=True), nullable=True))
    op.create_index(
        "uq_users_verified_phone", "users", ["verified_phone"], unique=True,
        postgresql_where=sa.text("verified_phone IS NOT NULL"),
    )
    # Grandfather every account that exists before tiers ship.
    op.execute("UPDATE users SET free_check_grant = 10")
    op.create_table(
        "billing_accounts",
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("stripe_customer_id", sa.Text(), nullable=False, unique=True),
        sa.Column("stripe_subscription_id", sa.Text(), nullable=True, unique=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="none"),
        sa.Column("current_period_start", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("current_period_end", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "billing_events",
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("received_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    _timeouts()
    op.drop_table("billing_events")
    op.drop_table("billing_accounts")
    # A Pro plan has no meaning without its billing row.
    op.execute("UPDATE users SET plan = 'trial' WHERE plan = 'pro'")
    op.drop_index("uq_users_verified_phone", table_name="users")
    op.drop_column("users", "phone_verified_at")
    op.drop_column("users", "verified_phone")
    op.drop_column("users", "free_check_grant")
