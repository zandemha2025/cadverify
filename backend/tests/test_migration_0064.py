"""Schema contract for 0064: machine schedules, and the "supplier" outcome."""
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
    path = Path(__file__).parent.parent / "alembic" / "versions" / "0064_schedule_and_supplier.py"
    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        old = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            spec = importlib.util.spec_from_file_location("migration_0064_test", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            alembic.op = old
    return module, mock_op


def test_it_follows_supplier_links():
    migration, _ = _load()
    assert migration.revision == "0064_schedule_and_supplier"
    assert migration.down_revision == "0063_supplier_links"
    assert len(migration.revision) <= 32


def test_up_down_up_adds_the_schedule_and_widens_the_outcome_check():
    migration, op = _load()
    for step in ("up", "down", "up"):
        op.reset_mock()
        if step == "up":
            migration.upgrade()
            (added,) = op.add_column.call_args_list
            assert added.args[0] == "machine_instances" and added.args[1].name == "schedule"
            assert added.args[1].nullable
            (check,) = op.create_check_constraint.call_args_list
            assert check.args[:2] == ("ck_cost_decisions_disposition", "cost_decisions")
            assert "'supplier'" in check.args[2]
            assert not [c for c in op.execute.call_args_list if "UPDATE" in str(c.args[0]).upper()]
        else:
            migration.downgrade()
            updates = [str(c.args[0]) for c in op.execute.call_args_list if "UPDATE" in str(c.args[0]).upper()]
            # Stated in the docstring: a kept-with-the-supplier outcome reads as bought outside.
            assert updates == ["UPDATE cost_decisions SET user_disposition = 'outside' WHERE user_disposition = 'supplier'"]
            (check,) = op.create_check_constraint.call_args_list
            assert "'supplier'" not in check.args[2] and "'redesign'" in check.args[2]
            assert {c.args for c in op.drop_column.call_args_list} == {("machine_instances", "schedule")}
    assert "supplier" in migration.__doc__ and "'outside'" in migration.__doc__


def test_the_models_match_the_migration():
    from src.db.models import CostDecision, MachineInstance

    assert MachineInstance.__table__.c.schedule.nullable
    (check,) = [c for c in CostDecision.__table__.constraints if c.name == "ck_cost_decisions_disposition"]
    assert "'supplier'" in str(check.sqltext)


@pytest.mark.asyncio
@pytest.mark.skipif(not _PG, reason="requires PostgreSQL at schema head (0064+)")
async def test_a_schedule_is_stored_and_the_check_names_supplier():
    import uuid

    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng

    org, tag = str(ULID()), uuid.uuid4().hex[:10]
    try:
        async with eng.get_session_factory()() as s:
            await s.execute(text("INSERT INTO organizations (id, name, slug) VALUES (:id, 'Sup', :s)"),
                            {"id": org, "s": f"sup-{tag}"})
            await s.execute(text(
                "INSERT INTO machine_instances (ulid, org_id, name, process, count, capabilities, schedule) "
                "VALUES (:u, :o, 'VF-2', 'cnc_3axis', 3, '{}', '{\"shifts\": 2, \"hours_per_shift\": 8, "
                "\"days_per_year\": 240}')"), {"u": str(ULID()), "o": org})
            await s.commit()
            row = (await s.execute(text("SELECT schedule FROM machine_instances WHERE org_id = :o"),
                                   {"o": org})).scalar_one()
            assert row == {"shifts": 2, "hours_per_shift": 8, "days_per_year": 240}
            constraint = (await s.execute(text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_cost_decisions_disposition'"
            ))).scalar_one()
            assert "'supplier'" in constraint and "'inhouse'" in constraint and "'redesign'" in constraint
    finally:
        async with eng.get_session_factory()() as s:
            await s.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org})
            await s.commit()
        await eng.dispose_engine()
