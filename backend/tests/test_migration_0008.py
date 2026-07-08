"""Migration smoke tests for 0008_create_cost_decisions.

Mirrors test_migration_0002: no live Postgres in CI, so we load the migration
with alembic.op mocked and assert on the calls made during upgrade/downgrade.
"""
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
        / "0008_create_cost_decisions.py"
    )
    assert migration_path.exists(), f"Migration file not found: {migration_path}"

    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        original_op = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            mod_name = "migration_0008_test"
            sys.modules.pop(mod_name, None)
            spec = importlib.util.spec_from_file_location(
                mod_name, str(migration_path)
            )
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
    assert mod.revision == "0008_create_cost_decisions"
    assert mod.down_revision == "0007"


def test_upgrade_creates_cost_decisions(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.upgrade()

    tables = [c.args[0] for c in mock_op.create_table.call_args_list]
    assert "cost_decisions" in tables


def test_upgrade_columns_present(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.upgrade()

    call = next(
        c for c in mock_op.create_table.call_args_list if c.args[0] == "cost_decisions"
    )
    cols = [a.name for a in call.args[1:] if hasattr(a, "name")]
    for required in [
        "id",
        "ulid",
        "user_id",
        "mesh_hash",
        "params_hash",
        "engine_version",
        "filename",
        "file_type",
        "result_json",
        "make_now_process",
        "crossover_qty",
        "quantities",
        "label",
        "is_public",
        "share_short_id",
        "created_at",
    ]:
        assert required in cols, f"Missing column: {required}"


def test_upgrade_creates_dedup_and_share_indexes(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.upgrade()

    execute_calls = " ".join(str(c) for c in mock_op.execute.call_args_list)
    assert "uq_cost_decisions_dedup" in execute_calls
    assert "ix_cost_decisions_share" in execute_calls
    assert "share_short_id IS NOT NULL" in execute_calls


def test_downgrade_drops_cost_decisions(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.downgrade()

    dropped = [c.args[0] for c in mock_op.drop_table.call_args_list]
    assert "cost_decisions" in dropped
    # Never drops parent tables
    assert "users" not in dropped
    assert "analyses" not in dropped


def test_re_upgrade_idempotent(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.downgrade()
    mock_op.create_table.reset_mock()
    mod.upgrade()
    tables = [c.args[0] for c in mock_op.create_table.call_args_list]
    assert "cost_decisions" in tables
