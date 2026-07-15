"""Schema contract for org-scoped multipart direct uploads."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from src.db.models import DirectUpload


def _load():
    mock_op = MagicMock()
    mock_op.get_bind.return_value.dialect.name = "postgresql"
    path = (
        Path(__file__).parent.parent
        / "alembic"
        / "versions"
        / "0044_direct_uploads.py"
    )
    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        old = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            spec = importlib.util.spec_from_file_location("migration_0044_test", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            alembic.op = old
    return module, mock_op


def test_direct_upload_model_carries_tenant_lifecycle_and_cleanup_state():
    columns = DirectUpload.__table__.c
    assert columns.org_id.nullable is False
    assert columns.user_id.nullable is False
    assert columns.object_key.unique is None  # table-level named constraint
    assert columns.storage_cleaned_at.nullable is True
    assert columns.idempotency_key_hash.nullable is False
    assert columns.request_fingerprint.nullable is False
    assert columns.expected_checksum_sha256.nullable is False
    assert columns.checksum_verified_at.nullable is True
    assert columns.expires_at.nullable is False
    assert {index.name for index in DirectUpload.__table__.indexes} >= {
        "ix_direct_uploads_org_status",
        "ix_direct_uploads_status_expires",
    }
    constraints = {constraint.name for constraint in DirectUpload.__table__.constraints}
    assert "uq_direct_uploads_batch_id" in constraints
    assert "uq_direct_uploads_object_key" in constraints
    assert "uq_direct_uploads_org_idempotency" in constraints
    assert "ck_direct_uploads_hash_lengths" in constraints
    assert "ck_direct_uploads_status" in constraints


def test_migration_0044_follows_head_and_is_reversible():
    migration, op = _load()
    assert migration.revision == "0044_direct_uploads"
    assert migration.down_revision == "0043_notification_dismiss"
    assert len(migration.revision) <= 32

    migration.upgrade()
    create_args = op.create_table.call_args.args
    assert create_args[0] == "direct_uploads"
    columns = {item.name: item for item in create_args[1:] if hasattr(item, "type")}
    assert columns["org_id"].nullable is False
    assert columns["multipart_upload_id"].nullable is False
    assert columns["idempotency_key_hash"].nullable is False
    assert columns["expected_checksum_sha256"].nullable is False
    assert columns["checksum_verified_at"].nullable is True
    assert columns["storage_cleaned_at"].nullable is True
    assert op.create_index.call_count == 3

    migration.downgrade()
    op.drop_table.assert_called_once_with("direct_uploads")


def test_migration_0044_upgrade_and_downgrade_execute_against_database():
    migration, _ = _load()
    engine = sa.create_engine("sqlite://")

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE organizations (id TEXT PRIMARY KEY)"
        )
        connection.exec_driver_sql("CREATE TABLE users (id BIGINT PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE batches (id BIGINT PRIMARY KEY)")
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()

        inspector = sa.inspect(connection)
        columns = {
            column["name"]: column
            for column in inspector.get_columns("direct_uploads")
        }
        assert columns["idempotency_key_hash"]["nullable"] is False
        assert columns["request_fingerprint"]["nullable"] is False
        assert columns["expected_checksum_sha256"]["nullable"] is False
        assert columns["checksum_verified_at"]["nullable"] is True
        assert {index["name"] for index in inspector.get_indexes("direct_uploads")} == {
            "ix_direct_uploads_org_status",
            "ix_direct_uploads_status_expires",
            "ix_direct_uploads_user_created",
        }
        assert {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("direct_uploads")
        } >= {
            "uq_direct_uploads_batch_id",
            "uq_direct_uploads_object_key",
            "uq_direct_uploads_org_idempotency",
        }
        assert {
            constraint["name"]
            for constraint in inspector.get_check_constraints("direct_uploads")
        } >= {
            "ck_direct_uploads_hash_lengths",
            "ck_direct_uploads_status",
        }

        migration.downgrade()
        assert not sa.inspect(connection).has_table("direct_uploads")
