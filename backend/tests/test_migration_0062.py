"""Schema contract for two-step sign-in (migration 0062)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


def _load():
    mock_op = MagicMock()
    mock_op.get_bind.return_value.dialect.name = "postgresql"
    path = Path(__file__).parent.parent / "alembic" / "versions" / "0062_two_step_sign_in.py"
    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        old = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            spec = importlib.util.spec_from_file_location("migration_0062_test", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            alembic.op = old
    return module, mock_op


def test_chain():
    migration, _ = _load()
    assert migration.revision == "0062_two_step_sign_in"
    assert migration.down_revision == "0061_api_key_scope"
    assert len(migration.revision) <= 32


def test_upgrade_creates_sealed_secret_and_hashed_code_tables_and_the_org_rule():
    migration, op = _load()
    migration.upgrade()
    tables = {c.args[0]: c.args[1:] for c in op.create_table.call_args_list}
    assert set(tables) == {"user_two_step", "user_two_step_recovery_codes"}
    secret_cols = {c.name: c for c in tables["user_two_step"] if hasattr(c, "name") and hasattr(c, "nullable")}
    assert {"secret_sealed", "pending_secret_sealed", "last_used_step", "failed_attempts", "locked_until"} <= set(secret_cols)
    checks = " ".join(str(c.sqltext) for c in tables["user_two_step"] if c.__class__.__name__ == "CheckConstraint")
    assert "fernet:v1:%" in checks  # never plain text
    code_cols = {c.name for c in tables["user_two_step_recovery_codes"] if hasattr(c, "nullable")}
    assert "code_hash" in code_cols and "code" not in code_cols
    (add,) = op.add_column.call_args_list
    assert add.args[0] == "organizations" and add.args[1].name == "require_two_step" and not add.args[1].nullable
    migration.downgrade()
    assert op.drop_column.call_args.args == ("organizations", "require_two_step")
    assert [c.args[0] for c in op.drop_table.call_args_list] == ["user_two_step_recovery_codes", "user_two_step"]
