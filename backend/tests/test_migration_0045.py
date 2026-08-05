"""Schema contract for bounded, crash-safe batch scheduling."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.db.models import Batch, BatchItem


def _load():
    mock_op = MagicMock()
    mock_op.get_bind.return_value.dialect.name = "postgresql"
    path = (
        Path(__file__).parent.parent
        / "alembic"
        / "versions"
        / "0045_batch_scheduler.py"
    )
    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        old = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            spec = importlib.util.spec_from_file_location("migration_0045_test", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            alembic.op = old
    return module, mock_op


def test_batch_models_carry_bounds_and_durable_retry_lease():
    batch_constraints = {item.name for item in Batch.__table__.constraints}
    item_constraints = {item.name for item in BatchItem.__table__.constraints}

    assert "ck_batches_concurrency_limit" in batch_constraints
    assert "ck_batch_items_priority" in item_constraints
    assert "ck_batch_items_attempt_count" in item_constraints
    assert BatchItem.__table__.c.attempt_count.nullable is False
    assert BatchItem.__table__.c.attempt_count.server_default.arg == "0"
    assert BatchItem.__table__.c.lease_started_at.nullable is True


def test_migration_0045_follows_direct_upload_head_and_is_reversible():
    migration, op = _load()
    assert migration.revision == "0045_batch_scheduler"
    assert migration.down_revision == "0044_direct_uploads"
    assert len(migration.revision) <= 32

    migration.upgrade()
    added = [call.args[1].name for call in op.add_column.call_args_list]
    assert added == ["attempt_count", "lease_started_at"]
    created_checks = {
        call.args[0] for call in op.create_check_constraint.call_args_list
    }
    assert created_checks == {
        "ck_batches_concurrency_limit",
        "ck_batch_items_priority",
        "ck_batch_items_attempt_count",
    }

    migration.downgrade()
    dropped = [call.args[1] for call in op.drop_column.call_args_list]
    assert dropped == ["lease_started_at", "attempt_count"]
