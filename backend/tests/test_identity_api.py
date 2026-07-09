"""Identity in the cost response + the confirm endpoint — live-Postgres route tests.

Drives the USER-VISIBLE half of identity Slice 1 through an ASGI client with only
the auth principal + DB session overridden (the real routers, ``resolve_org``, the
retrieval engine, and the ``part_signatures`` corpus all run against the live DB):

  * MATCH + SELF-EXCLUSION — POST /validate/cost with a near-duplicate of a seeded
    part returns ``identity.grounded == true`` whose top match is that seeded part,
    and the query part's OWN mesh_hash (seeded as a decoy row) is NEVER a match.
  * CONFIRM WRITE-BACK — POST /identity/confirm stamps the declared identity onto
    the corpus row (source user_confirmed, provenance USER) and a subsequent
    retrieval reflects it.
  * ANONYMOUS — the public demo route (no org) returns ``identity: null``, no error.
  * CROSS-ORG — org B confirming org A's mesh_hash is a 404 and leaves A's row
    untouched.

Skipped unless DATABASE_URL is Postgres at schema head (``alembic upgrade head``).
"""
from __future__ import annotations

import os
import uuid

import pytest

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)


def _build_app():
    from fastapi import FastAPI

    from src.api.identity import router as identity_router
    from src.api.routes import router as core_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(core_router, prefix="/api/v1")
    app.include_router(identity_router, prefix="/api/v1/identity")
    return app


def _act_as(app, user_id: int) -> None:
    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id, api_key_id=0, key_prefix="session", role="analyst"
    )


def _seed_meshes():
    """Four geometrically distinct prior parts with declared identities (the corpus
    the retrieval engine z-scores + ranks over)."""
    import trimesh

    return [
        ("cube", trimesh.creation.box(extents=[40, 40, 40]),
         "PN-1001", "Battery enclosure block", "PowerPack"),
        ("plate", trimesh.creation.box(extents=[120, 80, 4]),
         "PN-1002", "Mounting plate bracket", "Chassis"),
        ("rod", trimesh.creation.cylinder(radius=6, height=120, sections=64),
         "PN-1003", "Drive shaft rod", "Drivetrain"),
        ("disc", trimesh.creation.cylinder(radius=45, height=8, sections=96),
         "PN-1004", "Sensor cover disc", "Sensors"),
    ]


