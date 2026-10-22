"""Schema contract for single-part direct uploads (purpose 'part', migration 0055)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import CheckConstraint

from src.db.models import DirectUpload


def _load(part_rows: int = 0):
    mock_op = MagicMock()
    mock_op.get_bind.return_value.execute.return_value.scalar.return_value = part_rows
    path = Path(__file__).parent.parent / "alembic" / "versions" / "0055_direct_upload_parts.py"
    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        old = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            spec = importlib.util.spec_from_file_location("migration_0055_test", path)
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


def test_model_allows_both_purposes():
    assert _purpose_check() == "purpose IN ('batch_zip', 'part')"


def test_upgrade_recreates_only_the_purpose_check():
    migration, op = _load()
    assert migration.revision == "0055_direct_upload_parts"
    assert migration.down_revision == "0054_part_actuals"
    assert len(migration.revision) <= 32

    migration.upgrade()
    assert op.drop_constraint.call_args.args == ("ck_direct_uploads_purpose", "direct_uploads")
    assert op.drop_constraint.call_args.kwargs == {"type_": "check"}
    assert op.create_check_constraint.call_args.args == (
        "ck_direct_uploads_purpose", "direct_uploads", "purpose IN ('batch_zip', 'part')",
    )
    assert _purpose_check() == op.create_check_constraint.call_args.args[2]
    assert not op.create_table.called and not op.add_column.called


def test_downgrade_restores_the_batch_only_check_when_no_part_rows():
    migration, op = _load(part_rows=0)
    migration.downgrade()
    assert op.create_check_constraint.call_args.args == (
        "ck_direct_uploads_purpose", "direct_uploads", "purpose IN ('batch_zip')",
    )


def test_downgrade_refuses_while_part_uploads_exist():
    migration, op = _load(part_rows=3)
    with pytest.raises(RuntimeError, match="3 single-part direct upload"):
        migration.downgrade()
    # Nothing was changed: no rows deleted, no constraint touched.
    assert not op.drop_constraint.called
    assert not op.create_check_constraint.called
    assert not op.execute.called
