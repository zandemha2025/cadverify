"""Schema contract for immutable federated identity bindings."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import sqlalchemy as sa


def _load():
    mock_op = MagicMock()
    mock_op.get_bind.return_value.dialect.name = "postgresql"
    path = (
        Path(__file__).parent.parent
        / "alembic"
        / "versions"
        / "0039_auth_identities.py"
    )
    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        old = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            spec = importlib.util.spec_from_file_location("migration_0039_test", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            alembic.op = old
    return module, mock_op


def test_auth_identity_revision_and_unique_bindings():
    migration, op = _load()
    assert migration.revision == "0039_auth_identities"
    assert migration.down_revision == "0038_pilot_receipts"
    assert len(migration.revision) <= 32

    migration.upgrade()
    create = op.create_table.call_args
    assert create.args[0] == "auth_identities"
    rendered = "\n".join(str(arg) for arg in create.args[1:])
    assert "provider" in rendered
    assert "issuer" in rendered
    assert "subject" in rendered
    assert "user_id" in rendered
    unique_names = {
        arg.name for arg in create.args[1:] if isinstance(arg, sa.UniqueConstraint)
    }
    assert unique_names == {
        "uq_auth_identity_provider_issuer_subject",
        "uq_auth_identity_user_provider_issuer",
    }
    op.create_index.assert_called_once_with(
        "ix_auth_identities_user_id", "auth_identities", ["user_id"]
    )
