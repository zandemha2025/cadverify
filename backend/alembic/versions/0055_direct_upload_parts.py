"""Direct uploads for single parts: a second upload purpose, ``part``.

A browser-to-storage multipart upload so far carried only a batch ZIP
(``batch_zip``). A single CAD file (STEP, IGES or STL, optionally gzipped or in
a one-part ZIP) now uploads the same way, on every plan, and is checked on the
background worker from the stored object. Only the purpose CHECK changes.

Downgrade: a ``part`` row can't exist before 0055. Rather than delete
customer uploads silently, the downgrade refuses while any exist; abort or
let them expire and be swept first.

Revision ID: 0055_direct_upload_parts
Revises: 0054_part_actuals
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0055_direct_upload_parts"
down_revision = "0054_part_actuals"
branch_labels = None
depends_on = None

CONSTRAINT = "ck_direct_uploads_purpose"
TABLE = "direct_uploads"


def upgrade():
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(CONSTRAINT, TABLE, "purpose IN ('batch_zip', 'part')")


def downgrade():
    remaining = op.get_bind().execute(
        sa.text("SELECT count(*) FROM direct_uploads WHERE purpose = 'part'")
    ).scalar()
    if remaining:
        raise RuntimeError(
            f"Cannot downgrade 0055_direct_upload_parts: {remaining} single-part direct "
            "upload row(s) exist (purpose 'part'). Abort them or let the sweep expire "
            "them, then retry; nothing was changed."
        )
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(CONSTRAINT, TABLE, "purpose IN ('batch_zip')")
