"""Re-pricing reuses the analysed geometry, and the price is the same as fresh.

The first check asks the material while the geometry check runs, then prices;
changing the material later re-prices. Neither re-runs the parse + geometry
analysis when this account just analysed the same file in this process.
"""
from __future__ import annotations

import asyncio
import io
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import trimesh

from src.costing import EstimateOptions, estimate_decision, report_to_dict
from src.services import part_geometry_cache as pgc

QTY = [1, 100, 1000, 2000, 5000, 10000]


def _block_stl() -> bytes:
    """A 40 x 30 x 20 mm block with a through hole: watertight, real features."""
    block = trimesh.creation.box(extents=(40, 30, 20))
    hole = trimesh.creation.cylinder(radius=5, height=30, sections=48)
    part = block.difference(hole)
    buf = io.BytesIO()
    part.export(buf, file_type="stl")
    return buf.getvalue()


def _entry(faces=10, mesh=None):
    return pgc.AnalysedPart(result=object(), mesh=mesh or MagicMock(), features=[],
                            identity_vec=None, suffix=".stl", faces=faces)


@pytest.fixture(autouse=True)
def _empty_cache():
    pgc.clear()
    yield
    pgc.clear()


def test_cache_is_scoped_bounded_and_expires(monkeypatch):
    a, b = pgc.key(1, b"part", "p.stl", "mm"), pgc.key(2, b"part", "p.stl", "mm")
    assert a != b  # another account never reuses this upload
    assert pgc.key(1, b"part", "q.stl", "mm") != a  # nor another name or units
    assert pgc.key(1, b"part", "p.stl", "inch") != a
    assert pgc.put(a, _entry())
    assert pgc.get(a) is not None and pgc.get(b) is None

    monkeypatch.setenv("COST_GEOMETRY_CACHE_ENTRIES", "2")
    monkeypatch.setenv("COST_GEOMETRY_CACHE_MAX_FACES", "100")
    keys = [pgc.key(1, bytes([i]), "p.stl", "mm") for i in range(3)]
    for k in keys:
        pgc.put(k, _entry(faces=40))
    assert [pgc.get(k) is not None for k in keys] == [False, True, True]  # oldest evicted
    assert not pgc.put(pgc.key(1, b"big", "p.stl", "mm"), _entry(faces=101))
    pgc.put(pgc.key(1, b"mid", "p.stl", "mm"), _entry(faces=90))  # face budget evicts
    assert pgc.size() == 1

    monkeypatch.setenv("COST_GEOMETRY_CACHE_TTL_SEC", "0.05")
    pgc.put(a, _entry())
    import time
    time.sleep(0.06)
    assert pgc.get(a) is None
    monkeypatch.setenv("COST_GEOMETRY_CACHE_ENTRIES", "0")
    assert not pgc.put(a, _entry())  # off


def test_only_the_last_priced_part_keeps_its_lazy_caches():
    m1, m2 = MagicMock(), MagicMock()
    k1, k2 = pgc.key(1, b"one", "p.stl", "mm"), pgc.key(1, b"two", "p.stl", "mm")
    pgc.put(k1, _entry(mesh=m1))
    assert m1._cache.clear.call_count == 1  # stored small
    pgc.put(k2, _entry(mesh=m2))
    pgc.get(k1)
    assert m2._cache.clear.call_count == 2  # stored, then cooled when k1 got warm
    before = m1._cache.clear.call_count
    pgc.get(k1)
    assert m1._cache.clear.call_count == before  # the warm one stays warm


def _price(result, mesh, features, material):
    rep = estimate_decision(result, mesh, features, EstimateOptions(
        quantities=QTY, material_class=material, material_class_is_user=material != "polymer"))
    return report_to_dict(rep)


@pytest.mark.asyncio
async def test_validation_leaves_the_exact_part_the_cost_engine_builds():
    """The analysed part /validate keeps prices exactly like a fresh cost run."""
    from src.api import routes
    from src.services import analysis_service

    data = _block_stl()
    user = types.SimpleNamespace(user_id=4242, api_key_id=0)
    stored = {}
    real_put = pgc.put

    def capture(k, entry):
        stored[k] = entry
        return real_put(k, entry)

    persisted = types.SimpleNamespace(id=1, ulid="01TEST", org_id=None)
    with patch.object(analysis_service, "_check_cache", AsyncMock(return_value=None)), \
         patch.object(analysis_service, "_persist_analysis", AsyncMock(return_value=persisted)), \
         patch.object(analysis_service, "_write_usage_event", AsyncMock()), \
         patch("src.auth.org_context.resolve_org", AsyncMock(return_value=None)), \
         patch("src.services.audit_service.emit_event", AsyncMock()), \
         patch.object(pgc, "put", capture):
        await analysis_service.run_analysis(
            file_bytes=data, filename="block.stl", processes=None, rule_pack=None,
            user=user, session=MagicMock(),
        )
    key = pgc.key(4242, data, "block.stl", "mm")
    assert key in stored, "a full, ungoverned analysis keeps its part for pricing"
    reused = pgc.get(key)

    mesh, _ = await routes._parse_mesh_async(data, "block.stl")
    fresh = await asyncio.to_thread(routes._run_cost_engine_ctx, mesh, "block.stl")
    result, m, ctx = fresh
    for material in ("polymer", "aluminum", "stainless"):
        with reused.lock:
            again = _price(reused.result, reused.mesh, reused.features, material)
        assert again == _price(result, m, ctx.features, material), material
    from src.eval import similarity
    assert list(reused.identity_vec) == list(similarity.feature_vector(m, result.geometry, ctx))


@pytest.mark.asyncio
async def test_a_governed_or_partial_analysis_is_not_kept():
    from src.services import analysis_service

    data = _block_stl()
    user = types.SimpleNamespace(user_id=7, api_key_id=0)
    persisted = types.SimpleNamespace(id=1, ulid="01TEST", org_id=None)
    with patch.object(analysis_service, "_check_cache", AsyncMock(return_value=None)), \
         patch.object(analysis_service, "_persist_analysis", AsyncMock(return_value=persisted)), \
         patch.object(analysis_service, "_write_usage_event", AsyncMock()), \
         patch("src.auth.org_context.resolve_org", AsyncMock(return_value=None)), \
         patch("src.services.audit_service.emit_event", AsyncMock()):
        await analysis_service.run_analysis(
            file_bytes=data, filename="block.stl", processes="fdm,cnc_3axis", rule_pack=None,
            user=user, session=MagicMock(),
        )
        await analysis_service.run_analysis(
            file_bytes=data, filename="block.stl", processes=None, rule_pack="aerospace",
            user=user, session=MagicMock(),
        )
    assert pgc.size() == 0
