"""Security review R3, F3: a worker job prices and saves into the job's org, never the person's active one.

A big file's check (POST /api/v1/checks, POST /uploads/from-link) and a big kept
part's re-price ran on the worker with the job's org for the analysis, but the
pricing step (routes._run_cost_decision -> _cost_decision) resolved the user's
ACTIVE org and read the org's machines, rates and calibration there, then saved
the cost decision and the part's source bytes into it. A person who switched
org while the job waited moved org A's CAD into org B. The catalog worker
guarded this (batch_tasks.CatalogOrgChanged); the stored-check worker did not.

Now ``_cost_decision`` takes ``org_id`` and every worker path passes the job's.
"""
from __future__ import annotations

import ast
import asyncio
import io
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import trimesh

from src.jobs import stored_check_tasks as t

JOB_ORG, ACTIVE_ORG = "org-A", "org-B"


class _Result:
    def scalar_one_or_none(self):
        return "01ANALYSIS"


class _Session:
    async def execute(self, *_a, **_k):
        return _Result()

    async def commit(self):
        return None


def _factory():
    @asynccontextmanager
    async def _cm():
        yield _Session()
    return _cm


def test_stored_check_never_prices_into_a_different_org(monkeypatch):
    """The reviewer's proof: the stub prices into an explicit org_id when the worker passes one."""
    import src.api.routes as routes
    import src.auth.org_context as org_context
    from src.services import analysis_service
    from src.services import direct_upload_service as uploads
    from src.services import kept_part_jobs

    fd, stl = tempfile.mkstemp(suffix=".stl")
    os.close(fd)
    trimesh.creation.box(extents=(10, 10, 10)).export(stl)
    saved_into: list = []

    async def _false(*_a, **_k):
        return False

    async def _noop(*_a, **_k):
        return None

    async def _claim(_ulid):
        upload = SimpleNamespace(ulid="01UPLOAD", org_id=JOB_ORG, purpose="part", filename="part.stl",
                                 object_key="k", expected_size_bytes=os.path.getsize(stl),
                                 expected_checksum_sha256="0" * 64)
        return {"params": {"direct_upload_id": "01UPLOAD", "filename": "part.stl"}, "user_id": 7,
                "org_id": JOB_ORG}, upload

    async def _admit(_user, name, _data):
        return None, "identity"

    async def _run_analysis(**kwargs):
        assert kwargs["org_id"] == JOB_ORG
        return analysis_service.AnalysisRun(result={}, analysis_id=1)

    async def _active_org(_session, _user_id):
        return ACTIVE_ORG  # the user switched to org B while the job waited

    async def _run_cost_decision(**kwargs):
        org = kwargs.get("org_id") or await org_context.resolve_org(kwargs["session"], kwargs["user"].user_id)
        saved_into.append(org)
        return {"saved": {"id": "01COST"}}

    def _download(_upload, _progress=None):
        fd2, p = tempfile.mkstemp(suffix=".stl")
        os.close(fd2)
        with open(stl, "rb") as src, open(p, "wb") as out:
            out.write(src.read())
        return p

    monkeypatch.setattr(kept_part_jobs, "is_kept_job", _false)
    monkeypatch.setattr(t, "_claim", _claim)
    monkeypatch.setattr(t, "_patch", _noop)
    monkeypatch.setattr(t, "_finish", _noop)
    monkeypatch.setattr(t, "_admit", _admit)
    monkeypatch.setattr(t, "_keep_preview", _noop)
    monkeypatch.setattr(t, "_owned_processes", _noop)
    monkeypatch.setattr(t, "get_session_factory", _factory)
    monkeypatch.setattr(uploads, "download_to_bounded_tempfile", _download)
    monkeypatch.setattr(analysis_service, "run_analysis", _run_analysis)
    monkeypatch.setattr(org_context, "resolve_org", _active_org)
    monkeypatch.setattr(routes, "_run_cost_decision", _run_cost_decision)

    asyncio.run(t.run_stored_check({}, "01JOB"))
    os.unlink(stl)
    # Was ["org-B"]: org A's part priced and kept in org B.
    assert saved_into == [JOB_ORG], saved_into


