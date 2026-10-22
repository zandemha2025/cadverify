"""Schema contract for supplier links (0063): what a link shows, and package links."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")


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
    assert index.kwargs["unique"] is True and "IS NOT NULL" in str(index.kwargs["postgresql_where"])
    migration.downgrade()
    dropped = {c.args for c in op.drop_column.call_args_list}
    assert {(t, n) for t, n in added} == dropped



@pytest.mark.asyncio
@pytest.mark.skipif(not _PG, reason="requires PostgreSQL at schema head (0063+)")
async def test_a_package_short_id_can_never_match_two_packages():
    """A public link resolves to one package: a duplicate short id is refused."""
    import uuid

    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    from ulid import ULID

    import src.db.engine as eng

    org, tag = str(ULID()), uuid.uuid4().hex[:10]
    short = f"p{tag}x"

    def pkg(sid):
        return {"u": str(ULID()), "o": org, "s": sid}

    insert = text("INSERT INTO rfq_packages (ulid, org_id, title, items_json, warnings_json, share_short_id) "
                  "VALUES (:u, :o, 'RFQ', '[]', '[]', :s)")
    try:
        async with eng.get_session_factory()() as s:
            await s.execute(text("INSERT INTO organizations (id, name, slug) VALUES (:id, 'Dup', :s)"),
                            {"id": org, "s": f"dup-{tag}"})
            await s.execute(insert, pkg(short))
            await s.execute(insert, pkg(None))
            await s.execute(insert, pkg(None))  # many packages without a link are fine
            await s.commit()
        async with eng.get_session_factory()() as s:
            with pytest.raises(IntegrityError):
                await s.execute(insert, pkg(short))
            await s.rollback()
    finally:
        async with eng.get_session_factory()() as s:
            await s.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org})
            await s.commit()
        await eng.dispose_engine()


def test_the_models_match_the_migration():
    from src.db.models import CostDecision, RfqPackage

    assert CostDecision.__table__.c.share_options.nullable
    cols = RfqPackage.__table__.c
    for name in ("share_short_id", "share_created_at", "share_created_by", "share_expires_at",
                 "share_revoked_at", "share_options"):
        assert cols[name].nullable, name
    assert not cols.is_public.nullable and str(cols.is_public.server_default.arg) == "false"
    (index,) = [i for i in RfqPackage.__table__.indexes if i.name == "ix_rfq_packages_share"]
    assert index.unique is True
