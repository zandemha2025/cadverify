"""Schema contract for part specs, the sign-off role and user settings (migration 0056)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlalchemy import CheckConstraint

from src.db.models import Organization, PartContext, User


def _load():
    mock_op = MagicMock()
    mock_op.get_bind.return_value.dialect.name = "postgresql"
    path = Path(__file__).parent.parent / "alembic" / "versions" / "0056_part_specs_signoff.py"
    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        old = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            spec = importlib.util.spec_from_file_location("migration_0056_test", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            alembic.op = old
    return module, mock_op


def _signoff_check() -> str:
    (check,) = [
        c for c in Organization.__table__.constraints
        if isinstance(c, CheckConstraint) and c.name == "ck_organizations_signoff_role"
    ]
    return str(check.sqltext)


def test_model_matches_the_migration():
    assert PartContext.__table__.c.part_specs.nullable is True
    assert Organization.__table__.c.signoff_role.nullable is True
    prefs = User.__table__.c.preferences
    assert prefs.nullable is False
    assert prefs.server_default is not None
    migration, _ = _load()
    assert _signoff_check() == migration.SIGNOFF_RULE


def test_upgrade_adds_three_columns_after_head():
    migration, op = _load()
    assert migration.revision == "0056_part_specs_signoff"
    assert migration.down_revision == "0055_direct_upload_parts"
    assert len(migration.revision) <= 32

    migration.upgrade()
    added = {(c.args[0], c.args[1].name): c.args[1] for c in op.add_column.call_args_list}
    assert set(added) == {
        ("part_contexts", "part_specs"),
        ("organizations", "signoff_role"),
        ("users", "preferences"),
    }
    assert added[("part_contexts", "part_specs")].nullable is True
    assert added[("organizations", "signoff_role")].nullable is True
    assert added[("users", "preferences")].nullable is False
    assert "'{}'" in str(added[("users", "preferences")].server_default.arg)
    assert op.create_check_constraint.call_args.args == (
        "ck_organizations_signoff_role", "organizations",
        "signoff_role IS NULL OR signoff_role IN ('member', 'admin')",
    )
    # Additive only: nothing dropped, no table created, no data rewritten.
    assert not op.drop_column.called and not op.create_table.called
    assert not op.alter_column.called


def test_downgrade_drops_exactly_what_upgrade_added():
    migration, op = _load()
    migration.downgrade()
    dropped = {c.args for c in op.drop_column.call_args_list}
    assert dropped == {
        ("users", "preferences"),
        ("organizations", "signoff_role"),
        ("part_contexts", "part_specs"),
    }
    assert op.drop_constraint.call_args.args == ("ck_organizations_signoff_role", "organizations")
    assert op.drop_constraint.call_args.kwargs == {"type_": "check"}
    assert not op.add_column.called
