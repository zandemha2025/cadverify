"""Schema contract for API key scope and expiry (``api_keys.scope``/``expires_at``, 0061)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.db.models import ApiKey


def _load():
    mock_op = MagicMock()
    mock_op.get_bind.return_value.dialect.name = "postgresql"
    path = Path(__file__).parent.parent / "alembic" / "versions" / "0061_api_key_scope.py"
    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        old = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            spec = importlib.util.spec_from_file_location("migration_0061_test", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            alembic.op = old
    return module, mock_op


def test_model_matches_the_migration():
    migration, _ = _load()
    assert migration.revision == "0061_api_key_scope"
    assert migration.down_revision == "0060_org_is_personal"
    assert len(migration.revision) <= 32
    table = ApiKey.__table__
    assert table.c.scope.nullable and table.c.expires_at.nullable
    checks = {c.name: str(c.sqltext) for c in table.constraints if c.name == "ck_api_keys_scope"}
    assert checks == {"ck_api_keys_scope": "scope IS NULL OR scope IN ('read', 'read_write')"}


def test_upgrade_adds_nullable_columns_so_existing_keys_keep_working():
    migration, op = _load()
    migration.upgrade()
    added = {call.args[1].name: call.args[1] for call in op.add_column.call_args_list}
    assert set(added) == {"scope", "expires_at"}
    assert all(col.nullable and col.server_default is None for col in added.values())
    (check,) = op.create_check_constraint.call_args_list
    assert check.args[:2] == ("ck_api_keys_scope", "api_keys")
    migration.downgrade()
    dropped = sorted(call.args[1] for call in op.drop_column.call_args_list)
    assert dropped == ["expires_at", "scope"]
    assert op.drop_constraint.call_args.args == ("ck_api_keys_scope", "api_keys")