def test_the_cost_decision_reads_and_saves_only_in_the_org_it_is_given(monkeypatch):
    """The real ``_run_cost_decision`` with ``org_id``: every org read and save uses it; the active org is never read."""
    import src.api.routes as routes
    import src.auth.org_context as org_context
    from fastapi import UploadFile
    from starlette.datastructures import Headers

    from src.auth.require_api_key import AuthedUser
    from src.services import (
        calibration_service,
        cost_decision_service,
        identity_retrieval_service,
        machine_inventory_service,
        source_artifact_service,
    )

    seen: dict[str, list] = {}

    def note(what: str, org) -> None:
        seen.setdefault(what, []).append(org)

    async def _active_org(_session, _user_id):
        note("resolve_org (the active org)", ACTIVE_ORG)
        return ACTIVE_ORG

    async def _inventory(_session, org_id):
        note("machines", org_id)
        return []

    async def _save_source(org_id, *_a, **_k):
        note("kept source", org_id)

    async def _save_costable(org_id, *_a, **_k):
        note("costable mesh", org_id)

    async def _costable_exists(org_id, *_a, **_k):
        note("costable mesh", org_id)
        return True

    async def _calibrate(_session, org_id, result):
        note("calibration", org_id)
        return result

    async def _persist(_session, user, *, org_id=None, **_k):
        note("cost decision", org_id if org_id is not None else await org_context.resolve_org(_session, user.user_id))
        return SimpleNamespace(ulid="01COST")

    async def _identity(_session, org_id, *_a, **_k):
        note("identity", org_id)
        return SimpleNamespace(to_dict=lambda: None)

    monkeypatch.setattr(org_context, "resolve_org", _active_org)
    monkeypatch.setattr(machine_inventory_service, "load_org_inventory", _inventory)
    monkeypatch.setattr(source_artifact_service, "save_source_artifact", _save_source)
    monkeypatch.setattr(source_artifact_service, "save_costable_mesh_artifact", _save_costable)
    monkeypatch.setattr(source_artifact_service, "costable_mesh_exists", _costable_exists)
    monkeypatch.setattr(calibration_service, "apply_org_calibration", _calibrate)
    monkeypatch.setattr(cost_decision_service, "cost_persist_enabled", lambda: True)
    monkeypatch.setattr(cost_decision_service, "persist_cost_decision", _persist)
    monkeypatch.setattr(identity_retrieval_service, "retrieve_identity", _identity)

    stl = trimesh.creation.box(extents=(20, 20, 20)).export(file_type="stl")
    upload = UploadFile(file=io.BytesIO(stl), filename="block.stl",
                        headers=Headers({"content-type": "application/octet-stream"}))
    user = AuthedUser(user_id=7, api_key_id=0, key_prefix="worker", role="analyst", org_id=JOB_ORG)
    session = AsyncMock()
    session.execute.return_value = MagicMock()

    report = asyncio.run(routes._run_cost_decision(
        file=upload, qty="1,100", region=None, cavities=1, complexity="moderate", material_class="polymer",
        user=user, session=session, org_id=JOB_ORG))

    assert report["saved"]["id"] == "01COST"
    assert "resolve_org (the active org)" not in seen, seen
    for what in ("machines", "kept source", "calibration", "cost decision", "identity"):
        assert seen.get(what) and set(seen[what]) == {JOB_ORG}, (what, seen)


def test_a_kept_parts_reprice_prices_in_the_kept_parts_org(monkeypatch):
    import src.api.routes as routes
    from src.api import part_recheck
    from src.auth.require_api_key import AuthedUser
    from src.services import cad_fix_service, source_artifact_service

    got: dict = {}

    async def _read(org_id, digest):
        got["read"] = org_id
        return b"solid x\nendsolid x\n", ".stl"

    async def _saved(_session, org_id, _digest):
        return [1, 100], "polymer", "saved_cost_check"

    async def _name(_session, org_id, _digest, suffix):
        return "part" + suffix

    async def _cost(**kwargs):
        got["priced"] = kwargs.get("org_id")
        return {}

    monkeypatch.setattr(source_artifact_service, "read_source_artifact", _read)
    monkeypatch.setattr(cad_fix_service, "_saved_cost_inputs", _saved)
    monkeypatch.setattr(part_recheck, "_kept_name", _name)
    monkeypatch.setattr(routes, "_run_cost_decision", _cost)

    user = AuthedUser(user_id=7, api_key_id=0, key_prefix="worker", role="analyst", org_id=JOB_ORG)
    asyncio.run(part_recheck.recheck_kept(AsyncMock(), org_id=JOB_ORG, digest="a" * 64, user=user,
                                          response=MagicMock()))
    assert got == {"read": JOB_ORG, "priced": JOB_ORG}


_SRC = Path(__file__).resolve().parents[1] / "src"
# Every caller that runs on the worker, or whose body the worker runs.
_WORKER_PRICING_CALLERS = [
    "jobs/stored_check_tasks.py",   # a big file's check, a link import
    "jobs/batch_tasks.py",          # a catalog part
    "services/catalog_bodies.py",   # a catalog part's bodies
    "api/part_recheck.py",          # recheck_kept: a big kept part's re-price on the worker
]


@pytest.mark.parametrize("path", _WORKER_PRICING_CALLERS)
def test_every_worker_pricing_call_names_its_org(path):
    tree = ast.parse((_SRC / path).read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", getattr(n.func, "attr", None)) == "_run_cost_decision"]
    assert calls, f"{path} no longer prices through _run_cost_decision; update this list"
    for call in calls:
        assert any(k.arg == "org_id" for k in call.keywords), f"{path}:{call.lineno} prices without org_id"
