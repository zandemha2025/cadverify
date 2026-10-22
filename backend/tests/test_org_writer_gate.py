"""Org viewers are read-only: every route that changes or publishes org data
requires org role member or above through the shared gate (``require_org_writer``,
or its twin ``require_org_checker`` on routes that check a new part), and every
read stays open to viewers.
"""
from __future__ import annotations

import importlib
import os
import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from ulid import ULID

from src.auth import rbac
from src.auth.rbac import require_org_checker, require_org_writer
from src.auth.require_api_key import AuthedUser, require_api_key

# Routes that check a new part answer a viewer with the "check new parts" line.
CHECKS = {"routes", "uploads", "reconstruct_router", "checks", "part_fixes", "part_recheck"}

# (module, endpoint function) for every write that changes or publishes org data.
GATED = {
    "actuals": ["import_actuals", "apply_calibration", "undo_calibration"],
    "batch_router": ["create_batch", "create_catalog_run", "cancel_batch"],
    "bom": ["ingest_assembly", "onboard_bom"],
    "cost_decisions": [
        "set_cost_decision_disposition",
        "create_cost_share",
        "revoke_cost_share",
    ],
    "groundtruth": [
        "create_ground_truth",
        "recalibrate_ground_truth",
        "import_ground_truth",
    ],
    "identity": ["confirm_identity", "onboard_library"],
    "integrations": ["create_run"],
    "machine_inventory": [
        "put_shop_capabilities",
        "import_machines",
        "create_machine",
        "patch_machine",
        "delete_machine",
    ],
    "manifest": ["import_manifest"],
    "part_context": ["declare_part_context"],
    "part_revisions": ["set_revision_of"],
    "reconstruct_router": ["reconstruct"],
    "rfq_packages": ["create_rfq_package"],
    "routes": [
        "validate_file",
        "validate_fit",
        "validate_preview_mesh",
        "validate_assembly",
        "validate_quick",
        "validate_demo",
        "validate_cost",
        "validate_cost_demo",
        "validate_repair",
    ],
    "share": ["create_share", "revoke_share"],
    "checks": ["start_stored_check"],
    "part_fixes": ["apply_part_fix", "repair_stored_part"],
    "part_recheck": ["recheck_stored_part", "check_stored_bodies", "body_as_own_part"],
    "data_control": ["delete_part"],
    "uploads": [
        "initiate_multipart_upload",
        "put_relayed_part",
        "refresh_multipart_part_urls",
        "complete_multipart_upload",
        "abort_multipart_upload",
    ],
}

# Reads (and the read-only actuals preview) that viewers keep.
OPEN_TO_VIEWERS = {"actuals": ["preview_actuals"]}


def _calls(dependant):
    yield dependant.call
    for sub in dependant.dependencies:
        yield from _calls(sub)


def _routes(module_name: str):
    from fastapi import APIRouter

    module = importlib.import_module(f"src.api.{module_name}")
    routers = [v for v in vars(module).values() if isinstance(v, APIRouter)]
    return [r for router in routers for r in router.routes if isinstance(r, APIRoute)]


def _gate_of(route: APIRoute):
    for call in _calls(route.dependant):
        if call is require_org_writer or call is require_org_checker:
            return call
    return None


def _gated(route: APIRoute) -> bool:
    return _gate_of(route) is not None


@pytest.mark.parametrize("module_name", sorted(GATED))
def test_every_org_data_write_requires_an_org_member(module_name):
    routes = _routes(module_name)
    by_name: dict[str, list[APIRoute]] = {}
    for route in routes:
        by_name.setdefault(route.endpoint.__name__, []).append(route)
    expected = require_org_checker if module_name in CHECKS else require_org_writer
    for fn in GATED[module_name]:
        assert fn in by_name, f"{module_name}.{fn} not found"
        for route in by_name[fn]:
            assert _gate_of(route) is expected, f"{module_name}.{fn} {route.path} lacks {expected.__name__}"


