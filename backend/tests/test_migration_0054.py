"""Schema contract for part actuals (hours-only rows, match basis) and org calibrations."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.db.models import GroundTruthRecordRow, OrgCalibration


def _load():
    mock_op = MagicMock()
    mock_op.get_bind.return_value.dialect.name = "postgresql"
    mock_op.get_bind.return_value.execute.return_value.scalar.return_value = 2
    path = Path(__file__).parent.parent / "alembic" / "versions" / "0054_part_actuals.py"
    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        old = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            spec = importlib.util.spec_from_file_location("migration_0054_test", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            alembic.op = old
    return module, mock_op


def test_model_matches_the_migration():
    gt = GroundTruthRecordRow.__table__
    assert gt.c.actual_unit_cost_usd.nullable is True
    for name in ("part_number", "machine", "match_basis"):
        assert gt.c[name].nullable is True
    names = {c.name for c in gt.constraints}
    assert {"ck_ground_truth_cost_or_hours", "ck_ground_truth_match_basis"} <= names
    assert "ix_ground_truth_records_org_evidence" in {i.name for i in gt.indexes}

    cal = OrgCalibration.__table__
    assert cal.c.org_id.nullable is False
    (org_fk,) = cal.c.org_id.foreign_keys
    assert org_fk.ondelete == "CASCADE"
    for name in ("applied_by", "undone_by"):
        (fk,) = cal.c[name].foreign_keys
        assert fk.ondelete == "SET NULL"
    assert cal.c.undone_at.nullable is True
    assert "ck_org_calibrations_status" in {c.name for c in cal.constraints}


def test_migration_0054_follows_head_and_is_reversible():
    migration, op = _load()
    assert migration.revision == "0054_part_actuals"
    assert migration.down_revision == "0053_data_control"
    assert len(migration.revision) <= 32

    migration.upgrade()
    op.alter_column.assert_called_once()
    assert op.alter_column.call_args.kwargs["nullable"] is True
    added = [c.args[1].name for c in op.add_column.call_args_list]
    assert added == ["part_number", "machine", "match_basis"]
    (create,) = op.create_table.call_args_list
    assert create.args[0] == "org_calibrations"
    cols = {getattr(c, "name", None) for c in create.args[1:]}
    assert {"factors", "basis", "status", "applied_by", "applied_at", "undone_by", "undone_at"} <= cols

    op.reset_mock()
    op.get_bind.return_value.execute.return_value.scalar.return_value = 2
    migration.downgrade()
    # Hours-only rows can't exist before 0054: they are deleted before NOT NULL returns.
    executed = [str(c.args[0]) for c in op.execute.call_args_list]
    assert any("DELETE FROM ground_truth_records WHERE actual_unit_cost_usd IS NULL" in s for s in executed)
    assert op.alter_column.call_args.kwargs["nullable"] is False
    assert op.drop_table.call_args.args == ("org_calibrations",)
    dropped = [c.args[1] for c in op.drop_column.call_args_list]
    assert dropped == ["match_basis", "machine", "part_number"]
