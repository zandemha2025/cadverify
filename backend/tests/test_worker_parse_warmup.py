from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest

@pytest.mark.asyncio
async def test_worker_blocks_on_real_parse_warmup_before_ready(monkeypatch):
    monkeypatch.setattr("src.services.reconstruction_service.check_reconstruction_availability", lambda: {"available": False, "effective_backend": "none"})
    with patch("src.parsers.parse_pool.startup") as start, \
         patch("src.parsers.parse_pool.prewarm", return_value=2) as warm, \
         patch("src.db.engine.init_engine", new=AsyncMock()), \
         patch("src.jobs.worker.write_heartbeat", new=AsyncMock()):
        from src.jobs.worker import startup
        ctx = {"redis": AsyncMock()}
        await startup(ctx)
    start.assert_called_once_with()
    warm.assert_called_once_with(block=True, timeout=90.0)
    assert ctx["parse_workers_warmup_dispatched"] == 2


def test_parse_warmup_fixture_is_real_small_step():
    fixture = Path(__file__).parents[1] / "src/parsers/fixtures/prewarm-cube.step"
    data = fixture.read_bytes()
    assert 1_000 < len(data) < 50_000
    assert b"ISO-10303-21" in data
    source = (Path(__file__).parents[1] / "src/parsers/parse_pool.py").read_text()
    assert 'prewarm_step_from_bytes(fixture, "prewarm-cube.step")' in source


def test_real_parse_warmup_uses_bounded_mesh_density():
    from src.parsers.step_mesher import is_step_supported, prewarm_step_from_bytes

    if not is_step_supported():
        pytest.skip("gmsh not installed; STEP parse path unavailable")
    fixture = Path(__file__).parents[1] / "src/parsers/fixtures/prewarm-cube.step"
    mesh = prewarm_step_from_bytes(fixture.read_bytes(), fixture.name)

    assert mesh.is_watertight
    assert 0 < len(mesh.faces) <= 1_000
