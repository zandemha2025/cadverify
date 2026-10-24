"""Schema contract for the personal-org marker (``organizations.is_personal``, 0060)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.auth.org_context import matches_legacy_personal_naming, personal_org_name, personal_org_slug
from src.db.models import Organization


def _load():
    mock_op = MagicMock()
    mock_op.get_bind.return_value.dialect.name = "postgresql"
    path = Path(__file__).parent.parent / "alembic" / "versions" / "0060_org_is_personal.py"
    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        old = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            spec = importlib.util.spec_from_file_location("migration_0060_test", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            alembic.op = old
    return module, mock_op


def test_model_matches_the_migration():
    migration, _ = _load()
    assert migration.revision == "0060_org_is_personal"
    assert migration.down_revision == "0059_part_buy_price"
    assert len(migration.revision) <= 32
    col = Organization.__table__.c.is_personal
    assert not col.nullable and str(col.server_default.arg) == "false"


def test_upgrade_adds_the_column_and_marks_only_personal_orgs():
    migration, op = _load()
    personal = ("01P", personal_org_name("pat.smith@corp.example"), personal_org_slug("pat.smith@corp.example"))
    lookalike = ("01L", "pat's Organization", personal_org_slug("Pat's-Organization"))
    named = ("01N", "Acme Corp", personal_org_slug("Acme-Corp"))
    op.get_bind.return_value.execute.return_value.fetchall.return_value = [personal, lookalike, named]
    migration.upgrade()
    (call,) = op.add_column.call_args_list
    table, column = call.args
    assert table == "organizations" and column.name == "is_personal" and not column.nullable
    updates = [c for c in op.get_bind.return_value.execute.call_args_list if "UPDATE" in str(c.args[0])]
    assert len(updates) == 1 and updates[0].args[1] == {"ids": ["01P"]}
    migration.downgrade()
    assert op.drop_column.call_args.args == ("organizations", "is_personal")


def test_the_backfill_rule_is_the_one_personal_orgs_were_created_with():
    migration, _ = _load()
    for email in ("pat@corp.example", "Pat.Smith+x@corp.example", "o'neil@corp.example", "@odd", "x@y"):
        name, slug = personal_org_name(email), personal_org_slug(email)
        assert migration.legacy_personal(name, slug) is matches_legacy_personal_naming(name, slug) is True
    assert migration.legacy_personal("Acme Corp", "acme-corp-ab12cd34") is False
    assert migration.legacy_personal(None, None) is False
