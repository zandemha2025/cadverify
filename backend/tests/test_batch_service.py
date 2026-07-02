"""Unit tests for batch_service module."""
from __future__ import annotations

import io
import os
import zipfile

import pytest

from src.services.batch_service import (
    BATCH_MAX_FILE_BYTES,
    BATCH_MAX_ITEMS,
    DEFAULT_BATCH_CONCURRENCY,
    MAX_COMPRESSION_RATIO,
    extract_zip_to_items,
    parse_csv_manifest,
)


# ---------------------------------------------------------------------------
# CSV manifest parsing
# ---------------------------------------------------------------------------


def test_parse_csv_manifest_valid():
    """Parse valid CSV with all 4 columns."""
    csv_content = (
        "filename,process_types,rule_pack,priority\n"
        "part1.stl,fdm,automotive,high\n"
        "part2.step,cnc_milling,aerospace,normal\n"
    )
    items = parse_csv_manifest(csv_content)
    assert len(items) == 2
    assert items[0]["filename"] == "part1.stl"
    assert items[0]["process_types"] == "fdm"
    assert items[0]["rule_pack"] == "automotive"
    assert items[0]["priority"] == "high"
    assert items[1]["filename"] == "part2.step"
    assert items[1]["priority"] == "normal"


def test_parse_csv_manifest_missing_filename():
    """Raises ValueError when filename column is missing."""
    csv_content = "process_types,rule_pack\nfdm,automotive\n"
    with pytest.raises(ValueError, match="filename"):
        parse_csv_manifest(csv_content)


def test_parse_csv_manifest_default_priority():
    """Missing priority defaults to 'normal'."""
    csv_content = "filename\npart1.stl\npart2.step\n"
    items = parse_csv_manifest(csv_content)
    assert len(items) == 2
    assert items[0]["priority"] == "normal"
    assert items[1]["priority"] == "normal"


def test_parse_csv_manifest_invalid_priority():
    """Raises ValueError on invalid priority value."""
    csv_content = "filename,priority\npart1.stl,urgent\n"
    with pytest.raises(ValueError, match="invalid priority"):
        parse_csv_manifest(csv_content)


def test_parse_csv_manifest_optional_columns_empty():
    """Optional columns default to None when empty."""
    csv_content = "filename,process_types,rule_pack,priority\npart.stl,,,\n"
    items = parse_csv_manifest(csv_content)
    assert items[0]["process_types"] is None
    assert items[0]["rule_pack"] is None
    assert items[0]["priority"] == "normal"  # empty -> default


# ---------------------------------------------------------------------------
# ZIP extraction helpers
# ---------------------------------------------------------------------------


def _make_zip(files: dict[str, bytes]) -> bytes:
    """Create an in-memory ZIP from {filename: content} dict."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _make_zip_with_ratio(filename: str, uncompressed_size: int) -> bytes:
    """Create a ZIP with a file that has a high compression ratio (repeated bytes)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Highly compressible data (all zeros)
        zf.writestr(filename, b"\x00" * uncompressed_size)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# ZIP extraction tests
# ---------------------------------------------------------------------------


def test_extract_zip_valid(tmp_path, monkeypatch):
    """Extract ZIP with 2 STL files, verify paths."""
    monkeypatch.setattr(
        "src.services.batch_service.BATCH_BLOB_DIR", str(tmp_path)
    )
    zip_bytes = _make_zip({
        "part1.stl": b"solid part1\nendsolid",
        "part2.stp": b"ISO-10303-21; fake step data",
    })
    results = extract_zip_to_items(zip_bytes, "test-batch-001")
    assert len(results) == 2
    for r in results:
        assert "path" in r
        assert os.path.exists(r["path"])
        assert r["size"] > 0


