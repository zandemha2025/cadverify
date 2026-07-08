"""Tests for the reconstruction engine module.

Tests that require heavy optional dependencies (tsr, rembg, torch) are
skipped when those packages are not installed so CI without a GPU still
passes.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pytest
import trimesh
from PIL import Image, ImageDraw

from src.reconstruction.engine import (
    ReconstructionEngine,
    ReconstructParams,
    ReconstructResult,
)
from src.reconstruction.preprocessing import (
    ACCEPTED_IMAGE_TYPES,
    MAX_IMAGE_BYTES,
    detect_blur,
    resize_and_center,
    select_best_image,
    validate_image,
)
from src.reconstruction.scoring import (
    compute_reconstruction_confidence,
    confidence_level,
    confidence_message,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_image_bytes() -> bytes:
    """Create a small JPEG image with a black circle on white background."""
    img = Image.new("RGB", (256, 256), "white")
    draw = ImageDraw.Draw(img)
    draw.ellipse([64, 64, 192, 192], fill="black")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def large_test_image_bytes() -> bytes:
    """Create a larger JPEG image for select_best_image comparison."""
    img = Image.new("RGB", (512, 512), "white")
    draw = ImageDraw.Draw(img)
    draw.ellipse([64, 64, 448, 448], fill="black")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def watertight_mesh() -> trimesh.Trimesh:
    """Return a watertight unit sphere mesh."""
    return trimesh.creation.icosphere(subdivisions=3, radius=50.0)


@pytest.fixture
def degenerate_mesh() -> trimesh.Trimesh:
    """Return a mesh with degenerate (zero-area) faces."""
    verts = np.array([
        [0, 0, 0],
        [1, 0, 0],
        [0, 1, 0],
        [0, 0, 1],
        # Degenerate: three collinear points
        [2, 0, 0],
        [3, 0, 0],
        [4, 0, 0],
    ], dtype=np.float64)
    faces = np.array([
        [0, 1, 2],
        [0, 1, 3],
        [0, 2, 3],
        [1, 2, 3],
        # Degenerate face
        [4, 5, 6],
    ], dtype=np.int64)
    return trimesh.Trimesh(vertices=verts, faces=faces, process=False)


# ---------------------------------------------------------------------------
# Preprocessing: validation
# ---------------------------------------------------------------------------


class TestPreprocessingValidation:
    def test_validates_format_rejects_unsupported(self):
        with pytest.raises(ValueError, match="Unsupported image type"):
            validate_image(b"fake", "application/pdf")

    def test_validates_format_accepts_jpeg(self, test_image_bytes: bytes):
        # Should not raise
        validate_image(test_image_bytes, "image/jpeg")

    def test_validates_size_rejects_oversized(self):
        big = b"\x00" * (MAX_IMAGE_BYTES + 1)
        with pytest.raises(ValueError, match="exceeds maximum"):
            validate_image(big, "image/jpeg")

    def test_validates_size_accepts_normal(self, test_image_bytes: bytes):
        validate_image(test_image_bytes, "image/jpeg")


# ---------------------------------------------------------------------------
# Preprocessing: pipeline components
# ---------------------------------------------------------------------------


class TestPreprocessingPipeline:
    def test_detect_blur_returns_positive(self, test_image_bytes: bytes):
        img = Image.open(io.BytesIO(test_image_bytes)).convert("RGB")
        score = detect_blur(img)
        assert score > 0

    def test_resize_and_center_output_size(self, test_image_bytes: bytes):
        img = Image.open(io.BytesIO(test_image_bytes)).convert("RGB")
        result = resize_and_center(img, target_size=512)
        assert result.size == (512, 512)

    def test_preprocess_image_returns_tuple(self, test_image_bytes: bytes):
        """Full pipeline with rembg mocked out."""
        mock_remove = MagicMock(side_effect=lambda img, **kw: img.convert("RGBA"))
        with patch("src.reconstruction.preprocessing.remove_background") as mock_bg:
            # Bypass rembg; just return the image as-is
            mock_bg.side_effect = lambda img: img
            from src.reconstruction.preprocessing import preprocess_image

            result_img, metadata = preprocess_image(
                test_image_bytes, "image/jpeg"
            )
        assert isinstance(result_img, Image.Image)
        assert "blur_score" in metadata
        assert "original_size" in metadata
        assert result_img.size == (512, 512)


# ---------------------------------------------------------------------------
# Preprocessing: select_best_image
# ---------------------------------------------------------------------------


class TestSelectBestImage:
    def test_selects_larger_sharper_image(
        self, test_image_bytes: bytes, large_test_image_bytes: bytes
    ):
        images = [
            (test_image_bytes, "image/jpeg"),
            (large_test_image_bytes, "image/jpeg"),
        ]
        best_idx = select_best_image(images)
        assert best_idx == 1  # larger image should win

    def test_single_image_returns_zero(self, test_image_bytes: bytes):
        images = [(test_image_bytes, "image/jpeg")]
        assert select_best_image(images) == 0

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="At least one image"):
            select_best_image([])


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------


class TestConfidenceScoring:
    def test_watertight_mesh_high_confidence(
        self, watertight_mesh: trimesh.Trimesh
    ):
        score = compute_reconstruction_confidence(watertight_mesh)
        assert score > 0.7, f"Watertight sphere should score > 0.7, got {score}"

    def test_degenerate_mesh_lower_confidence(
        self, degenerate_mesh: trimesh.Trimesh
    ):
        score = compute_reconstruction_confidence(degenerate_mesh)
        assert score < 0.7, f"Degenerate mesh should score < 0.7, got {score}"

    def test_empty_mesh_zero(self):
        mesh = trimesh.Trimesh()
        assert compute_reconstruction_confidence(mesh) == 0.0

    def test_score_in_range(self, watertight_mesh: trimesh.Trimesh):
        score = compute_reconstruction_confidence(watertight_mesh)
        assert 0.0 <= score <= 1.0


class TestConfidenceLevel:
    def test_high(self):
        assert confidence_level(0.8) == "high"

    def test_medium(self):
        assert confidence_level(0.5) == "medium"

    def test_low(self):
        assert confidence_level(0.2) == "low"


class TestConfidenceMessage:
    def test_high_none(self):
        assert confidence_message("high") is None

    def test_medium_message(self):
        msg = confidence_message("medium")
        assert msg is not None
        assert "moderate" in msg

    def test_low_message(self):
        msg = confidence_message("low")
        assert msg is not None
        assert "low" in msg


# ---------------------------------------------------------------------------
# Engine protocol compliance
# ---------------------------------------------------------------------------


class TestZeroEgressBackendResolution:
    """The HONESTY / zero-egress-by-default invariant (F-ARCH-4 fix).

    Default backend is local-only: no customer-derived imagery leaves the
    deployment without an explicit, informed operator opt-in. When no local
    model is installed and remote egress is not opted in, reconstruction
    announces itself unavailable instead of silently egressing.
    """

    def test_default_is_local_never_remote(self, monkeypatch):
        from src.services import reconstruction_service as rs

        monkeypatch.delenv("RECONSTRUCTION_BACKEND", raising=False)
        monkeypatch.delenv("RECONSTRUCTION_ALLOW_REMOTE_EGRESS", raising=False)
        assert rs.DEFAULT_RECONSTRUCTION_BACKEND == "local"
        assert rs.configured_backend() == "local"

    def test_no_local_no_optin_is_unavailable_not_egress(self, monkeypatch):
        """Core guarantee: unavailable is announced, never a silent egress."""
        from src.services import reconstruction_service as rs

        monkeypatch.delenv("RECONSTRUCTION_BACKEND", raising=False)
        monkeypatch.delenv("RECONSTRUCTION_ALLOW_REMOTE_EGRESS", raising=False)
        monkeypatch.setattr(rs, "local_backend_available", lambda: False)

        with pytest.raises(rs.ReconstructionUnavailableError) as exc:
            rs.resolve_reconstruction_backend()
        assert exc.value.code == "RECONSTRUCTION_UNAVAILABLE"

        report = rs.check_reconstruction_availability()
        assert report["available"] is False
        assert report["egress"] is False
        assert report["effective_backend"] == "none"

        # The factory must refuse -- it must NOT hand back a remote (egress) engine.
        with pytest.raises(rs.ReconstructionUnavailableError):
            rs.get_reconstruction_engine()

    def test_local_available_is_local_no_egress(self, monkeypatch):
        from src.services import reconstruction_service as rs

        monkeypatch.delenv("RECONSTRUCTION_BACKEND", raising=False)
        monkeypatch.delenv("RECONSTRUCTION_ALLOW_REMOTE_EGRESS", raising=False)
        monkeypatch.setattr(rs, "local_backend_available", lambda: True)

        backend, egress = rs.resolve_reconstruction_backend()
        assert backend == "local"
        assert egress is False
        report = rs.check_reconstruction_availability()
        assert report["available"] is True
        assert report["egress"] is False

    def test_explicit_remote_backend_opts_in_to_egress(self, monkeypatch):
        from src.services import reconstruction_service as rs

        monkeypatch.setenv("RECONSTRUCTION_BACKEND", "remote")
        backend, egress = rs.resolve_reconstruction_backend()
        assert backend == "remote"
        assert egress is True
        report = rs.check_reconstruction_availability()
        assert report["available"] is True
        assert report["egress"] is True

    def test_allow_remote_egress_flag_enables_fallback(self, monkeypatch):
        """No local model but explicit egress opt-in => remote fallback allowed."""
        from src.services import reconstruction_service as rs

        monkeypatch.delenv("RECONSTRUCTION_BACKEND", raising=False)
        monkeypatch.setenv("RECONSTRUCTION_ALLOW_REMOTE_EGRESS", "1")
        monkeypatch.setattr(rs, "local_backend_available", lambda: False)

        backend, egress = rs.resolve_reconstruction_backend()
        assert backend == "remote"
        assert egress is True
        assert rs.remote_egress_allowed() is True

    def test_backend_none_is_disabled(self, monkeypatch):
        from src.services import reconstruction_service as rs

        monkeypatch.setenv("RECONSTRUCTION_BACKEND", "none")
        with pytest.raises(rs.ReconstructionUnavailableError):
            rs.resolve_reconstruction_backend()
        assert rs.check_reconstruction_availability()["available"] is False

    def test_egress_factory_logs_acknowledgment(self, monkeypatch, caplog):
        """Every egress path must log a loud data-egress acknowledgment."""
        import logging

        from src.services import reconstruction_service as rs

        monkeypatch.setenv("RECONSTRUCTION_BACKEND", "remote")
        monkeypatch.setenv("REPLICATE_API_TOKEN", "test-token")
        with caplog.at_level(logging.WARNING, logger="cadverify.reconstruction_service"):
            engine = rs.get_reconstruction_engine()
        assert engine is not None
        assert any("DATA EGRESS" in rec.getMessage() for rec in caplog.records)


class TestEngineProtocol:
    def test_local_is_subclass(self):
        """LocalTripoSR must be a subclass of ReconstructionEngine."""
        import ast

        tree = ast.parse((BACKEND_ROOT / "src/reconstruction/local_triposr.py").read_text())
        classes = {
            n.name: [b.attr if hasattr(b, "attr") else b.id for b in n.bases]
            for n in ast.walk(tree)
            if isinstance(n, ast.ClassDef)
        }
        assert "ReconstructionEngine" in classes.get("LocalTripoSR", [])

    def test_remote_is_subclass(self):
        """RemoteTripoSR must be a subclass of ReconstructionEngine."""
        import ast

        tree = ast.parse((BACKEND_ROOT / "src/reconstruction/remote_triposr.py").read_text())
        classes = {
            n.name: [b.attr if hasattr(b, "attr") else b.id for b in n.bases]
            for n in ast.walk(tree)
            if isinstance(n, ast.ClassDef)
        }
        assert "ReconstructionEngine" in classes.get("RemoteTripoSR", [])

    def test_reconstruct_params_defaults(self):
        p = ReconstructParams()
        assert p.resolution == 256
        assert p.output_format == "stl"

    def test_reconstruct_result_fields(self):
        r = ReconstructResult(
            mesh_bytes=b"stl", face_count=10, duration_ms=100.0, method="test"
        )
        assert r.mesh_bytes == b"stl"
        assert r.face_count == 10
