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


def test_extract_zip_accepts_iges_aliases(tmp_path, monkeypatch):
    """IGES/IGS are first-class batch CAD inputs, matching the validate route."""
    monkeypatch.setattr(
        "src.services.batch_service.BATCH_BLOB_DIR", str(tmp_path)
    )
    zip_bytes = _make_zip({
        "legacy.iges": b"IGES placeholder bytes",
        "alias.igs": b"IGS placeholder bytes",
    })
    results = extract_zip_to_items(zip_bytes, "test-batch-iges")
    assert [r["filename"] for r in results] == ["legacy.iges", "alias.igs"]
    assert all("path" in r for r in results)
    assert all(os.path.exists(r["path"]) for r in results)


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


def test_extract_zip_triages_native_and_drawing_files(tmp_path, monkeypatch):
    """Native CAD/drawing files become visible skipped rows, not silent drops."""
    monkeypatch.setattr(
        "src.services.batch_service.BATCH_BLOB_DIR", str(tmp_path)
    )
    zip_bytes = _make_zip({
        "assembly/gearbox.SLDASM": b"solidworks assembly",
        "drawings/plate.DWG": b"autocad drawing",
        "readme.txt": b"still ignored",
        "part.step": b"ISO-10303-21; fake step data",
    })
    results = extract_zip_to_items(zip_bytes, "test-batch-triage")
    by_name = {r["filename"]: r for r in results}
    assert set(by_name) == {"gearbox.SLDASM", "plate.DWG", "part.step"}
    assert by_name["part.step"]["path"]
    assert by_name["gearbox.SLDASM"]["status"] == "skipped"
    assert "Unsupported native CAD file type .sldasm" in by_name["gearbox.SLDASM"]["error"]
    assert by_name["plate.DWG"]["status"] == "skipped"
    assert "Unsupported drawing file type .dwg" in by_name["plate.DWG"]["error"]


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


def test_touch_batch_heartbeat_reassigns_manifest():
    from datetime import datetime, timezone
    from unittest.mock import MagicMock

    from src.db.models import Batch
    from src.services.batch_service import touch_batch_heartbeat

    batch = MagicMock(spec=Batch)
    batch.manifest_json = {"failure_reason": None, "keep": "me"}
    ts = datetime(2026, 7, 2, 12, 0, 0, tzinfo=timezone.utc)
    touch_batch_heartbeat(batch, now=ts)
    assert batch.manifest_json["heartbeat_at"] == ts.isoformat()
    assert batch.manifest_json["keep"] == "me"  # existing keys preserved


@pytest.mark.asyncio
async def test_sweep_reaps_stale_heartbeat_not_fresh():
    """Heartbeat-based staleness (F-ARCH-6/#2): reap a batch whose coordinator
    heartbeat has gone stale, but NEVER a legitimately long batch that is still
    ticking -- even when its started_at is far past the wall-clock TTL."""
    from datetime import datetime, timedelta, timezone
    from unittest.mock import AsyncMock, MagicMock

    from src.db.models import Batch
    from src.services.batch_service import sweep_orphaned_batches

    now = datetime(2026, 7, 2, 12, 0, 0, tzinfo=timezone.utc)

    stale = MagicMock(spec=Batch)
    stale.ulid = "STALE"
    stale.status = "processing"
    stale.started_at = now - timedelta(minutes=30)
    stale.created_at = now - timedelta(minutes=31)
    stale.manifest_json = {"heartbeat_at": (now - timedelta(seconds=120)).isoformat()}

    # Running for 10h (well past the 6h fixed TTL) but heartbeat is 3s old: alive.
    fresh = MagicMock(spec=Batch)
    fresh.ulid = "FRESH"
    fresh.status = "processing"
    fresh.started_at = now - timedelta(hours=10)
    fresh.created_at = now - timedelta(hours=10)
    fresh.manifest_json = {"heartbeat_at": (now - timedelta(seconds=3)).isoformat()}

    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = [stale, fresh]
    session.execute.return_value = exec_result

    reaped = await sweep_orphaned_batches(session, heartbeat_stale_seconds=30, now=now)

    assert reaped == 1
    assert stale.status == "failed"
    assert stale.manifest_json["failure_reason"] == "orphaned"
    assert fresh.status == "processing"  # long-running but alive -> untouched


@pytest.mark.asyncio
async def test_sweep_falls_back_to_ttl_when_no_heartbeat():
    """A batch whose coordinator never wrote a heartbeat is reaped via the
    wall-clock started_at TTL fallback, not the heartbeat window."""
    from datetime import datetime, timedelta, timezone
    from unittest.mock import AsyncMock, MagicMock

    from src.db.models import Batch
    from src.services.batch_service import sweep_orphaned_batches

    now = datetime(2026, 7, 2, 12, 0, 0, tzinfo=timezone.utc)

    old_no_hb = MagicMock(spec=Batch)
    old_no_hb.ulid = "OLD_NO_HB"
    old_no_hb.status = "processing"
    old_no_hb.started_at = now - timedelta(hours=10)
    old_no_hb.created_at = now - timedelta(hours=11)
    old_no_hb.manifest_json = None  # coordinator never ran / never ticked

    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = [old_no_hb]
    session.execute.return_value = exec_result

    # Tight heartbeat window would NOT matter (no heartbeat); TTL fallback fires.
    reaped = await sweep_orphaned_batches(
        session, ttl_seconds=6 * 3600, heartbeat_stale_seconds=30, now=now
    )

    assert reaped == 1
    assert old_no_hb.status == "failed"
    assert old_no_hb.manifest_json["failure_reason"] == "orphaned"


