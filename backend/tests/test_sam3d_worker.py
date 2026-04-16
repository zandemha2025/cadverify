"""Integration tests for the SAM-3D arq worker task (run_sam3d_job).

Covers: SAM-3D success, fallback on failure, fallback on empty segments,
mesh load failure, and segment serialization helpers.
"""
from __future__ import annotations

import io
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import trimesh

from src.analysis.models import FeatureSegment, FeatureType
from src.segmentation.sam3d.types import SemanticLabel, SemanticSegment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_job(ulid: str = "test-job-001", mesh_hash: str = "abc123") -> MagicMock:
    """Create a mock Job ORM object."""
    job = MagicMock()
    job.ulid = ulid
    job.status = "queued"
    job.params_json = {"mesh_hash": mesh_hash}
    job.started_at = None
    job.completed_at = None
    job.result_json = None
    return job


def _mock_session_factory(job):
    """Return a mock session factory whose execute returns *job*."""
    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.first.return_value = job
    session.execute.return_value = exec_result

    async def _commit():
        pass
    session.commit = _commit

    ctx_mgr = AsyncMock()
    ctx_mgr.__aenter__.return_value = session
    ctx_mgr.__aexit__.return_value = False

    factory = MagicMock(return_value=ctx_mgr)
    return factory


def _write_stl_blob(tmp_path, mesh_hash: str = "abc123") -> str:
    """Write a small valid STL to tmp_path and return the blob dir."""
    blob_dir = str(tmp_path / "meshes")
    os.makedirs(blob_dir, exist_ok=True)
    mesh = trimesh.creation.box(extents=[10, 10, 10])
    blob_path = os.path.join(blob_dir, f"{mesh_hash}.bin")
    mesh.export(blob_path, file_type="stl")
    return blob_dir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRunSam3dJob:
    """Tests for run_sam3d_job task function."""

    @pytest.mark.asyncio
    async def test_sam3d_success_path(self, tmp_path):
        """SAM-3D succeeds -> job.status == 'done', method == 'sam3d'."""
        job = _make_job()
        factory = _mock_session_factory(job)
        blob_dir = _write_stl_blob(tmp_path)

        fake_segments = [
            SemanticSegment(
                label=SemanticLabel.FLANGE,
                face_indices=[0, 1, 2],
                centroid=(1.0, 2.0, 3.0),
                confidence=0.9,
                view_agreement=0.8,
            ),
        ]

        with (
            patch("src.jobs.tasks.get_session_factory", return_value=factory),
            patch("src.segmentation.sam3d.pipeline.segment_sam3d", return_value=fake_segments),
            patch.dict(os.environ, {"MESH_BLOB_DIR": blob_dir, "SAM3D_ENABLED": "true"}),
        ):
            from src.jobs.tasks import run_sam3d_job
            result = await run_sam3d_job({}, "test-job-001")

        assert job.status == "done"
        assert result["method"] == "sam3d"
        assert result["segment_count"] == 1

    @pytest.mark.asyncio
    async def test_sam3d_fallback_on_failure(self, tmp_path):
        """SAM-3D raises RuntimeError -> falls back to heuristic, status == 'partial'."""
        job = _make_job()
        factory = _mock_session_factory(job)
        blob_dir = _write_stl_blob(tmp_path)

        with (
            patch("src.jobs.tasks.get_session_factory", return_value=factory),
            patch("src.segmentation.sam3d.pipeline.segment_sam3d", side_effect=RuntimeError("GPU OOM")),
            patch.dict(os.environ, {"MESH_BLOB_DIR": blob_dir, "SAM3D_ENABLED": "true"}),
        ):
            from src.jobs.tasks import run_sam3d_job
            result = await run_sam3d_job({}, "test-job-001")

        assert job.status == "partial"
        assert result["method"] == "heuristic_fallback"
        assert result["segment_count"] > 0

    @pytest.mark.asyncio
    async def test_sam3d_empty_segments_triggers_fallback(self, tmp_path):
        """SAM-3D returns [] -> treated as failure, falls back to heuristic."""
        job = _make_job()
        factory = _mock_session_factory(job)
        blob_dir = _write_stl_blob(tmp_path)

        with (
            patch("src.jobs.tasks.get_session_factory", return_value=factory),
            patch("src.segmentation.sam3d.pipeline.segment_sam3d", return_value=[]),
            patch.dict(os.environ, {"MESH_BLOB_DIR": blob_dir, "SAM3D_ENABLED": "true"}),
        ):
            from src.jobs.tasks import run_sam3d_job
            result = await run_sam3d_job({}, "test-job-001")

        assert job.status == "partial"
        assert result["method"] == "heuristic_fallback"

    @pytest.mark.asyncio
    async def test_mesh_blob_load_failure_marks_partial(self, tmp_path):
        """Non-existent blob path -> job.status == 'partial', mesh_load_failed."""
        job = _make_job(mesh_hash="nonexistent")
        factory = _mock_session_factory(job)

        with (
            patch("src.jobs.tasks.get_session_factory", return_value=factory),
            patch.dict(os.environ, {"MESH_BLOB_DIR": str(tmp_path / "nodir")}),
        ):
            from src.jobs.tasks import run_sam3d_job
            result = await run_sam3d_job({}, "test-job-001")

        assert job.status == "partial"
        assert result["error"] == "mesh_load_failed"


class TestSegmentToDict:
    """Tests for _segment_to_dict serialization helper."""

    def test_semantic_segment_serialization(self):
        """SemanticSegment -> dict with label, face_indices, centroid, confidence."""
        from src.jobs.tasks import _segment_to_dict

        seg = SemanticSegment(
            label=SemanticLabel.MOUNTING_HOLE,
            face_indices=[0, 1, 2, 3],
            centroid=(5.0, 6.0, 7.0),
            confidence=0.95,
            view_agreement=0.85,
        )
        d = _segment_to_dict(seg)
        assert d["label"] == "mounting_hole"
        assert d["face_indices"] == [0, 1, 2, 3]
        assert d["centroid"] == [5.0, 6.0, 7.0]
        assert d["confidence"] == 0.95
        assert d["view_agreement"] == 0.85

    def test_feature_segment_serialization(self):
        """FeatureSegment (heuristic fallback) -> dict with feature_type, segment_id."""
        from src.jobs.tasks import _segment_to_dict

        seg = FeatureSegment(
            segment_id=42,
            feature_type=FeatureType.OVERHANG,
            face_indices=[10, 11, 12],
            centroid=(1.0, 2.0, 3.0),
            confidence=0.7,
        )
        d = _segment_to_dict(seg)
        assert d["feature_type"] == "overhang"
        assert d["face_indices"] == [10, 11, 12]
        assert d["centroid"] == [1.0, 2.0, 3.0]
        assert d["confidence"] == 0.7
        assert d["segment_id"] == 42
