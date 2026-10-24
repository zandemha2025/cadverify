"""Schema contract for a part's current buy price (``part_contexts.buy_price``, 0059)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.db.models import PartContext


def _load(dialect: str = "postgresql"):
    mock_op = MagicMock()
    mock_op.get_bind.return_value.dialect.name = dialect
    path = Path(__file__).parent.parent / "alembic" / "versions" / "0059_part_buy_price.py"
    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        old = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            spec = importlib.util.spec_from_file_location("migration_0059_test", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            alembic.op = old
    return module, mock_op


def test_model_matches_the_migration():
    migration, _ = _load()
    assert migration.revision == "0059_part_buy_price"
    assert migration.down_revision == "0058_direct_upload_links"
    assert len(migration.revision) <= 32
    col = PartContext.__table__.c.buy_price
    assert col.nullable


def test_upgrade_adds_one_nullable_column_and_downgrade_drops_it():
    migration, op = _load()
    migration.upgrade()
    (call,) = op.add_column.call_args_list
    table, column = call.args
    assert table == "part_contexts" and column.name == "buy_price" and column.nullable
    assert not op.create_table.called
    migration.downgrade()
    assert op.drop_column.call_args.args == ("part_contexts", "buy_price")
