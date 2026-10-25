"""Schema contract for the free catalog-run allowance (catalog_parts)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.db.models import CatalogPart


def _load():
    mock_op = MagicMock()
    path = Path(__file__).parent.parent / "alembic" / "versions" / "0052_catalog_allowance.py"
    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        old = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            spec = importlib.util.spec_from_file_location("migration_0052_test", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            alembic.op = old
    return module, mock_op


def test_model_matches_the_migration():
    table = CatalogPart.__table__
    assert [c.name for c in table.primary_key.columns] == ["user_id", "file_hash"]
    assert table.c.batch_id.nullable is True
    assert table.c.batch_item_id.nullable is True
    assert table.c.state.nullable is False
    # Deleting a batch keeps the slot used; deleting the account removes its rows.
    (batch_fk,) = table.c.batch_id.foreign_keys
    assert batch_fk.ondelete == "SET NULL"
    (user_fk,) = table.c.user_id.foreign_keys
    assert user_fk.ondelete == "CASCADE"


def test_migration_0052_creates_and_drops_the_table():
    migration, op = _load()
    assert migration.revision == "0052_catalog_allowance"
    assert migration.down_revision == "0051_self_serve_plans"
    assert len(migration.revision) <= 32

    migration.upgrade()
    (create,) = op.create_table.call_args_list
    assert create.args[0] == "catalog_parts"
    names = [getattr(c, "name", None) for c in create.args[1:]]
    for column in ("user_id", "file_hash", "batch_id", "batch_item_id", "state", "created_at", "updated_at"):
        assert column in names
    index = op.create_index.call_args
    assert index.args == ("ix_catalog_parts_batch_item", "catalog_parts", ["batch_item_id"])

    migration.downgrade()
    assert op.drop_index.call_args.args == ("ix_catalog_parts_batch_item",)
    assert op.drop_table.call_args.args == ("catalog_parts",)
