"""Schema contract for per-user notification dismissal state."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.db.models import NotificationRead


def _load():
    mock_op = MagicMock()
    mock_op.get_bind.return_value.dialect.name = "postgresql"
    path = (
        Path(__file__).parent.parent
        / "alembic"
        / "versions"
        / "0043_notification_dismissal.py"
    )
    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        old = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            spec = importlib.util.spec_from_file_location("migration_0043_test", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            alembic.op = old
    return module, mock_op


def test_model_exposes_nullable_personal_dismissal_timestamp():
    columns = NotificationRead.__table__.c
    assert columns.dismissed_at.nullable is True
    assert "ix_notification_reads_user_dismissed" in {
        index.name for index in NotificationRead.__table__.indexes
    }


def test_migration_adds_and_removes_notification_dismissal_contract():
    migration, op = _load()
    assert migration.revision == "0043_notification_dismiss"
    assert migration.down_revision == "0042_cost_disposition"
    assert len(migration.revision) <= 32

    migration.upgrade()

    added = op.add_column.call_args.args[1]
    assert op.add_column.call_args.args[0] == "notification_reads"
    assert added.name == "dismissed_at"
    assert added.nullable is True
    op.create_index.assert_called_once_with(
        "ix_notification_reads_user_dismissed",
        "notification_reads",
        ["user_id", "dismissed_at"],
        unique=False,
    )

    migration.downgrade()
    op.drop_index.assert_called_once_with(
        "ix_notification_reads_user_dismissed",
        table_name="notification_reads",
    )
    op.drop_column.assert_called_once_with("notification_reads", "dismissed_at")
