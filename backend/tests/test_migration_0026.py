"""Migration smoke tests for 0026_gt_actuals_metadata.

No live Postgres here: load the migration with ``alembic.op`` mocked and assert
the DDL is additive, nullable/default-safe, and reversible.
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
        / "0026_gt_actuals_metadata.py"
    )
    assert migration_path.exists(), f"Migration file not found: {migration_path}"

    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        original_op = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            mod_name = "migration_0026_test"
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


_NEW_COLUMNS = (
    "source_type",
    "vendor_quote_id",
    "invoice_date",
    "actual_machine_hours",
    "actual_setup_hours",
    "actual_labor_hours",
    "actual_inspection_hours",
    "actual_cycle_seconds",
    "evidence_sha256",
    "evidence_uri",
)


def test_revision_chain(migration_and_op):
    mod, _ = migration_and_op
    assert mod.revision == "0026_gt_actuals_metadata"
    assert mod.down_revision == "0025_invite_invited_user"
    assert len(mod.revision) <= 32


def test_upgrade_adds_metadata_columns_additively(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.upgrade()

    added = {
        (c.args[0], c.args[1].name): c.args[1]
        for c in mock_op.add_column.call_args_list
    }
    for col in _NEW_COLUMNS:
        assert ("ground_truth_records", col) in added, col

    source_type = added[("ground_truth_records", "source_type")]
    assert source_type.nullable is False
    assert source_type.server_default.arg == "actual"

    for col in _NEW_COLUMNS:
        if col == "source_type":
            continue
        assert added[("ground_truth_records", col)].nullable is True, col


def test_downgrade_reverses_columns(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.downgrade()

    dropped = {(c.args[0], c.args[1]) for c in mock_op.drop_column.call_args_list}
    for col in _NEW_COLUMNS:
        assert ("ground_truth_records", col) in dropped, col
