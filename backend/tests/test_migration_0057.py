"""Schema contract for account deletion (migration 0057).

The receipt scope gains ``account``; usage rows outlive a deleted organization
(nullable org, ``ON DELETE SET NULL``); and the free-allowance ledger of deleted
accounts exists, keyed by an email fingerprint. Constraints are added NOT VALID
and validated after, and downgrade restores both.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlalchemy import CheckConstraint

from src.db.models import DataDeletion, DeletedAccountAllowance, UsageEvent


def _load(dialect: str = "postgresql"):
    mock_op = MagicMock()
    mock_op.get_bind.return_value.dialect.name = dialect
    path = Path(__file__).parent.parent / "alembic" / "versions" / "0057_account_deletion.py"
    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        old = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            spec = importlib.util.spec_from_file_location("migration_0057_test", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            alembic.op = old
    return module, mock_op


def _check(table, name: str) -> str:
    (check,) = [c for c in table.constraints if isinstance(c, CheckConstraint) and c.name == name]
    return str(check.sqltext)


def _sql(op) -> list[str]:
    return [" ".join(str(c.args[0]).split()) for c in op.execute.call_args_list]


def test_models_match_the_migration():
    migration, _ = _load()
    assert _check(DataDeletion.__table__, "ck_data_deletions_scope") == migration.SCOPE_RULE
    org = UsageEvent.__table__.c.org_id
    assert org.nullable is True
    (fk,) = org.foreign_keys
    assert fk.ondelete == "SET NULL" and fk.column.table.name == "organizations"
    table = DeletedAccountAllowance.__table__
    assert table.name == migration.LEDGER
    assert [c.name for c in table.primary_key.columns] == ["email_hmac"]
    assert {c.name for c in table.columns} == {"email_hmac", "checks_used", "catalog_parts_used", "deleted_at"}
    assert _check(table, migration.LEDGER_CHECK) == migration.LEDGER_RULE
    # The ledger never holds an email.
    assert not any(c.name == "email" or c.name.endswith("_email") for c in table.columns)


def test_upgrade_after_head_adds_constraints_not_valid_then_validates():
    migration, op = _load()
    assert migration.revision == "0057_account_deletion"
    assert migration.down_revision == "0056_part_specs_signoff"
    assert len(migration.revision) <= 32
    migration.upgrade()
    sql = _sql(op)
    assert sql[:2] == ["SET LOCAL lock_timeout = '5000'", "SET LOCAL statement_timeout = '60000'"]
    dropped = [c.args for c in op.drop_constraint.call_args_list]
    assert dropped == [("ck_data_deletions_scope", "data_deletions"), ("fk_usage_events_org", "usage_events")]
    assert (
        "ALTER TABLE data_deletions ADD CONSTRAINT ck_data_deletions_scope "
        "CHECK (scope IN ('part', 'organization', 'account')) NOT VALID"
    ) in sql
    assert "ALTER TABLE data_deletions VALIDATE CONSTRAINT ck_data_deletions_scope" in sql
    assert (
        "ALTER TABLE usage_events ADD CONSTRAINT fk_usage_events_org FOREIGN KEY (org_id) "
        "REFERENCES organizations (id) ON DELETE SET NULL NOT VALID"
    ) in sql
    assert "ALTER TABLE usage_events VALIDATE CONSTRAINT fk_usage_events_org" in sql
    # Each constraint is validated after it is added.
    assert sql.index("ALTER TABLE usage_events VALIDATE CONSTRAINT fk_usage_events_org") > next(
        i for i, s in enumerate(sql) if "ADD CONSTRAINT fk_usage_events_org" in s
    )
    alter = op.alter_column.call_args
    assert alter.args == ("usage_events", "org_id") and alter.kwargs["nullable"] is True
    (table,) = [c.args for c in op.create_table.call_args_list]
    assert table[0] == "deleted_account_allowances"
    columns = {c.name: c for c in table[1:] if hasattr(c, "name") and hasattr(c, "type")}
    assert columns["email_hmac"].primary_key is True
    assert columns["checks_used"].nullable is False and columns["catalog_parts_used"].nullable is False
    # Nothing existing is deleted on the way up.
    assert not any(s.startswith("DELETE") for s in sql)
    assert not op.drop_table.called and not op.drop_column.called


def test_downgrade_restores_both_constraints_and_drops_the_ledger():
    migration, op = _load()
    migration.downgrade()
    sql = _sql(op)
    op.drop_table.assert_called_once_with("deleted_account_allowances")
    # Rows the old schema can't hold go first, then the old rules come back.
    assert sql.index("DELETE FROM usage_events WHERE org_id IS NULL") < next(
        i for i, s in enumerate(sql) if "ADD CONSTRAINT fk_usage_events_org" in s
    )
    assert (
        "ALTER TABLE usage_events ADD CONSTRAINT fk_usage_events_org FOREIGN KEY (org_id) "
        "REFERENCES organizations (id) ON DELETE CASCADE NOT VALID"
    ) in sql
    alter = op.alter_column.call_args
    assert alter.args == ("usage_events", "org_id") and alter.kwargs["nullable"] is False
    assert sql.index("DELETE FROM data_deletions WHERE scope = 'account'") < next(
        i for i, s in enumerate(sql) if "ADD CONSTRAINT ck_data_deletions_scope" in s
    )
    assert (
        "ALTER TABLE data_deletions ADD CONSTRAINT ck_data_deletions_scope "
        "CHECK (scope IN ('part', 'organization')) NOT VALID"
    ) in sql
    assert not op.create_table.called


def test_other_dialects_use_plain_constraints():
    migration, op = _load("sqlite")
    migration.upgrade()
    assert not op.execute.called
    op.create_check_constraint.assert_called_once_with(
        "ck_data_deletions_scope", "data_deletions", "scope IN ('part', 'organization', 'account')"
    )
    op.create_foreign_key.assert_called_once_with(
        "fk_usage_events_org", "usage_events", "organizations", ["org_id"], ["id"], ondelete="SET NULL"
    )
