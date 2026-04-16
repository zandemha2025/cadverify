"""Tests for async job endpoints and job_service functions.

Covers:
- GET /api/v1/jobs/{id} status polling
- GET /api/v1/jobs/{id}/result retrieval
- Auth scoping (404 for other user's jobs)
- Idempotent job creation
- Idempotent mesh blob storage
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.auth.require_api_key import AuthedUser
from src.db.models import Job
from src.services import job_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_job(
    ulid: str = "01TEST000000000000000001",
    user_id: int = 42,
    analysis_id: int = 1,
    job_type: str = "sam3d",
    status: str = "queued",
    result_json: dict | None = None,
    created_at: datetime | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> MagicMock:
    """Create a Job-like mock for testing (no DB required)."""
    job = MagicMock(spec=Job)
    job.id = 1
    job.ulid = ulid
    job.user_id = user_id
    job.analysis_id = analysis_id
    job.job_type = job_type
    job.status = status
    job.result_json = result_json
    job.params_json = {"mesh_hash": "abc123"}
    job.created_at = created_at or datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
    job.started_at = started_at
    job.completed_at = completed_at
    return job


def _fake_user(user_id: int = 42) -> AuthedUser:
    return AuthedUser(user_id=user_id, api_key_id=101, key_prefix="test_pfx")


# ---------------------------------------------------------------------------
# GET /api/v1/jobs/{id} — status polling
# ---------------------------------------------------------------------------

class TestGetJobStatus:
    """Tests for the job status polling endpoint."""

    @pytest.mark.asyncio
    async def test_get_job_status_queued(self):
        """GET /jobs/{id} returns status=queued with no result_url."""
        job = _make_job(status="queued")

        with patch.object(job_service, "get_job_for_user", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = job

            from src.api.jobs_router import get_job_status

            # Build mock dependencies
            mock_session = AsyncMock()
            user = _fake_user(user_id=42)

            result = await get_job_status(
                job_id=job.ulid,
                user=user,
                session=mock_session,
            )

            assert result["job_id"] == job.ulid
            assert result["status"] == "queued"
            assert result["job_type"] == "sam3d"
            assert result["result_url"] is None
            mock_get.assert_awaited_once_with(mock_session, job.ulid, 42)

    @pytest.mark.asyncio
    async def test_get_job_status_done_has_result_url(self):
        """GET /jobs/{id} returns result_url when status is done."""
        job = _make_job(
            status="done",
            completed_at=datetime(2026, 4, 15, 12, 1, 5, tzinfo=timezone.utc),
        )

        with patch.object(job_service, "get_job_for_user", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = job

            from src.api.jobs_router import get_job_status

            result = await get_job_status(
                job_id=job.ulid,
                user=_fake_user(),
                session=AsyncMock(),
            )

            assert result["status"] == "done"
            assert result["result_url"] == f"/api/v1/jobs/{job.ulid}/result"
            assert result["completed_at"] is not None

    @pytest.mark.asyncio
    async def test_job_404_other_user(self):
        """GET /jobs/{id} returns 404 for another user's job (D-12)."""
        with patch.object(job_service, "get_job_for_user", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None  # not found for this user

            from fastapi import HTTPException
            from src.api.jobs_router import get_job_status

            with pytest.raises(HTTPException) as exc_info:
                await get_job_status(
                    job_id="01NONEXISTENT",
                    user=_fake_user(user_id=99),  # different user
                    session=AsyncMock(),
                )

            assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/jobs/{id}/result
# ---------------------------------------------------------------------------

class TestGetJobResult:
    """Tests for the job result retrieval endpoint."""

    @pytest.mark.asyncio
    async def test_job_result_not_ready(self):
        """GET /jobs/{id}/result returns 404 when job is still running."""
        job = _make_job(status="running")

        with patch.object(job_service, "get_job_for_user", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = job

            from fastapi import HTTPException
            from src.api.jobs_router import get_job_result

            with pytest.raises(HTTPException) as exc_info:
                await get_job_result(
                    job_id=job.ulid,
                    user=_fake_user(),
                    session=AsyncMock(),
                )

            assert exc_info.value.status_code == 404
            assert "not yet available" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_job_result_done(self):
        """GET /jobs/{id}/result returns full result when status is done."""
        segments = {"segments": [{"id": 1, "type": "hole", "confidence": 0.95}]}
        job = _make_job(status="done", result_json=segments)

        with patch.object(job_service, "get_job_for_user", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = job

            from src.api.jobs_router import get_job_result

            result = await get_job_result(
                job_id=job.ulid,
                user=_fake_user(),
                session=AsyncMock(),
            )

            assert result["job_id"] == job.ulid
            assert result["status"] == "done"
            assert result["result"]["segments"][0]["type"] == "hole"

    @pytest.mark.asyncio
    async def test_job_result_partial(self):
        """GET /jobs/{id}/result returns result for partial (fallback) status."""
        job = _make_job(status="partial", result_json={"segments": [], "fallback": True})

        with patch.object(job_service, "get_job_for_user", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = job

            from src.api.jobs_router import get_job_result

            result = await get_job_result(
                job_id=job.ulid,
                user=_fake_user(),
                session=AsyncMock(),
            )

            assert result["status"] == "partial"
            assert result["result"]["fallback"] is True


# ---------------------------------------------------------------------------
# Idempotent job creation
# ---------------------------------------------------------------------------

class TestIdempotentJobCreation:
    """Tests for create_sam3d_job idempotency."""

    @pytest.mark.asyncio
    async def test_idempotent_returns_existing_job(self):
        """Calling create_sam3d_job twice returns the same job."""
        existing_job = _make_job(ulid="01EXISTING0000000000001")

        session = AsyncMock()
        exec_result = MagicMock()
        exec_result.scalars.return_value.first.return_value = existing_job
        session.execute.return_value = exec_result

        result = await job_service.create_sam3d_job(
            session=session,
            analysis_id=1,
            user_id=42,
            mesh_hash="abc123",
        )

        assert result.ulid == "01EXISTING0000000000001"
        # Should not have called session.add (no new job created)
        assert not hasattr(session, '_added') or len(getattr(session, '_added', [])) == 0

    @pytest.mark.asyncio
    async def test_creates_new_job_when_none_exists(self):
        """create_sam3d_job creates a new job when no existing one found."""
        session = AsyncMock()
        exec_result = MagicMock()
        exec_result.scalars.return_value.first.return_value = None
        session.execute.return_value = exec_result

        added_objects = []
        session.add = lambda obj: added_objects.append(obj)

        async def _fake_flush():
            for obj in added_objects:
                if hasattr(obj, "id") and obj.id is None:
                    obj.id = 99

        session.flush = _fake_flush

        result = await job_service.create_sam3d_job(
            session=session,
            analysis_id=1,
            user_id=42,
            mesh_hash="abc123",
        )

        assert result.job_type == "sam3d"
        assert result.status == "queued"
        assert result.analysis_id == 1
        assert result.user_id == 42
        assert len(added_objects) == 1


# ---------------------------------------------------------------------------
# Mesh blob storage
# ---------------------------------------------------------------------------

class TestSaveMeshBlob:
    """Tests for save_mesh_blob idempotency."""

    @pytest.mark.asyncio
    async def test_save_mesh_blob_creates_file(self):
        """save_mesh_blob writes file and returns path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"MESH_BLOB_DIR": tmpdir}):
                path = await job_service.save_mesh_blob("deadbeef", b"mesh-data")

                assert os.path.exists(path)
                assert path.endswith("deadbeef.bin")
                with open(path, "rb") as f:
                    assert f.read() == b"mesh-data"

    @pytest.mark.asyncio
    async def test_save_mesh_blob_idempotent(self):
        """Calling save_mesh_blob twice with same hash does not overwrite."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"MESH_BLOB_DIR": tmpdir}):
                path1 = await job_service.save_mesh_blob("deadbeef", b"original")
                path2 = await job_service.save_mesh_blob("deadbeef", b"different")

                assert path1 == path2
                # Content should be the original (not overwritten)
                with open(path1, "rb") as f:
                    assert f.read() == b"original"