def test_extract_zip_ignores_non_cad(tmp_path, monkeypatch):
    """ZIP with .txt files skips them silently."""
    monkeypatch.setattr(
        "src.services.batch_service.BATCH_BLOB_DIR", str(tmp_path)
    )
    zip_bytes = _make_zip({
        "readme.txt": b"not a CAD file",
        "part.stl": b"solid test\nendsolid",
        "notes.pdf": b"PDF content",
    })
    results = extract_zip_to_items(zip_bytes, "test-batch-002")
    assert len(results) == 1
    assert results[0]["filename"] == "part.stl"


def test_extract_zip_oversized_file_skipped(tmp_path, monkeypatch):
    """File >BATCH_MAX_FILE_BYTES results in status='skipped'."""
    monkeypatch.setattr(
        "src.services.batch_service.BATCH_BLOB_DIR", str(tmp_path)
    )
    # Temporarily lower the limit for testing
    monkeypatch.setattr("src.services.batch_service.BATCH_MAX_FILE_BYTES", 100)

    zip_bytes = _make_zip({
        "small.stl": b"solid small\nendsolid",
        "big.stl": b"x" * 200,  # exceeds 100 byte limit
    })
    results = extract_zip_to_items(zip_bytes, "test-batch-003")
    assert len(results) == 2
    small = [r for r in results if r["filename"] == "small.stl"][0]
    big = [r for r in results if r["filename"] == "big.stl"][0]
    assert "path" in small
    assert big["status"] == "skipped"
    assert "exceeds limit" in big["error"]


def test_extract_zip_bomb_rejected(tmp_path, monkeypatch):
    """ZIP with >100:1 compression ratio raises ValueError."""
    monkeypatch.setattr(
        "src.services.batch_service.BATCH_BLOB_DIR", str(tmp_path)
    )
    # Create highly compressible data (zeros compress extremely well)
    zip_bytes = _make_zip_with_ratio("bomb.stl", 10 * 1024 * 1024)

    # Verify the ratio is actually high enough
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        info = zf.infolist()[0]
        if info.compress_size > 0:
            ratio = info.file_size / info.compress_size
            assert ratio > MAX_COMPRESSION_RATIO, (
                f"Test setup: ratio {ratio:.0f} must exceed {MAX_COMPRESSION_RATIO}"
            )

    with pytest.raises(ValueError, match="zip bomb"):
        extract_zip_to_items(zip_bytes, "test-batch-bomb")


def test_extract_zip_max_items_exceeded(tmp_path, monkeypatch):
    """ZIP with >BATCH_MAX_ITEMS files raises ValueError."""
    monkeypatch.setattr(
        "src.services.batch_service.BATCH_BLOB_DIR", str(tmp_path)
    )
    monkeypatch.setattr("src.services.batch_service.BATCH_MAX_ITEMS", 3)

    files = {f"part{i}.stl": b"solid\nendsolid" for i in range(5)}
    zip_bytes = _make_zip(files)

    with pytest.raises(ValueError, match="exceeding limit"):
        extract_zip_to_items(zip_bytes, "test-batch-overflow")


def test_extract_zip_path_traversal_prevention(tmp_path, monkeypatch):
    """Path traversal attempts are sanitized via os.path.basename()."""
    monkeypatch.setattr(
        "src.services.batch_service.BATCH_BLOB_DIR", str(tmp_path)
    )
    zip_bytes = _make_zip({
        "../../../etc/passwd.stl": b"traversal attempt",
        "subdir/nested/part.stl": b"nested file",
    })
    results = extract_zip_to_items(zip_bytes, "test-batch-traversal")
    # Both should be extracted with safe names (basename only)
    for r in results:
        if "path" in r:
            assert ".." not in r["path"]
            dirname = os.path.dirname(r["path"])
            assert dirname == os.path.join(str(tmp_path), "test-batch-traversal")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_concurrency_limit_default():
    """Verify DEFAULT_BATCH_CONCURRENCY=10."""
    assert DEFAULT_BATCH_CONCURRENCY == 10


# ---------------------------------------------------------------------------
# Basename dedup (F-ARCH-9): same-named files in different folders must not
# silently collapse.
# ---------------------------------------------------------------------------


