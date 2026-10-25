"""Direct uploads fetched from a share link: a third upload purpose, ``link``.

``POST /api/v1/uploads/from-link`` takes a share link to one CAD file (Google
Drive, Dropbox, OneDrive/SharePoint, an S3 object URL). Its ``direct_uploads``
row reserves the organization's upload admission like any upload, and the
worker fetches the bytes and checks them (``src.services.link_import``). Only
the purpose CHECK changes; it is added ``NOT VALID`` and validated afterwards,
so the table isn't locked against writes while existing rows are checked.

Downgrade: a ``link`` row can't exist before 0058. Rather than delete customer
uploads silently, the downgrade refuses while any exist; let their checks
finish and the sweep clean them first.

Revision ID: 0058_direct_upload_links
Revises: 0057_account_deletion
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0058_direct_upload_links"
down_revision = "0057_account_deletion"
branch_labels = None
depends_on = None

CONSTRAINT = "ck_direct_uploads_purpose"
TABLE = "direct_uploads"
PURPOSE_RULE = "purpose IN ('batch_zip', 'part', 'link')"
OLD_PURPOSE_RULE = "purpose IN ('batch_zip', 'part')"


def _pg() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _purpose_check(rule: str) -> None:
    if _pg():
        op.execute("SET LOCAL lock_timeout = '5000'")
        op.execute("SET LOCAL statement_timeout = '60000'")
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    if _pg():
        op.execute(f"ALTER TABLE {TABLE} ADD CONSTRAINT {CONSTRAINT} CHECK ({rule}) NOT VALID")
        op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {CONSTRAINT}")
    else:
        op.create_check_constraint(CONSTRAINT, TABLE, rule)


def upgrade():
    _purpose_check(PURPOSE_RULE)


def downgrade():
    remaining = op.get_bind().execute(
        sa.text("SELECT count(*) FROM direct_uploads WHERE purpose = 'link'")
    ).scalar()
    if remaining:
        raise RuntimeError(
            f"Cannot downgrade 0058_direct_upload_links: {remaining} link direct "
            "upload row(s) exist (purpose 'link'). Let their checks finish and the "
            "sweep clean them, then retry; nothing was changed."
        )
    _purpose_check(OLD_PURPOSE_RULE)
