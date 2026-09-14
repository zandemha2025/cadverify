import asyncio
import hashlib
import time
from unittest.mock import AsyncMock, patch

import pytest

from src.services.analysis_service import _persist_source_evidence


class _Mesh:
    def export(self, *, file_type):
        assert file_type == "stl"
        time.sleep(0.04)
        return b"costable-stl"


@pytest.mark.asyncio
async def test_source_and_derivative_are_both_durable_and_overlap():
    source = b"exact-source"
    digest = hashlib.sha256(source).hexdigest()
    events: list[str] = []

    async def save_source(*_args):
        events.append("source-start")
        await asyncio.sleep(0.08)
        events.append("source-durable")

    async def save_costable(*_args):
        events.append("costable-start")
        await asyncio.sleep(0.08)
        events.append("costable-durable")

    started = time.perf_counter()
    with (
        patch(
            "src.services.source_artifact_service.save_source_artifact",
            new=save_source,
        ),
        patch(
            "src.services.source_artifact_service.costable_mesh_exists",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "src.services.source_artifact_service.save_costable_mesh_artifact",
            new=save_costable,
        ),
    ):
        await _persist_source_evidence(
            "org-a", digest, "part.step", source, parsed_mesh=_Mesh()
        )

    elapsed = time.perf_counter() - started
    assert events[-1] in {"source-durable", "costable-durable"}
    assert {"source-durable", "costable-durable"}.issubset(events)
    assert elapsed < 0.17, "independent durable writes regressed to serial execution"


@pytest.mark.asyncio
async def test_source_evidence_waits_for_both_and_propagates_a_failed_write():
    source = b"exact-source"
    digest = hashlib.sha256(source).hexdigest()
    costable_finished = False

    async def fail_source(*_args):
        await asyncio.sleep(0.01)
        raise OSError("source store unavailable")

    async def save_costable(*_args):
        nonlocal costable_finished
        await asyncio.sleep(0.08)
        costable_finished = True

    with (
        patch(
            "src.services.source_artifact_service.save_source_artifact",
            new=fail_source,
        ),
        patch(
            "src.services.source_artifact_service.costable_mesh_exists",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "src.services.source_artifact_service.save_costable_mesh_artifact",
            new=save_costable,
        ),
    ):
        with pytest.raises(ExceptionGroup) as failure:
            await _persist_source_evidence(
                "org-a", digest, "part.step", source, parsed_mesh=_Mesh()
            )

    assert any("source store unavailable" in str(error) for error in failure.value.exceptions)
    assert not costable_finished
