"""Focused regressions for the batch/design release-failure matrix."""
from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.auth.require_api_key import AuthedUser, require_api_key
from src.auth.rate_limit import limiter
from src.db.engine import get_db_session
from src.db.models import Analysis, Batch, BatchItem, DesignProject, DesignRevision, Job
from src.designs.generator import GeneratedArtifacts
from src.designs.schema import PlatePlan

ORG_ID = "01ORGRELEASEEVIDENCE000001"
DESIGN_ID = "01DESIGNQUEUEFAILED0000001"
REVISION_ID = "01REVISIONQUEUEFAILED00001"
JOB_ID = "01JOBQUEUEFAILED0000000001"


def _scalar_result(value):
    result = MagicMock()
    result.scalars.return_value.first.return_value = value
    return result


class _SessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_args):
        return False


class _SessionFactory:
    def __init__(self, sessions):
        self.sessions = list(sessions)

    def __call__(self):
        return _SessionContext(self.sessions.pop(0))


def _request(headers: dict[str, str]):
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [
                (name.lower().encode("ascii"), value.encode("ascii"))
                for name, value in headers.items()
            ],
        }
    )


def test_fault_selection_is_secret_gated_and_operation_scoped(monkeypatch):
    from fastapi import HTTPException

    from src.services.release_fault_injection import (
        DESIGN_FAULT_MODES,
        requested_release_fault,
    )

    headers = {
        "x-proofshape-e2e-token": "release-secret",
        "x-proofshape-e2e-fault": "cad_kernel",
    }
    monkeypatch.delenv("E2E_FAULT_INJECTION_TOKEN", raising=False)
    assert requested_release_fault(_request(headers), DESIGN_FAULT_MODES) is None

    monkeypatch.setenv("E2E_FAULT_INJECTION_TOKEN", "release-secret")
    assert requested_release_fault(_request(headers), DESIGN_FAULT_MODES) == "cad_kernel"

    headers["x-proofshape-e2e-fault"] = "batch_queue"
    with pytest.raises(HTTPException) as exc:
        requested_release_fault(_request(headers), DESIGN_FAULT_MODES)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_design_queue_failure_is_durable_and_returns_retryable_revision(monkeypatch):
    from src.services import design_service

    session = AsyncMock()
    session.add = MagicMock()
    monkeypatch.setattr(design_service, "resolve_org", AsyncMock(return_value=ORG_ID))
    monkeypatch.setattr(design_service, "emit_event", AsyncMock())
    enqueue = AsyncMock()
    monkeypatch.setattr(design_service, "_enqueue", enqueue)
    user = AuthedUser(user_id=7, api_key_id=0, key_prefix="session")

    with pytest.raises(design_service.DesignQueueUnavailableError) as exc:
        await design_service.create_design(
            session,
            user,
            name="Queue recovery plate",
            plan=PlatePlan(
                kind="plate",
                width_mm=80.0,
                depth_mm=50.0,
                thickness_mm=6.0,
                holes=[],
            ),
            design_note="retain these inputs",
            release_test_fault="design_queue",
        )

    enqueue.assert_not_awaited()
    project = exc.value.project
    revision = exc.value.revision
    assert project.status == "failed"
    assert project.current_revision == 1
    assert revision.status == "failed"
    assert revision.error_code == "DESIGN_ENQUEUE_FAILED"
    assert revision.error_detail == design_service.DESIGN_QUEUE_FAILURE_COPY
    assert revision.operation_plan_json["width_mm"] == 80.0
    assert revision.design_note == "retain these inputs"
    assert session.commit.await_count == 2
    serialized = design_service.serialize_design(project, revision)
    assert serialized["revision"]["links"] == {
        "preview": None,
        "download_step": None,
        "verify": None,
    }


