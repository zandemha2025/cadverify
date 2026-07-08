"""Migration smoke tests for 0033_integration_proof_levels."""
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
        / "0033_integration_run_proof_levels.py"
    )
    assert migration_path.exists(), f"Migration file not found: {migration_path}"

    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        original_op = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            mod_name = "migration_0033_test"
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
    assert mod.revision == "0033_integration_proof_levels"
    assert mod.down_revision == "0032_rfq_packages"
    assert len(mod.revision) <= 32


def test_upgrade_adds_proof_level_columns_constraints_and_index(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.upgrade()

    added_columns = [c.args[1].name for c in mock_op.add_column.call_args_list]
    assert added_columns == [
        "connector_mode",
        "boundary_label",
        "api_name",
        "api_version",
        "external_tenant_hash",
        "correlation_ids_json",
        "watermark",
        "idempotency_key",
        "source_record_count",
        "normalized_record_count",
    ]
    constraints = {c.args[0] for c in mock_op.create_check_constraint.call_args_list}
    assert "ck_integration_runs_connector_mode" in constraints
    assert "ck_integration_runs_boundary_label" in constraints
    indexes = {c.args[0] for c in mock_op.create_index.call_args_list}
    assert "ix_integration_runs_org_boundary" in indexes
    assert any(
        "normalized_record_count = rows_valid" in str(call.args[0])
        for call in mock_op.execute.call_args_list
    )


def test_downgrade_removes_proof_level_schema(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.downgrade()

    dropped_columns = [c.args[1] for c in mock_op.drop_column.call_args_list]
    assert dropped_columns == [
        "normalized_record_count",
        "source_record_count",
        "idempotency_key",
        "watermark",
        "correlation_ids_json",
        "external_tenant_hash",
        "api_version",
        "api_name",
        "boundary_label",
        "connector_mode",
    ]
