"""BOM hierarchy (customer-context Slice 3) integration tests against live Postgres.

Drives ``/api/v1/bom`` through an ASGI client with only the auth principal
overridden — the real ``get_db_session`` -> ``resolve_org`` and the migration-0037
``bom_edges`` table run against the live DB. Proves:

  * BOM CSV onboard (handle->door qty 2, door->car qty 4) persists the tree and a
    bad row is skipped while the batch survives.
  * ``GET /bom/{key}/ancestry`` returns the real child->root chain + rolled-up
    multiplier + provenance; ``annual_volume`` at 100000 roots/year = 2 x 4 x 100000.
  * Cross-tenant isolation — org B never sees org A's tree (has_tree=false).
  * The AS1 real assembly (when gmsh is present) ingests its known hierarchy and
    rolled_up_multiplier(bolt) == 6.

Skipped unless DATABASE_URL is Postgres at schema head (``alembic upgrade head``).
"""
from __future__ import annotations

import os
import uuid

import pytest

from tests.cad_fixtures import as1_fixture_bytes

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)


def _build_app():
    from fastapi import FastAPI

    from src.api.bom import router as bom_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(bom_router, prefix="/api/v1/bom")
    return app


def _act_as(app, user_id: int) -> None:
    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id, api_key_id=0, key_prefix="session", role="analyst"
    )


async def _seed_org(s, oid, uid_email):
    from sqlalchemy import text
    from ulid import ULID

    await s.execute(
        text(
            "INSERT INTO organizations (id, name, slug, created_at) "
            "VALUES (:id, :n, :sl, now())"
        ),
        {"id": oid, "n": f"org {oid[-6:]}", "sl": oid[-8:].lower()},
    )
    uid = int(
        (
            await s.execute(
                text(
                    "INSERT INTO users (email, email_lower, role, auth_provider) "
                    "VALUES (:e, :el, 'analyst', 'password') RETURNING id"
                ),
                {"e": uid_email, "el": uid_email.lower()},
            )
        ).first()[0]
    )
    await s.execute(
        text(
            "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
            "VALUES (:id, :o, :u, 'admin', now())"
        ),
        {"id": str(ULID()), "o": oid, "u": uid},
    )
    return uid


