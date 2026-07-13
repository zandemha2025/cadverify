"""Schema contract for durable four-way cost-decision dispositions."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.db.models import CostDecision


def _load():
    mock_op = MagicMock()
    mock_op.get_bind.return_value.dialect.name = "postgresql"
    path = (
        Path(__file__).parent.parent
        / "alembic"
        / "versions"
        / "0042_cost_decision_disposition.py"
    )
    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        old = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            spec = importlib.util.spec_from_file_location("migration_0042_test", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            alembic.op = old
    return module, mock_op


def test_model_exposes_disposition_fields_and_allowed_values():
    columns = CostDecision.__table__.c
    assert columns.user_disposition.nullable is True
    assert columns.disposition_note.nullable is True
    assert columns.disposition_updated_at.nullable is True
    assert columns.disposition_updated_by_user_id.nullable is True

    check = next(
        c
        for c in CostDecision.__table__.constraints
        if c.name == "ck_cost_decisions_disposition"
    )
    sql = str(check.sqltext)
    for value in ("inhouse", "outside", "acquire", "redesign"):
        assert value in sql


def test_migration_adds_and_removes_disposition_contract():
    migration, op = _load()
    assert migration.revision == "0042_cost_disposition"
    assert migration.down_revision == "0041_org_scoped_dedup"
    assert len(migration.revision) <= 32

    migration.upgrade()

    added = {
        call.args[1].name: call.args[1]
        for call in op.add_column.call_args_list
        if call.args[0] == "cost_decisions"
    }
    assert set(added) == {
        "user_disposition",
        "disposition_note",
        "disposition_updated_at",
        "disposition_updated_by_user_id",
    }
    assert all(column.nullable is True for column in added.values())
    op.create_check_constraint.assert_called_once()
    check_call = op.create_check_constraint.call_args
    assert check_call.args[0] == "ck_cost_decisions_disposition"
    assert check_call.args[1] == "cost_decisions"

    migration.downgrade()
    op.drop_constraint.assert_called_once_with(
        "ck_cost_decisions_disposition",
        "cost_decisions",
        type_="check",
    )
    assert [call.args[1] for call in op.drop_column.call_args_list] == [
        "disposition_updated_by_user_id",
        "disposition_updated_at",
        "disposition_note",
        "user_disposition",
    ]