def test_design_queue_api_returns_failed_design_and_exact_copy(monkeypatch):
    from src.api import designs
    from src.services import design_service

    monkeypatch.setenv("E2E_FAULT_INJECTION_TOKEN", "release-secret")
    project = DesignProject(
        id=1,
        ulid=DESIGN_ID,
        org_id=ORG_ID,
        created_by=7,
        name="Queue recovery plate",
        status="failed",
        source_kind="template",
        current_revision=1,
    )
    revision = DesignRevision(
        id=2,
        ulid=REVISION_ID,
        design_id=1,
        org_id=ORG_ID,
        created_by=7,
        revision_no=1,
        status="failed",
        operation_plan_json={
            "kind": "plate",
            "width_mm": 80.0,
            "depth_mm": 50.0,
            "thickness_mm": 6.0,
            "holes": [],
        },
        generation_engine="proofshape-occ-v1",
        error_code="DESIGN_ENQUEUE_FAILED",
        error_detail=design_service.DESIGN_QUEUE_FAILURE_COPY,
    )
    create = AsyncMock(
        side_effect=design_service.DesignQueueUnavailableError(project, revision)
    )
    monkeypatch.setattr(designs.svc, "create_design", create)
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(designs.router, prefix="/api/v1/designs")
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=7,
        api_key_id=0,
        key_prefix="session",
        role="analyst",
    )
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()
    response = TestClient(app).post(
        "/api/v1/designs",
        json={
            "name": project.name,
            "design_note": "retain me",
            "plan": revision.operation_plan_json,
        },
        headers={
            "x-proofshape-e2e-token": "release-secret",
            "x-proofshape-e2e-fault": "design_queue",
        },
    )
    assert response.status_code == 503, response.text
    body = response.json()
    assert body["detail"] == {
        "code": "DESIGN_ENQUEUE_FAILED",
        "message": design_service.DESIGN_QUEUE_FAILURE_COPY,
    }
    assert body["design"]["id"] == DESIGN_ID
    assert body["design"]["revision"]["status"] == "failed"
    assert body["design"]["revision"]["links"] == {
        "preview": None,
        "download_step": None,
        "verify": None,
    }
    assert create.await_args.kwargs["release_test_fault"] == "design_queue"


def _design_worker_rows(fault: str):
    job = MagicMock(spec=Job)
    job.ulid = JOB_ID
    job.user_id = 7
    job.org_id = ORG_ID
    job.job_type = "design_generation"
    job.status = "queued"
    job.params_json = {"revision_ulid": REVISION_ID, "release_test_fault": fault}
    job.result_json = None

    revision = MagicMock(spec=DesignRevision)
    revision.ulid = REVISION_ID
    revision.design_id = 11
    revision.org_id = ORG_ID
    revision.revision_no = 1
    revision.status = "queued"
    revision.operation_plan_json = {
        "kind": "plate",
        "width_mm": 80.0,
        "depth_mm": 50.0,
        "thickness_mm": 6.0,
        "holes": [],
    }
    revision.step_object_key = None
    revision.stl_object_key = None
    revision.geometry_hash = None

    project = MagicMock(spec=DesignProject)
    project.id = 11
    project.ulid = DESIGN_ID
    project.org_id = ORG_ID
    project.current_revision = 1
    project.status = "generating"
    return job, revision, project


async def _run_design_fault(monkeypatch, fault: str):
    from src.jobs import design_tasks

    job, revision, project = _design_worker_rows(fault)
    first = AsyncMock()
    first.execute = AsyncMock(
        side_effect=[
            _scalar_result(job),
            _scalar_result(revision),
            _scalar_result(project),
        ]
    )
    failed = AsyncMock()
    failed.execute = AsyncMock(
        side_effect=[
            _scalar_result(job),
            _scalar_result(revision),
            _scalar_result(project),
        ]
    )
    factory = _SessionFactory([first, failed])
    monkeypatch.setattr(design_tasks, "get_session_factory", lambda: factory)
    monkeypatch.setattr(design_tasks, "emit_event", AsyncMock())
    result = await design_tasks._run_design_generation_job(JOB_ID)
    return result, job, revision, project


@pytest.mark.asyncio
async def test_cad_kernel_fault_uses_exact_copy_and_creates_no_artifact(monkeypatch):
    from src.jobs import design_tasks
    from src.services.design_service import DESIGN_KERNEL_FAILURE_COPY

    generate = MagicMock()
    monkeypatch.setattr(design_tasks, "generate_design_artifacts", generate)
    result, job, revision, project = await _run_design_fault(monkeypatch, "cad_kernel")

    generate.assert_not_called()
    assert result == {
        "code": "DESIGN_GENERATION_FAILED",
        "message": DESIGN_KERNEL_FAILURE_COPY,
    }
    assert job.status == revision.status == project.status == "failed"
    assert revision.error_detail == DESIGN_KERNEL_FAILURE_COPY
    assert revision.step_object_key is None
    assert revision.stl_object_key is None


