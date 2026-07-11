"""Production object-store wiring beyond the adapter-level contract."""
from __future__ import annotations

import io
import zipfile
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def s3_environment(monkeypatch):
    moto = pytest.importorskip("moto", reason="moto not installed")
    boto3 = pytest.importorskip("boto3", reason="boto3 not installed")
    mock = moto.mock_aws()
    mock.start()
    try:
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="cadverify-production-paths")
        monkeypatch.setenv("OBJECT_STORE_BACKEND", "s3")
        monkeypatch.setenv("OBJECT_STORE_S3_BUCKET", "cadverify-production-paths")
        monkeypatch.setenv("OBJECT_STORE_S3_REGION", "us-east-1")
        monkeypatch.setenv("OBJECT_STORE_S3_PREFIX", "production")
        yield client
    finally:
        mock.stop()


def _zip_with(filename: str, payload: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(filename, payload)
    return buf.getvalue()


def test_batch_zip_is_shared_through_s3(s3_environment):
    from src.services import batch_service

    mesh = b"solid production\nendsolid production\n"
    items = batch_service.extract_zip_to_items(
        _zip_with("part.stl", mesh), "batch-production-1"
    )

    assert items[0]["path"].startswith("s3://cadverify-production-paths/")
    assert batch_service.read_batch_blob("batch-production-1", "part.stl") == mesh
    assert s3_environment.get_object(
        Bucket="cadverify-production-paths",
        Key="production/batch/batch-production-1/part.stl",
    )["Body"].read() == mesh

    batch_service.cleanup_batch_files("batch-production-1")
    assert batch_service._batch_store().list_keys("batch-production-1") == []


@pytest.mark.asyncio
async def test_reconstruction_inputs_and_output_are_shared_through_s3(s3_environment):
    from src.services import reconstruction_service

    job_ulid = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    images = [(b"png-payload", "image/png"), (b"jpeg-payload", "image/jpeg")]

    await reconstruction_service.save_reconstruction_images(job_ulid, images)
    assert reconstruction_service.load_reconstruction_images(job_ulid) == images

    locator = await reconstruction_service.save_reconstruction_mesh(
        job_ulid, b"solid mesh\nendsolid mesh\n"
    )
    assert locator.startswith("s3://cadverify-production-paths/")
    assert s3_environment.get_object(
        Bucket="cadverify-production-paths",
        Key=f"production/reconstruct/{job_ulid}/output/mesh.stl",
    )["Body"].read() == b"solid mesh\nendsolid mesh\n"


def test_factory_isolates_each_purpose_under_configured_prefix(s3_environment):
    from src.storage import get_object_store

    meshes = get_object_store("meshes", default_root="/tmp/unused")
    reports = get_object_store("cost-pdf", default_root="/tmp/unused")
    assert meshes.url("same.bin").endswith("/production/meshes/same.bin")
    assert reports.url("same.bin").endswith("/production/cost-pdf/same.bin")


@pytest.mark.asyncio
async def test_parts_master_zip_requests_use_isolated_object_namespaces(tmp_path):
    from src.api.identity import _read_onboard_zip_files

    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    first.write_bytes(b"zip")
    second.write_bytes(b"zip")

    with (
        patch(
            "src.services.batch_service.stream_upload_to_tempfile",
            new=AsyncMock(side_effect=[str(first), str(second)]),
        ),
        patch(
            "src.services.batch_service.extract_zip_path_to_items",
            return_value=[],
        ) as extract,
        patch("src.services.batch_service.cleanup_batch_files") as cleanup,
    ):
        await _read_onboard_zip_files(AsyncMock())
        await _read_onboard_zip_files(AsyncMock())

    namespaces = [call.args[1] for call in extract.call_args_list]
    assert len(namespaces) == 2
    assert namespaces[0].startswith("parts-master-")
    assert namespaces[1].startswith("parts-master-")
    assert namespaces[0] != namespaces[1]
    assert [call.args[0] for call in cleanup.call_args_list] == namespaces