def test_heartbeat_stale_floor_is_600_not_60():
    """B2: the default heartbeat-stale floor must be 600s, not the old 60s.

    run_batch_coordinator's re-enqueued ticks and every batch item
    (run_batch_item) share the SAME 12-slot arq pool, each job up to
    job_timeout=600s. Under pool saturation, or a deploy pause/worker
    restart, the NEXT heartbeat refresh for a perfectly healthy batch can be
    delayed well past 60s. A 60s floor treated that delay as death and
    permanently stranded the batch's not-yet-queued items. 600s matches the
    real worst-case delay (one more full-length job draining from the shared
    pool) before a tick or item can refresh the heartbeat again.
    """
    from src.services import batch_service as bs

    assert bs.BATCH_HEARTBEAT_STALE_FLOOR_SECONDS == 600
    # FACTOR(10) * default poll interval(2) = 20s, far under the floor, so the
    # floor -- not the factor -- determines the default.
    assert bs.BATCH_HEARTBEAT_STALE_SECONDS >= 600


@pytest.mark.asyncio
async def test_sweep_survives_batch_whose_heartbeat_is_90_to_600s_old():
    """B3 (verifier's reproduction): a batch whose heartbeat is stale by the
    OLD 60s floor's standard (90-600s old) but still within the NEW 600s
    floor must SURVIVE the sweeper using the DEFAULT staleness window (no
    override) -- proving the raised floor, not just an explicit test
    parameter, is what protects it.

    This is exactly the verifier's failure mode: a coordinator tick delayed
    by arq pool saturation, or a >60s deploy pause, used to falsely orphan a
    live batch. Whether the heartbeat was last touched by the coordinator's
    own tick or by an item completing (see B1 in batch_tasks.run_batch_item)
    is irrelevant here -- both write the same manifest_json['heartbeat_at']
    field, so either source keeps this batch alive.
    """
    from datetime import datetime, timedelta, timezone
    from unittest.mock import AsyncMock, MagicMock

    from src.db.models import Batch
    from src.services.batch_service import sweep_orphaned_batches

    now = datetime(2026, 7, 2, 12, 0, 0, tzinfo=timezone.utc)

    for age_seconds in (90, 300, 599):
        batch = MagicMock(spec=Batch)
        batch.ulid = f"LIVE_{age_seconds}"
        batch.status = "processing"
        batch.started_at = now - timedelta(hours=2)
        batch.created_at = now - timedelta(hours=2, minutes=1)
        batch.manifest_json = {
            "heartbeat_at": (now - timedelta(seconds=age_seconds)).isoformat()
        }

        session = AsyncMock()
        exec_result = MagicMock()
        exec_result.scalars.return_value.all.return_value = [batch]
        session.execute.return_value = exec_result

        # No heartbeat_stale_seconds override -- exercises the real default,
        # which must now be floored at 600s.
        reaped = await sweep_orphaned_batches(session, now=now)

        assert reaped == 0, f"age={age_seconds}s should survive under the 600s floor"
        assert batch.status == "processing"


@pytest.mark.asyncio
async def test_sweep_reaps_batch_with_no_activity_beyond_the_floor():
    """B3: a batch with no coordinator heartbeat AND no item activity beyond
    the (new, 600s) floor is reaped -- the raised floor protects legitimately
    live batches but must not disable reaping of genuinely dead ones."""
    from datetime import datetime, timedelta, timezone
    from unittest.mock import AsyncMock, MagicMock

    from src.db.models import Batch
    from src.services.batch_service import sweep_orphaned_batches

    now = datetime(2026, 7, 2, 12, 0, 0, tzinfo=timezone.utc)

    dead = MagicMock(spec=Batch)
    dead.ulid = "DEAD"
    dead.status = "processing"
    dead.started_at = now - timedelta(hours=2)
    dead.created_at = now - timedelta(hours=2, minutes=1)
    # Last heartbeat (from either the coordinator or an item) is older than
    # the 600s floor: no activity of any kind for over 10 minutes.
    dead.manifest_json = {"heartbeat_at": (now - timedelta(seconds=650)).isoformat()}

    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = [dead]
    session.execute.return_value = exec_result

    reaped = await sweep_orphaned_batches(session, now=now)

    assert reaped == 1
    assert dead.status == "failed"
    assert dead.manifest_json["failure_reason"] == "orphaned"


@pytest.mark.asyncio
async def test_mark_pending_items_terminal_updates_non_terminal_only():
    """F-ARCH-1/#3: on enqueue failure, non-terminal items are moved to a
    terminal state so progress reads stay consistent."""
    from unittest.mock import AsyncMock

    from src.services.batch_service import mark_pending_items_terminal

    session = AsyncMock()
    await mark_pending_items_terminal(session, batch_id=7, terminal_status="skipped")

    session.execute.assert_awaited_once()
    args, kwargs = session.execute.await_args
    sql = str(args[0]).lower()
    assert "update batch_items" in sql
    # Only non-terminal rows are touched.
    assert "'pending'" in sql and "'queued'" in sql and "'processing'" in sql
    assert args[1] == {"s": "skipped", "b": 7}