@pytest.mark.asyncio
async def test_object_store_fault_cleans_partial_bytes_and_exposes_no_links(monkeypatch):
    from src.jobs import design_tasks
    from src.services import design_service

    artifacts = GeneratedArtifacts(
        step_bytes=b"STEP" * 64,
        stl_bytes=b"STL" * 64,
        metadata={"bbox_mm": [80.0, 50.0, 6.0]},
    )
    monkeypatch.setattr(design_tasks, "generate_design_artifacts", MagicMock(return_value=artifacts))
    store = MagicMock()
    monkeypatch.setattr(design_tasks, "_design_store", lambda: store)

    result, _job, revision, project = await _run_design_fault(monkeypatch, "object_store")

    assert result == {
        "code": "DESIGN_ARTIFACT_STORE_FAILED",
        "message": design_service.DESIGN_STORE_FAILURE_COPY,
    }
    assert store.put.call_count == 1
    store.delete_prefix.assert_called_once()
    assert revision.step_object_key is None
    assert revision.stl_object_key is None
    assert design_service.serialize_revision(project, revision)["links"] == {
        "preview": None,
        "download_step": None,
        "verify": None,
    }


@pytest.mark.asyncio
async def test_batch_progress_reports_exact_completed_failed_skipped_arithmetic():
    from src.services.batch_service import get_batch_progress

    batch = MagicMock(spec=Batch)
    batch.id = 9
    batch.ulid = "01BATCHCANCELLED0000000001"
    batch.status = "cancelled"
    batch.input_mode = "zip"
    batch.total_items = 6
    batch.concurrency_limit = 1
    batch.created_at = datetime.now(timezone.utc)
    batch.started_at = datetime.now(timezone.utc)
    batch.completed_at = datetime.now(timezone.utc)
    session = AsyncMock()
    batch_result = _scalar_result(batch)
    count_result = MagicMock()
    count_result.all.return_value = [
        (9, "completed", 2),
        (9, "failed", 1),
        (9, "skipped", 3),
    ]
    session.execute = AsyncMock(side_effect=[batch_result, count_result])

    progress = await get_batch_progress(session, batch.ulid, user_id=7)
    assert progress is not None
    assert progress["completed_items"] == 2
    assert progress["failed_items"] == 1
    assert progress["skipped_items"] == 3
    assert progress["pending_items"] == 0
    assert sum(progress[key] for key in ("completed_items", "failed_items", "skipped_items")) == 6


@pytest.mark.asyncio
async def test_batch_item_and_csv_share_exact_result_fields():
    from src.services import batch_service

    item = MagicMock(spec=BatchItem)
    item.id = 3
    item.filename = "fixture.step"
    item.status = "completed"
    item.duration_ms = 125.5
    item.error_message = None
    analysis = MagicMock(spec=Analysis)
    analysis.ulid = "01ANALYSISBATCHRESULT00001"
    analysis.verdict = "pass"
    analysis.result_json = {"best_process": "cnc_milling", "issues": [{"id": 1}]}
    expected = {
        "analysis_url": "/api/v1/analyses/01ANALYSISBATCHRESULT00001",
        "verdict": "pass",
        "best_process": "cnc_milling",
        "issue_count": 1,
    }
    assert batch_service.dfm_analysis_result_fields(analysis) == expected

    rows = MagicMock()
    rows.all.return_value = [(item, analysis)]
    empty = MagicMock()
    empty.all.return_value = []
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[rows, empty])
    csv_text = "".join(
        [chunk async for chunk in batch_service.generate_results_csv(session, batch_id=5)]
    )
    assert csv_text.splitlines()[0] == (
        "filename,status,verdict,best_process,issue_count,duration_ms,analysis_url,error"
    )
    assert csv_text.splitlines()[1] == (
        "fixture.step,completed,pass,cnc_milling,1,125.5,"
        "/api/v1/analyses/01ANALYSISBATCHRESULT00001,"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("item_status", "batch_status", "expected_status"),
    [
        ("completed", "processing", "completed"),
        ("queued", "cancelled", "skipped"),
    ],
)
async def test_duplicate_or_cancelled_batch_item_task_does_no_work(
    monkeypatch,
    item_status,
    batch_status,
    expected_status,
):
    from src.jobs import batch_tasks
    from src.services import analysis_service

    item = MagicMock(spec=BatchItem)
    item.ulid = "01BATCHITEMDUPLICATE000001"
    item.batch_id = 12
    item.status = item_status
    batch = MagicMock(spec=Batch)
    batch.id = 12
    batch.ulid = "01BATCHDUPLICATE000000001"
    batch.status = batch_status
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_scalar_result(item), _scalar_result(batch)])
    factory = _SessionFactory([session])
    monkeypatch.setattr(batch_tasks, "get_session_factory", lambda: factory)
    run_analysis = AsyncMock()
    monkeypatch.setattr(analysis_service, "run_analysis", run_analysis)

    await batch_tasks.run_batch_item({}, item.ulid)

    run_analysis.assert_not_awaited()
    assert item.status == expected_status
    if batch_status == "cancelled":
        session.commit.assert_awaited_once()