@_requires_pg
@pytest.mark.asyncio
async def test_cost_response_identity_confirm_and_isolation():
    import trimesh
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng
    from src.eval import similarity
    from src.services import part_signature_service as sigsvc
    from src.services.analysis_service import compute_mesh_hash

    tag = uuid.uuid4().hex[:10]
    org_a, org_b = str(ULID()), str(ULID())

    # The uploaded part: a near-duplicate of the seeded PN-1002 mounting plate.
    near_dup = trimesh.creation.box(extents=[122, 81, 4.1])
    stl_bytes = near_dup.export(file_type="stl")
    self_hash = compute_mesh_hash(stl_bytes)

    async def _mk_user(s, label):
        email = f"id-{tag}-{label}@example.com"
        return int(
            (
                await s.execute(
                    text(
                        "INSERT INTO users (email, email_lower, role, auth_provider) "
                        "VALUES (:e, :el, 'analyst', 'password') RETURNING id"
                    ),
                    {"e": email, "el": email.lower()},
                )
            ).first()[0]
        )

    async with eng.get_session_factory()() as s:
        for oid, nm in ((org_a, f"A {tag}"), (org_b, f"B {tag}")):
            await s.execute(
                text(
                    "INSERT INTO organizations (id, name, slug, created_at) "
                    "VALUES (:id, :n, :sl, now())"
                ),
                {"id": oid, "n": nm, "sl": f"{oid[-8:].lower()}"},
            )
        uid_a = await _mk_user(s, "a")
        uid_b = await _mk_user(s, "b")
        for oid, uid in ((org_a, uid_a), (org_b, uid_b)):
            await s.execute(
                text(
                    "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
                    "VALUES (:id, :o, :u, 'admin', now())"
                ),
                {"id": str(ULID()), "o": oid, "u": uid},
            )
        # Seed org A's corpus: four distinct prior parts …
        for _tag, mesh, pn, name, prog in _seed_meshes():
            vec = similarity.vector_for_mesh(mesh)
            await sigsvc.upsert_signature(
                s, org_a, f"hash-{_tag}-{tag}", vec,
                declared_part_id=pn, declared_name=name, program=prog,
            )
        # … PLUS a DECOY row keyed by the uploaded part's OWN mesh_hash (an exact
        # match to itself). Without self-exclusion this would rank #1; the engine
        # must drop it so a part never matches itself.
        await sigsvc.upsert_signature(
            s, org_a, self_hash, similarity.vector_for_mesh(near_dup),
            declared_part_id="PN-SELF", declared_name="SELF must be excluded",
            program="Self",
        )
        await s.commit()

    # Real DB sessions for the route (only the auth principal is overridden).
    async def _real_session():
        async with eng.get_session_factory()() as s:
            yield s

    from src.db.engine import get_db_session

    app = _build_app()
    app.dependency_overrides[get_db_session] = _real_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        files = {"file": ("mounting-plate.stl", stl_bytes, "application/octet-stream")}
        form = {"qty": "1,100", "material_class": "aluminum"}

        # ── MATCH + SELF-EXCLUSION ──────────────────────────────────────────
        _act_as(app, uid_a)
        r = await c.post("/api/v1/validate/cost", files=files, data=form)
        assert r.status_code == 200, r.text
        identity = r.json()["identity"]
        assert identity is not None
        assert identity["grounded"] is True
        top = identity["matches"][0]
        assert top["declared_part_id"] == "PN-1002"
        assert top["declared_name"] == "Mounting plate bracket"
        assert top["confidence_bucket"] in ("HIGH", "MEDIUM")
        assert top["provenance"].startswith("RETRIEVED")
        # Self-exclusion: the query part's own mesh_hash is NEVER a match.
        assert all(m["mesh_hash"] != self_hash for m in identity["matches"])
        assert not any(m["declared_part_id"] == "PN-SELF" for m in identity["matches"])
        assert any("SUGGESTION" in cav for cav in identity["caveats"])

        # ── CONFIRM WRITE-BACK ──────────────────────────────────────────────
        plate_hash = f"hash-plate-{tag}"
        r = await c.post(
            "/api/v1/identity/confirm",
            json={
                "mesh_hash": plate_hash,
                "declared_part_id": "PN-CONFIRMED-9",
                "declared_name": "Confirmed mounting plate",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["provenance"] == "USER"
        assert body["confirmed"] is True
        assert body["declared_part_id"] == "PN-CONFIRMED-9"
        # A supplied field wins; an omitted field (program) is preserved.
        assert body["program"] == "Chassis"

        # A subsequent cost call reflects the confirmed identity as the top match.
        r = await c.post("/api/v1/validate/cost", files=files, data=form)
        assert r.status_code == 200, r.text
        top2 = r.json()["identity"]["matches"][0]
        assert top2["declared_part_id"] == "PN-CONFIRMED-9"

        # ── CROSS-ORG: B cannot confirm A's row (404, A untouched) ──────────
        _act_as(app, uid_b)
        r = await c.post(
            "/api/v1/identity/confirm",
            json={"mesh_hash": plate_hash, "declared_part_id": "PN-HIJACK"},
        )
        assert r.status_code == 404

    # ── ANONYMOUS: the public demo route has no org → identity null ─────────
    app.dependency_overrides.pop(get_db_session, None)
    app.dependency_overrides.clear()
    transport2 = ASGITransport(app=app)
    async with AsyncClient(transport=transport2, base_url="http://t") as c:
        r = await c.post(
            "/api/v1/validate/cost/demo",
            files={"file": ("anon.stl", stl_bytes, "application/octet-stream")},
            data=form,
        )
        assert r.status_code == 200, r.text
        assert r.json()["identity"] is None

    # A's confirmed row survived the cross-org attempt unchanged.
    async with eng.get_session_factory()() as s:
        rows = await sigsvc.list_signatures(s, org_a)
        plate = next(r for r in rows if r.mesh_hash == f"hash-plate-{tag}")
        assert plate.declared_part_id == "PN-CONFIRMED-9"
        assert plate.source == sigsvc.SOURCE_USER_CONFIRMED

    # ── cleanup ─────────────────────────────────────────────────────────────
    async with eng.get_session_factory()() as s:
        await s.execute(
            text("DELETE FROM part_signatures WHERE org_id IN (:a, :b)"),
            {"a": org_a, "b": org_b},
        )
        await s.execute(
            text("DELETE FROM memberships WHERE org_id IN (:a, :b)"),
            {"a": org_a, "b": org_b},
        )
        await s.execute(
            text("DELETE FROM users WHERE id IN (:a, :b)"), {"a": uid_a, "b": uid_b}
        )
        await s.execute(
            text("DELETE FROM organizations WHERE id IN (:a, :b)"),
            {"a": org_a, "b": org_b},
        )
        await s.commit()
    await eng.dispose_engine()
