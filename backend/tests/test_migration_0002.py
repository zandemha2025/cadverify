"""Migration smoke tests for 0002_create_analyses_jobs_usage_events.

Since no live Postgres is available in CI, these tests verify the migration
file's structure, table definitions, and upgrade/downgrade functions by
mocking alembic.op and inspecting the calls made during upgrade/downgrade.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers: load migration with mocked alembic.op
# ---------------------------------------------------------------------------

def _load_migration_with_mock_op():
    """Load the 0002 migration module with alembic.op replaced by a MagicMock.

    Returns (module, mock_op) tuple.
    """
    mock_op = MagicMock()

    migration_path = (
        Path(__file__).parent.parent
        / "alembic"
        / "versions"
        / "0002_create_analyses_jobs_usage_events.py"
    )
    assert migration_path.exists(), f"Migration file not found: {migration_path}"

    # Patch alembic.op before importing the migration
    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        # Also ensure `from alembic import op` resolves by making alembic a real
        # module with `op` as an attribute
        import alembic
        original_op = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            # Remove cached module if re-running
            mod_name = "migration_0002_test"
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
    """Fixture returning (migration_module, fresh_mock_op)."""
    mod, mock_op = _load_migration_with_mock_op()
    return mod, mock_op


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_upgrade_creates_tables(migration_and_op):
    """upgrade() calls create_table for analyses, jobs, usage_events."""
    mod, mock_op = migration_and_op
    import alembic
    alembic.op = mock_op

    mod.upgrade()

    table_names = [c.args[0] for c in mock_op.create_table.call_args_list]
    assert "analyses" in table_names
    assert "jobs" in table_names
    assert "usage_events" in table_names


def test_downgrade_removes_phase3_tables(migration_and_op):
    """downgrade() drops analyses, jobs, usage_events but not users/api_keys."""
    mod, mock_op = migration_and_op
    import alembic
    alembic.op = mock_op

    mod.downgrade()

    dropped = [c.args[0] for c in mock_op.drop_table.call_args_list]
    assert "analyses" in dropped
    assert "jobs" in dropped
    assert "usage_events" in dropped
    assert "users" not in dropped
    assert "api_keys" not in dropped


def test_re_upgrade_idempotent(migration_and_op):
    """upgrade() can be called after downgrade() without error."""
    mod, mock_op = migration_and_op
    import alembic
    alembic.op = mock_op

    mod.downgrade()
    mock_op.create_table.reset_mock()
    mod.upgrade()

    table_names = [c.args[0] for c in mock_op.create_table.call_args_list]
    assert "analyses" in table_names
    assert "jobs" in table_names
    assert "usage_events" in table_names


def test_dedup_index_exists(migration_and_op):
    """upgrade() creates the uq_analyses_dedup unique constraint."""
    mod, mock_op = migration_and_op
    import alembic
    alembic.op = mock_op

    mod.upgrade()

    execute_calls = [str(c) for c in mock_op.execute.call_args_list]
    dedup_calls = [c for c in execute_calls if "uq_analyses_dedup" in c]
    assert len(dedup_calls) >= 1, (
        f"Expected uq_analyses_dedup constraint, got: {execute_calls}"
    )


def test_analyses_columns_correct(migration_and_op):
    """upgrade() creates analyses table with all required columns."""
    mod, mock_op = migration_and_op
    import alembic
    alembic.op = mock_op

    mod.upgrade()

    analyses_call = None
    for c in mock_op.create_table.call_args_list:
        if c.args[0] == "analyses":
            analyses_call = c
            break

    assert analyses_call is not None, "analyses table not created"

    column_names = []
    for arg in analyses_call.args[1:]:
        if hasattr(arg, "name"):
            column_names.append(arg.name)

    required_columns = [
        "id", "ulid", "user_id", "mesh_hash", "process_set_hash",
        "analysis_version", "filename", "file_type", "file_size_bytes",
        "result_json", "verdict", "face_count", "duration_ms",
    ]
    for col in required_columns:
        assert col in column_names, f"Missing column: {col}"


def test_migration_revision_chain(migration_and_op):
    """Migration 0002 correctly references 0001 as its down_revision."""
    mod, _ = migration_and_op
    assert mod.revision == "0002_create_analyses_jobs_usage_events"
    assert mod.down_revision == "0001_create_users_api_keys"
