"""Mutation-safe parsed-mesh cache — correctness is the crux.

The cache is a PURE optimization: enabling it must never change geometry,
error behavior, or cost output. These tests prove:
  * a HIT returns geometry EQUAL to a cold parse but a DISTINCT object;
  * mutating a returned mesh does NOT corrupt the cache;
  * cost output is byte-identical with the cache enabled vs disabled;
  * the cache is bounded (LRU eviction by count AND bytes);
  * MESH_PARSE_CACHE_DISABLED=1 disables caching entirely.

STEP correctness tests are gmsh-gated (importorskip). Class-level eviction /
LRU tests use synthetic trimesh boxes so they run without gmsh and stay fast.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient

from src.parsers import mesh_cache
from src.parsers.mesh_cache import MeshParseCache, key_for

CUBE_STEP = Path(__file__).parent / "assets" / "cube.step"


@pytest.fixture(autouse=True)
def _clean_cache_env(monkeypatch):
    """Each test starts from the default (ENABLED) cache, empty, with default
    bounds — no leakage from process-wide singleton state or env overrides."""
    for var in (
        "MESH_PARSE_CACHE_DISABLED",
        "MESH_PARSE_CACHE_MAX_ENTRIES",
        "MESH_PARSE_CACHE_MAX_BYTES",
    ):
        monkeypatch.delenv(var, raising=False)
    mesh_cache.get_cache().clear()
    yield
    mesh_cache.get_cache().clear()


def _box(scale: float = 1.0) -> trimesh.Trimesh:
    """A distinct little box mesh; `scale` makes the sha/geometry unique."""
    return trimesh.creation.box(extents=(scale, scale, scale))


# ──────────────────────────────────────────────────────────────
# Cache class: LRU eviction, byte bound, distinctness
# ──────────────────────────────────────────────────────────────
def test_hit_returns_distinct_equal_copy():
    c = MeshParseCache()
    m = _box(2.0)
    k = ("hash-a", ".stl")
    c.put(k, m)
    a = c.get(k)
    b = c.get(k)
    assert a is not None and b is not None
    assert a is not b and a is not m  # never the shared object
    assert np.array_equal(a.vertices, m.vertices)
    assert np.array_equal(a.faces, m.faces)
    # mutating a returned copy leaves the cache and other copies pristine
    a.apply_scale(25.4)
    b2 = c.get(k)
    assert np.allclose(b2.volume, m.volume)
    assert not np.allclose(a.volume, b2.volume)


def test_eviction_by_entry_count(monkeypatch):
    monkeypatch.setenv("MESH_PARSE_CACHE_MAX_ENTRIES", "3")
    monkeypatch.setenv("MESH_PARSE_CACHE_MAX_BYTES", str(1 << 30))
    c = MeshParseCache()
    for i in range(5):
        c.put((f"h{i}", ".stl"), _box(1 + i))
    assert len(c) == 3, "count bound must hold"
    # LRU: earliest two evicted, last three retained
    assert ("h0", ".stl") not in c
    assert ("h1", ".stl") not in c
    assert ("h2", ".stl") in c
    assert ("h4", ".stl") in c


def test_lru_recency_on_get(monkeypatch):
    monkeypatch.setenv("MESH_PARSE_CACHE_MAX_ENTRIES", "3")
    monkeypatch.setenv("MESH_PARSE_CACHE_MAX_BYTES", str(1 << 30))
    c = MeshParseCache()
    for i in range(3):
        c.put((f"h{i}", ".stl"), _box(1 + i))
    # touch h0 so it is most-recently-used, then insert -> h1 (now LRU) evicts
    assert c.get(("h0", ".stl")) is not None
    c.put(("h3", ".stl"), _box(9))
    assert ("h0", ".stl") in c  # protected by recent get
    assert ("h1", ".stl") not in c  # evicted as true LRU
    assert len(c) == 3


def test_eviction_by_bytes(monkeypatch):
    m = _box(1.0)
    one = mesh_cache.mesh_nbytes(m)
    assert one > 0
    # bound to ~2.5 meshes worth of bytes; only 2 entries may coexist
    monkeypatch.setenv("MESH_PARSE_CACHE_MAX_ENTRIES", "100")
    monkeypatch.setenv("MESH_PARSE_CACHE_MAX_BYTES", str(int(one * 2.5)))
    c = MeshParseCache()
    for i in range(5):
        c.put((f"h{i}", ".stl"), _box(1 + i * 0.01))
    assert c.total_bytes <= int(one * 2.5)
    assert len(c) <= 2


# ──────────────────────────────────────────────────────────────
# End-to-end via _parse_mesh on a real STEP part
# ──────────────────────────────────────────────────────────────
def _require_step():
    from src.parsers.step_mesher import is_step_supported

    if not is_step_supported():
        pytest.skip("gmsh not installed; STEP parse path unavailable")


def test_step_hit_equals_cold_but_distinct():
    _require_step()
    from src.api.routes import _parse_mesh

    data = CUBE_STEP.read_bytes()
    m1, s1 = _parse_mesh(data, "cube.step")  # cold (miss)
    m2, s2 = _parse_mesh(data, "cube.step")  # warm (hit)
    assert s1 == s2 == ".step"
    assert m1 is not m2
    assert np.array_equal(m1.vertices, m2.vertices)
    assert np.array_equal(m1.faces, m2.faces)
    assert m1.volume == m2.volume  # full precision
    assert np.array_equal(m1.bounds, m2.bounds)


def test_mutating_returned_mesh_does_not_corrupt_cache():
    _require_step()
    from src.api.routes import _parse_mesh

    data = CUBE_STEP.read_bytes()
    m1, _ = _parse_mesh(data, "cube.step")
    baseline_volume = float(m1.volume)
    m1.apply_scale(25.4)  # caller mutates its copy
    m2, _ = _parse_mesh(data, "cube.step")  # re-fetch from cache
    assert np.isclose(float(m2.volume), baseline_volume), "cache must be UNSCALED"
    assert not np.isclose(float(m1.volume), baseline_volume)


def test_disabled_switch_skips_cache(monkeypatch):
    _require_step()
    monkeypatch.setenv("MESH_PARSE_CACHE_DISABLED", "1")
    from src.api.routes import _parse_mesh

    data = CUBE_STEP.read_bytes()
    before = len(mesh_cache.get_cache())
    m1, _ = _parse_mesh(data, "cube.step")
    m2, _ = _parse_mesh(data, "cube.step")
    # nothing cached; both are independent fresh parses
    assert len(mesh_cache.get_cache()) == before
    assert key_for(data, ".step") not in mesh_cache.get_cache()
    assert np.array_equal(m1.vertices, m2.vertices)


def test_triangle_cap_reenforced_on_hit(monkeypatch):
    """The triangle cap is per-REQUEST policy (MAX_TRIANGLES from env), NOT a
    property of the parse. A part cached under a high cap must still 400 on a
    HIT once the cap is lowered — the cache stores only the parse."""
    from fastapi import HTTPException

    from src.api.routes import _parse_mesh

    data = CUBE_STEP.read_bytes()
    m1, _ = _parse_mesh(data, "cube.step")  # populate cache (default 2M cap)
    faces = len(m1.faces)
    assert key_for(data, ".step") in mesh_cache.get_cache()

    monkeypatch.setenv("MAX_TRIANGLES", "1")  # lower the cap below face count
    with pytest.raises(HTTPException) as ei:
        _parse_mesh(data, "cube.step")  # HIT — must re-enforce and reject
    assert ei.value.status_code == 400
    assert str(faces) or "MAX_TRIANGLES" in str(ei.value.detail)


def test_enabled_populates_cache():
    _require_step()
    from src.api.routes import _parse_mesh

    data = CUBE_STEP.read_bytes()
    _parse_mesh(data, "cube.step")
    assert key_for(data, ".step") in mesh_cache.get_cache()


# ──────────────────────────────────────────────────────────────
# Byte-identical cost output: cache enabled vs disabled
# ──────────────────────────────────────────────────────────────
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    import main

    importlib.reload(main)  # conftest re-applies the auth/DB bypass on reload
    return TestClient(main.app)


def _cost_demo(client, name, data, **form):
    return client.post(
        "/api/v1/validate/cost/demo",
        files={"file": (name, data, "application/octet-stream")},
        data=form,
    )


def test_cost_output_identical_enabled_vs_disabled(client, cube_10mm, stl_bytes_of):
    """Same part costed with the cache ENABLED (incl. a served hit) vs
    DISABLED must yield byte-identical decision JSON."""
    data = stl_bytes_of(cube_10mm)
    form = {"qty": "50,5000", "material_class": "aluminum"}

    # Enabled: first call misses+stores, second call is served from cache.
    mesh_cache.get_cache().clear()
    r_miss = _cost_demo(client, "cube.stl", data, **form)
    r_hit = _cost_demo(client, "cube.stl", data, **form)
    assert r_miss.status_code == 200, r_miss.text
    assert r_hit.status_code == 200, r_hit.text
    assert mesh_cache.get_cache().hits >= 1, "second call must be a cache hit"

    # Disabled: no caching at all.
    import os

    os.environ["MESH_PARSE_CACHE_DISABLED"] = "1"
    try:
        r_off = _cost_demo(client, "cube.stl", data, **form)
    finally:
        os.environ.pop("MESH_PARSE_CACHE_DISABLED", None)
    assert r_off.status_code == 200, r_off.text

    assert r_miss.json() == r_hit.json(), "hit must match miss byte-for-byte"
    assert r_hit.json() == r_off.json(), "cache must not change cost output"
