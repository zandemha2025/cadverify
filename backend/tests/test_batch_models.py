"""Unit tests for Batch, BatchItem, WebhookDelivery ORM models."""
from __future__ import annotations

import pytest
from ulid import ULID

from src.db.models import Batch, BatchItem, WebhookDelivery


def test_batch_model_instantiation():
    """Batch can be instantiated with required fields and generates ULID."""
    batch = Batch(
        user_id=1,
        input_mode="zip",
    )
    assert batch.user_id == 1
    assert batch.input_mode == "zip"
    # ULID default is set via column default (evaluated at flush), but we
    # can verify the model accepts manual assignment
    batch.ulid = str(ULID())
    assert len(batch.ulid) == 26  # ULID string length


def test_batch_item_model_instantiation():
    """BatchItem can be instantiated with FK to Batch."""
    item = BatchItem(
        batch_id=42,
        filename="part.stl",
    )
    assert item.batch_id == 42
    assert item.filename == "part.stl"
    item.ulid = str(ULID())
    assert len(item.ulid) == 26


def test_webhook_delivery_model_instantiation():
    """WebhookDelivery can be instantiated with FK to Batch."""
    delivery = WebhookDelivery(
        batch_id=42,
        event_type="batch_item.completed",
        payload_json={"item_ulid": "abc123", "status": "completed"},
    )
    assert delivery.batch_id == 42
    assert delivery.event_type == "batch_item.completed"
    assert delivery.payload_json["status"] == "completed"


def test_batch_model_ulid_default_callable():
    """Batch model has a callable ULID default on the ulid column."""
    col = Batch.__table__.c.ulid
    assert col.default is not None
    assert callable(col.default.arg)
    # Each call produces a unique ULID
    ulid1 = col.default.arg(None)
    ulid2 = col.default.arg(None)
    assert ulid1 != ulid2
    assert len(ulid1) == 26


def test_batch_item_ulid_default_callable():
    """BatchItem model has a callable ULID default on the ulid column."""
    col = BatchItem.__table__.c.ulid
    assert col.default is not None
    assert callable(col.default.arg)


def test_webhook_delivery_tablename():
    """WebhookDelivery has correct __tablename__."""
    assert WebhookDelivery.__tablename__ == "webhook_deliveries"


def test_batch_item_fk_to_batches():
    """BatchItem has FK to batches.id with CASCADE delete."""
    col = BatchItem.__table__.c.batch_id
    fks = list(col.foreign_keys)
    assert len(fks) == 1
    assert fks[0].target_fullname == "batches.id"
    assert fks[0].ondelete == "CASCADE"


def test_batch_item_fk_to_analyses():
    """BatchItem has FK to analyses.id with SET NULL delete."""
    col = BatchItem.__table__.c.analysis_id
    fks = list(col.foreign_keys)
    assert len(fks) == 1
    assert fks[0].target_fullname == "analyses.id"
    assert fks[0].ondelete == "SET NULL"
