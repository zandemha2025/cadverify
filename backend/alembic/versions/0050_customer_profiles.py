"""Account profile and durable Notion synchronization markers."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0050_customer_profiles"
down_revision = "0049_trial_checks"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("full_name", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("phone", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("signup_metadata", JSONB(), nullable=False, server_default="{}"))
    op.add_column("users", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("notion_page_id", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("crm_sync_after", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_users_crm_sync_after", "users", ["crm_sync_after"])


def downgrade():
    op.drop_index("ix_users_crm_sync_after", table_name="users")
    for column in ["crm_sync_after", "notion_page_id", "last_seen_at", "signup_metadata", "phone", "full_name"]:
        op.drop_column("users", column)