@pytest.mark.parametrize("module_name", sorted(GATED))
def test_reads_stay_open_to_viewers(module_name):
    open_fns = set(OPEN_TO_VIEWERS.get(module_name, []))
    for route in _routes(module_name):
        is_read = route.methods <= {"GET", "HEAD"}
        if is_read or route.endpoint.__name__ in open_fns:
            assert not _gated(route), f"{module_name}.{route.endpoint.__name__} {route.path} is a read"


# ── the gate itself ──────────────────────────────────────────────────────────


def _gate_app(user: AuthedUser, gate=require_org_writer) -> FastAPI:
    app = FastAPI()

    @app.post("/write")
    async def _write(_user: AuthedUser = Depends(gate)):
        return {"ok": True}

    app.dependency_overrides[require_api_key] = lambda: user
    return app


async def _post(app: FastAPI):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        return await client.post("/write")


def _user(role: str = "analyst", org_id: str | None = None) -> AuthedUser:
    return AuthedUser(user_id=7, api_key_id=0, key_prefix="session", role=role, org_id=org_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("org_role", ["member", "admin"])
async def test_members_and_admins_may_write(monkeypatch, org_role):
    monkeypatch.setattr(rbac, "lookup_org_membership", AsyncMock(return_value=("org-a", org_role)))
    resp = await _post(_gate_app(_user()))
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_an_org_viewer_gets_a_plain_refusal_naming_the_org(monkeypatch):
    monkeypatch.setattr(rbac, "lookup_org_membership", AsyncMock(return_value=("org-a", "viewer")))
    monkeypatch.setattr(rbac, "_org_name", AsyncMock(return_value="Acme Tooling"))
    resp = await _post(_gate_app(_user()))
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert detail["code"] == "org_member_required"
    assert detail["org_name"] == "Acme Tooling" and detail["org_role"] == "viewer"
    assert detail["message"] == (
        "You're a viewer in Acme Tooling: you can open its parts and records. "
        "Ask an admin for member access to change them."
    )

    check = await _post(_gate_app(_user(), gate=require_org_checker))
    assert check.status_code == 403
    assert check.json()["detail"]["message"] == (
        "You're a viewer in Acme Tooling: you can open its parts and records. "
        "Ask an admin for member access to check new parts."
    )


@pytest.mark.asyncio
async def test_capability_probes_answer_with_the_same_rule(monkeypatch):
    lookup = AsyncMock(return_value=("org-a", "viewer"))
    monkeypatch.setattr(rbac, "lookup_org_membership", lookup)
    assert await rbac.org_role_allows_writes(_user()) is False
    lookup.return_value = ("org-a", "member")
    assert await rbac.org_role_allows_writes(_user()) is True
    assert await rbac.org_role_allows_writes(_user(role="viewer")) is False


@pytest.mark.asyncio
async def test_a_platform_viewer_is_still_refused_by_the_platform_role(monkeypatch):
    monkeypatch.setattr(rbac, "lookup_org_membership", AsyncMock(return_value=("org-a", "admin")))
    resp = await _post(_gate_app(_user(role="viewer")))
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "insufficient_role"


@pytest.mark.asyncio
async def test_a_key_from_another_org_is_refused(monkeypatch):
    monkeypatch.setattr(rbac, "lookup_org_membership", AsyncMock(return_value=("org-b", "admin")))
    monkeypatch.setattr(rbac, "_org_name", AsyncMock(return_value="Org B"))
    resp = await _post(_gate_app(_user(org_id="org-a")))
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "api_key_org_mismatch"


@pytest.mark.asyncio
async def test_platform_superadmin_keeps_the_bypass(monkeypatch):
    monkeypatch.setattr(rbac, "lookup_org_membership", AsyncMock(return_value=None))
    resp = await _post(_gate_app(_user(role="superadmin")))
    assert resp.status_code == 200


# ── live: a viewer reads machines but cannot add one or start a check ───────

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)


