"""Real Postgres + OpenCASCADE Design Studio lifecycle and tenant isolation.

Skipped unless DATABASE_URL points at Postgres migrated to head. The ARQ enqueue
call is replaced with a no-op and the exact worker task is invoked directly;
queue transport is already covered separately, while this test proves the
database, artifact, audit, and HTTP boundaries in one event loop.
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock

import pytest

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(not _PG, reason="requires live Postgres")


def _build_app():
    from fastapi import FastAPI

    from src.api.designs import router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router, prefix="/api/v1/designs")
    return app


def _act_as(app, user_id: int, role: str = "analyst") -> None:
    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id,
        api_key_id=0,
        key_prefix="session",
        role=role,
    )


@_requires_pg
@pytest.mark.asyncio
async def test_design_lifecycle_worker_artifacts_audit_and_isolation(monkeypatch, tmp_path):
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng
    from src.jobs.design_tasks import run_design_generation_job
    from src.services import design_service

    monkeypatch.setenv("RATE_LIMIT_DISABLED", "1")
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "local")
    monkeypatch.setenv("DESIGN_BLOB_DIR", str(tmp_path / "designs"))
    monkeypatch.setattr(design_service, "_enqueue", AsyncMock())

    tag = uuid.uuid4().hex[:10]
    org_a, org_b = str(ULID()), str(ULID())
    async with eng.get_session_factory()() as session:
        for oid, label in ((org_a, "A"), (org_b, "B")):
            await session.execute(
                text(
                    "INSERT INTO organizations (id, name, slug) "
                    "VALUES (:id, :name, :slug)"
                ),
                {"id": oid, "name": f"Design {label} {tag}", "slug": f"ds-{tag}-{label.lower()}"},
            )

        async def make_user(label: str, org_id: str) -> int:
            email = f"design-{tag}-{label}@example.com"
            user_id = int(
                (
                    await session.execute(
                        text(
                            "INSERT INTO users (email, email_lower, role, auth_provider, current_org_id) "
                            "VALUES (:email, :email, 'analyst', 'password', :org) RETURNING id"
                        ),
                        {"email": email, "org": org_id},
                    )
                ).scalar_one()
            )
            await session.execute(
                text(
                    "INSERT INTO memberships (id, org_id, user_id, org_role) "
                    "VALUES (:id, :org, :user, 'admin')"
                ),
                {"id": str(ULID()), "org": org_id, "user": user_id},
            )
            return user_id

        user_a = await make_user("a", org_a)
        user_b = await make_user("b", org_b)
        await session.commit()

    app = _build_app()
    transport = ASGITransport(app=app)
    design_id = ""
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            _act_as(app, user_a)
            response = await client.post(
                "/api/v1/designs",
                json={
                    "name": "Tenant A plate",
                    "design_note": "integration evidence",
                    "plan": {
                        "kind": "plate",
                        "width_mm": 60.0,
                        "depth_mm": 40.0,
                        "thickness_mm": 5.0,
                        "holes": [
                            {"x_mm": -18.0, "y_mm": -10.0, "diameter_mm": 5.0},
                            {"x_mm": 18.0, "y_mm": 10.0, "diameter_mm": 5.0},
                        ],
                    },
                },
            )
            assert response.status_code == 202, response.text
            accepted = response.json()
            design_id = accepted["design"]["id"]
            job_id = accepted["job_id"]

            worker_result = await run_design_generation_job({}, job_id)
            assert worker_result["design_id"] == design_id
            assert len(worker_result["geometry_hash"]) == 64

            detail = await client.get(f"/api/v1/designs/{design_id}")
            assert detail.status_code == 200, detail.text
            ready = detail.json()["design"]
            assert ready["status"] == "ready"
            assert ready["revision"]["geometry"]["bbox_mm"] == [60.0, 40.0, 5.0]
            assert ready["revision"]["step_size_bytes"] > 128

            preview = await client.get(f"/api/v1/designs/{design_id}/preview.stl")
            assert preview.status_code == 200
            assert preview.content.startswith(b"solid")
            step = await client.get(f"/api/v1/designs/{design_id}/download.step")
            assert step.status_code == 200
            assert b"ISO-10303-21" in step.content[:256]
            assert step.headers["x-geometry-sha256"] == ready["revision"]["geometry_hash"]
            history = await client.get(f"/api/v1/designs/{design_id}/revisions")
            assert history.status_code == 200
            assert [item["number"] for item in history.json()["revisions"]] == [1]

            # Same public id is existence-obscured from another organization.
            _act_as(app, user_b)
            assert (await client.get(f"/api/v1/designs/{design_id}")).status_code == 404
            assert (await client.get(f"/api/v1/designs/{design_id}/preview.stl")).status_code == 404
            assert (await client.get(f"/api/v1/designs/{design_id}/revisions/1")).status_code == 404
            assert (await client.post(
                f"/api/v1/designs/{design_id}/revisions",
                json={"plan": ready["revision"]["plan"]},
            )).status_code == 404
            assert (await client.get("/api/v1/designs")).json()["designs"] == []

            _act_as(app, user_a)
            revision_response = await client.post(
                f"/api/v1/designs/{design_id}/revisions",
                json={
                    "design_note": "thicker revision",
                    "plan": {
                        **ready["revision"]["plan"],
                        "thickness_mm": 7.0,
                    },
                },
            )
            assert revision_response.status_code == 202, revision_response.text
            second = revision_response.json()
            assert second["design"]["current_revision"] == 2
            await run_design_generation_job({}, second["job_id"])
            revised = (await client.get(f"/api/v1/designs/{design_id}")).json()["design"]
            assert revised["status"] == "ready"
            assert revised["revision"]["number"] == 2
            assert revised["revision"]["geometry"]["bbox_mm"] == [60.0, 40.0, 7.0]
            history = (await client.get(f"/api/v1/designs/{design_id}/revisions")).json()
            assert [item["number"] for item in history["revisions"]] == [2, 1]
            assert history["revisions"][1]["geometry"]["bbox_mm"] == [60.0, 40.0, 5.0]
            old_step = await client.get(
                f"/api/v1/designs/{design_id}/revisions/1/download.step"
            )
            assert old_step.status_code == 200
            assert b"ISO-10303-21" in old_step.content[:256]
            assert old_step.headers["x-geometry-sha256"] == history["revisions"][1]["geometry_hash"]

            archived = await client.delete(f"/api/v1/designs/{design_id}")
            assert archived.status_code == 204
            assert (await client.get("/api/v1/designs")).json()["designs"] == []

        async with eng.get_session_factory()() as session:
            actions = (
                await session.execute(
                    text(
                        "SELECT action FROM audit_log WHERE resource_id IN "
                        "(SELECT ulid FROM design_revisions WHERE design_id = "
                        "(SELECT id FROM design_projects WHERE ulid = :design)) "
                        "OR resource_id = :design"
                    ),
                    {"design": design_id},
                )
            ).scalars().all()
            assert "design.created" in actions
            assert actions.count("design.generation_requested") == 2
            assert actions.count("design.generated") == 2
            assert "design.archived" in actions
    finally:
        async with eng.get_session_factory()() as session:
            if design_id:
                revision_ids = (
                    await session.execute(
                        text(
                            "SELECT ulid FROM design_revisions WHERE design_id = "
                            "(SELECT id FROM design_projects WHERE ulid = :design)"
                        ),
                        {"design": design_id},
                    )
                ).scalars().all()
                await session.execute(
                    text("DELETE FROM audit_log WHERE resource_id = :design OR resource_id = ANY(:revisions)"),
                    {"design": design_id, "revisions": list(revision_ids)},
                )
            await session.execute(
                text("DELETE FROM organizations WHERE id IN (:a, :b)"),
                {"a": org_a, "b": org_b},
            )
            await session.execute(
                text("DELETE FROM users WHERE id IN (:a, :b)"),
                {"a": user_a, "b": user_b},
            )
            await session.commit()
        await eng.dispose_engine()
