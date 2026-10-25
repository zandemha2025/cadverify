"""Deleting a part or an organization, against real Postgres and a real object store.

Skipped unless DATABASE_URL points at Postgres migrated to head. Each test
seeds two organizations with every kind of row and stored file a part owns,
deletes through the HTTP routes, and then proves: everything the part (or the
org) owned is gone, nothing of another part or another org was touched, the
audit trail keeps the fact (who, when, which SHA-256) without the content,
deletes are idempotent, and the roles hold.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not _PG, reason="requires live Postgres")]


def _app():
    from fastapi import FastAPI

    from src.api.cost_decisions import public_cost_share_router, router as cost_router
    from src.api.data_control import parts_router, router
    from src.api.part_preview import router as preview_router
    from src.api.share import public_share_router, share_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(preview_router, prefix="/api/v1/parts")
    app.include_router(parts_router, prefix="/api/v1/parts")
    app.include_router(router, prefix="/api/v1")
    app.include_router(share_router, prefix="/api/v1/analyses")
    app.include_router(public_share_router, prefix="/s")
    app.include_router(cost_router, prefix="/api/v1/cost-decisions")
    app.include_router(public_cost_share_router, prefix="/s")
    return app


def _act(app, user_id: int, role: str = "analyst") -> None:
    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id, api_key_id=0, key_prefix="session", role=role
    )


@pytest.fixture
def stores(tmp_path, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_DISABLED", "1")
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "local")
    monkeypatch.setenv("OBJECT_STORE_LOCAL_ROOT", str(tmp_path / "objects"))
    monkeypatch.setenv("PDF_CACHE_DIR", str(tmp_path / "pdf"))
    from src.api import part_preview

    part_preview._cache.clear()
    return tmp_path


def _obj(root: Path, purpose: str, key: str) -> Path:
    return root / "objects" / purpose / key


class World:
    """Two orgs, their users and seeded parts (ids by label)."""

    def __init__(self, tag: str):
        self.tag = tag
        self.orgs: dict[str, str] = {}
        self.users: dict[str, int] = {}
        self.parts: dict[str, dict] = {}


async def _org(session, w: World, label: str) -> str:
    from sqlalchemy import text
    from ulid import ULID

    oid = str(ULID())
    await session.execute(
        text("INSERT INTO organizations (id, name, slug) VALUES (:id, :n, :s)"),
        {"id": oid, "n": f"Acme {label} {w.tag}", "s": f"dd-{w.tag}-{label.lower()}"},
    )
    w.orgs[label] = oid
    return oid


async def _user(session, w: World, label: str, org_label: str, org_role: str, role: str = "analyst") -> int:
    from sqlalchemy import text
    from ulid import ULID

    email = f"dd-{w.tag}-{label}@example.com"
    uid = int(
        (
            await session.execute(
                text(
                    "INSERT INTO users (email, email_lower, role, auth_provider, current_org_id, plan) "
                    "VALUES (:e, :e, :r, 'password', :o, 'pilot') RETURNING id"
                ),
                {"e": email, "r": role, "o": w.orgs[org_label]},
            )
        ).scalar_one()
    )
    await session.execute(
        text("INSERT INTO memberships (id, org_id, user_id, org_role) VALUES (:id, :o, :u, :r)"),
        {"id": str(ULID()), "o": w.orgs[org_label], "u": uid, "r": org_role},
    )
    w.users[label] = uid
    return uid


async def _seed_part(session, root: Path, w: World, label: str, org_label: str, user_label: str,
                     *, data: bytes | None = None, parent: str | None = None) -> dict:
    """One part with a row in every table a part owns, and its stored files."""
    from src.db.models import (
        Analysis, AuditLog, Batch, BatchItem, CostDecision, GroundTruthRecordRow, Job,
        Notification, PartContext, PartSignature, PartSummary, RfqPackage, UsageEvent, WebhookDelivery,
    )
    from src.services import share_links
    from src.services.source_artifact_service import save_source_artifact

    org, uid = w.orgs[org_label], w.users[user_label]
    data = data or f"solid {label} {w.tag} {uuid.uuid4().hex}\nendsolid\n".encode()
    h = hashlib.sha256(data).hexdigest()
    name = f"{label}-secret-bracket.stl"
    a = Analysis(user_id=uid, org_id=org, mesh_hash=h, process_set_hash="p", analysis_version="v",
                 filename=name, file_type="stl", file_size_bytes=len(data), result_json={"verdict": "pass"},
                 verdict="pass", face_count=12, duration_ms=1.0)
    d = CostDecision(user_id=uid, org_id=org, mesh_hash=h, params_hash=f"pp-{label}", engine_version="t",
                     filename=name, file_type="stl", result_json={"decision": {}})
    session.add_all([a, d])
    await session.flush()
    share_links.open_link(a, uid, 30, f"a{uuid.uuid4().hex[:11]}")
    share_links.open_link(d, uid, None, f"d{uuid.uuid4().hex[:11]}")
    batch = Batch(user_id=uid, org_id=org, input_mode="zip", total_items=2, completed_items=2)
    session.add(batch)
    await session.flush()
    item = BatchItem(batch_id=batch.id, org_id=org, filename=name, status="completed", analysis_id=a.id)
    other_item = BatchItem(batch_id=batch.id, org_id=org, filename="unrelated.stl", status="completed")
    session.add_all([item, other_item])
    await session.flush()
    session.add_all([
        PartContext(org_id=org, mesh_hash=h, program=f"Program {label}", annual_volume=500),
        PartSummary(org_id=org, mesh_hash=h, triage_bucket="makeable", updated_at=datetime.now(timezone.utc),
                    row_json={"filename": name}),
        PartSignature(org_id=org, mesh_hash=h, signature=[0.0] * 18, declared_name=name),
        GroundTruthRecordRow(org_id=org, user_id=uid, part_id=name, process="cnc_3axis", quantity=10,
                             actual_unit_cost_usd=12.5, evidence_sha256=h),
        GroundTruthRecordRow(org_id=org, user_id=uid, part_id=f"PN-{label}", process="cnc_3axis",
                             quantity=10, actual_unit_cost_usd=9.0),
        Notification(org_id=org, kind="decision.created", title=f"Verification recorded - {name}",
                     source_type="cost_decision", source_id=d.ulid),
        Job(user_id=uid, org_id=org, job_type="sam3d", analysis_id=a.id, params_json={"mesh_hash": h}),
        AuditLog(user_id=uid, org_id=org, user_email="x", action="analysis.created", resource_type="analysis",
                 resource_id=a.ulid, file_hash=h, result_summary="pass", detail_json={"file_name": name}),
        AuditLog(user_id=uid, org_id=org, user_email="x", action="decision.created", resource_type="cost_decision",
                 resource_id=d.ulid, detail_json={"filename": name}),
        # Who did it, from where: the actor's email, network address and browser.
        AuditLog(user_id=uid, org_id=org, user_email=f"actor-{label}-{w.tag}@example.com", action="share.created",
                 resource_type="analysis", resource_id=a.share_short_id, ip_address="203.0.113.7",
                 user_agent=f"Mozilla/5.0 actor-{label}"),
        UsageEvent(user_id=uid, org_id=org, event_type="analysis", analysis_id=a.id, mesh_hash=h,
                   face_count=12, duration_ms=1.0),
        WebhookDelivery(batch_id=batch.id, org_id=org, event_type="batch_item.completed",
                        payload_json={"item_ulid": item.ulid, "filename": name}),
        RfqPackage(org_id=org, user_id=uid, title=f"RFQ package - {name}", item_count=1,
                   items_json=[{"decision": {"id": d.ulid, "mesh_hash": h, "filename": name,
                                             "approval_status": "unreviewed", "is_stale": False}}],
                   warnings_json=[{"decision_id": d.ulid, "message": f"{name} is not approved."}]),
    ])
    if parent:
        session.add(AuditLog(user_id=uid, org_id=org, user_email="x", action="part.fix_applied",
                             resource_type="part", resource_id=h, file_hash=h,
                             detail_json={"parent_mesh_hash": parent, "fix": "fillet"}))
    await session.flush()
    await save_source_artifact(org, h, name, data)
    from src.services import cad_fix_service as fx

    costable = _obj(root, "source-artifacts", f"{org}/{h}/costable-v2-mm.stl")
    costable.write_bytes(data)
    if parent:
        await fx._put_json(fx._record_key(org, h, "derived-from.json"),
                           {"parent_mesh_hash": parent, "parent_filename": w.parts_by_hash[parent]["name"]})
        await fx._put_json(fx._record_key(org, parent, "fixes/fillet.json"),
                           {"fix": "fillet", "outcome": "cleared", "fixed_mesh_hash": h})
    pdf_dir = root / "pdf"
    pdf_dir.mkdir(exist_ok=True)
    (pdf_dir / f"{a.ulid}.v3.pdf").write_bytes(b"%PDF dfm")
    for purpose, key, body in (
        ("cost-pdf", f"cost-{d.ulid}-abcdef12.pdf", b"%PDF cost"),
        ("meshes", f"{h}.bin", data),
        ("batch", f"{batch.ulid}/{name}", data),
        ("batch", f"{batch.ulid}/unrelated.stl", b"other"),
    ):
        path = _obj(root, purpose, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    part = {"hash": h, "name": name, "data": data, "analysis": a.ulid, "decision": d.ulid,
            "a_share": a.share_short_id, "d_share": d.share_short_id, "batch": batch.id,
            "batch_ulid": batch.ulid, "org": org}
    w.parts[label] = part
    w.parts_by_hash[h] = part
    return part


async def _world(root: Path) -> World:
    import src.db.engine as eng

    w = World(uuid.uuid4().hex[:10])
    w.parts_by_hash = {}
    async with eng.get_session_factory()() as s:
        await _org(s, w, "A")
        await _org(s, w, "B")
        await _user(s, w, "owner", "A", "member")
        await _user(s, w, "colleague", "A", "member")
        await _user(s, w, "admin", "A", "admin")
        await _user(s, w, "viewer", "A", "viewer", role="viewer")
        await _user(s, w, "outsider", "B", "admin")
        p = await _seed_part(s, root, w, "P", "A", "owner")
        await _seed_part(s, root, w, "C", "A", "owner", parent=p["hash"])
        await _seed_part(s, root, w, "Q", "A", "owner")
        # Org B uploaded the very same bytes as P: its copy is its own.
        await _seed_part(s, root, w, "BP", "B", "outsider", data=p["data"])
        await s.commit()
    return w


async def _count(sql: str, **params) -> int:
    import src.db.engine as eng
    from sqlalchemy import text

    async with eng.get_session_factory()() as s:
        return int((await s.execute(text(sql), params)).scalar_one())


_PART_TABLES = {
    "analyses": "mesh_hash", "cost_decisions": "mesh_hash", "part_contexts": "mesh_hash",
    "part_summaries": "mesh_hash", "part_signatures": "mesh_hash", "ground_truth_records": "evidence_sha256",
}


async def _rows_for(org: str, h: str) -> dict[str, int]:
    out = {t: await _count(f"SELECT count(*) FROM {t} WHERE org_id = :o AND {c} = :h", o=org, h=h)
           for t, c in _PART_TABLES.items()}
    out["jobs"] = await _count("SELECT count(*) FROM jobs WHERE org_id = :o AND params_json->>'mesh_hash' = :h", o=org, h=h)
    return out


async def _cleanup(w: World) -> None:
    import src.db.engine as eng
    from sqlalchemy import text

    async with eng.get_session_factory()() as s:
        ids = list(w.users.values())
        await s.execute(text("DELETE FROM data_deletions WHERE org_id = ANY(:o) OR requested_by = ANY(:u)"),
                        {"o": list(w.orgs.values()), "u": ids})
        await s.execute(text("DELETE FROM audit_log WHERE user_id = ANY(:u) OR org_id = ANY(:o)"),
                        {"u": ids, "o": list(w.orgs.values())})
        orgs = (await s.execute(text("SELECT org_id FROM memberships WHERE user_id = ANY(:u)"), {"u": ids})).scalars().all()
        await s.execute(text("DELETE FROM organizations WHERE id = ANY(:o)"), {"o": list({*w.orgs.values(), *orgs})})
        await s.execute(text("DELETE FROM users WHERE id = ANY(:u)"), {"u": ids})
        await s.commit()
    await eng.dispose_engine()


async def test_deleting_a_part_removes_everything_it_owns_and_nothing_else(stores):
    from httpx import ASGITransport, AsyncClient

    w = await _world(stores)
    A, B = w.orgs["A"], w.orgs["B"]
    P, C, Q, BP = (w.parts[k] for k in ("P", "C", "Q", "BP"))
    app = _app()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            # The 3D view is cached in this process before the delete.
            _act(app, w.users["owner"])
            assert (await client.get(f"/api/v1/parts/{P['hash']}/source-status")).status_code == 200

            preview = await client.get(f"/api/v1/parts/{P['hash']}/deletion-preview")
            assert preview.status_code == 200, preview.text
            pv = preview.json()
            assert pv["can_delete"] is True and pv["file_name"] == P["name"]
            assert pv["fixed_copies"] == [C["hash"]]
            assert pv["will_remove"]["checks"] == 2 and pv["will_remove"]["cost_records"] == 2
            assert pv["will_remove"]["active_share_links"] == 4
            assert pv["will_remove"]["actual_costs"] == 2

            # Another org never sees it: same 404 as a hash nobody has.
            _act(app, w.users["outsider"])
            assert (await client.get(f"/api/v1/parts/{Q['hash']}/deletion-preview")).status_code == 404
            assert (await client.delete(f"/api/v1/parts/{Q['hash']}")).status_code == 404
            assert (await client.delete(f"/api/v1/parts/{'0' * 64}")).status_code == 404

            _act(app, w.users["owner"])
            r = await client.delete(f"/api/v1/parts/{P['hash']}")
            assert r.status_code == 200, r.text
            receipt = r.json()
            assert receipt["status"] == "done", receipt
            assert receipt["scope"] == "part" and receipt["target"] == P["hash"]
            assert receipt["removed"]["analyses"] == 2 and receipt["removed"]["cost_decisions"] == 2
            assert receipt["files"]["steps_done"] == receipt["files"]["steps_total"]
            assert P["name"] not in str(receipt) and C["name"] not in str(receipt)

            # Idempotent: the same receipt, nothing else changes.
            again = await client.delete(f"/api/v1/parts/{P['hash']}")
            assert again.status_code == 200 and again.json()["id"] == receipt["id"]
            status = await client.get(f"/api/v1/data-deletions/{receipt['id']}")
            assert status.status_code == 200 and status.json()["status"] == "done"
            _act(app, w.users["outsider"])
            assert (await client.get(f"/api/v1/data-deletions/{receipt['id']}")).status_code == 404

            # Its links stop working; another org's link to the same bytes still works.
            for path in (f"/s/{P['a_share']}", f"/s/cost/{P['d_share']}", f"/s/{C['a_share']}"):
                assert (await client.get(path)).status_code == 404, path
            assert (await client.get(f"/s/{BP['a_share']}")).status_code == 200
            assert (await client.get(f"/s/{Q['a_share']}")).status_code == 200

            # The 3D view is the plain 404 now, even from this process's cache path.
            _act(app, w.users["owner"])
            assert (await client.get(f"/api/v1/parts/{P['hash']}/source-status")).status_code == 404
            assert (await client.get(f"/api/v1/parts/{P['hash']}/preview.glb")).status_code == 404

        for part in (P, C):
            assert set((await _rows_for(A, part["hash"])).values()) == {0}, part["name"]
        for org, part in ((A, Q), (B, BP)):
            assert set((await _rows_for(org, part["hash"])).values()) == {1}, part["name"]
        # Actual costs logged by part number only stay.
        assert await _count("SELECT count(*) FROM ground_truth_records WHERE org_id=:o AND part_id='PN-P'", o=A) == 1
        # Usage counts stay, without the deleted file's fingerprint; other parts and orgs keep theirs.
        assert await _count("SELECT count(*) FROM usage_events WHERE org_id=:o AND user_id=:u", o=A,
                            u=w.users["owner"]) == 3
        for part in (P, C):
            assert await _count("SELECT count(*) FROM usage_events WHERE mesh_hash=:h AND org_id=:o",
                                h=part["hash"], o=A) == 0
        assert await _count("SELECT count(*) FROM usage_events WHERE mesh_hash=:h AND org_id=:o", h=Q["hash"], o=A) == 1
        assert await _count("SELECT count(*) FROM usage_events WHERE mesh_hash=:h AND org_id=:o", h=P["hash"], o=B) == 1
        # Batch items that produced it go (with their delivery logs); the batch's counters follow.
        assert await _count("SELECT count(*) FROM batch_items WHERE batch_id=:b", b=P["batch"]) == 1
        assert await _count("SELECT total_items FROM batches WHERE id=:b", b=P["batch"]) == 1
        assert await _count("SELECT count(*) FROM webhook_deliveries WHERE batch_id=:b", b=P["batch"]) == 0
        assert await _count("SELECT count(*) FROM webhook_deliveries WHERE batch_id=:b", b=Q["batch"]) == 1
        assert await _count("SELECT count(*) FROM notifications WHERE source_id=:d", d=P["decision"]) == 0
        assert await _count("SELECT count(*) FROM notifications WHERE source_id=:d", d=Q["decision"]) == 1
        # An RFQ package left empty is deleted; another part's package is untouched.
        assert await _count("SELECT count(*) FROM rfq_packages WHERE org_id=:o AND title LIKE :t", o=A, t="%P-secret%") == 0
        assert await _count("SELECT count(*) FROM rfq_packages WHERE org_id=:o", o=A) == 1

        # The audit trail keeps the events, without their content, plus who deleted which hash.
        assert await _count("SELECT count(*) FROM audit_log WHERE resource_id=:a", a=P["analysis"]) == 1
        assert await _count(
            "SELECT count(*) FROM audit_log WHERE org_id=:o AND detail_json::text LIKE :n", o=A, n="%P-secret%") == 0
        assert await _count(
            "SELECT count(*) FROM audit_log WHERE org_id=:o AND detail_json::text LIKE :n", o=A, n="%C-secret%") == 0
        assert await _count(
            "SELECT count(*) FROM audit_log WHERE resource_id=:a AND result_summary IS NULL "
            "AND detail_json->>'redacted' = 'part_deleted'", a=P["analysis"]) == 1
        assert await _count("SELECT count(*) FROM audit_log WHERE detail_json::text LIKE :n", n="%Q-secret%") == 2
        assert await _count(
            "SELECT count(*) FROM audit_log WHERE action='part.deleted' AND org_id=:o AND file_hash=:h AND user_id=:u",
            o=A, h=P["hash"], u=w.users["owner"]) == 1

        root = stores
        for part in (P, C):
            assert not (root / "objects" / "source-artifacts" / A / part["hash"]).exists()
            assert not _obj(root, "cost-pdf", f"cost-{part['decision']}-abcdef12.pdf").exists()
            assert not (root / "pdf" / f"{part['analysis']}.v3.pdf").exists()
            assert not _obj(root, "batch", f"{part['batch_ulid']}/{part['name']}").exists()
            assert _obj(root, "batch", f"{part['batch_ulid']}/unrelated.stl").exists()
        # Org B uploaded P's bytes too: its stored file and the shared SAM-3D blob stay.
        assert (root / "objects" / "source-artifacts" / B / P["hash"]).exists()
        assert _obj(root, "meshes", f"{P['hash']}.bin").exists()
        assert not _obj(root, "meshes", f"{C['hash']}.bin").exists()
        assert (root / "objects" / "source-artifacts" / A / Q["hash"]).exists()
        assert _obj(root, "cost-pdf", f"cost-{Q['decision']}-abcdef12.pdf").exists()
    finally:
        await _cleanup(w)


async def test_roles_who_may_delete_a_part(stores):
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text

    import src.db.engine as eng

    w = await _world(stores)
    Q = w.parts["Q"]
    app = _app()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            _act(app, w.users["viewer"], role="viewer")
            assert (await client.delete(f"/api/v1/parts/{Q['hash']}")).status_code == 403
            # A member deletes only what only they checked; Q is the owner's.
            _act(app, w.users["colleague"])
            pv = (await client.get(f"/api/v1/parts/{Q['hash']}/deletion-preview")).json()
            assert pv["can_delete"] is False and "admin" in pv["reason"]
            r = await client.delete(f"/api/v1/parts/{Q['hash']}")
            assert r.status_code == 403 and r.json()["detail"]["code"] == "part_delete_not_allowed"
            # The owner can't once a colleague also checked it; an admin can.
            async with eng.get_session_factory()() as s:
                await s.execute(
                    text("UPDATE cost_decisions SET user_id=:u WHERE ulid=:d"),
                    {"u": w.users["colleague"], "d": Q["decision"]},
                )
                await s.commit()
            _act(app, w.users["owner"])
            assert (await client.delete(f"/api/v1/parts/{Q['hash']}")).status_code == 403
            _act(app, w.users["admin"])
            r = await client.delete(f"/api/v1/parts/{Q['hash']}")
            assert r.status_code == 200, r.text
        assert set((await _rows_for(w.orgs["A"], Q["hash"])).values()) == {0}
    finally:
        await _cleanup(w)


async def test_keeping_the_fixed_copies(stores):
    from httpx import ASGITransport, AsyncClient

    from src.services import cad_fix_service as fx

    w = await _world(stores)
    A = w.orgs["A"]
    P, C = w.parts["P"], w.parts["C"]
    app = _app()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            _act(app, w.users["owner"])
            pv = (await client.get(f"/api/v1/parts/{P['hash']}/deletion-preview?keep_fixed_copies=true")).json()
            assert pv["will_remove"]["fixed_copies"] == 0 and pv["fixed_copies"] == [C["hash"]]
            r = await client.delete(f"/api/v1/parts/{P['hash']}?keep_fixed_copies=true")
            assert r.status_code == 200, r.text
            assert r.json()["removed"]["kept_fixed_copies"] == [C["hash"]]
        assert set((await _rows_for(A, P["hash"])).values()) == {0}
        assert set((await _rows_for(A, C["hash"])).values()) == {1}
        link = await fx._get_json(fx._record_key(A, C["hash"], "derived-from.json"))
        assert link["parent_mesh_hash"] == P["hash"] and "parent_filename" not in link
        assert link["parent_deleted_at"]
    finally:
        await _cleanup(w)


async def test_deleting_a_fixed_copy_unlinks_it_from_its_original(stores):
    from httpx import ASGITransport, AsyncClient

    from src.services import cad_fix_service as fx

    w = await _world(stores)
    A = w.orgs["A"]
    P, C = w.parts["P"], w.parts["C"]
    app = _app()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            _act(app, w.users["owner"])
            r = await client.delete(f"/api/v1/parts/{C['hash']}")
            assert r.status_code == 200, r.text
        assert set((await _rows_for(A, P["hash"])).values()) == {1}
        record = await fx._get_json(fx._record_key(A, P["hash"], "fixes/fillet.json"))
        assert record["fixed_mesh_hash"] is None and record["fixed_copy_deleted_at"]
    finally:
        await _cleanup(w)


async def test_deleting_the_organization(stores):
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text

    import src.db.engine as eng

    w = await _world(stores)
    A, B = w.orgs["A"], w.orgs["B"]
    async with eng.get_session_factory()() as s:
        await s.execute(text("INSERT INTO trial_checks (user_id, check_id, file_hash, completed, operations) "
                             "VALUES (:u, 'c1', 'f1', true, '{}')"), {"u": w.users["owner"]})
        await s.execute(text("INSERT INTO billing_accounts (user_id, stripe_customer_id, status) "
                             "VALUES (:u, :c, 'active')"), {"u": w.users["admin"], "c": f"cus_{w.tag}"})
        await s.execute(text("INSERT INTO catalog_parts (user_id, file_hash, state) VALUES (:u, 'f2', 'counted')"),
                        {"u": w.users["owner"]})
        before = dict((await s.execute(text("SELECT id, session_version FROM users WHERE id = ANY(:u)"),
                                       {"u": list(w.users.values())})).all())
        await s.commit()
    app = _app()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            _act(app, w.users["owner"])
            assert (await client.get("/api/v1/orgs/current/deletion-preview")).status_code == 403
            assert (await client.post("/api/v1/orgs/current/delete",
                                      json={"confirm_name": f"Acme A {w.tag}"})).status_code == 403
            _act(app, w.users["admin"])
            pv = (await client.get("/api/v1/orgs/current/deletion-preview")).json()
            assert pv["name"] == f"Acme A {w.tag}" and pv["will_remove"]["members"] == 4
            assert pv["will_remove"]["parts"] == 3
            wrong = await client.post("/api/v1/orgs/current/delete", json={"confirm_name": "Acme"})
            assert wrong.status_code == 400 and wrong.json()["detail"]["code"] == "confirm_name_mismatch"
            r = await client.post("/api/v1/orgs/current/delete", json={"confirm_name": f"  Acme A {w.tag} "})
            assert r.status_code == 200, r.text
            receipt = r.json()
            assert receipt["status"] == "done" and receipt["scope"] == "organization"
            assert receipt["removed"]["members_signed_out"] == 3
            assert (await client.get(f"/api/v1/data-deletions/{receipt['id']}")).json()["status"] == "done"
            # Links from the org are gone; org B's still work.
            assert (await client.get(f"/s/{w.parts['Q']['a_share']}")).status_code == 404
            assert (await client.get(f"/s/{w.parts['BP']['a_share']}")).status_code == 200

        assert await _count("SELECT count(*) FROM organizations WHERE id=:o", o=A) == 0
        for table in ("analyses", "cost_decisions", "part_contexts", "batches", "batch_items", "jobs",
                      "notifications", "rfq_packages", "ground_truth_records", "memberships", "part_signatures"):
            assert await _count(f"SELECT count(*) FROM {table} WHERE org_id=:o", o=A) == 0, table
        assert await _count("SELECT count(*) FROM analyses WHERE org_id=:o", o=B) == 1
        assert not (stores / "objects" / "source-artifacts" / A).exists()
        assert (stores / "objects" / "source-artifacts" / B).exists()
        assert not _obj(stores, "batch", w.parts["Q"]["batch_ulid"]).exists()
        assert _obj(stores, "meshes", f"{w.parts['P']['hash']}.bin").exists()  # org B has those bytes
        assert not _obj(stores, "meshes", f"{w.parts['Q']['hash']}.bin").exists()
        # Cached PDFs aren't keyed by org: the ones whose record is gone go, org B's stay.
        Q, BP = w.parts["Q"], w.parts["BP"]
        assert not _obj(stores, "cost-pdf", f"cost-{Q['decision']}-abcdef12.pdf").exists()
        assert _obj(stores, "cost-pdf", f"cost-{BP['decision']}-abcdef12.pdf").exists()
        assert not (stores / "pdf" / f"{Q['analysis']}.v3.pdf").exists()
        assert (stores / "pdf" / f"{BP['analysis']}.v3.pdf").exists()

        # Every member lands in a live org of their own and (except the actor) is signed out.
        async with eng.get_session_factory()() as s:
            rows = (await s.execute(text(
                "SELECT u.id, u.session_version, u.current_org_id, m.org_role FROM users u "
                "JOIN memberships m ON m.user_id = u.id AND m.org_id = u.current_org_id "
                "WHERE u.id = ANY(:u)"), {"u": [w.users[k] for k in ("owner", "colleague", "admin", "viewer")]})).all()
        assert len(rows) == 4
        for uid, version, org_id, role in rows:
            assert org_id != A and role == "admin"
            assert version == before[uid] + (0 if uid == w.users["admin"] else 1)
        # The account-level ledgers and billing record stay.
        assert await _count("SELECT count(*) FROM trial_checks WHERE user_id=:u", u=w.users["owner"]) == 1
        assert await _count("SELECT count(*) FROM catalog_parts WHERE user_id=:u", u=w.users["owner"]) == 1
        assert await _count("SELECT count(*) FROM billing_accounts WHERE user_id=:u", u=w.users["admin"]) == 1
        # The tombstone keeps the fact; the org's audit rows keep no content.
        assert await _count("SELECT count(*) FROM audit_log WHERE action='organization.deleted' AND resource_id=:o "
                            "AND user_id=:u", o=A, u=w.users["admin"]) == 1
        assert await _count("SELECT count(*) FROM audit_log WHERE detail_json::text LIKE :n", n="%Q-secret%") == 0
        assert await _count("SELECT count(*) FROM audit_log WHERE detail_json::text LIKE :n", n=f"%Acme A {w.tag}%") == 0
        # The org's audit rows drop who did each thing and from where: email, network address, browser.
        assert await _count("SELECT count(*) FROM audit_log WHERE user_email LIKE :e", e=f"actor-%-{w.tag}@%") == 1
        assert await _count("SELECT count(*) FROM audit_log WHERE user_email = :e", e=f"actor-BP-{w.tag}@example.com") == 1
        assert await _count(
            "SELECT count(*) FROM audit_log WHERE detail_json->>'deletion_id' = :d AND detail_json->>'redacted' = "
            "'organization_deleted' AND (user_email <> 'redacted' OR ip_address IS NOT NULL OR user_agent IS NOT NULL)",
            d=receipt["id"]) == 0
        assert await _count(
            "SELECT count(*) FROM audit_log WHERE detail_json->>'deletion_id' = :d AND user_email = 'redacted'",
            d=receipt["id"]) >= 3
        assert await _count("SELECT count(*) FROM audit_log WHERE user_agent LIKE 'Mozilla/5.0 actor-%' "
                            "AND user_agent IN ('Mozilla/5.0 actor-P', 'Mozilla/5.0 actor-C', 'Mozilla/5.0 actor-Q') "
                            "AND org_id IS NULL") == 0
        # Usage counts no longer name any of the org's files.
        assert await _count("SELECT count(*) FROM usage_events WHERE org_id IS NULL AND mesh_hash = ANY(:h)",
                            h=[w.parts[k]["hash"] for k in ("P", "C", "Q")]) == 0
        assert await _count("SELECT count(*) FROM usage_events WHERE org_id=:o AND mesh_hash IS NOT NULL", o=B) == 1
        assert await _count("SELECT count(*) FROM data_deletions WHERE org_id=:o AND final_sweep_due_at IS NOT NULL",
                            o=A) == 1
    finally:
        async with eng.get_session_factory()() as s:
            await s.execute(text("DELETE FROM billing_accounts WHERE user_id = ANY(:u)"), {"u": list(w.users.values())})
            await s.commit()
        await _cleanup(w)


async def test_final_sweep_catches_a_file_written_after_the_org_was_deleted(stores):
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text

    import src.db.engine as eng
    from src.services import data_deletion_service as svc

    w = await _world(stores)
    A = w.orgs["A"]
    app = _app()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            _act(app, w.users["admin"])
            receipt = (await client.post("/api/v1/orgs/current/delete",
                                         json={"confirm_name": f"Acme A {w.tag}"})).json()
        late = stores / "objects" / "source-artifacts" / A / ("e" * 64) / "source.stl"
        late.parent.mkdir(parents=True)
        late.write_bytes(b"a check that was still running")
        assert await svc.final_sweep(receipt["id"]) is None  # not due yet
        async with eng.get_session_factory()() as s:
            await s.execute(text("UPDATE data_deletions SET final_sweep_due_at = now() - interval '1 minute' "
                                 "WHERE ulid = :u"), {"u": receipt["id"]})
            await s.commit()
            stale, sweeps = await svc.pending_deletions(s)
        assert receipt["id"] in sweeps
        assert (await svc.final_sweep(receipt["id"])) is not None
        assert not late.exists()
    finally:
        await _cleanup(w)


async def test_a_storage_failure_is_retried_until_done(stores, monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text

    import src.db.engine as eng
    from src.services import data_deletion_service as svc

    w = await _world(stores)
    P = w.parts["Q"]
    real = svc._run_step_sync
    calls = {"n": 0}

    def flaky(org_id, step):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("object store unavailable")
        return real(org_id, step)

    monkeypatch.setattr(svc, "_run_step_sync", flaky)
    from src.api import data_control

    enqueued: list[str] = []

    async def fake_enqueue(ulid: str) -> None:
        enqueued.append(ulid)

    monkeypatch.setattr(data_control, "_enqueue_retry", fake_enqueue)
    app = _app()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            _act(app, w.users["owner"])
            r = await client.delete(f"/api/v1/parts/{P['hash']}")
            assert r.status_code == 200, r.text
            first = r.json()
            # The database part is done and the receipt says files are still being removed.
            assert first["status"] == "removing_files" and first["files"]["retrying"] is True
            assert enqueued == [first["id"]]
            assert set((await _rows_for(w.orgs["A"], P["hash"])).values()) == {0}
        async with eng.get_session_factory()() as s:
            await s.execute(text("UPDATE data_deletions SET updated_at = now() - interval '10 minutes' "
                                 "WHERE ulid = :u"), {"u": first["id"]})
            await s.commit()
            stale, _ = await svc.pending_deletions(s)
        assert first["id"] in stale
        from src.jobs.data_deletion_tasks import sweep_data_deletions

        result = await sweep_data_deletions({})
        assert result["processed"] >= 1
        assert await _count("SELECT count(*) FROM data_deletions WHERE ulid=:u AND status='done'", u=first["id"]) == 1
        assert not (stores / "objects" / "source-artifacts" / w.orgs["A"] / P["hash"]).exists()
    finally:
        await _cleanup(w)


async def test_two_deletes_at_once_make_one_receipt(stores):
    import asyncio

    from httpx import ASGITransport, AsyncClient

    w = await _world(stores)
    P = w.parts["Q"]
    app = _app()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            _act(app, w.users["owner"])
            a, b = await asyncio.gather(
                client.delete(f"/api/v1/parts/{P['hash']}"), client.delete(f"/api/v1/parts/{P['hash']}")
            )
        assert a.status_code == 200 and b.status_code == 200, (a.text, b.text)
        assert a.json()["id"] == b.json()["id"]
        assert await _count("SELECT count(*) FROM data_deletions WHERE target=:h", h=P["hash"]) == 1
        assert await _count("SELECT count(*) FROM audit_log WHERE action='part.deleted' AND file_hash=:h",
                            h=P["hash"]) == 1
    finally:
        await _cleanup(w)
