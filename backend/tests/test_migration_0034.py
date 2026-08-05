"""Migration smoke tests for 0034_scim_identities."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _load_migration_with_mock_op():
    mock_op = MagicMock()
    migration_path = (
        Path(__file__).parent.parent / "alembic" / "versions" / "0034_scim_identities.py"
    )
    assert migration_path.exists(), f"Migration file not found: {migration_path}"

    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        original_op = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            mod_name = "migration_0034_test"
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
    assert mod.revision == "0034_scim_identities"
    assert mod.down_revision == "0033_integration_proof_levels"
    assert len(mod.revision) <= 32


def test_upgrade_creates_scim_identity_table_and_indexes(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.upgrade()

    created_tables = [c.args[0] for c in mock_op.create_table.call_args_list]
    assert created_tables == ["scim_identities"]

    table_args = mock_op.create_table.call_args_list[0].args
    names = {getattr(arg, "name", None) for arg in table_args if getattr(arg, "name", None)}
    assert "uq_scim_identities_org_user" in names
    assert "uq_scim_identities_org_external" in names
    assert "ck_scim_identities_org_role" in names

    created_indexes = {c.args[0] for c in mock_op.create_index.call_args_list}
    assert "ix_scim_identities_org_active" in created_indexes


def test_downgrade_drops_scim_identity_table(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.downgrade()

    assert [c.args[0] for c in mock_op.drop_table.call_args_list] == ["scim_identities"]
