"""Repro: prod instance dies on /validate for the gmsh-exported stepped shaft.

The audit fixture (⌀15×40 + ⌀10×15 fused, ⌀2 through-bore) parses clean
(preview-mesh 200 on prod) but the full /validate kills the deployed instance
(502 + instance restart, deterministic, cold instance). CI runs the exact
path on the same locked linux deps: parse pool → full analyzer set →
analysis-service serialization. If this segfaults/OOMs here, the CI exit
carries the signal prod swallows.
"""
from __future__ import annotations

import gzip
import pathlib

import pytest

ASSET = pathlib.Path(__file__).parent / "assets" / "stepped_shaft.stp.gz"


@pytest.fixture(scope="module")
def shaft_bytes() -> bytes:
    return gzip.decompress(ASSET.read_bytes())


def test_parse_pool_handles_the_fixture_shaft(shaft_bytes):
    from src.api.routes import _parse_mesh

    mesh, suffix = _parse_mesh(shaft_bytes, "stepped_shaft.stp")
    assert suffix == ".stp" and len(mesh.faces) > 100


def test_full_engine_on_the_fixture_shaft(shaft_bytes):
    from src.api.routes import _run_cost_engine_ctx, _parse_mesh

    mesh, _ = _parse_mesh(shaft_bytes, "stepped_shaft.stp")
    result, m, ctx = _run_cost_engine_ctx(mesh, "stepped_shaft.stp")
    codes = sorted({i.code for s in result.process_scores for i in s.issues})
    print("issue codes:", codes)
    assert "DEEP_HOLE" in codes          # the severe-bore finding must be there
    turning = next(s for s in result.process_scores if s.process.value == "cnc_turning")
    assert turning.score < 1.0


def test_analysis_service_path_on_the_fixture_shaft(shaft_bytes):
    """The exact service path /validate drives (DB-backed)."""
    import asyncio

    async def run():
        from src.services import analysis_service

        class _U:
            user_id = 1
            role = "user"

        from src.db.engine import get_engine
        eng = get_engine()
        from sqlalchemy.ext.asyncio import AsyncSession
        async with AsyncSession(eng) as session:
            return await analysis_service.run_analysis(
                file_bytes=shaft_bytes, filename="stepped_shaft.stp",
                processes=None, rule_pack=None, user=_U(), session=session,
                include_thickness=False,
            )

    result = asyncio.run(run())
    d = result if isinstance(result, dict) else getattr(result, "__dict__", {})
    assert d