def _batch_api_app(session: AsyncMock) -> FastAPI:
    from src.api.batch_router import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=7,
        api_key_id=0,
        key_prefix="session",
        role="analyst",
    )
    app.dependency_overrides[get_db_session] = lambda: session
    return app


def test_batch_item_api_and_csv_fields_use_the_same_analysis_identity(monkeypatch):
    from src.api import batch_router

    batch = MagicMock(spec=Batch)
    batch.id = 22
    batch.ulid = "01BATCHDETAILRESULT00000001"
    item = MagicMock(spec=BatchItem)
    item.id = 31
    item.ulid = "01ITEMDETAILRESULT000000001"
    item.filename = "detail.step"
    item.status = "completed"
    item.priority = "normal"
    item.analysis_id = 42
    item.error_message = None
    item.duration_ms = 125.5
    item.created_at = datetime.now(timezone.utc)
    analysis = MagicMock(spec=Analysis)
    analysis.ulid = "01ANALYSISBATCHRESULT00001"
    analysis.verdict = "pass"
    analysis.result_json = {"best_process": "cnc_milling", "issues": [{"id": 1}]}
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_scalar_result(batch))
    monkeypatch.setattr(
        batch_router.batch_service,
        "get_batch_items_page",
        AsyncMock(return_value=([(item, analysis)], False)),
    )
    response = TestClient(_batch_api_app(session)).get(
        f"/api/v1/batch/{batch.ulid}/items"
    )
    assert response.status_code == 200, response.text
    row = response.json()["items"][0]
    assert row["status"] == "completed"
    assert row["analysis_url"] == "/api/v1/analyses/01ANALYSISBATCHRESULT00001"
    assert row["verdict"] == "pass"
    assert row["best_process"] == "cnc_milling"
    assert row["issue_count"] == 1
    assert row["error_message"] is None


def test_batch_queue_fault_returns_durable_failed_identity(monkeypatch):
    from src.api import batch_router

    monkeypatch.setenv("E2E_FAULT_INJECTION_TOKEN", "release-secret")
    session = AsyncMock()
    batch = MagicMock(spec=Batch)
    batch.id = 22
    batch.ulid = "01BATCHQUEUEFAILED00000001"
    batch.status = "pending"
    batch.manifest_json = None
    batch.total_items = 0
    batch.failed_items = 0

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("fixture.step", b"ISO-10303-21; fixture")
    buffer.seek(0)

    with patch.object(batch_router, "batch_service") as service, patch(
        "src.jobs.arq_backend.get_arq_pool", new_callable=AsyncMock
    ) as pool:
        service.create_batch = AsyncMock(return_value=batch)
        service.stream_upload_to_tempfile = AsyncMock(return_value="/tmp/missing-release-fixture.zip")
        service.extract_zip_path_to_items.return_value = [
            {"filename": "fixture.step", "path": "/tmp/fixture.step", "size": 24}
        ]
        service.create_batch_items = AsyncMock(return_value=1)
        service.mark_pending_items_terminal = AsyncMock()
        service.mark_batch_failed.side_effect = lambda row, _reason: setattr(row, "status", "failed")

        response = TestClient(_batch_api_app(session)).post(
            "/api/v1/batch",
            files={"file": ("fixture.zip", buffer, "application/zip")},
            headers={
                "x-proofshape-e2e-token": "release-secret",
                "x-proofshape-e2e-fault": "batch_queue",
            },
        )

    assert response.status_code == 503, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "BATCH_ENQUEUE_FAILED"
    assert detail["accepted_batch"] == {
        "batch_id": batch.ulid,
        "status": "failed",
        "status_url": f"/api/v1/batch/{batch.ulid}",
    }
    assert batch.manifest_json["release_test_fault"] == "batch_queue"
    service.mark_pending_items_terminal.assert_awaited_once_with(session, batch.id, "skipped")
    pool.assert_not_awaited()
