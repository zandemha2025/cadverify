"""Part specs, who may sign off, and per-user settings.

Three additive, nullable (or defaulted) columns. Nothing existing is rewritten:

* ``part_contexts.part_specs`` (JSONB, NULL): the specs a user declared for the
  part, stored with its other declared context. Surface finish (named finishes
  and a roughness Ra), heat treatment, inspection level, and the certifications
  whoever makes it must hold (with the NADCAP special processes). NULL means
  nothing was declared, so every existing row reads exactly as before.
* ``organizations.signoff_role`` (TEXT, NULL): the organization role allowed to
  sign off a recorded make-or-buy decision, ``member`` or ``admin``. NULL keeps
  today's rule: anyone who can record an outcome can sign it off.
* ``users.preferences`` (JSONB, NOT NULL, default ``{}``): per-user settings
  that follow the person across devices, first ``{"length_unit": "mm"|"in"}``.

Sign-off reuses ``cost_decisions.approved_by_user_id / approved_at /
approval_note``; staleness reuses ``stale_at / stale_reason``.

Downgrade drops the three columns (and the role CHECK). The declared specs,
the sign-off role setting and user settings are lost on downgrade; recorded
sign-offs are not touched.

Revision ID: 0056_part_specs_signoff
Revises: 0055_direct_upload_parts
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0056_part_specs_signoff"
down_revision = "0055_direct_upload_parts"
branch_labels = None
depends_on = None

SIGNOFF_CHECK = "ck_organizations_signoff_role"
SIGNOFF_RULE = "signoff_role IS NULL OR signoff_role IN ('member', 'admin')"


def _timeouts() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5000'")
        op.execute("SET LOCAL statement_timeout = '60000'")


def upgrade():
    _timeouts()
    op.add_column("part_contexts", sa.Column("part_specs", JSONB(), nullable=True))
    op.add_column("organizations", sa.Column("signoff_role", sa.Text(), nullable=True))
    op.create_check_constraint(SIGNOFF_CHECK, "organizations", SIGNOFF_RULE)
    op.add_column(
        "users",
        sa.Column("preferences", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade():
    _timeouts()
    op.drop_column("users", "preferences")
    op.drop_constraint(SIGNOFF_CHECK, "organizations", type_="check")
    op.drop_column("organizations", "signoff_role")
    op.drop_column("part_contexts", "part_specs")
