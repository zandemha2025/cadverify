"""Migration safety tests for 0038_pilot_request_receipts."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa


def _load_migration_with_mock_op():
    mock_op = MagicMock()
    mock_op.get_bind.return_value.dialect.name = "postgresql"
    migration_path = (
        Path(__file__).parent.parent
        / "alembic"
        / "versions"
        / "0038_pilot_request_receipts.py"
    )
    assert migration_path.exists(), f"Migration file not found: {migration_path}"

    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        original_op = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            mod_name = "migration_0038_test"
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
    assert mod.revision == "0038_pilot_receipts"
    assert mod.down_revision == "0037_bom_edges"
    assert len(mod.revision) <= 32


def test_upgrade_reclassifies_duplicates_before_unique_index(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.upgrade()

    operations = [call[0] for call in mock_op.method_calls]
    assert operations[-1] == "create_index"
    sql = "\n".join(str(call.args[0]) for call in mock_op.execute.call_args_list)
    assert "LOCK TABLE audit_log IN SHARE MODE" in sql
    assert "row_number() OVER" in sql
    assert "pilot.requested.duplicate" in sql
    create = mock_op.create_index.call_args
    assert create.args[:3] == (
        "uq_audit_log_pilot_request_receipt",
        "audit_log",
        ["resource_id"],
    )
    assert create.kwargs["unique"] is True


def test_upgrade_uses_portable_sql_without_postgres_locks_on_sqlite(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    mock_op.get_bind.return_value.dialect.name = "sqlite"
    alembic.op = mock_op
    mod.upgrade()

    sql = "\n".join(str(call.args[0]) for call in mock_op.execute.call_args_list)
    assert "SET LOCAL" not in sql
    assert "LOCK TABLE" not in sql
    assert "ranked_pilot_receipts" in sql
    mock_op.create_index.assert_called_once()


def test_duplicate_reclassification_executes_on_sqlite(migration_and_op):
    mod, _ = migration_and_op
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE audit_log ("
                "id INTEGER PRIMARY KEY, action TEXT NOT NULL, resource_id TEXT)"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO audit_log (id, action, resource_id) VALUES "
                "(1, 'pilot.requested', 'same'), "
                "(2, 'pilot.requested', 'same'), "
                "(3, 'pilot.requested', 'other')"
            )
        )
        conn.execute(mod._RECLASSIFY_DUPLICATES)
        rows = conn.execute(
            sa.text("SELECT id, action FROM audit_log ORDER BY id")
        ).all()

    assert rows == [
        (1, "pilot.requested"),
        (2, "pilot.requested.duplicate"),
        (3, "pilot.requested"),
    ]


def test_downgrade_drops_index_then_restores_legacy_actions(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.downgrade()

    operations = [call[0] for call in mock_op.method_calls]
    assert operations[-2:] == ["drop_index", "execute"]
    restore_sql = str(mock_op.execute.call_args.args[0])
    assert "pilot.requested.duplicate" in restore_sql
