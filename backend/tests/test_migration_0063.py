"""Schema contract for supplier links (0063): what a link shows, and package links."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


def _load():
    mock_op = MagicMock()
    mock_op.get_bind.return_value.dialect.name = "postgresql"
    path = Path(__file__).parent.parent / "alembic" / "versions" / "0063_supplier_links.py"
    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        old = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            spec = importlib.util.spec_from_file_location("migration_0063_test", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            alembic.op = old
    return module, mock_op


def test_it_follows_two_step_sign_in():
    migration, _ = _load()
    assert migration.revision == "0063_supplier_links"
    assert migration.down_revision == "0062_two_step_sign_in"
    assert len(migration.revision) <= 32


def test_upgrade_only_adds_nullable_columns_and_downgrade_drops_them():
    migration, op = _load()
    migration.upgrade()
    added = {(c.args[0], c.args[1].name): c.args[1] for c in op.add_column.call_args_list}
    assert set(added) == {
        ("cost_decisions", "share_options"),
        ("rfq_packages", "is_public"), ("rfq_packages", "share_short_id"), ("rfq_packages", "share_created_at"),
        ("rfq_packages", "share_created_by"), ("rfq_packages", "share_expires_at"),
        ("rfq_packages", "share_revoked_at"), ("rfq_packages", "share_options"),
    }
    for (table, name), col in added.items():
        if name == "is_public":
            assert not col.nullable and str(col.server_default.arg) == "false"
        else:
            assert col.nullable, (table, name)
    assert not [c for c in op.execute.call_args_list if "UPDATE" in str(c.args[0]).upper()]  # no backfill
    (index,) = op.create_index.call_args_list
    assert index.args[:3] == ("ix_rfq_packages_share", "rfq_packages", ["share_short_id"])
    migration.downgrade()
    dropped = {c.args for c in op.drop_column.call_args_list}
    assert {(t, n) for t, n in added} == dropped
