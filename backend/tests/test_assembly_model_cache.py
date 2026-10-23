"""The extracted assembly model kept for one check (``assembly_model_cache``).

The app asks /validate/assembly three times about one assembly file: json (the
probe), then glb (the 3D view) and analysis. Each extracted the whole model again
(7.7 s of gmsh each for the 30-body asm-30). The model is kept for the check that
made it (organization, person, file) for about a minute, as a copy per call.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.parsers import assembly_model_cache, mesh_cache, parse_pool

ASSETS = Path(__file__).parent / "assets"


@pytest.fixture(autouse=True)
def _clean():
    assembly_model_cache.clear()
    yield
    assembly_model_cache.clear()


def _model(parts: int = 2):
    import trimesh

    meshes = [trimesh.creation.box(extents=(10, 10, 10)) for _ in range(parts)]
    return SimpleNamespace(part_count=parts, parts=[SimpleNamespace(mesh=m) for m in meshes])


def test_a_kept_model_is_a_copy_for_its_own_check_only():
    model = _model()
    assembly_model_cache.put("org:1:abc", ".step", model, mesh_single_part=True)
    got = assembly_model_cache.get("org:1:abc", ".step", meshed=True)
    assert got is not model and got.parts[0].mesh is not model.parts[0].mesh
    assert (got.parts[0].mesh.vertices == model.parts[0].mesh.vertices).all()
    got.parts[0].mesh.vertices += 1.0  # a caller changing its copy changes nobody else's
    again = assembly_model_cache.get("org:1:abc", ".step", meshed=True)
    assert (again.parts[0].mesh.vertices == model.parts[0].mesh.vertices).all()
    assert assembly_model_cache.get("org:2:abc", ".step", meshed=True) is None  # another person
    assert assembly_model_cache.get(None, ".step", meshed=True) is None


def test_a_single_part_read_for_the_probe_does_not_serve_a_meshed_call():
    single = SimpleNamespace(part_count=1, parts=[SimpleNamespace(mesh=None)])
    assembly_model_cache.put("org:1:abc", ".step", single, mesh_single_part=False)
    assert assembly_model_cache.get("org:1:abc", ".step", meshed=True) is None
    assert assembly_model_cache.get("org:1:abc", ".step", meshed=False) is not None


def test_kept_models_expire_are_bounded_and_go_with_the_files_data(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(assembly_model_cache.time, "monotonic", lambda: now[0])
    assembly_model_cache.put("org:1:aaa", ".step", _model(), mesh_single_part=True)
    now[0] += assembly_model_cache.TTL_SEC + 1
    assert assembly_model_cache.get("org:1:aaa", ".step", meshed=True) is None
    for n in range(assembly_model_cache.MAX_ENTRIES + 2):
        assembly_model_cache.put(f"org:1:{n:03x}", ".step", _model(), mesh_single_part=True)
    assert len(assembly_model_cache._STORE) == assembly_model_cache.MAX_ENTRIES
    big = _model(parts=1)
    big.parts[0].mesh = SimpleNamespace(faces=range(assembly_model_cache.MAX_FACES + 1))
    assembly_model_cache.put("org:1:big", ".step", big, mesh_single_part=True)
    assert assembly_model_cache.get("org:1:big", ".step", meshed=True) is None
    last = f"{assembly_model_cache.MAX_ENTRIES + 1:03x}"
    assert assembly_model_cache.get(f"org:1:{last}", ".step", meshed=True) is not None
    mesh_cache.forget_hashes([last])  # the file's data is deleted
    assert assembly_model_cache.get(f"org:1:{last}", ".step", meshed=True) is None


def test_one_check_extracts_its_assembly_once(monkeypatch):
    from src.api import routes
    from src.services import compute_budget

    calls = []

    async def _extract(data, suffix, *, mesh_single_part=True):
        calls.append(mesh_single_part)
        return _model()

    monkeypatch.setattr(parse_pool, "submit_assembly_async", _extract)
    monkeypatch.setattr(routes, "is_step_supported", lambda: True)
    data = (ASSETS / "cube.step").read_bytes()

    async def _check(key):
        with compute_budget.check_scope(key):
            probe = await routes._extract_assembly_async(data, "a.step", mesh_single_part=False)
            view = await routes._extract_assembly_async(data, "a.step")
            analysis = await routes._extract_assembly_async(data, "a.step")
        return probe, view, analysis

    probe, view, analysis = asyncio.run(_check("org:1:abc"))
    assert calls == [False] and probe.part_count == view.part_count == analysis.part_count == 2
    assert view is not analysis and view.parts[0].mesh is not analysis.parts[0].mesh
    asyncio.run(_check("org:2:abc"))  # another person's check extracts its own
    assert calls == [False, False]
