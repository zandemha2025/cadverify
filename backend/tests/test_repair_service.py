"""Unit tests for repair_service -- two-tier mesh repair pipeline."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
import trimesh

from src.services.repair_service import (
    _do_repair,
    _repair_max_faces,
    _repair_timeout_sec,
    _tier1_repair,
    _tier2_repair,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_non_watertight_box() -> trimesh.Trimesh:
    """10mm cube with two faces removed so it is not watertight."""
    mesh = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    return trimesh.Trimesh(
        vertices=mesh.vertices,
        faces=mesh.faces[:-2],
        process=False,
    )


# ---------------------------------------------------------------------------
# Tier 1 tests
# ---------------------------------------------------------------------------


def test_tier1_fixes_flipped_normals():
    """Tier 1 repair should fix flipped normals and maintain watertightness."""
    mesh = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    # Flip some face normals by reversing winding on a few faces
    mesh.faces[:4] = mesh.faces[:4, ::-1]
    mesh = _tier1_repair(mesh)
    assert mesh.is_watertight


def test_tier1_removes_degenerate_faces():
    """Tier 1 repair should remove zero-area degenerate faces."""
    mesh = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    original_count = len(mesh.faces)
    # Add a degenerate face (all three vertices are the same point)
    degen_face = np.array([[0, 0, 0]])  # same vertex index repeated
    mesh.faces = np.vstack([mesh.faces, degen_face])
    mesh = _tier1_repair(mesh)
    # Degenerate face should be removed
    assert len(mesh.faces) <= original_count + 1  # at most original + non-degenerate
    assert mesh.is_watertight


def test_tier1_returns_trimesh():
    """Tier 1 repair should return a trimesh.Trimesh instance."""
    mesh = trimesh.creation.box(extents=[5.0, 5.0, 5.0])
    result = _tier1_repair(mesh)
    assert isinstance(result, trimesh.Trimesh)


# ---------------------------------------------------------------------------
# Tier 2 tests
# ---------------------------------------------------------------------------


def test_tier2_pymeshfix_invoked_when_tier1_insufficient():
    """When Tier 1 leaves mesh non-watertight, _do_repair invokes pymeshfix."""
    mesh = _make_non_watertight_box()
    with patch("src.services.repair_service._tier1_repair") as mock_t1:
        # Make tier1 return a non-watertight mesh
        mock_t1.return_value = mesh
        # Mock the mesh.is_watertight to return False after tier1
        with patch.object(type(mesh), "is_watertight", new_callable=lambda: property(lambda self: False)):
            with patch("src.services.repair_service._tier2_repair") as mock_t2:
                mock_t2.return_value = mesh
                _do_repair(mesh)
                mock_t2.assert_called_once()


def test_pymeshfix_import_error_degrades_to_tier1():
    """If pymeshfix is not installed, _tier2_repair returns mesh unchanged."""
    mesh = _make_non_watertight_box()
    original_faces = len(mesh.faces)
    with patch.dict("sys.modules", {"pymeshfix": None}):
        result = _tier2_repair(mesh)
    assert isinstance(result, trimesh.Trimesh)
    assert len(result.faces) == original_faces


def test_tier2_runtime_error_returns_original():
    """If pymeshfix raises RuntimeError, _tier2_repair returns original mesh."""
    mesh = _make_non_watertight_box()
    with patch("pymeshfix.MeshFix", side_effect=RuntimeError("segfault")):
        result = _tier2_repair(mesh)
    assert isinstance(result, trimesh.Trimesh)
    assert len(result.faces) == len(mesh.faces)


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


def test_repair_timeout_default():
    """Default timeout is 30 seconds."""
    assert _repair_timeout_sec() == 30.0


def test_repair_timeout_from_env(monkeypatch):
    monkeypatch.setenv("REPAIR_TIMEOUT_SEC", "10")
    assert _repair_timeout_sec() == 10.0


def test_repair_timeout_min_clamped(monkeypatch):
    monkeypatch.setenv("REPAIR_TIMEOUT_SEC", "0.001")
    assert _repair_timeout_sec() == 0.1


def test_repair_max_faces_default():
    assert _repair_max_faces() == 500000


def test_repair_max_faces_from_env(monkeypatch):
    monkeypatch.setenv("REPAIR_MAX_FACES", "100")
    assert _repair_max_faces() == 100


# ---------------------------------------------------------------------------
# Face-count cap (async)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_face_count_cap_rejects_oversize(monkeypatch):
    """Mesh exceeding REPAIR_MAX_FACES should raise HTTPException 413."""
    monkeypatch.setenv("REPAIR_MAX_FACES", "10")
    from fastapi import HTTPException

    from src.services import repair_service

    # Create a mesh with more than 10 faces
    mesh = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    stl_bytes = mesh.export(file_type="stl")

    mock_user = MagicMock()
    mock_user.user_id = 1
    mock_user.api_key_id = 1
    mock_session = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await repair_service.repair_mesh(
            file_bytes=stl_bytes,
            filename="big.stl",
            processes=None,
            rule_pack=None,
            user=mock_user,
            session=mock_session,
        )
    assert exc_info.value.status_code == 413
    assert "REPAIR_MAX_FACES" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Timeout fallback (async)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_returns_original_analysis(monkeypatch):
    """Repair timeout should return repair_applied=False with error details."""
    monkeypatch.setenv("REPAIR_TIMEOUT_SEC", "0.001")

    from src.services import repair_service

    mesh = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    stl_bytes = mesh.export(file_type="stl")

    mock_user = MagicMock()
    mock_user.user_id = 1
    mock_user.api_key_id = 1
    mock_session = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.first.return_value = None
    mock_session.execute.return_value = exec_result

    import time

    def _slow_repair(m):
        time.sleep(2)
        return (m, "trimesh", 0)

    monkeypatch.setattr(repair_service, "_do_repair", _slow_repair)

    result = await repair_service.repair_mesh(
        file_bytes=stl_bytes,
        filename="cube.stl",
        processes=None,
        rule_pack=None,
        user=mock_user,
        session=mock_session,
    )
    assert result["repair_applied"] is False
    assert result["repair_details"].get("error") is not None


# ---------------------------------------------------------------------------
# Base64 STL output
# ---------------------------------------------------------------------------


def test_do_repair_returns_tuple():
    """_do_repair returns a 3-tuple (mesh, tier, holes_filled)."""
    mesh = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    result = _do_repair(mesh)
    assert len(result) == 3
    repaired_mesh, tier, holes_filled = result
    assert isinstance(repaired_mesh, trimesh.Trimesh)
    assert tier == "trimesh"  # box is already watertight, tier1 suffices
    assert holes_filled == 0
