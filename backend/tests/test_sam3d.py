"""Tests for the SAM-3D semantic segmentation pipeline scaffolding."""

from __future__ import annotations

import json
import os
import tempfile

import numpy as np
import pytest
import trimesh

from src.segmentation.sam3d.config import SAM3DConfig
from src.segmentation.sam3d.types import Mask, SemanticLabel, SemanticSegment, ViewRender
from src.segmentation.sam3d.pipeline import is_sam3d_available, segment_sam3d
from src.segmentation.sam3d import cache
from src.segmentation.sam3d import classifier
from src.segmentation.sam3d import lifter
from src.segmentation.sam3d import renderer


# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def cube_mesh() -> trimesh.Trimesh:
    return trimesh.creation.box(extents=[10.0, 10.0, 10.0])


@pytest.fixture
def empty_mesh() -> trimesh.Trimesh:
    return trimesh.Trimesh()


@pytest.fixture
def tmp_cache_dir(tmp_path):
    return str(tmp_path / "sam3d_cache")


# ──────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────

class TestConfig:
    def test_defaults(self):
        cfg = SAM3DConfig()
        assert cfg.enabled is False
        assert cfg.num_views == 24
        assert cfg.num_points == 10000
        assert cfg.min_segment_faces == 5
        assert cfg.confidence_threshold == 0.7

    def test_from_env_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("SAM3D_ENABLED", raising=False)
        monkeypatch.delenv("SAM3D_MODEL_PATH", raising=False)
        monkeypatch.delenv("SAM3D_CACHE_DIR", raising=False)
        cfg = SAM3DConfig.from_env()
        assert cfg.enabled is False
        assert cfg.model_path == ""

    def test_from_env_enabled(self, monkeypatch):
        monkeypatch.setenv("SAM3D_ENABLED", "true")
        monkeypatch.setenv("SAM3D_MODEL_PATH", "/weights/sam3d.pt")
        monkeypatch.setenv("SAM3D_CACHE_DIR", "/custom/cache")
        cfg = SAM3DConfig.from_env()
        assert cfg.enabled is True
        assert cfg.model_path == "/weights/sam3d.pt"
        assert cfg.cache_dir == "/custom/cache"

    def test_from_env_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("SAM3D_ENABLED", "True")
        cfg = SAM3DConfig.from_env()
        assert cfg.enabled is True

        monkeypatch.setenv("SAM3D_ENABLED", "TRUE")
        cfg = SAM3DConfig.from_env()
        assert cfg.enabled is True


# ──────────────────────────────────────────────────────────────
# Types
# ──────────────────────────────────────────────────────────────

class TestSemanticLabel:
    def test_all_expected_values(self):
        expected = {
            "bearing_seat", "gasket_face", "mounting_hole",
            "cooling_channel", "lightening_pocket", "structural_web",
            "thread_region", "keyway", "flange", "datum_surface", "unknown",
        }
        actual = {label.value for label in SemanticLabel}
        assert actual == expected

    def test_is_string_enum(self):
        assert isinstance(SemanticLabel.BEARING_SEAT, str)
        assert SemanticLabel.BEARING_SEAT == "bearing_seat"


class TestSemanticSegment:
    def test_construction(self):
        seg = SemanticSegment(
            label=SemanticLabel.BEARING_SEAT,
            face_indices=[0, 1, 2, 3],
            centroid=(1.0, 2.0, 3.0),
            confidence=0.9,
            view_agreement=0.75,
        )
        assert seg.label == SemanticLabel.BEARING_SEAT
        assert seg.face_indices == [0, 1, 2, 3]
        assert seg.centroid == (1.0, 2.0, 3.0)
        assert seg.confidence == 0.9
        assert seg.view_agreement == 0.75
        assert seg.metadata == {}

    def test_metadata_default(self):
        seg = SemanticSegment(
            label=SemanticLabel.UNKNOWN,
            face_indices=[],
            centroid=(0.0, 0.0, 0.0),
            confidence=0.0,
            view_agreement=0.0,
        )
        assert seg.metadata == {}
        seg.metadata["key"] = "value"
        assert seg.metadata["key"] == "value"


# ──────────────────────────────────────────────────────────────
# Pipeline: disabled / graceful degradation
# ──────────────────────────────────────────────────────────────

