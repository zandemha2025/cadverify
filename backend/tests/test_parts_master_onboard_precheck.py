"""Library onboarding checks a ZIP's size and file count before extracting it.

The ZIP's own directory declares each entry's uncompressed size, and the
extractor never writes more than that, so the onboarding size cap
(PARTS_MASTER_MAX_MB) and file cap are applied to those declared numbers
first. An archive over either cap is refused with 413 and nothing is
extracted to the blob store.
"""
from __future__ import annotations

import io
import zipfile
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


@pytest.fixture()
def onboard(monkeypatch, tmp_path):
    from fastapi import FastAPI

    from src.api import identity
    from src.auth.rate_limit import limiter
    from src.auth.require_api_key import AuthedUser, require_api_key
    from src.db.engine import get_db_session
    from src.services import batch_service

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(identity.router, prefix="/api/v1/identity")
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=1, api_key_id=0, key_prefix="session", role="analyst"
    )
    session = AsyncMock()

    async def fake_session():
        yield session

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(identity, "resolve_org", AsyncMock(return_value="org-onboard-precheck"))
    importer = AsyncMock(return_value={
        "onboarded": 0, "unnamed": 0, "skipped": [], "manifest_errors": [],
        "manifest_registered": 0, "library_size": 0,
    })
    monkeypatch.setattr(identity.pmsvc, "onboard_library", importer)
    monkeypatch.setattr(batch_service, "BATCH_BLOB_DIR", str(tmp_path / "blobs"))

    extracted: list[str] = []
    real_extract = batch_service.extract_zip_path_to_items

    def spy_extract(path, namespace):
        extracted.append(namespace)
        return real_extract(path, namespace)

    monkeypatch.setattr(batch_service, "extract_zip_path_to_items", spy_extract)

    async def post(files):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            return await c.post("/api/v1/identity/library/onboard", files=files)

    return identity, post, extracted, importer, tmp_path


@pytest.mark.asyncio
async def test_zip_over_size_cap_is_refused_before_extraction(onboard, monkeypatch):
    identity, post, extracted, importer, tmp_path = onboard
    monkeypatch.setattr(identity, "_ONBOARD_MAX_BYTES", 1000)
    # Compresses to well under 1000 bytes; declares 1200 bytes of CAD.
    body = _zip({"a.stl": b"\0" * 600, "b.stl": b"\0" * 600})
    assert len(body) < 1000
    r = await post([("zip", ("library.zip", body))])
    assert r.status_code == 413, r.text
    assert "onboarding upload" in r.json()["detail"]
    assert extracted == []
    importer.assert_not_awaited()
    assert not list((tmp_path / "blobs").rglob("*.stl"))


@pytest.mark.asyncio
async def test_zip_over_remaining_budget_after_direct_files_is_refused_first(onboard, monkeypatch):
    identity, post, extracted, importer, _ = onboard
    monkeypatch.setattr(identity, "_ONBOARD_MAX_BYTES", 1000)
    body = _zip({"b.stl": b"\0" * 600})
    r = await post([("files", ("a.stl", b"\0" * 500)), ("zip", ("library.zip", body))])
    assert r.status_code == 413, r.text
    assert extracted == []
    importer.assert_not_awaited()


@pytest.mark.asyncio
async def test_zip_over_file_cap_is_refused_before_extraction(onboard, monkeypatch):
    identity, post, extracted, importer, _ = onboard
    monkeypatch.setattr(identity.pmsvc, "ONBOARD_MAX_FILES", 2)
    body = _zip({f"p{i}.stl": b"solid\n" for i in range(3)})
    r = await post([("zip", ("library.zip", body))])
    assert r.status_code == 413, r.text
    assert "file cap" in r.json()["detail"]
    assert extracted == []
    importer.assert_not_awaited()


@pytest.mark.asyncio
async def test_zip_within_caps_is_extracted_and_onboarded(onboard, monkeypatch):
    identity, post, extracted, importer, _ = onboard
    monkeypatch.setattr(identity, "_ONBOARD_MAX_BYTES", 1000)
    monkeypatch.setattr(identity.pmsvc, "ONBOARD_MAX_FILES", 2)
    # Non-CAD entries do not count toward either cap, as in the extractor.
    body = _zip({"a.stl": b"\0" * 400, "b.stl": b"\0" * 400, "drawing.pdf": b"\0" * 5000})
    r = await post([("zip", ("library.zip", body))])
    assert r.status_code == 200, r.text
    assert len(extracted) == 1
    files = importer.await_args.args[3]
    assert sorted(name for name, _ in files) == ["a.stl", "b.stl"]
