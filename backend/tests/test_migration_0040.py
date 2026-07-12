"""Schema contract for org-scoped Design Studio revision evidence."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import sqlalchemy as sa


def _load():
    mock_op = MagicMock()
    mock_op.get_bind.return_value.dialect.name = "postgresql"
    path = Path(__file__).parent.parent / "alembic" / "versions" / "0040_design_studio.py"
    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        old = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            spec = importlib.util.spec_from_file_location("migration_0040_test", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            alembic.op = old
    return module, mock_op


def test_design_studio_revision_and_tenant_tables():
    migration, op = _load()
    assert migration.revision == "0040_design_studio"
    assert migration.down_revision == "0039_auth_identities"
    assert len(migration.revision) <= 32

    migration.upgrade()
    tables = {call.args[0]: call.args[1:] for call in op.create_table.call_args_list}
    assert set(tables) == {"design_projects", "design_revisions"}
    projects = "\n".join(str(arg) for arg in tables["design_projects"])
    revisions = "\n".join(str(arg) for arg in tables["design_revisions"])
    for field in ("ulid", "org_id", "created_by", "current_revision", "status"):
        assert field in projects
    for field in (
        "design_id",
        "org_id",
        "revision_no",
        "operation_plan_json",
        "step_object_key",
        "stl_object_key",
        "geometry_hash",
    ):
        assert field in revisions
    uniques = {
        arg.name
        for arg in tables["design_revisions"]
        if isinstance(arg, sa.UniqueConstraint)
    }
    assert "uq_design_revisions_design_number" in uniques
