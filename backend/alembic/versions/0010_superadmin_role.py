"""widen users.role CHECK to admit the platform 'superadmin' tier

W1 step 2 (org-scoped RBAC), purely additive: the only schema delta is
replacing the ``ck_users_role`` CHECK constraint added in 0005 so that
``users.role`` may also be ``'superadmin'`` (platform staff who transcend org
boundaries). No column, table, index, or default changes — every pre-existing
row (viewer/analyst/admin) still satisfies the widened constraint, so the
upgrade never rewrites or rejects data.

Downgrade narrows the CHECK back to the original three-value set. That reversal
will (correctly) fail if any row has been promoted to ``'superadmin'`` — you
cannot downgrade past live platform staff without first demoting them; this is
the intended safety property, not a bug.

Revision ID: 0010_superadmin_role
Revises: 0009_org_tenancy
Create Date: 2026-07-03
"""
from __future__ import annotations

from alembic import op

revision = "0010_superadmin_role"
down_revision = "0009_org_tenancy"
branch_labels = None
depends_on = None

_CK = "ck_users_role"
_ROLES_WITH_SUPERADMIN = "role IN ('viewer', 'analyst', 'admin', 'superadmin')"
_ROLES_ORIGINAL = "role IN ('viewer', 'analyst', 'admin')"


def upgrade() -> None:
    op.drop_constraint(_CK, "users", type_="check")
    op.create_check_constraint(_CK, "users", _ROLES_WITH_SUPERADMIN)


def downgrade() -> None:
    op.drop_constraint(_CK, "users", type_="check")
    op.create_check_constraint(_CK, "users", _ROLES_ORIGINAL)
