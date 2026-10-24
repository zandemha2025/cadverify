"""Two-step sign-in: authenticator-app secrets, recovery codes, an org rule.

- ``user_two_step``: one row per account that has started or finished setting
  up two-step sign-in. ``secret_sealed`` / ``pending_secret_sealed`` hold the
  TOTP secret sealed with the connector-credential Fernet key
  (``fernet:v1:`` prefix), never in plain text. ``last_used_step`` stops a code
  being used twice; ``failed_attempts`` and ``locked_until`` limit guessing.
- ``user_two_step_recovery_codes``: ten single-use codes per account, stored
  as HMAC-SHA256 hex digests (never the codes), ``used_at`` once spent.
- ``organizations.require_two_step``: an admin's rule that members sign in
  with a code (organization single sign-on is exempt).

Both tables cascade with the user row. Additive: no existing row changes
meaning (every organization starts with the rule off, every account with
two-step off). Downgrade drops the tables and the column; any two-step setup
is then gone and accounts sign in with a password or email link alone.

Revision ID: 0062_two_step_sign_in
Revises: 0061_api_key_scope
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0062_two_step_sign_in"
down_revision = "0061_api_key_scope"
branch_labels = None
depends_on = None

SECRETS = "user_two_step"
CODES = "user_two_step_recovery_codes"
ORGS = "organizations"
RULE = "require_two_step"


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5000'")
    op.create_table(
        SECRETS,
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("secret_sealed", sa.Text(), nullable=True),
        sa.Column("enabled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("pending_secret_sealed", sa.Text(), nullable=True),
        sa.Column("pending_created_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_used_step", sa.BigInteger(), nullable=True),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("locked_until", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "secret_sealed IS NULL OR secret_sealed LIKE 'fernet:v1:%'", name="ck_user_two_step_secret_sealed"
        ),
        sa.CheckConstraint(
            "pending_secret_sealed IS NULL OR pending_secret_sealed LIKE 'fernet:v1:%'",
            name="ck_user_two_step_pending_sealed",
        ),
        sa.CheckConstraint(
            "(enabled_at IS NULL) = (secret_sealed IS NULL)", name="ck_user_two_step_enabled_has_secret"
        ),
    )
    op.create_table(
        CODES,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "code_hash", name="uq_two_step_recovery_user_hash"),
    )
    op.add_column(ORGS, sa.Column(RULE, sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade():
    op.drop_column(ORGS, RULE)
    op.drop_table(CODES)
    op.drop_table(SECRETS)
