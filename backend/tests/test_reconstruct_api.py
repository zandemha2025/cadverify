"""Tests for reconstruct_router endpoints and reconstruction task auto-feed.

Uses mocked dependencies (no real DB, reconstruction engine, or rembg).
"""
from __future__ import annotations

import io
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import trimesh
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from src.api.reconstruct_router import router
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session
from src.db.models import Job

# ---------------------------------------------------------------------------
# Test app setup
# ---------------------------------------------------------------------------

app = FastAPI()
app.include_router(router)

_TEST_USER = AuthedUser(user_id=42, api_key_id=1, key_prefix="cv_live_test")
_OTHER_USER = AuthedUser(user_id=99, api_key_id=2, key_prefix="cv_live_other")


def _override_auth():
    return _TEST_USER


def _override_auth_other():
    return _OTHER_USER


def _override_session():
    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.first.return_value = None
    session.execute.return_value = exec_result
    return session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_test_image_bytes(fmt: str = "PNG") -> bytes:
    """Create a small test image as bytes."""
    img = Image.new("RGB", (256, 256), color=(128, 128, 128))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def _make_job(
    ulid: str = "01RECON0000000000000001",
    user_id: int = 42,
    status: str = "queued",
    result_json: dict | None = None,
) -> MagicMock:
    job = MagicMock(spec=Job)
    job.id = 1
    job.ulid = ulid
    job.user_id = user_id
    job.job_type = "reconstruction"
    job.status = status
    job.params_json = {"image_count": 1, "process_types": None, "rule_pack": None}
    job.result_json = result_json
    job.created_at = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
    job.started_at = None
    job.completed_at = None
    return job


# ---------------------------------------------------------------------------
# Tests: POST /api/v1/reconstruct
# ---------------------------------------------------------------------------