@pytest.fixture
def _engine():
    import src.db.engine as eng

    eng._ENGINE = None
    eng._SESSION_FACTORY = None
    yield eng
    eng._ENGINE = None
    eng._SESSION_FACTORY = None


async def _pg(sql: str, *args):
    import asyncpg

    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


@_requires_pg
@pytest.mark.asyncio
async def test_viewer_reads_but_cannot_write_machines_or_start_checks(_engine):
    from src.api import machine_inventory, routes
    from src.db.engine import get_db_session

    tag = uuid.uuid4().hex[:10]
    org = str(ULID())
    await _pg(
        "INSERT INTO organizations (id, name, slug, created_at) VALUES ($1, $2, $3, now())",
        org,
        f"Shop {tag}",
        f"shop-{tag}",
    )
    ids = {}
    for who, role in (("viewer", "viewer"), ("member", "member")):
        rows = await _pg(
            "INSERT INTO users (email, email_lower, auth_provider, current_org_id) "
            "VALUES ($1, $1, 'password', $2) RETURNING id",
            f"{who}-{tag}@corp.example",
            org,
        )
        ids[who] = int(rows[0]["id"])
        await _pg(
            "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
            "VALUES ($1, $2, $3, $4, now())",
            str(ULID()),
            org,
            ids[who],
            role,
        )

    def _app(user_id: int) -> FastAPI:
        app = FastAPI()
        app.include_router(machine_inventory.router, prefix="/api/v1/machine-inventory")
        app.include_router(routes.router, prefix="/api/v1")

        async def _session():
            async with _engine.get_session_factory()() as s:
                try:
                    yield s
                    await s.commit()
                except Exception:
                    await s.rollback()
                    raise

        app.dependency_overrides[require_api_key] = lambda: AuthedUser(
            user_id=user_id, api_key_id=0, key_prefix="session", role="analyst"
        )
        app.dependency_overrides[get_db_session] = _session
        return app

    machine = {"name": f"Mill {tag}", "process": "cnc_3axis"}
    try:
        async with AsyncClient(
            transport=ASGITransport(app=_app(ids["viewer"])), base_url="http://t"
        ) as viewer:
            listed = await viewer.get("/api/v1/machine-inventory")
            assert listed.status_code == 200, listed.text
            refused = await viewer.post("/api/v1/machine-inventory", json=machine)
            assert refused.status_code == 403
            assert refused.json()["detail"]["code"] == "org_member_required"
            check = await viewer.post(
                "/api/v1/validate", files={"file": ("cube.stl", b"solid x\nendsolid x\n")}
            )
            assert check.status_code == 403
            assert check.json()["detail"]["message"] == (
                f"You're a viewer in Shop {tag}: you can open its parts and records. "
                "Ask an admin for member access to check new parts."
            )
        reserved = await _pg(
            "SELECT count(*) AS n FROM trial_checks WHERE user_id=$1", ids["viewer"]
        )
        assert int(reserved[0]["n"]) == 0

        async with AsyncClient(
            transport=ASGITransport(app=_app(ids["member"])), base_url="http://t"
        ) as member:
            created = await member.post("/api/v1/machine-inventory", json=machine)
            assert created.status_code in (200, 201), created.text
        rows = await _pg("SELECT count(*) AS n FROM machine_instances WHERE org_id=$1", org)
        assert int(rows[0]["n"]) == 1
    finally:
        await _pg("DELETE FROM machine_instances WHERE org_id=$1", org)
        await _pg("DELETE FROM audit_log WHERE org_id=$1", org)
        await _pg("DELETE FROM trial_checks WHERE user_id = ANY($1::bigint[])", list(ids.values()))
        await _pg("DELETE FROM memberships WHERE org_id=$1", org)
        await _pg("DELETE FROM users WHERE id = ANY($1::bigint[])", list(ids.values()))
        await _pg("DELETE FROM organizations WHERE id=$1", org)
        await _engine.dispose_engine()
