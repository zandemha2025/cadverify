"""Migration smoke tests for 0027_cost_decision_governance."""
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
        / "0027_cost_decision_governance.py"
    )
    assert migration_path.exists(), f"Migration file not found: {migration_path}"

    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        original_op = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            mod_name = "migration_0027_test"
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
    "approval_status",
    "approved_by_user_id",
    "approved_at",
    "approval_note",
    "stale_at",
    "stale_reason",
)


def test_revision_chain(migration_and_op):
    mod, _ = migration_and_op
    assert mod.revision == "0027_cost_decision_governance"
    assert mod.down_revision == "0026_gt_actuals_metadata"
    assert len(mod.revision) <= 32


def test_upgrade_adds_governance_columns(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.upgrade()

    added = {
        (c.args[0], c.args[1].name): c.args[1]
        for c in mock_op.add_column.call_args_list
    }
    for col in _NEW_COLUMNS:
        assert ("cost_decisions", col) in added, col

    approval_status = added[("cost_decisions", "approval_status")]
    assert approval_status.nullable is False
    assert approval_status.server_default.arg == "unreviewed"

    for col in _NEW_COLUMNS:
        if col == "approval_status":
            continue
        assert added[("cost_decisions", col)].nullable is True, col

    mock_op.create_foreign_key.assert_called_once()
    mock_op.create_index.assert_called_once_with(
        "ix_cost_decisions_org_stale",
        "cost_decisions",
        ["org_id", "stale_at"],
    )


def test_downgrade_reverses_governance_columns(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.downgrade()

    dropped = {(c.args[0], c.args[1]) for c in mock_op.drop_column.call_args_list}
    for col in _NEW_COLUMNS:
        assert ("cost_decisions", col) in dropped, col
    mock_op.drop_index.assert_called_once_with(
        "ix_cost_decisions_org_stale", table_name="cost_decisions"
    )