def test_extract_zip_dedups_same_basename_across_folders(tmp_path, monkeypatch):
    monkeypatch.setattr("src.services.batch_service.BATCH_BLOB_DIR", str(tmp_path))
    zip_bytes = _make_zip({
        "a/part.stl": b"solid A\nendsolid",
        "b/part.stl": b"solid B\nendsolid",
    })
    results = extract_zip_to_items(zip_bytes, "dedup-batch")
    names = sorted(r["filename"] for r in results)
    assert names == ["part.stl", "part_1.stl"]
    # Both files land on distinct paths, both present on disk (no collapse).
    paths = [r["path"] for r in results]
    assert len(set(paths)) == 2
    for p in paths:
        assert os.path.exists(p)


def test_extract_zip_dedup_off_switch(tmp_path, monkeypatch):
    """BATCH_ZIP_DEDUP=0 restores flat last-wins basenames (documented off-switch)."""
    monkeypatch.setattr("src.services.batch_service.BATCH_BLOB_DIR", str(tmp_path))
    monkeypatch.setenv("BATCH_ZIP_DEDUP", "0")
    zip_bytes = _make_zip({
        "a/part.stl": b"solid A\nendsolid",
        "b/part.stl": b"solid B\nendsolid",
    })
    results = extract_zip_to_items(zip_bytes, "dedup-off")
    assert all(r["filename"] == "part.stl" for r in results)


# ---------------------------------------------------------------------------
# Streaming upload with early rejection (F-ARCH-9)
# ---------------------------------------------------------------------------


class _FakeUpload:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    async def read(self, n):
        return self._chunks.pop(0) if self._chunks else b""


@pytest.mark.asyncio
async def test_stream_upload_rejects_oversize_early():
    from src.services.batch_service import stream_upload_to_tempfile, ZipTooLargeError

    up = _FakeUpload([b"x" * 10, b"y" * 10])
    with pytest.raises(ZipTooLargeError):
        await stream_upload_to_tempfile(up, max_bytes=15)


@pytest.mark.asyncio
async def test_stream_upload_writes_and_returns_path():
    from src.services.batch_service import stream_upload_to_tempfile

    up = _FakeUpload([b"hello", b"world"])
    path = await stream_upload_to_tempfile(up, max_bytes=1000)
    try:
        with open(path, "rb") as f:
            assert f.read() == b"helloworld"
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# Orphan sweep (F-ARCH-1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_orphaned_batches_marks_stale_only():
    from datetime import datetime, timedelta, timezone
    from unittest.mock import AsyncMock, MagicMock

    from src.db.models import Batch
    from src.services.batch_service import sweep_orphaned_batches

    now = datetime(2026, 7, 2, 12, 0, 0, tzinfo=timezone.utc)

    stale = MagicMock(spec=Batch)
    stale.ulid = "OLD"
    stale.status = "processing"
    stale.started_at = now - timedelta(hours=10)
    stale.created_at = now - timedelta(hours=11)
    stale.manifest_json = None

    fresh = MagicMock(spec=Batch)
    fresh.ulid = "NEW"
    fresh.status = "pending"
    fresh.started_at = None
    fresh.created_at = now - timedelta(minutes=5)
    fresh.manifest_json = None

    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = [stale, fresh]
    session.execute.return_value = exec_result

    reaped = await sweep_orphaned_batches(session, ttl_seconds=6 * 3600, now=now)

    assert reaped == 1
    assert stale.status == "failed"
    assert stale.manifest_json["failure_reason"] == "orphaned"
    assert fresh.status == "pending"  # untouched


def test_mark_batch_failed_preserves_existing_manifest():
    from unittest.mock import MagicMock

    from src.db.models import Batch
    from src.services.batch_service import mark_batch_failed

    batch = MagicMock(spec=Batch)
    batch.manifest_json = {"s3_bucket": "b"}
    mark_batch_failed(batch, "enqueue_failed")
    assert batch.status == "failed"
    assert batch.manifest_json["failure_reason"] == "enqueue_failed"
    assert batch.manifest_json["s3_bucket"] == "b"  # not clobbered
