"""Migration smoke tests for 0010_superadmin_role.

Mirrors test_migration_0009: no live Postgres here, so the migration is loaded
with ``alembic.op`` mocked and we assert on the DDL calls. The only delta is a
CHECK-constraint swap on ``users.role`` to admit ``'superadmin'`` — purely
additive, fully reversible. The real up/down against Postgres is proven by the
scratch-DB run that accompanies this branch.
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
        / "0010_superadmin_role.py"
    )
    assert migration_path.exists(), f"Migration file not found: {migration_path}"

    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        original_op = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            mod_name = "migration_0010_test"
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
    assert mod.revision == "0010_superadmin_role"
    assert mod.down_revision == "0009_org_tenancy"


def test_upgrade_widens_role_check_to_superadmin(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.upgrade()

    # old CHECK dropped, new CHECK created including 'superadmin'
    dropped = [c.args[0] for c in mock_op.drop_constraint.call_args_list]
    assert "ck_users_role" in dropped
    created = mock_op.create_check_constraint.call_args_list
    assert created, "expected a CHECK constraint to be (re)created"
    name, table, cond = created[-1].args[0], created[-1].args[1], created[-1].args[2]
    assert name == "ck_users_role"
    assert table == "users"
    assert "superadmin" in cond
    # every legacy value is still permitted (additive, no data rejected)
    for legacy in ("viewer", "analyst", "admin"):
        assert legacy in cond


def test_upgrade_touches_no_other_schema(migration_and_op):
    """Purely additive: no columns/tables/indexes created or dropped."""
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.upgrade()

    mock_op.add_column.assert_not_called()
    mock_op.drop_column.assert_not_called()
    mock_op.create_table.assert_not_called()
    mock_op.drop_table.assert_not_called()
    mock_op.create_index.assert_not_called()
    mock_op.drop_index.assert_not_called()


def test_downgrade_narrows_role_check_back(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.downgrade()

    created = mock_op.create_check_constraint.call_args_list
    assert created, "downgrade must re-create the original CHECK"
    cond = created[-1].args[2]
    assert "superadmin" not in cond
    for legacy in ("viewer", "analyst", "admin"):
        assert legacy in cond
