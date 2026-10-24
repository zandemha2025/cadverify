"""Schema contract for link uploads (purpose 'link', migration 0058).

The purpose CHECK gains 'link', added NOT VALID and validated afterwards on
PostgreSQL. Downgrade refuses while any link row exists.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import CheckConstraint

from src.db.models import DirectUpload


def _load(link_rows: int = 0, dialect: str = "postgresql"):
    mock_op = MagicMock()
    mock_op.get_bind.return_value.dialect.name = dialect
    mock_op.get_bind.return_value.execute.return_value.scalar.return_value = link_rows
    path = Path(__file__).parent.parent / "alembic" / "versions" / "0058_direct_upload_links.py"
    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        old = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            spec = importlib.util.spec_from_file_location("migration_0058_test", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            alembic.op = old
    return module, mock_op


def _purpose_check() -> str:
    (check,) = [
        c for c in DirectUpload.__table__.constraints
        if isinstance(c, CheckConstraint) and c.name == "ck_direct_uploads_purpose"
    ]
    return str(check.sqltext)


def _sql(op) -> list[str]:
    return [" ".join(str(c.args[0]).split()) for c in op.execute.call_args_list]


def test_model_matches_the_migration():
    migration, _ = _load()
    assert migration.revision == "0058_direct_upload_links"
    assert migration.down_revision == "0057_account_deletion"
    assert len(migration.revision) <= 32
    assert _purpose_check() == migration.PURPOSE_RULE == "purpose IN ('batch_zip', 'part', 'link')"


def test_upgrade_adds_the_check_not_valid_then_validates_it():
    migration, op = _load()
    migration.upgrade()
    assert op.drop_constraint.call_args.args == ("ck_direct_uploads_purpose", "direct_uploads")
    sql = _sql(op)
    add = "ALTER TABLE direct_uploads ADD CONSTRAINT ck_direct_uploads_purpose CHECK (purpose IN ('batch_zip', 'part', 'link')) NOT VALID"
    validate = "ALTER TABLE direct_uploads VALIDATE CONSTRAINT ck_direct_uploads_purpose"
    assert add in sql and validate in sql and sql.index(add) < sql.index(validate)
    assert not op.create_table.called and not op.add_column.called


def test_other_dialects_create_the_check_directly():
    migration, op = _load(dialect="sqlite")
    migration.upgrade()
    assert op.create_check_constraint.call_args.args == (
        "ck_direct_uploads_purpose", "direct_uploads", "purpose IN ('batch_zip', 'part', 'link')",
    )


def test_downgrade_restores_the_part_check_when_no_link_rows():
    migration, op = _load(link_rows=0)
    migration.downgrade()
    assert "ALTER TABLE direct_uploads ADD CONSTRAINT ck_direct_uploads_purpose CHECK (purpose IN ('batch_zip', 'part')) NOT VALID" in _sql(op)


def test_downgrade_refuses_while_link_uploads_exist():
    migration, op = _load(link_rows=2)
    with pytest.raises(RuntimeError, match="2 link direct upload"):
        migration.downgrade()
    assert not op.drop_constraint.called
    assert not op.create_check_constraint.called
    assert not any("ALTER TABLE" in s for s in _sql(op))
