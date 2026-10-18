"""Unit tests for repair_service -- two-tier mesh repair pipeline."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
import trimesh

from src.services.repair_service import (
    REPAIR_VOLUME_WARN_PCT,
    _do_repair,
    _pre_repair_volume,
    _repair_max_faces,
    _repair_timeout_sec,
    _tier1_repair,
    _tier2_repair,
    _volume_check,
)

OPEN_BORED_BLOCK = Path(__file__).parent / "assets" / "open-bored-block-mm.iges"
# 20 x 15 x 10 mm block with a 6 mm through-bore: 3000 - pi * 3^2 * 10 mm3.
BORED_BLOCK_MM3 = 3000.0 - np.pi * 9.0 * 10.0


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


@pytest.fixture(scope="module")
def open_bored_block() -> trimesh.Trimesh:
    """The bored block with its upper cap removed (945 open boundary edges).

    Tessellating this IGES takes ~40 s, so parse it once per module through the
    route parser, which also warms the parse cache repair_mesh reads. Repair
    mutates its input: tests take ``.copy()``.
    """
    from src.api.routes import _parse_mesh

    mesh, _ = _parse_mesh(OPEN_BORED_BLOCK.read_bytes(), OPEN_BORED_BLOCK.name)
    return mesh


def _boundary_edge_count(mesh: trimesh.Trimesh) -> int:
    return len(trimesh.grouping.group_rows(mesh.edges_sorted, require_count=1))


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


def test_tier2_real_pymeshfix_closes_open_cad_mesh(open_bored_block, caplog):
    """Unmocked: the installed pymeshfix must actually close a real open mesh.

    _tier2_repair swallows engine errors and hands back the input, so an API
    mismatch (pymeshfix 0.18 dropped repair(verbose=) and .v/.f) only shows up
    as a still-open mesh -- assert the repaired solid, not merely no exception.
    """
    mesh = open_bored_block.copy()
    assert not mesh.is_watertight
    assert _boundary_edge_count(mesh) == 945

    with caplog.at_level("WARNING", logger="cadverify.repair_service"):
        repaired = _tier2_repair(mesh)

    assert "pymeshfix repair failed" not in caplog.text
    assert repaired is not mesh
    assert repaired.is_watertight
    assert _boundary_edge_count(repaired) == 0
    assert repaired.volume > 0


def test_do_repair_falls_through_to_pymeshfix_on_open_cad_mesh(open_bored_block):
    """trimesh alone cannot close the open cap; the pipeline reaches tier 2."""
    repaired, tier, _ = _do_repair(open_bored_block.copy())
    assert tier == "pymeshfix"
    assert repaired.is_watertight


# ---------------------------------------------------------------------------
# Volume-change check
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("offset", [(0.0, 0.0, 0.0), (1000.0, -250.0, 40.0)])
def test_pre_repair_volume_caps_holes_independent_of_origin(offset):
    """A box missing one face is 1000 mm3 once capped, wherever it sits.

    trimesh's open-mesh volume reads 500 here (and about -99,500 at x=+1000), which
    would report a perfect fill as a +100% change.
    """
    mesh = _make_non_watertight_box()
    mesh.apply_translation(offset)
    assert _pre_repair_volume(mesh) == pytest.approx(1000.0)


def test_pre_repair_volume_open_bored_block_matches_authored_solid(open_bored_block):
    """Capping the missing top face (square loop + bore loop) restores the bore."""
    mesh = open_bored_block.copy()
    faces_before = mesh.faces.copy()
    assert _pre_repair_volume(mesh) == pytest.approx(BORED_BLOCK_MM3, rel=1e-3)
    rotated = mesh.copy()
    rotated.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    assert _pre_repair_volume(rotated) == pytest.approx(BORED_BLOCK_MM3, rel=1e-3)
    np.testing.assert_array_equal(mesh.faces, faces_before)  # never mutated


def test_pre_repair_volume_ignores_flipped_and_inverted_winding():
    flipped = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    flipped.faces[:4] = flipped.faces[:4, ::-1]
    flipped = trimesh.Trimesh(flipped.vertices, flipped.faces, process=False)
    inverted = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    inverted.invert()
    assert _pre_repair_volume(flipped) == pytest.approx(1000.0)
    assert _pre_repair_volume(inverted) == pytest.approx(1000.0)


def test_pre_repair_volume_unmeasurable_returns_none():
    sheet = trimesh.Trimesh(
        vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]], faces=[[0, 1, 2]], process=False
    )
    assert _pre_repair_volume(sheet) is None


def test_volume_check_threshold_boundary():
    assert REPAIR_VOLUME_WARN_PCT == 2.0
    assert _volume_check(1000.0, 1000.0) == (0.0, None)
    assert _volume_check(1000.0, 1019.9) == (1.99, None)
    assert _volume_check(1000.0, 980.1) == (-1.99, None)
    pct, warning = _volume_check(1000.0, 1020.1)
    assert pct == 2.01 and "+2.0%" in warning
    pct, warning = _volume_check(1000.0, 900.0)
    assert pct == -10.0 and "-10.0%" in warning


def test_volume_check_without_baseline_warns_instead_of_staying_silent():
    pct, warning = _volume_check(None, 1000.0)
    assert pct is None
    assert "could not be measured" in warning


@pytest.mark.asyncio
async def test_repair_mesh_warns_when_repair_fills_the_bore(open_bored_block, monkeypatch):
    """End to end through repair_mesh: the shell closes, the bore is filled, warn."""
    from src.services import analysis_service, repair_service

    # The open_bored_block fixture warmed the parse cache, so repair_mesh's own
    # _parse_mesh call is a cache hit rather than a second ~40 s tessellation.

    monkeypatch.setattr(
        analysis_service,
        "run_analysis",
        AsyncMock(return_value={"overall_verdict": "fail"}),
    )
    result = await repair_service.repair_mesh(
        file_bytes=OPEN_BORED_BLOCK.read_bytes(),
        filename="open-bored-block-mm.iges",
        processes=None,
        rule_pack=None,
        user=MagicMock(),
        session=AsyncMock(),
    )

    assert result["repair_applied"] is True
    details = result["repair_details"]
    assert details["tier"] == "pymeshfix"
    assert details["original_volume_mm3"] == pytest.approx(BORED_BLOCK_MM3, rel=1e-3)
    assert details["repaired_volume_mm3"] == pytest.approx(3000.0, rel=1e-3)
    assert details["volume_change_pct"] == pytest.approx(10.4, abs=0.1)
    assert "+10.4%" in details["volume_warning"]
    assert "bores" in details["volume_warning"]


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
    mock_session.add = MagicMock()

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
    mock_session.add = MagicMock()
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
    # str(TimeoutError()) is empty; the user-facing reason must still explain.
    assert result["repair_details"]["reason"] == "Repair timed out after 0.1 s."


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
