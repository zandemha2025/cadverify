"""Schema contract for 0065: a library draft's last editor, and recorded self-approval."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
DRAFTS = {"rate_card_versions", "shop_profile_versions", "material_library_versions"}


def _load():
    mock_op = MagicMock()
    mock_op.get_bind.return_value.dialect.name = "postgresql"
    path = Path(__file__).parent.parent / "alembic" / "versions" / "0065_draft_editor.py"
    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        old = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            spec = importlib.util.spec_from_file_location("migration_0065_test", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            alembic.op = old
    return module, mock_op


def test_it_follows_schedule_and_supplier():
    migration, _ = _load()
    assert migration.revision == "0065_draft_editor"
    assert migration.down_revision == "0064_schedule_and_supplier"
    assert len(migration.revision) <= 32


def test_up_down_up_adds_and_drops_four_nullable_columns():
    migration, op = _load()
    for step in ("up", "down", "up"):
        op.reset_mock()
        if step == "up":
            migration.upgrade()
            added = {(c.args[0], c.args[1].name): c.args[1] for c in op.add_column.call_args_list}
            assert set(added) == {(t, "edited_by") for t in DRAFTS} | {("change_requests", "self_approved")}
            assert all(col.nullable for col in added.values())
            for table in DRAFTS:
                (fk,) = added[(table, "edited_by")].foreign_keys
                assert fk.target_fullname == "users.id" and fk.ondelete == "SET NULL"
            # Additive: no backfill, nothing rewritten.
            assert not [c for c in op.execute.call_args_list if "UPDATE" in str(c.args[0]).upper()]
        else:
            migration.downgrade()
            dropped = {c.args for c in op.drop_column.call_args_list}
            assert dropped == {(t, "edited_by") for t in DRAFTS} | {("change_requests", "self_approved")}
            assert not [c for c in op.execute.call_args_list if "UPDATE" in str(c.args[0]).upper()]


def test_the_models_match_the_migration():
    from src.db.models import ChangeRequest, MaterialLibraryVersion, RateCardVersion, ShopProfileVersion

    for model in (RateCardVersion, ShopProfileVersion, MaterialLibraryVersion):
        col = model.__table__.c.edited_by
        assert col.nullable
        (fk,) = col.foreign_keys
        assert fk.target_fullname == "users.id" and fk.ondelete == "SET NULL"
    assert ChangeRequest.__table__.c.self_approved.nullable


@pytest.mark.asyncio
@pytest.mark.skipif(not _PG, reason="requires PostgreSQL at schema head (0065+)")
async def test_the_columns_exist_nullable_with_their_foreign_keys():
    from sqlalchemy import text

    import src.db.engine as eng

    try:
        async with eng.get_session_factory()() as s:
            cols = (await s.execute(text(
                "SELECT table_name, column_name, is_nullable, data_type FROM information_schema.columns "
                "WHERE column_name IN ('edited_by', 'self_approved') AND table_schema = current_schema()"
            ))).all()
            assert {(t, c) for t, c, _n, _d in cols} == {(t, "edited_by") for t in DRAFTS} | {
                ("change_requests", "self_approved")}
            assert all(n == "YES" for _t, _c, n, _d in cols)
            fks = (await s.execute(text(
                "SELECT conrelid::regclass::text, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE contype = 'f' AND pg_get_constraintdef(oid) LIKE 'FOREIGN KEY (edited_by)%'"
            ))).all()
            assert {t for t, _d in fks} == DRAFTS
            assert all("REFERENCES users(id) ON DELETE SET NULL" in d for _t, d in fks)
    finally:
        await eng.dispose_engine()
