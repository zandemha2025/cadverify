"""Migration smoke tests for 0009_org_tenancy.

Mirrors test_migration_0008: no live Postgres here, so we load the migration
with alembic.op mocked and assert on the calls made during upgrade/downgrade.
The backfill loop needs a real DB bind, so we stub get_bind() to return an
empty user set — that still drives the full DDL path (Phase 1 table/column
creation and Phase 3 NOT NULL + FK + index) structurally. The *real* backfill
(with seeded multi-user data) is proven by the up->down->up Postgres proof.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _load_migration_with_mock_op():
    mock_op = MagicMock()
    # Phase-2 backfill reads users via op.get_bind(); return an empty set so the
    # per-user loop is a no-op and Phase 1 + Phase 3 DDL still execute.
    mock_op.get_bind.return_value.execute.return_value.fetchall.return_value = []

    # 0009 imports org_context, which imports the ORM models. Keep those modules
    # outside patch.dict(sys.modules, ...) so repeated fixture loads do not drop
    # src.db.models while leaving its SQLAlchemy metadata populated.
    import src.auth.org_context  # noqa: F401

    migration_path = (
        Path(__file__).parent.parent
        / "alembic"
        / "versions"
        / "0009_org_tenancy.py"
    )
    assert migration_path.exists(), f"Migration file not found: {migration_path}"

    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        original_op = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            mod_name = "migration_0009_test"
            sys.modules.pop(mod_name, None)
            spec = importlib.util.spec_from_file_location(
                mod_name, str(migration_path)
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        finally:
            if original_op is None:
                try:
                    delattr(alembic, "op")
                except AttributeError:
                    pass
            else:
                alembic.op = original_op

    return mod, mock_op


@pytest.fixture
def migration_and_op():
    return _load_migration_with_mock_op()


def test_revision_chain(migration_and_op):
    mod, _ = migration_and_op
    assert mod.revision == "0009_org_tenancy"
    assert mod.down_revision == "0008_create_cost_decisions"


def test_eight_not_null_tables_enumerated(migration_and_op):
    mod, _ = migration_and_op
    assert set(mod._NOT_NULL_ORG_TABLES) == {
        "api_keys", "analyses", "cost_decisions", "jobs",
        "usage_events", "batches", "batch_items", "webhook_deliveries",
    }
    # users.current_org_id and audit_log.org_id are intentionally NOT in this
    # NOT-NULL set.
    assert "users" not in mod._NOT_NULL_ORG_TABLES
    assert "audit_log" not in mod._NOT_NULL_ORG_TABLES


def test_hot_tables_get_composite_index(migration_and_op):
    mod, _ = migration_and_op
    composite = {
        name: cols for name, tbl, cols in mod._ORG_INDEXES if len(cols) == 2
    }
    assert composite == {
        "ix_analyses_org_user": ["org_id", "user_id"],
        "ix_cost_decisions_org_user": ["org_id", "user_id"],
        "ix_batches_org_user": ["org_id", "user_id"],
        "ix_jobs_org_user": ["org_id", "user_id"],
    }


def test_upgrade_phase1_creates_org_tables(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.upgrade()

    created = [c.args[0] for c in mock_op.create_table.call_args_list]
    assert {"organizations", "teams", "memberships"} <= set(created)
    # nullable org_id added to every user-scoped table
    added = {(c.args[0], c.args[1].name) for c in mock_op.add_column.call_args_list}
    assert ("users", "current_org_id") in added
    for tbl in mod._NOT_NULL_ORG_TABLES + ["audit_log"]:
        assert (tbl, "org_id") in added


def test_upgrade_phase3_sets_not_null_and_indexes(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.upgrade()

    # NOT NULL flipped on exactly the eight data tables
    not_nulled = {
        c.args[0]
        for c in mock_op.alter_column.call_args_list
        if c.kwargs.get("nullable") is False
    }
    assert not_nulled == set(mod._NOT_NULL_ORG_TABLES)
    # every planned org index is created
    created_idx = {c.args[0] for c in mock_op.create_index.call_args_list}
    for idx_name, _tbl, _cols in mod._ORG_INDEXES:
        assert idx_name in created_idx


def test_downgrade_drops_only_new_tables(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.downgrade()

    dropped = [c.args[0] for c in mock_op.drop_table.call_args_list]
    assert {"organizations", "teams", "memberships"} == set(dropped)
    # never drops any pre-existing table
    for keep in ("users", "analyses", "cost_decisions", "batches", "audit_log"):
        assert keep not in dropped
    # org_id columns removed from the ten user-scoped tables
    dropped_cols = {
        (c.args[0], c.args[1]) for c in mock_op.drop_column.call_args_list
    }
    assert ("users", "current_org_id") in dropped_cols
    for tbl in mod._NOT_NULL_ORG_TABLES + ["audit_log"]:
        assert (tbl, "org_id") in dropped_cols
