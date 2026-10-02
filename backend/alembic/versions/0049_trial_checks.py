"""Durable lifetime check reservations, including prior completed work."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

revision = "0049_trial_checks"
down_revision = "0048_disposition_basis"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "trial_checks",
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("check_id", sa.Text(), primary_key=True),
        sa.Column("file_hash", sa.Text(), nullable=False),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("operations", JSONB(), nullable=False),
    )
    # Preserve lifetime usage. A cost decision linked to the same uploaded part
    # as an analysis belongs to that prior check, rather than charging it twice.
    op.execute("""
        INSERT INTO trial_checks (user_id, check_id, file_hash, created_at, completed, operations)
        SELECT user_id, 'legacy-analysis-' || id, mesh_hash, created_at, true, '{}'::jsonb FROM analyses
    """)
    op.execute("""
        INSERT INTO trial_checks (user_id, check_id, file_hash, created_at, completed, operations)
        SELECT c.user_id, 'legacy-cost-' || c.id, c.mesh_hash, c.created_at, true, '{}'::jsonb
        FROM cost_decisions c WHERE NOT EXISTS (
            SELECT 1 FROM analyses a WHERE a.user_id = c.user_id AND a.mesh_hash = c.mesh_hash
        )
    """)


def downgrade():
    op.drop_table("trial_checks")