class TestReconstructEndpoint:
    """Tests for POST /api/v1/reconstruct."""

    def test_reconstruct_endpoint_202(self):
        """POST with 1 image returns 202 with job_id, status, poll_url, estimated_seconds."""
        test_app = FastAPI()
        test_app.include_router(router)
        test_app.dependency_overrides[require_api_key] = _override_auth
        test_app.dependency_overrides[get_db_session] = _override_session

        mock_job = _make_job()

        with patch(
            "src.services.reconstruction_service.create_reconstruction_job",
            new_callable=AsyncMock,
            return_value=mock_job,
        ):
            client = TestClient(test_app)
            img_bytes = _make_test_image_bytes()
            resp = client.post(
                "/api/v1/reconstruct",
                files=[("images", ("test.png", img_bytes, "image/png"))],
            )

        assert resp.status_code == 202
        body = resp.json()
        assert body["job_id"] == mock_job.ulid
        assert body["status"] == "queued"
        assert "poll_url" in body
        assert body["estimated_seconds"] == 30

    def test_reconstruct_rejects_no_images(self):
        """POST with no images returns 422 (FastAPI validation)."""
        test_app = FastAPI()
        test_app.include_router(router)
        test_app.dependency_overrides[require_api_key] = _override_auth
        test_app.dependency_overrides[get_db_session] = _override_session

        client = TestClient(test_app)
        resp = client.post("/api/v1/reconstruct")
        assert resp.status_code == 422

    def test_reconstruct_rejects_too_many_images(self):
        """POST with 5 images returns 400."""
        test_app = FastAPI()
        test_app.include_router(router)
        test_app.dependency_overrides[require_api_key] = _override_auth
        test_app.dependency_overrides[get_db_session] = _override_session

        client = TestClient(test_app)
        img_bytes = _make_test_image_bytes()
        files = [("images", (f"img{i}.png", img_bytes, "image/png")) for i in range(5)]
        resp = client.post("/api/v1/reconstruct", files=files)
        assert resp.status_code == 400
        assert "1-4" in resp.json()["detail"]

    def test_reconstruct_requires_auth(self):
        """POST without auth override returns 401."""
        test_app = FastAPI()
        test_app.include_router(router)
        # No auth override -- require_api_key will reject
        test_app.dependency_overrides[get_db_session] = _override_session

        client = TestClient(test_app)
        img_bytes = _make_test_image_bytes()
        resp = client.post(
            "/api/v1/reconstruct",
            files=[("images", ("test.png", img_bytes, "image/png"))],
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/reconstructions/{id}/mesh.stl
# ---------------------------------------------------------------------------


class TestMeshDownload:
    """Tests for GET /api/v1/reconstructions/{id}/mesh.stl."""

    def test_mesh_download(self, tmp_path):
        """GET returns 200 with STL content after job completes."""
        test_app = FastAPI()
        test_app.include_router(router)
        test_app.dependency_overrides[require_api_key] = _override_auth
        test_app.dependency_overrides[get_db_session] = _override_session

        # Write a test STL to disk
        mesh = trimesh.creation.box(extents=[10, 10, 10])
        stl_path = str(tmp_path / "mesh.stl")
        mesh.export(stl_path)

        with patch(
            "src.services.reconstruction_service.get_reconstruction_mesh_path",
            new_callable=AsyncMock,
            return_value=stl_path,
        ):
            client = TestClient(test_app)
            resp = client.get("/api/v1/reconstructions/01RECON0000000000000001/mesh.stl")

        assert resp.status_code == 200
        assert "application/sla" in resp.headers.get("content-type", "")

    def test_mesh_download_wrong_user(self):
        """GET with different user returns 404 (IDOR protection)."""
        test_app = FastAPI()
        test_app.include_router(router)
        test_app.dependency_overrides[require_api_key] = _override_auth_other
        test_app.dependency_overrides[get_db_session] = _override_session

        with patch(
            "src.services.reconstruction_service.get_reconstruction_mesh_path",
            new_callable=AsyncMock,
            return_value=None,  # service returns None for wrong user
        ):
            client = TestClient(test_app)
            resp = client.get("/api/v1/reconstructions/01RECON0000000000000001/mesh.stl")

        assert resp.status_code == 404

    def test_mesh_download_job_not_done(self):
        """GET before job completes returns 404."""
        test_app = FastAPI()
        test_app.include_router(router)
        test_app.dependency_overrides[require_api_key] = _override_auth
        test_app.dependency_overrides[get_db_session] = _override_session

        with patch(
            "src.services.reconstruction_service.get_reconstruction_mesh_path",
            new_callable=AsyncMock,
            return_value=None,  # service returns None for incomplete job
        ):
            client = TestClient(test_app)
            resp = client.get("/api/v1/reconstructions/01RECON0000000000000001/mesh.stl")

        assert resp.status_code == 404
        assert "not complete" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Tests: Auto-feed to analysis
# ---------------------------------------------------------------------------


class TestAutoFeed:
    """Test that reconstruction task auto-feeds into analysis pipeline."""

    @pytest.mark.asyncio
    async def test_auto_feed_to_validate(self, tmp_path):
        """After reconstruction, result_json contains analysis_id and analysis_url."""
        from src.reconstruction.engine import ReconstructResult

        # Prepare test STL bytes
        mesh = trimesh.creation.box(extents=[10, 10, 10])
        stl_buf = io.BytesIO()
        mesh.export(stl_buf, file_type="stl")
        stl_bytes = stl_buf.getvalue()

        # Create a mock reconstruction result
        mock_result = ReconstructResult(
            mesh_bytes=stl_bytes,
            face_count=12,
            duration_ms=1234.5,
            method="triposr_remote",
        )

        # Set up blob dir with test images
        blob_dir = str(tmp_path / "blobs")
        job_ulid = "01RECON0000000000000001"
        input_dir = os.path.join(blob_dir, job_ulid, "input")
        os.makedirs(input_dir, exist_ok=True)

        img_bytes = _make_test_image_bytes()
        with open(os.path.join(input_dir, "image_000.png"), "wb") as f:
            f.write(img_bytes)

        # Mock job
        mock_job = MagicMock(spec=Job)
        mock_job.ulid = job_ulid
        mock_job.user_id = 42
        mock_job.status = "queued"
        mock_job.params_json = {
            "image_count": 1,
            "process_types": "fdm",
            "rule_pack": None,
        }
        mock_job.result_json = None
        mock_job.started_at = None
        mock_job.completed_at = None

        # Mock analysis row
        mock_analysis = MagicMock()
        mock_analysis.id = 10
        mock_analysis.ulid = "01ANALYSIS000000000001"

        # Build mock session
        mock_session = AsyncMock()
        exec_result = MagicMock()
        exec_result.scalars.return_value.first.side_effect = [
            mock_job,  # first call: load job
            mock_analysis,  # for analysis row lookup
        ]
        exec_result.scalar_one_or_none.return_value = 10  # analysis id
        mock_session.execute.return_value = exec_result

        mock_session_factory = MagicMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        # Mock engine
        mock_engine = AsyncMock()
        mock_engine.reconstruct.return_value = mock_result

        with (
            patch("src.db.engine.get_session_factory", return_value=mock_session_factory),
            patch("src.services.reconstruction_service.RECON_BLOB_DIR", blob_dir),
            patch("src.services.reconstruction_service.get_reconstruction_engine", return_value=mock_engine),
            patch("src.services.reconstruction_service.save_reconstruction_mesh", new_callable=AsyncMock, return_value=str(tmp_path / "mesh.stl")),
            patch("src.reconstruction.preprocessing.remove_background", side_effect=lambda img: img),
            patch("src.services.analysis_service.run_analysis", new_callable=AsyncMock, return_value={"verdict": "pass"}),
            patch("src.services.analysis_service.get_latest_analysis_id", new_callable=AsyncMock, return_value=10),
            patch("src.services.analysis_service.compute_mesh_hash", return_value="fakehash"),
        ):
            from src.jobs.reconstruction_tasks import run_reconstruction_job

            result = await run_reconstruction_job({}, job_ulid)

        assert result.get("analysis_id") == "01ANALYSIS000000000001"
        assert result.get("analysis_url") == "/api/v1/analyses/01ANALYSIS000000000001"
        assert "reconstruction" in result
        assert result["reconstruction"]["method"] == "triposr_remote"
        assert mock_job.status == "done"
