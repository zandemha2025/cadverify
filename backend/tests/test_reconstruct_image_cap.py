"""Reconstruction images are read with a cap, not whole and then measured.

Each uploaded photo is read in chunks and refused as soon as it passes
MAX_IMAGE_BYTES, so an oversize image is never held in memory in full and
no job is created for it.
"""
from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from starlette.datastructures import UploadFile

from src.api.reconstruct_router import router
from src.auth.rbac import require_org_checker
from src.auth.require_api_key import AuthedUser, require_api_key
from src.auth.validation_caps import require_paid_access
from src.db.engine import get_db_session

_AVAILABLE = {
    "available": True, "configured_backend": "local", "effective_backend": "local",
    "egress": False, "reason": "local reconstruction",
}
_HEADERS = {"Idempotency-Key": "01ARZ3NDEKTSV4RRFFQ69G5FAV"}


def _client():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_paid_access] = lambda: None
    def _user():
        return AuthedUser(user_id=42, api_key_id=1, key_prefix="cv_live_test")

    app.dependency_overrides[require_api_key] = _user
    app.dependency_overrides[require_org_checker] = _user
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()
    return TestClient(app)


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color=(10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def read_sizes(monkeypatch):
    sizes: list[int] = []
    original = UploadFile.read

    async def spy(self, size=-1):
        sizes.append(size)
        return await original(self, size)

    monkeypatch.setattr(UploadFile, "read", spy)
    return sizes


def test_oversize_image_is_refused_without_an_unbounded_read(monkeypatch, read_sizes):
    monkeypatch.setattr("src.reconstruction.preprocessing.MAX_IMAGE_BYTES", 4096)
    create = AsyncMock()
    with patch("src.services.reconstruction_service.check_reconstruction_availability",
               return_value=_AVAILABLE), \
         patch("src.services.reconstruction_service.create_reconstruction_job", create):
        resp = _client().post(
            "/api/v1/reconstruct",
            files=[("images", ("big.png", b"\x89PNG" + b"\0" * 10_000, "image/png"))],
            headers=_HEADERS,
        )
    assert resp.status_code == 400, resp.text
    assert "4096 bytes" in resp.json()["detail"]
    create.assert_not_awaited()
    assert read_sizes and all(size > 0 for size in read_sizes), read_sizes


def test_images_within_cap_reach_the_job_whole(monkeypatch, read_sizes):
    monkeypatch.setattr("src.reconstruction.preprocessing.MAX_IMAGE_BYTES", 1 << 20)
    job = MagicMock(ulid="01RECON0000000000000001", status="queued")
    create = AsyncMock(return_value=job)
    a, b = _png(), _png()[::-1]
    with patch("src.services.reconstruction_service.check_reconstruction_availability",
               return_value=_AVAILABLE), \
         patch("src.services.reconstruction_service.create_reconstruction_job", create):
        resp = _client().post(
            "/api/v1/reconstruct",
            files=[("images", ("a.png", a, "image/png")), ("images", ("b.png", b, "image/png"))],
            headers=_HEADERS,
        )
    assert resp.status_code == 202, resp.text
    image_data = create.await_args.args[2]
    assert image_data == [(a, "image/png"), (b, "image/png")]
    assert all(size > 0 for size in read_sizes), read_sizes