class TestPipeline:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("SAM3D_ENABLED", raising=False)
        assert is_sam3d_available() is False

    def test_returns_empty_when_disabled(self, cube_mesh, monkeypatch):
        monkeypatch.delenv("SAM3D_ENABLED", raising=False)
        result = segment_sam3d(cube_mesh)
        assert result == []

    def test_returns_empty_with_disabled_config(self, cube_mesh):
        cfg = SAM3DConfig(enabled=False)
        result = segment_sam3d(cube_mesh, config=cfg)
        assert result == []

    def test_returns_empty_for_empty_mesh(self, empty_mesh):
        cfg = SAM3DConfig(enabled=True)
        result = segment_sam3d(empty_mesh, config=cfg)
        assert result == []

    def test_returns_empty_for_none_mesh(self):
        cfg = SAM3DConfig(enabled=True)
        result = segment_sam3d(None, config=cfg)
        assert result == []

    def test_returns_empty_when_renderer_unavailable(self, cube_mesh, monkeypatch):
        """When pyrender is absent, render_views returns [] and pipeline exits."""
        cfg = SAM3DConfig(enabled=True)
        monkeypatch.setattr(renderer, "_PYRENDER_AVAILABLE", False)
        result = segment_sam3d(cube_mesh, config=cfg)
        assert result == []

    def test_is_available_when_enabled(self, monkeypatch):
        monkeypatch.setenv("SAM3D_ENABLED", "true")
        assert is_sam3d_available() is True


# ──────────────────────────────────────────────────────────────
# Cache
# ──────────────────────────────────────────────────────────────

class TestCache:
    def test_miss_returns_none(self, cube_mesh, tmp_cache_dir):
        result = cache.get(cube_mesh, tmp_cache_dir)
        assert result is None

    def test_roundtrip(self, cube_mesh, tmp_cache_dir):
        segments = [
            SemanticSegment(
                label=SemanticLabel.BEARING_SEAT,
                face_indices=[0, 1, 2],
                centroid=(1.0, 2.0, 3.0),
                confidence=0.85,
                view_agreement=0.9,
                metadata={"source": "test"},
            ),
            SemanticSegment(
                label=SemanticLabel.MOUNTING_HOLE,
                face_indices=[5, 6, 7, 8],
                centroid=(4.0, 5.0, 6.0),
                confidence=0.72,
                view_agreement=0.6,
            ),
        ]
        cache.put(cube_mesh, segments, tmp_cache_dir)
        restored = cache.get(cube_mesh, tmp_cache_dir)

        assert restored is not None
        assert len(restored) == 2
        assert restored[0].label == SemanticLabel.BEARING_SEAT
        assert restored[0].face_indices == [0, 1, 2]
        assert restored[0].confidence == 0.85
        assert restored[0].metadata == {"source": "test"}
        assert restored[1].label == SemanticLabel.MOUNTING_HOLE

    def test_different_mesh_different_key(self, cube_mesh, tmp_cache_dir):
        other_mesh = trimesh.creation.box(extents=[20.0, 20.0, 20.0])
        segments = [
            SemanticSegment(
                label=SemanticLabel.FLANGE,
                face_indices=[0],
                centroid=(0.0, 0.0, 0.0),
                confidence=0.5,
                view_agreement=0.5,
            ),
        ]
        cache.put(cube_mesh, segments, tmp_cache_dir)
        assert cache.get(other_mesh, tmp_cache_dir) is None

    def test_corrupted_file_returns_none(self, cube_mesh, tmp_cache_dir):
        """Write garbage and verify get() returns None gracefully."""
        os.makedirs(tmp_cache_dir, exist_ok=True)
        key = cache._mesh_hash(cube_mesh)
        path = cache._cache_path(tmp_cache_dir, key)
        with open(path, "w") as f:
            f.write("not valid json{{{{")
        assert cache.get(cube_mesh, tmp_cache_dir) is None


# ──────────────────────────────────────────────────────────────
# Renderer
# ──────────────────────────────────────────────────────────────

class TestRenderer:
    def test_empty_mesh_returns_empty(self, empty_mesh):
        views = renderer.render_views(empty_mesh, num_views=4)
        assert views == []

    def test_none_mesh_returns_empty(self):
        views = renderer.render_views(None, num_views=4)
        assert views == []

    def test_icosphere_cameras_count(self):
        cams = renderer._icosphere_cameras(12, radius=10.0)
        assert len(cams) == 12
        for cam in cams:
            assert cam.shape == (4, 4)

    def test_look_at_identity_target(self):
        mat = renderer._look_at(
            eye=np.array([0.0, 0.0, 5.0]),
            target=np.array([0.0, 0.0, 0.0]),
            up=np.array([0.0, 1.0, 0.0]),
        )
        assert mat.shape == (4, 4)
        # Camera should be at (0, 0, 5)
        np.testing.assert_allclose(mat[:3, 3], [0.0, 0.0, 5.0], atol=1e-9)

    def test_renderer_available_flag(self):
        # Just verify the function runs without error
        result = renderer.is_renderer_available()
        assert isinstance(result, bool)


