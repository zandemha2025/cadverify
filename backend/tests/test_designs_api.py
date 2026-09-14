"""HTTP contract tests for the Design Studio boundary."""
from __future__ import annotations

import io
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.designs import require_design_mutation, router
from src.auth.rate_limit import limiter
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session
from src.db.models import DesignProject, DesignRevision, Job


def _rows(status: str = "generating"):
    project = DesignProject(
        id=1,
        ulid="01KZZZZZZZZZZZZZZZZZZZZZZZ",
        org_id="01KYYYYYYYYYYYYYYYYYYYYYYY",
        created_by=7,
        name="Mounting plate",
        status=status,
        source_kind="template",
        current_revision=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    revision = DesignRevision(
        id=2,
        ulid="01KXXXXXXXXXXXXXXXXXXXXXXX",
        design_id=1,
        org_id=project.org_id,
        created_by=7,
        revision_no=1,
        status="ready" if status == "ready" else "queued",
        operation_plan_json={
            "kind": "plate",
            "width_mm": 80.0,
            "depth_mm": 50.0,
            "thickness_mm": 6.0,
            "holes": [],
        },
        generation_engine="proofshape-occ-v1",
    )
    job = Job(
        id=3,
        ulid="01KWWWWWWWWWWWWWWWWWWWWWWW",
        user_id=7,
        org_id=project.org_id,
        job_type="design_generation",
        status="queued",
    )
    return project, revision, job


def _app(role: str = "analyst") -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router, prefix="/api/v1/designs")
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=7,
        api_key_id=0,
        key_prefix="session",
        role=role,
    )
    if role != "viewer":
        app.dependency_overrides[require_design_mutation] = lambda: AuthedUser(
            user_id=7,
            api_key_id=0,
            key_prefix="session",
            role=role,
        )

    async def session():
        yield AsyncMock()

    app.dependency_overrides[get_db_session] = session
    return app


def _payload():
    return {
        "name": "Mounting plate",
        "design_note": "fixture prototype",
        "plan": {
            "kind": "plate",
            "width_mm": 80.0,
            "depth_mm": 50.0,
            "thickness_mm": 6.0,
            "holes": [],
        },
    }


def test_create_returns_durable_poll_contract(monkeypatch):
    from src.api import designs

    project, revision, job = _rows()
    create = AsyncMock(return_value=(project, revision, job))
    monkeypatch.setattr(designs.svc, "create_design", create)
    response = TestClient(_app()).post("/api/v1/designs", json=_payload())
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["design"]["id"] == project.ulid
    assert body["design"]["revision"]["plan"]["kind"] == "plate"
    assert body["job_id"] == job.ulid
    assert body["poll_url"] == f"/api/v1/designs/{project.ulid}"
    assert create.await_args.kwargs["plan"].kind == "plate"


def test_create_rejects_generated_source_before_service(monkeypatch):
    from src.api import designs

    create = AsyncMock()
    monkeypatch.setattr(designs.svc, "create_design", create)
    payload = _payload()
    payload["plan"]["python_source"] = "__import__('os').system('id')"
    response = TestClient(_app()).post("/api/v1/designs", json=payload)
    assert response.status_code == 422
    create.assert_not_awaited()


