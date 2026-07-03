"""Migration smoke tests for 0012_batch_cost.

Mirrors test_migration_0010: no live Postgres here, so the migration is loaded
with ``alembic.op`` mocked and we assert on the DDL calls. Additive + fully
reversible: a ``batches.job_type`` column (server_default 'dfm', so existing rows
stay DFM with no backfill) plus four nullable cost columns and a
``cost_decision_id`` FK+index on ``batch_items``. The real up/down against
Postgres is proven by the scratch-DB run that accompanies this branch.
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
        / "0012_batch_cost.py"
    )
    assert migration_path.exists(), f"Migration file not found: {migration_path}"

    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        original_op = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            mod_name = "migration_0012_test"
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
    assert mod.revision == "0012_batch_cost"
    assert mod.down_revision == "0011_create_ground_truth_records"


def test_upgrade_adds_job_type_and_cost_columns(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.upgrade()

    # (table, column_name) pairs added
    added = [
        (c.args[0], c.args[1].name) for c in mock_op.add_column.call_args_list
    ]
    assert ("batches", "job_type") in added
    for col in ("quantities", "region", "material_class", "shop", "cost_decision_id"):
        assert ("batch_items", col) in added

    # job_type carries a 'dfm' server_default (existing rows need no backfill)
    job_type_col = next(
        c.args[1] for c in mock_op.add_column.call_args_list
        if c.args[0] == "batches" and c.args[1].name == "job_type"
    )
    assert job_type_col.server_default.arg == "dfm"
    assert job_type_col.nullable is False

    # the FK-join index on cost_decision_id
    idx_names = [c.args[0] for c in mock_op.create_index.call_args_list]
    assert "ix_batch_items_cost_decision_id" in idx_names


def test_downgrade_reverses_everything(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.downgrade()

    dropped_cols = [
        (c.args[0], c.args[1]) for c in mock_op.drop_column.call_args_list
    ]
    assert ("batches", "job_type") in dropped_cols
    for col in ("quantities", "region", "material_class", "shop", "cost_decision_id"):
        assert ("batch_items", col) in dropped_cols

    dropped_idx = [
        c.kwargs.get("table_name") or (c.args[0] if c.args else None)
        for c in mock_op.drop_index.call_args_list
    ]
    # index dropped by name (first positional arg)
    idx_first_args = [c.args[0] for c in mock_op.drop_index.call_args_list]
    assert "ix_batch_items_cost_decision_id" in idx_first_args
