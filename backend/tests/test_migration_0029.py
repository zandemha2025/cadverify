"""Migration smoke tests for 0029_notifications_inbox."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _load_migration_with_mock_op():
    mock_op = MagicMock()
    migration_path = (
        Path(__file__).parent.parent
        / "alembic"
        / "versions"
        / "0029_notifications_inbox.py"
    )
    assert migration_path.exists(), f"Migration file not found: {migration_path}"

    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        original_op = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            mod_name = "migration_0029_test"
            sys.modules.pop(mod_name, None)
            spec = importlib.util.spec_from_file_location(mod_name, str(migration_path))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        finally:
            if original_op is None:
                try:
                    delattr(alembic, "op")
                except AttributeError:
                    pass
            else:
                alembic.op = original_op

    return mod, mock_op


@pytest.fixture
def migration_and_op():
    return _load_migration_with_mock_op()


def test_revision_chain(migration_and_op):
    mod, _ = migration_and_op
    assert mod.revision == "0029_notifications_inbox"
    assert mod.down_revision == "0028_user_session_version"
    assert len(mod.revision) <= 32


def test_upgrade_creates_notification_tables_and_indexes(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.upgrade()

    created_tables = [c.args[0] for c in mock_op.create_table.call_args_list]
    assert created_tables == ["notifications", "notification_reads"]

    created_indexes = {c.args[0] for c in mock_op.create_index.call_args_list}
    assert "ix_notifications_org_status_created" in created_indexes
    assert "ix_notifications_org_kind_source" in created_indexes
    assert "ix_notification_reads_user_read" in created_indexes


def test_downgrade_drops_notification_tables(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.downgrade()

    dropped_tables = [c.args[0] for c in mock_op.drop_table.call_args_list]
    assert dropped_tables == ["notification_reads", "notifications"]
