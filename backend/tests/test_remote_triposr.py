from __future__ import annotations

import io
import json
from unittest.mock import patch

import httpx
import pytest
import respx
import trimesh
from PIL import Image

from src.reconstruction.engine import ReconstructParams
from src.reconstruction.remote_triposr import RemoteTripoSR


MODEL_VERSION = f"approved/triposr:{'a' * 64}"
PREDICTION_ID = "prediction123"
API_BASE = "https://api.replicate.com/v1"
OUTPUT_URL = "https://replicate.delivery/pbxt/mesh.stl"


def _configure(monkeypatch) -> None:
    monkeypatch.setenv("REPLICATE_API_TOKEN", "test-token")
    monkeypatch.setenv("TRIPOSR_REPLICATE_MODEL", MODEL_VERSION)
    monkeypatch.setenv("RECONSTRUCTION_TIMEOUT_SEC", "5")


def _image_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), (40, 90, 140)).save(buffer, format="PNG")
    return buffer.getvalue()


def _stl_bytes() -> bytes:
    exported = trimesh.creation.box(extents=(2, 3, 4)).export(file_type="stl")
    assert isinstance(exported, bytes)
    return exported


@pytest.mark.asyncio
@respx.mock
async def test_remote_reconstruction_uses_pinned_model_and_trusted_output(
    monkeypatch,
):
    _configure(monkeypatch)
    create = respx.post(f"{API_BASE}/predictions").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": PREDICTION_ID,
                "status": "processing",
            },
        )
    )
    poll = respx.get(f"{API_BASE}/predictions/{PREDICTION_ID}").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": PREDICTION_ID,
                "status": "succeeded",
                "output": {"mesh": OUTPUT_URL},
            },
        )
    )

    def output_response(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(
            200,
            content=_stl_bytes(),
            headers={"content-type": "model/stl"},
        )

    output = respx.get(OUTPUT_URL).mock(side_effect=output_response)
    monkeypatch.setattr(
        "src.reconstruction.remote_triposr._POLL_INTERVAL_SEC", 0
    )

    result = await RemoteTripoSR().reconstruct(
        _image_bytes(), ReconstructParams()
    )

    assert result.face_count == 12
    assert result.mesh_bytes
    assert result.method == "triposr_remote"
    assert create.called and poll.called and output.called
    request_body = json.loads(create.calls[0].request.content)
    assert request_body["version"] == MODEL_VERSION
    assert request_body["input"]["image"].startswith(
        "data:image/jpeg;base64,"
    )
    assert len(request_body["input"]["image"]) < 350_000
    assert create.calls[0].request.headers["Cancel-After"] == "5s"


@pytest.mark.asyncio
@respx.mock
async def test_remote_reconstruction_rejects_untrusted_output_url(monkeypatch):
    _configure(monkeypatch)
    respx.post(f"{API_BASE}/predictions").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": PREDICTION_ID,
                "status": "succeeded",
                "output": "https://attacker.example/mesh.stl",
            },
        )
    )
    with pytest.raises(RuntimeError, match="approved delivery domain"):
        await RemoteTripoSR().reconstruct(_image_bytes(), ReconstructParams())


@pytest.mark.asyncio
@respx.mock
async def test_remote_timeout_cancels_the_paid_prediction(monkeypatch):
    _configure(monkeypatch)
    respx.post(f"{API_BASE}/predictions").mock(
        return_value=httpx.Response(
            201,
            json={"id": PREDICTION_ID, "status": "processing"},
        )
    )
    cancel = respx.post(
        f"{API_BASE}/predictions/{PREDICTION_ID}/cancel"
    ).mock(return_value=httpx.Response(202))

    with patch(
        "src.reconstruction.remote_triposr.time.perf_counter",
        side_effect=[0.0, 0.0, 6.0],
    ):
        with pytest.raises(httpx.TimeoutException):
            await RemoteTripoSR().reconstruct(
                _image_bytes(), ReconstructParams()
            )

    assert cancel.called


@pytest.mark.asyncio
@respx.mock
async def test_health_checks_the_exact_pinned_version(monkeypatch):
    _configure(monkeypatch)
    version_url = f"{API_BASE}/models/approved/triposr/versions/{'a' * 64}"
    route = respx.get(version_url).mock(return_value=httpx.Response(200))

    assert await RemoteTripoSR().health_check() is True
    assert route.called


def test_remote_engine_refuses_unpinned_or_uncredentialed_configuration(
    monkeypatch,
):
    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
    monkeypatch.delenv("TRIPOSR_REPLICATE_MODEL", raising=False)
    with pytest.raises(RuntimeError, match="REPLICATE_API_TOKEN"):
        RemoteTripoSR()

    monkeypatch.setenv("REPLICATE_API_TOKEN", "test-token")
    monkeypatch.setenv("TRIPOSR_REPLICATE_MODEL", "stability-ai/triposr")
    with pytest.raises(RuntimeError, match="64-hex-version"):
        RemoteTripoSR()