def test_interpret_is_analyst_only_and_returns_reviewable_plan():
    response = TestClient(_app()).post(
        "/api/v1/designs/interpret",
        json={"prompt": "80 x 50 x 6 mm plate"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["plan"]["kind"] == "plate"
    forbidden = TestClient(_app(role="viewer")).post(
        "/api/v1/designs/interpret",
        json={"prompt": "80 x 50 x 6 mm plate"},
    )
    assert forbidden.status_code == 403


def test_viewer_cannot_generate(monkeypatch):
    from src.api import designs

    create = AsyncMock()
    monkeypatch.setattr(designs.svc, "create_design", create)
    response = TestClient(_app(role="viewer")).post(
        "/api/v1/designs", json=_payload()
    )
    assert response.status_code == 403
    create.assert_not_awaited()


def test_preview_streams_only_service_authorized_artifact(monkeypatch):
    from src.api import designs

    project, revision, _job = _rows(status="ready")
    stream = io.BytesIO(b"solid proofshape\nendsolid proofshape\n")
    opened = AsyncMock(return_value=(project, revision, stream))
    monkeypatch.setattr(designs.svc, "open_artifact", opened)
    response = TestClient(_app(role="viewer")).get(
        f"/api/v1/designs/{project.ulid}/preview.stl"
    )
    assert response.status_code == 200
    assert response.content.startswith(b"solid proofshape")
    assert response.headers["content-type"].startswith("model/stl")
    assert stream.closed
    assert opened.await_args.kwargs["kind"] == "stl"


def test_revision_compare_is_viewer_accessible_and_evidence_bound(monkeypatch):
    from src.api import designs

    project, before, _job = _rows(status="ready")
    before.geometry_hash = "a" * 64
    before.geometry_metadata_json = {
        "bbox_mm": [80.0, 50.0, 6.0],
        "volume_cm3": 23.5,
        "surface_elements": 120,
        "solid_count": 1,
        "engine": "proofshape-occ-v1",
    }
    after = DesignRevision(
        id=4,
        ulid="01KREVISIONTWOXXXXXXXXXXXX",
        design_id=project.id,
        org_id=project.org_id,
        created_by=7,
        revision_no=2,
        status="ready",
        operation_plan_json={
            "kind": "plate",
            "width_mm": 82.0,
            "depth_mm": 50.0,
            "thickness_mm": 6.0,
            "holes": [],
        },
        geometry_hash="b" * 64,
        geometry_metadata_json={
            "bbox_mm": [82.0, 50.0, 6.0],
            "volume_cm3": 24.1,
            "surface_elements": 124,
            "solid_count": 1,
            "engine": "proofshape-occ-v1",
        },
        generation_engine="proofshape-occ-v1",
    )
    get_revision = AsyncMock(
        side_effect=[(project, before), (project, after)]
    )
    monkeypatch.setattr(designs.svc, "get_revision", get_revision)

    response = TestClient(_app(role="viewer")).get(
        f"/api/v1/designs/{project.ulid}/revisions/compare?from=1&to=2"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["same_geometry"] is False
    assert body["plan_changes"] == [
        {"path": "width_mm", "before": 80.0, "after": 82.0, "delta": 2.0}
    ]
    assert {
        (change["path"], change["delta"])
        for change in body["geometry_changes"]
    } == {
        ("bbox_mm[0]", 2.0),
        ("surface_elements", 4.0),
        ("volume_cm3", 0.6),
    }
    assert "Surface correspondence is not inferred" in body["limits"]
    assert get_revision.await_args_list[0].args[1:3] == (project.ulid, 1)
    assert get_revision.await_args_list[1].args[1:3] == (project.ulid, 2)


def test_revision_compare_preserves_list_positions_instead_of_inferring_features():
    from src.services.design_service import build_revision_comparison

    project, before, _job = _rows(status="ready")
    before.operation_plan_json["holes"] = [
        {"x_mm": -30.0, "y_mm": -15.0, "diameter_mm": 6.0},
        {"x_mm": 30.0, "y_mm": 15.0, "diameter_mm": 8.0},
    ]
    after = DesignRevision(
        id=4,
        ulid="01KREVISIONTWOXXXXXXXXXXXX",
        design_id=project.id,
        org_id=project.org_id,
        created_by=7,
        revision_no=2,
        status="ready",
        operation_plan_json={
            **before.operation_plan_json,
            "holes": list(reversed(before.operation_plan_json["holes"])),
        },
        generation_engine="proofshape-occ-v1",
    )

    comparison = build_revision_comparison(project, before, after)
    paths = {change["path"] for change in comparison["plan_changes"]}
    assert paths == {
        "holes[0].diameter_mm",
        "holes[0].x_mm",
        "holes[0].y_mm",
        "holes[1].diameter_mm",
        "holes[1].x_mm",
        "holes[1].y_mm",
    }
    assert "Surface correspondence is not inferred" in comparison["limits"]


def test_revision_compare_rejects_same_revision_before_lookup(monkeypatch):
    from src.api import designs

    get_revision = AsyncMock()
    monkeypatch.setattr(designs.svc, "get_revision", get_revision)
    project, _revision, _job = _rows(status="ready")
    response = TestClient(_app(role="viewer")).get(
        f"/api/v1/designs/{project.ulid}/revisions/compare?from=1&to=1"
    )
    assert response.status_code == 400
    get_revision.assert_not_awaited()