# ──────────────────────────────────────────────────────────────
# Lifter
# ──────────────────────────────────────────────────────────────

class TestLifter:
    def test_empty_mask_list(self, cube_mesh):
        result = lifter.lift_masks(cube_mesh, [])
        assert result == []

    def test_empty_mesh(self, empty_mesh):
        result = lifter.lift_masks(empty_mesh, [])
        assert result == []

    def test_masks_with_no_valid_faces(self, cube_mesh):
        """Masks that map to no valid face IDs produce empty results."""
        face_ids = np.full((8, 8), -1, dtype=np.int32)
        view = ViewRender(
            rgb=np.zeros((8, 8, 3), dtype=np.uint8),
            depth=np.zeros((8, 8), dtype=np.float32),
            face_ids=face_ids,
            camera_transform=np.eye(4),
        )
        mask = Mask(
            binary_mask=np.ones((8, 8), dtype=bool),
            confidence=0.9,
        )
        result = lifter.lift_masks(cube_mesh, [(view, [mask])])
        assert result == []

    def test_single_view_with_valid_faces(self, cube_mesh):
        """A single view with face IDs should produce segments."""
        num_faces = len(cube_mesh.faces)
        face_ids = np.full((10, 10), -1, dtype=np.int32)
        # Fill a region with valid face indices
        for i in range(min(10, num_faces)):
            face_ids[i, :] = i

        view = ViewRender(
            rgb=np.zeros((10, 10, 3), dtype=np.uint8),
            depth=np.zeros((10, 10), dtype=np.float32),
            face_ids=face_ids,
            camera_transform=np.eye(4),
        )
        mask = Mask(
            binary_mask=np.ones((10, 10), dtype=bool),
            confidence=0.9,
        )
        result = lifter.lift_masks(cube_mesh, [(view, [mask])], min_faces=3)
        assert len(result) > 0
        faces, agreement = result[0]
        assert len(faces) >= 3
        assert 0.0 < agreement <= 1.0

    def test_merge_overlapping(self):
        segments = [{1, 2, 3}, {3, 4, 5}, {6, 7}]
        merged = lifter._merge_overlapping(segments)
        assert len(merged) == 2
        # {1,2,3} and {3,4,5} should merge into {1,2,3,4,5}
        large = max(merged, key=len)
        assert large == {1, 2, 3, 4, 5}
        small = min(merged, key=len)
        assert small == {6, 7}


# ──────────────────────────────────────────────────────────────
# Classifier
# ──────────────────────────────────────────────────────────────

class TestClassifier:
    def test_empty_faces_returns_unknown(self, cube_mesh):
        label, conf = classifier.classify(cube_mesh, [])
        assert label == SemanticLabel.UNKNOWN
        assert conf == 0.0

    def test_returns_label_and_confidence(self, cube_mesh):
        face_indices = list(range(min(5, len(cube_mesh.faces))))
        label, conf = classifier.classify(cube_mesh, face_indices)
        assert isinstance(label, SemanticLabel)
        assert 0.0 <= conf <= 1.0

    def test_flat_horizontal_faces(self):
        """Top faces of a box should classify as datum/gasket."""
        mesh = trimesh.creation.box(extents=[100.0, 100.0, 10.0])
        # Find top-facing faces (normal Z > 0.9)
        top_faces = [
            i for i, n in enumerate(mesh.face_normals)
            if n[2] > 0.9
        ]
        if top_faces:
            label, conf = classifier.classify(mesh, top_faces)
            assert label in (
                SemanticLabel.DATUM_SURFACE,
                SemanticLabel.GASKET_FACE,
            )
            assert conf > 0.0


# ──────────────────────────────────────────────────────────────
# Legacy entry point
# ──────────────────────────────────────────────────────────────

class TestLegacyEntryPoint:
    def test_import_from_legacy_module(self):
        from src.segmentation.sam3d_segmenter import (
            is_sam3d_available,
            segment_sam3d,
        )
        assert callable(is_sam3d_available)
        assert callable(segment_sam3d)

    def test_legacy_returns_empty_when_disabled(self, cube_mesh, monkeypatch):
        monkeypatch.delenv("SAM3D_ENABLED", raising=False)
        from src.segmentation.sam3d_segmenter import segment_sam3d as legacy_segment
        result = legacy_segment(cube_mesh)
        assert result == []
