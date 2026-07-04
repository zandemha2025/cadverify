"""Migration smoke tests for 0023_ps_makeability (Phase D).

Mirrors test_migration_0012: no live Postgres here, so the migration is loaded
with ``alembic.op`` mocked and we assert on the DDL calls. Additive + fully
reversible: ten nullable/defaulted makeability columns on ``part_summaries`` (so
existing rows need no backfill and the legacy columns stay byte-identical) plus
two org-leading indexes for the D3 rollup and the D4 ranking. The real up/down
against Postgres is proven by the live-PG round-trip test that accompanies this
branch (``test_makeability_projection.py::test_pg_migration_0023_round_trip``).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_migration_with_mock_op():
    from unittest.mock import MagicMock, patch

    mock_op = MagicMock()
    migration_path = (
        Path(__file__).parent.parent
        / "alembic"
        / "versions"
        / "0023_part_summary_makeability.py"
    )
    assert migration_path.exists(), f"Migration file not found: {migration_path}"

    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        original_op = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            mod_name = "migration_0023_test"
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


_NEW_COLUMNS = (
    "makeability_verdict",
    "in_house_makeable",
    "makeability_bucket",
    "makeability_stale",
    "unlock_process",
    "unlock_gate",
    "unlock_single",
    "unlock_need_num",
    "unlock_need_label",
    "makeability_gap",
)


def test_revision_chain(migration_and_op):
    mod, _ = migration_and_op
    assert mod.revision == "0023_ps_makeability"
    assert mod.down_revision == "0022_part_context_env"
    # <= 32 chars (alembic_version.version_num is varchar(32))
    assert len(mod.revision) <= 32


def test_upgrade_adds_all_makeability_columns_additively(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.upgrade()

    added = {
        (c.args[0], c.args[1].name) for c in mock_op.add_column.call_args_list
    }
    for col in _NEW_COLUMNS:
        assert ("part_summaries", col) in added, col

    # makeability_bucket is NOT NULL with a server_default 'unknown' so existing
    # rows need no backfill; makeability_stale defaults false. All others nullable.
    by_name = {
        c.args[1].name: c.args[1] for c in mock_op.add_column.call_args_list
    }
    bucket = by_name["makeability_bucket"]
    assert bucket.nullable is False
    assert bucket.server_default.arg == "unknown"
    stale = by_name["makeability_stale"]
    assert stale.nullable is False
    assert stale.server_default.arg == "false"
    for col in ("makeability_verdict", "in_house_makeable", "unlock_process",
                "unlock_gate", "unlock_single", "unlock_need_num",
                "unlock_need_label", "makeability_gap"):
        assert by_name[col].nullable is True, col


def test_upgrade_creates_org_leading_indexes(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.upgrade()

    idx = {c.args[0]: c for c in mock_op.create_index.call_args_list}
    assert "ix_part_summaries_org_mkbucket" in idx
    assert "ix_part_summaries_org_unlock" in idx
    # Both indexes are org-leading (org_id is the first column).
    for name in ("ix_part_summaries_org_mkbucket", "ix_part_summaries_org_unlock"):
        cols = idx[name].args[2]
        assert cols[0] == "org_id", name
    # the rollup index carries the bucket key + the keyset drill-down axis
    mkbucket_cols = idx["ix_part_summaries_org_mkbucket"].args[2]
    assert mkbucket_cols[1] == "makeability_bucket"
    # the ranking index carries the GROUP BY keys
    unlock_cols = idx["ix_part_summaries_org_unlock"].args[2]
    assert unlock_cols[1] == "unlock_process" and unlock_cols[2] == "unlock_gate"


def test_downgrade_reverses_everything(migration_and_op):
    mod, mock_op = migration_and_op
    import alembic

    alembic.op = mock_op
    mod.downgrade()

    dropped_cols = {
        (c.args[0], c.args[1]) for c in mock_op.drop_column.call_args_list
    }
    for col in _NEW_COLUMNS:
        assert ("part_summaries", col) in dropped_cols, col

    dropped_idx = {c.args[0] for c in mock_op.drop_index.call_args_list}
    assert "ix_part_summaries_org_mkbucket" in dropped_idx
    assert "ix_part_summaries_org_unlock" in dropped_idx