@_requires_pg
@pytest.mark.asyncio
async def test_bom_csv_onboard_ancestry_and_isolation():
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng

    tag = uuid.uuid4().hex[:10]
    org_a, org_b = str(ULID()), str(ULID())
    key = f"vehicle-{tag}"

    async with eng.get_session_factory()() as s:
        uid_a = await _seed_org(s, org_a, f"bom-{tag}-a@example.com")
        uid_b = await _seed_org(s, org_b, f"bom-{tag}-b@example.com")
        await s.commit()

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        _act_as(app, uid_a)

        # --- onboard a real multi-level BOM; one bad row must be skipped --------
        csv_text = (
            "parent_ref,child_ref,qty_per_parent,child_name\n"
            f"{key},door,4,Door assembly\n"
            "door,handle,2,Door handle\n"
            "door,,3,Nameless\n"  # bad: missing child_ref -> skipped, batch survives
        )
        r = await c.post(
            f"/api/v1/bom/onboard?assembly_key={key}",
            content=csv_text,
            headers={"content-type": "text/csv"},
        )
        assert r.status_code == 200, r.text
        summary = r.json()
        assert summary["edges"] == 2  # the two good edges
        assert summary["skipped"] == 1
        assert summary["roots"] == [key]

        # --- ancestry + rolled-up multiplier -----------------------------------
        r = await c.get(f"/api/v1/bom/{key}/ancestry?child_ref=handle")
        assert r.status_code == 200, r.text
        anc = r.json()
        assert anc["has_tree"] is True
        assert anc["ancestry"] == ["handle", "door", key]
        assert anc["rolled_up_multiplier"] == 8  # 2 x 4

        # --- re-onboard REPLACES the tree (idempotent per key) -----------------
        r = await c.post(
            f"/api/v1/bom/onboard?assembly_key={key}",
            content=(
                "parent_ref,child_ref,qty_per_parent\n"
                f"{key},door,4\ndoor,handle,2\n"
            ),
            headers={"content-type": "text/csv"},
        )
        assert r.json()["edges"] == 2

        # --- cross-tenant isolation: org B sees NO tree for org A's key --------
        _act_as(app, uid_b)
        r = await c.get(f"/api/v1/bom/{key}/ancestry?child_ref=handle")
        assert r.status_code == 200
        assert r.json()["has_tree"] is False
        assert r.json()["rolled_up_multiplier"] is None
        r = await c.get(f"/api/v1/bom/{key}")
        assert r.json()["edges"] == []

    # --- cleanup -------------------------------------------------------------
    async with eng.get_session_factory()() as s:
        for tbl in ("bom_edges", "memberships"):
            await s.execute(
                text(f"DELETE FROM {tbl} WHERE org_id IN (:a, :b)"),
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


@_requires_pg
@pytest.mark.asyncio
async def test_annual_volume_basis_rollup_vs_declared_fallback():
    """The payoff: a part linked to a BOM tree gets basis 'bom_rollup'; a part with
    no BOM linkage falls back to its flat declared volume with basis 'declared'."""
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng
    from src.services import bom_service as bom
    from src.services import part_context_service as pcsvc

    tag = uuid.uuid4().hex[:10]
    org = str(ULID())
    key = f"veh-{tag}"

    async with eng.get_session_factory()() as s:
        uid = await _seed_org(s, org, f"bomvol-{tag}@example.com")
        await s.commit()

    async with eng.get_session_factory()() as s:
        # persist handle->door(2)->car(4)
        rows, errs = bom.parse_bom(
            "parent_ref,child_ref,qty_per_parent\n"
            f"{key},door,4\ndoor,handle,2\n"
        )
        assert errs == []
        await bom.ingest_bom_rows(s, org, key, rows)

        # a part WITH bom linkage → rollup
        ctx_rollup = await pcsvc.upsert_context(
            s, org, f"mesh-handle-{tag}",
            {
                "annual_volume": 55,  # a stale flat number; the rollup must win
                "bom_assembly_key": key,
                "bom_child_ref": "handle",
                "bom_roots_per_year": 100000,
            },
        )
        # a part with NO bom linkage → declared fallback
        ctx_declared = await pcsvc.upsert_context(
            s, org, f"mesh-other-{tag}", {"annual_volume": 12000},
        )
        await s.flush()

        r1 = await bom.annual_volume_for_context(s, org, ctx_rollup)
        assert r1 == {"annual_volume": 800000, "annual_volume_basis": "bom_rollup"}

        r2 = await bom.annual_volume_for_context(s, org, ctx_declared)
        assert r2 == {"annual_volume": 12000, "annual_volume_basis": "declared"}
        await s.rollback()

    async with eng.get_session_factory()() as s:
        for tbl in ("bom_edges", "part_contexts", "memberships"):
            await s.execute(
                text(f"DELETE FROM {tbl} WHERE org_id = :o"), {"o": org}
            )
        await s.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
        await s.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org})
        await s.commit()
    await eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_as1_real_assembly_ingest_reproduces_hierarchy():
    """Ingest the REAL AS1 STEP assembly and assert the persisted tree reproduces
    the known hierarchy: bolt under nut-bolt-assembly under l-bracket-assembly under
    as1, with rolled_up_multiplier(bolt) == 6."""
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng
    from src.parsers.assembly_mesher import is_step_supported

    if not is_step_supported():
        pytest.skip("gmsh not installed — assembly extraction unavailable")

    from src.parsers.assembly_mesher import extract_assembly_from_bytes
    from src.services import bom_service as bom

    tag = uuid.uuid4().hex[:10]
    org = str(ULID())
    key = f"as1-{tag}"

    async with eng.get_session_factory()() as s:
        uid = await _seed_org(s, org, f"as1-{tag}@example.com")
        await s.commit()

    model = extract_assembly_from_bytes(as1_fixture_bytes(), "as1-tu-203.stp")

    async with eng.get_session_factory()() as s:
        summary = await bom.ingest_assembly(s, org, key, model)
        await s.commit()
        assert summary["roots"] == ["as1"]
        assert summary["edges"] >= 8

        anc = await bom.get_ancestry(s, org, key, "bolt")
        assert anc["ancestry"] == [
            "bolt", "nut-bolt-assembly", "l-bracket-assembly", "as1",
        ]
        assert anc["rolled_up_multiplier"] == 6
        # nut is the real DAG (2 via rod-assembly + 6 via l-brackets) = 8.
        nut = await bom.get_ancestry(s, org, key, "nut")
        assert nut["rolled_up_multiplier"] == 8

    async with eng.get_session_factory()() as s:
        for tbl in ("bom_edges", "memberships"):
            await s.execute(text(f"DELETE FROM {tbl} WHERE org_id = :o"), {"o": org})
        await s.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
        await s.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org})
        await s.commit()
    await eng.dispose_engine()
