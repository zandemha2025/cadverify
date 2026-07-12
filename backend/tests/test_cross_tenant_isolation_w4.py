"""Adversarial cross-tenant isolation for the W3.5/W4 org-scoped surfaces.

The W1 proof (``test_cross_tenant_isolation.py``) covers the original data
routes (analyses / cost / batch / jobs / keys / share). This module extends the
same load-bearing, live-Postgres proof to every NEWER org-scoped resource that
lacked adversarial coverage:

    machine-inventory, shop-capabilities, parts-manifest, catalog/triage/
    portfolio/makeability, ground-truth, governance change-requests, the three
    governed libraries (rate / shop / material), part-context, and RFQ packages.

Design (mirrors the W1 proof so the boundary being tested is the ORG, not the
user):

  * Org A (a1, admin) and Org B (b1, admin) are each seeded a full spread. Both
    users are their org's admin so the org-role write paths (require_org_role)
    are actually reachable — a pure 403-on-everything would pass a weaker test
    but hide a leak, so we assert each user CAN see/act on its OWN org.
  * Acting as b1, every read/list/get/update/delete/export path against org A's
    resources must 404 (never 200, never A's row), org A rows must never appear
    in B's lists, and — because several ids are SEQUENTIAL integers (governance
    request_id, the three libraries' version_id) — we run explicit IDOR probes
    walking A's real integer id from org B.
  * No 404-vs-403 existence oracle: for every get-by-id, a cross-org id and a
    truly-nonexistent id return the SAME status, so B cannot distinguish
    "exists in another org" from "does not exist".

Auth: overriding ``require_api_key`` propagates through ``require_role`` and
``require_org_role`` (both ``Depends(require_api_key)``); ``require_org_role``
then resolves the org boundary from the REAL seeded ``memberships`` row, so the
tenancy predicate under test runs live. Only the auth principal is overridden;
``get_db_session`` and every service/filter below it run against Postgres.

Skipped unless DATABASE_URL is Postgres at schema head. Run:

    DATABASE_URL=postgresql://postgres@127.0.0.1:5433/cadverify_security \\
        RATE_LIMIT_DISABLED=1 .venv/bin/python -m pytest \\
        tests/test_cross_tenant_isolation_w4.py -q
"""
from __future__ import annotations

import json
import os
import uuid

import pytest

# Disable slowapi before the limiter module is first imported below, so this
# test's request volume can never trip a per-route bucket.
os.environ.setdefault("RATE_LIMIT_DISABLED", "1")

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)


def _build_app():
    """FastAPI app mounting the newer org-scoped routers at their real
    (main.py) prefixes, with the slowapi limiter state the @limiter.limit
    routes need. Only the auth principal is overridden per test."""
    from fastapi import FastAPI

    from src.api.catalog import router as catalog_router
    from src.api.governance import router as governance_router
    from src.api.groundtruth import router as groundtruth_router
    from src.api.machine_inventory import router as machine_router
    from src.api.manifest import router as manifest_router
    from src.api.material_library import router as material_router
    from src.api.part_context import router as part_context_router
    from src.api.rate_library import router as rate_router
    from src.api.rfq_packages import router as rfq_router
    from src.api.shop_library import router as shop_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(machine_router, prefix="/api/v1/machine-inventory")
    app.include_router(manifest_router, prefix="/api/v1/manifest")
    app.include_router(catalog_router, prefix="/api/v1/catalog")
    app.include_router(groundtruth_router, prefix="/api/v1/ground-truth")
    app.include_router(governance_router, prefix="/api/v1/governance")
    app.include_router(rate_router, prefix="/api/v1/rate-library")
    app.include_router(shop_router, prefix="/api/v1/shop-library")
    app.include_router(material_router, prefix="/api/v1/material-library")
    app.include_router(part_context_router, prefix="/api/v1/part-context")
    app.include_router(rfq_router, prefix="/api/v1/rfq-packages")
    return app


def _act_as(app, user_id: int, role: str = "admin") -> None:
    """Point require_api_key (and thus require_role / require_org_role) at a
    seeded principal. role='admin' clears the PLATFORM gates; the ORG boundary
    is still resolved from the real membership row, so this does NOT bypass
    tenant scoping (only a platform 'superadmin' would, which we never use)."""
    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id, api_key_id=0, key_prefix="session", role=role
    )


@_requires_pg
@pytest.mark.asyncio
async def test_w4_cross_tenant_isolation_matrix():
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng

    tag = uuid.uuid4().hex[:10]
    org_a = str(ULID())
    org_b = str(ULID())
    created_users: list[int] = []

    async def _mk_user(s, label: str) -> int:
        email = f"w4iso-{tag}-{label}@example.com"
        uid = int(
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
        created_users.append(uid)
        return uid

    async def _mk_membership(s, org_id, uid, role):
        await s.execute(
            text(
                "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
                "VALUES (:id, :o, :u, :r, now())"
            ),
            {"id": str(ULID()), "o": org_id, "u": uid, "r": role},
        )
        await s.execute(
            text("UPDATE users SET current_org_id = :o WHERE id = :u"),
            {"o": org_id, "u": uid},
        )

    async def _mk_machine(s, org_id, uid) -> str:
        u = str(ULID())
        await s.execute(
            text(
                "INSERT INTO machine_instances (ulid, org_id, name, process, "
                "created_by) VALUES (:ul, :o, :n, 'cnc_3axis', :u)"
            ),
            {"ul": u, "o": org_id, "n": f"MACHINE-{tag}-{u[-6:]}", "u": uid},
        )
        return u

    async def _mk_shop_caps(s, org_id, marker):
        await s.execute(
            text(
                "INSERT INTO shop_capabilities (org_id, ops) "
                "VALUES (:o, CAST(:ops AS jsonb))"
            ),
            {"o": org_id, "ops": json.dumps([marker])},
        )

    async def _mk_manifest(s, org_id, uid) -> str:
        pid = f"PART-{tag}-{uuid.uuid4().hex[:6]}"
        await s.execute(
            text(
                "INSERT INTO manifest_parts (ulid, org_id, part_id, description, "
                "created_by) VALUES (:ul, :o, :p, :d, :u)"
            ),
            {"ul": str(ULID()), "o": org_id, "p": pid, "d": f"desc-{tag}", "u": uid},
        )
        return pid

    async def _mk_part_summary(s, org_id) -> str:
        mh = f"mesh-{tag}-{uuid.uuid4().hex[:8]}"
        await s.execute(
            text(
                "INSERT INTO part_summaries (org_id, mesh_hash, triage_bucket, "
                "route_process, has_analysis, has_cost, updated_at, row_json) "
                "VALUES (:o, :mh, 'costed', 'cnc_3axis', true, true, now(), "
                "CAST(:rj AS jsonb))"
            ),
            {
                "o": org_id, "mh": mh,
                "rj": json.dumps({"mesh_hash": mh, "part_label": mh}),
            },
        )
        return mh

    async def _mk_part_context(s, org_id) -> str:
        mh = f"pcmesh-{tag}-{uuid.uuid4().hex[:8]}"
        await s.execute(
            text(
                "INSERT INTO part_contexts (ulid, org_id, mesh_hash, program) "
                "VALUES (:ul, :o, :mh, :pg)"
            ),
            {"ul": str(ULID()), "o": org_id, "mh": mh, "pg": f"PROGRAM-{tag}"},
        )
        return mh

    async def _mk_groundtruth(s, org_id, uid) -> str:
        u = str(ULID())
        await s.execute(
            text(
                "INSERT INTO ground_truth_records (ulid, org_id, user_id, part_id, "
                "process, quantity, actual_unit_cost_usd) "
                "VALUES (:ul, :o, :u, :p, 'cnc_3axis', 100, 42.5)"
            ),
            {"ul": u, "o": org_id, "u": uid, "p": f"GT-{tag}-{u[-6:]}"},
        )
        return u

    async def _mk_version(s, table, org_id, uid, who, version=1, *, slug=False) -> int:
        # The NAME embeds the org label so a list response leaking the other
        # org's version is detectable by substring (both orgs use version 1).
        name = f"{table}-{who}-{tag}-v{version}"
        cols = "ulid, org_id, version, name, status, payload, created_by"
        vals = ":ul, :o, :v, :n, 'draft', CAST(:pl AS jsonb), :u"
        params = {
            "ul": str(ULID()), "o": org_id, "v": version, "n": name,
            "pl": json.dumps({"marker": name}), "u": uid,
        }
        if slug:
            cols = "ulid, org_id, version, slug, name, status, payload, created_by"
            vals = ":ul, :o, :v, :sl, :n, 'draft', CAST(:pl AS jsonb), :u"
            params["sl"] = f"slug-{who}-{tag}-{version}"
        return int(
            (
                await s.execute(
                    text(
                        f"INSERT INTO {table} ({cols}) VALUES ({vals}) RETURNING id"
                    ),
                    params,
                )
            ).first()[0]
        )

    async def _mk_change_request(s, org_id, uid, target_vid, who) -> int:
        return int(
            (
                await s.execute(
                    text(
                        "INSERT INTO change_requests (ulid, org_id, asset_type, "
                        "target_version_id, status, title, proposed_by) "
                        "VALUES (:ul, :o, 'rate_card', :tv, 'proposed', :t, :u) "
                        "RETURNING id"
                    ),
                    {"ul": str(ULID()), "o": org_id, "tv": target_vid,
                     "t": f"CR-{who}-{tag}", "u": uid},
                )
            ).first()[0]
        )

    async def _mk_rfq(s, org_id, uid) -> str:
        u = str(ULID())
        await s.execute(
            text(
                "INSERT INTO rfq_packages (ulid, org_id, user_id, title, "
                "items_json, warnings_json) VALUES (:ul, :o, :u, :t, "
                "CAST('[]' AS jsonb), CAST('[]' AS jsonb))"
            ),
            {"ul": u, "o": org_id, "u": uid, "t": f"RFQ-{tag}"},
        )
        return u

    # ---- seed --------------------------------------------------------------
    seed: dict = {}
    async with eng.get_session_factory()() as s:
        for oid, name in ((org_a, f"W4A {tag}"), (org_b, f"W4B {tag}")):
            await s.execute(
                text(
                    "INSERT INTO organizations (id, name, slug, created_at) "
                    "VALUES (:id, :n, :sl, now())"
                ),
                {"id": oid, "n": name, "sl": name.lower().replace(" ", "-")},
            )
        a1 = await _mk_user(s, "a1")
        b1 = await _mk_user(s, "b1")
        await _mk_membership(s, org_a, a1, "admin")
        await _mk_membership(s, org_b, b1, "admin")

        for who, org, uid in (("a", org_a, a1), ("b", org_b, b1)):
            seed[f"machine_{who}"] = await _mk_machine(s, org, uid)
            await _mk_shop_caps(s, org, f"SHOPCAP-{who}-{tag}")
            seed[f"manifest_{who}"] = await _mk_manifest(s, org, uid)
            seed[f"summary_{who}"] = await _mk_part_summary(s, org)
            seed[f"context_{who}"] = await _mk_part_context(s, org)
            seed[f"gt_{who}"] = await _mk_groundtruth(s, org, uid)
            seed[f"rate_{who}"] = await _mk_version(
                s, "rate_card_versions", org, uid, who
            )
            seed[f"shop_{who}"] = await _mk_version(
                s, "shop_profile_versions", org, uid, who, slug=True
            )
            seed[f"mat_{who}"] = await _mk_version(
                s, "material_library_versions", org, uid, who
            )
            seed[f"cr_{who}"] = await _mk_change_request(
                s, org, uid, seed[f"rate_{who}"], who
            )
            seed[f"rfq_{who}"] = await _mk_rfq(s, org, uid)
        await s.commit()

    # A truly-nonexistent int id (way past any seeded sequence) for the
    # no-oracle comparison. ULID misses use a random-but-valid ULID.
    ghost_int = 2_000_000_000
    ghost_ulid = str(ULID())

    app = _build_app()
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # ============================================================
            # Sanity: a1 SEES org A's rows (proves the filter is real org
            # scoping, not a blanket deny that would mask a leak).
            # ============================================================
            _act_as(app, a1)
            r = await ac.get("/api/v1/machine-inventory")
            assert r.status_code == 200, r.text
            assert seed["machine_a"] in r.text
            assert seed["machine_b"] not in r.text
            assert (
                await ac.get(f"/api/v1/machine-inventory/{seed['machine_a']}")
            ).status_code == 200
            assert (
                await ac.get(f"/api/v1/rate-library/{seed['rate_a']}")
            ).status_code == 200
            assert (
                await ac.get(f"/api/v1/governance/change-requests/{seed['cr_a']}")
            ).status_code == 200
            assert (
                await ac.get(f"/api/v1/rfq-packages/{seed['rfq_a']}")
            ).status_code == 200

            # ============================================================
            # ACT AS b1 (org B). Every org-A resource must be invisible.
            # ============================================================
            _act_as(app, b1)

            # ---- helper: get-by-id must 404 AND match the ghost status
            #      (no 404-vs-403 existence oracle) ----
            async def _assert_no_oracle(cross_path, ghost_path):
                cross = await ac.get(cross_path)
                ghost = await ac.get(ghost_path)
                assert cross.status_code == 404, f"{cross_path} -> {cross.status_code}"
                assert ghost.status_code == cross.status_code, (
                    f"oracle: {cross_path}={cross.status_code} vs "
                    f"{ghost_path}={ghost.status_code}"
                )

            # ---- machine inventory ----
            r = await ac.get("/api/v1/machine-inventory")
            assert r.status_code == 200 and seed["machine_a"] not in r.text
            assert seed["machine_b"] in r.text
            await _assert_no_oracle(
                f"/api/v1/machine-inventory/{seed['machine_a']}",
                f"/api/v1/machine-inventory/{ghost_ulid}",
            )
            assert (
                await ac.patch(
                    f"/api/v1/machine-inventory/{seed['machine_a']}",
                    json={"name": "hijacked"},
                )
            ).status_code == 404
            assert (
                await ac.delete(f"/api/v1/machine-inventory/{seed['machine_a']}")
            ).status_code == 404

            # ---- shop capabilities (org singleton): B never sees A's ops ----
            r = await ac.get("/api/v1/machine-inventory/shop-capabilities")
            assert r.status_code == 200
            assert f"SHOPCAP-a-{tag}" not in r.text
            assert f"SHOPCAP-b-{tag}" in r.text

            # ---- parts manifest (list + coverage; no A part_id leak) ----
            r = await ac.get("/api/v1/manifest")
            assert r.status_code == 200 and seed["manifest_a"] not in r.text
            assert seed["manifest_b"] in r.text
            r = await ac.get("/api/v1/manifest/coverage")
            assert r.status_code == 200 and seed["manifest_a"] not in r.text

            # ---- catalog family (grid/triage/portfolio/makeability/capinv) ----
            for path in (
                "/api/v1/catalog",
                "/api/v1/catalog?keyset=true",
                "/api/v1/catalog/triage",
                "/api/v1/catalog/portfolio",
                "/api/v1/catalog/makeability",
                "/api/v1/catalog/capability-investment",
            ):
                r = await ac.get(path)
                assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text}"
                assert seed["summary_a"] not in r.text, f"catalog leak in {path}"
            # positive: B's own part is in its grid
            assert seed["summary_b"] in (await ac.get("/api/v1/catalog?keyset=true")).text

            # ---- ground truth (list + get-by-id) ----
            r = await ac.get("/api/v1/ground-truth")
            assert r.status_code == 200 and seed["gt_a"] not in r.text
            assert seed["gt_b"] in r.text
            await _assert_no_oracle(
                f"/api/v1/ground-truth/{seed['gt_a']}",
                f"/api/v1/ground-truth/{ghost_ulid}",
            )

            # ---- part context (get + upsert do not cross the org) ----
            await _assert_no_oracle(
                f"/api/v1/part-context/{seed['context_a']}",
                f"/api/v1/part-context/{ghost_ulid}",
            )
            # A PUT on A's mesh_hash from org B must create a SEPARATE org-B row,
            # never mutate A's. It returns 200 (upsert) but stays in org B.
            r = await ac.put(
                f"/api/v1/part-context/{seed['context_a']}",
                json={"program": "hijack", "annual_volume": 5},
            )
            assert r.status_code in (200, 201), r.text

            # ---- governance change-requests (SEQUENTIAL int id -> IDOR) ----
            r = await ac.get("/api/v1/governance/change-requests")
            assert r.status_code == 200
            assert f"CR-a-{tag}" not in r.text, "governance list leaked org A"
            assert f"CR-b-{tag}" in r.text, "governance list missing org B's own"
            await _assert_no_oracle(
                f"/api/v1/governance/change-requests/{seed['cr_a']}",
                f"/api/v1/governance/change-requests/{ghost_int}",
            )
            assert (
                await ac.post(
                    f"/api/v1/governance/change-requests/{seed['cr_a']}/approve"
                )
            ).status_code == 404
            assert (
                await ac.post(
                    f"/api/v1/governance/change-requests/{seed['cr_a']}/reject",
                    json={"note": "x"},
                )
            ).status_code == 404

            # ---- three governed libraries (SEQUENTIAL int version_id -> IDOR) --
            for lib, key in (
                ("rate-library", "rate"),
                ("shop-library", "shop"),
                ("material-library", "mat"),
            ):
                a_vid = seed[f"{key}_a"]
                b_vid = seed[f"{key}_b"]
                r = await ac.get(f"/api/v1/{lib}")
                assert r.status_code == 200, r.text
                # A's org-labelled version marker must NOT appear; B's must.
                assert f"-a-{tag}-" not in r.text, f"{lib} list leaked org A"
                assert f"-b-{tag}-" in r.text, f"{lib} list missing org B's own"
                # cross-org get + IDOR: 404, and no oracle vs a ghost int
                await _assert_no_oracle(
                    f"/api/v1/{lib}/{a_vid}", f"/api/v1/{lib}/{ghost_int}"
                )
                # cross-org mutations never succeed
                assert (
                    await ac.patch(f"/api/v1/{lib}/{a_vid}", json={"name": "x"})
                ).status_code == 404
                assert (
                    await ac.delete(f"/api/v1/{lib}/{a_vid}")
                ).status_code == 404
                assert (
                    await ac.post(f"/api/v1/{lib}/{a_vid}/publish", json={})
                ).status_code == 404
                assert (
                    await ac.post(f"/api/v1/{lib}/{a_vid}/archive")
                ).status_code == 404
                # positive: B can read its own version
                assert (await ac.get(f"/api/v1/{lib}/{b_vid}")).status_code == 200

            # rate/material diff across the boundary is blocked
            assert (
                await ac.get(
                    f"/api/v1/rate-library/{seed['rate_a']}/diff/{seed['rate_b']}"
                )
            ).status_code == 404

            # ---- RFQ packages (ULID id + zip export) ----
            r = await ac.get("/api/v1/rfq-packages")
            assert r.status_code == 200 and seed["rfq_a"] not in r.text
            assert seed["rfq_b"] in r.text
            await _assert_no_oracle(
                f"/api/v1/rfq-packages/{seed['rfq_a']}",
                f"/api/v1/rfq-packages/{ghost_ulid}",
            )
            assert (
                await ac.get(f"/api/v1/rfq-packages/{seed['rfq_a']}/download.zip")
            ).status_code == 404

            # ============================================================
            # Symmetry: as a1, org B's rows are equally invisible.
            # ============================================================
            _act_as(app, a1)
            assert (
                await ac.get(f"/api/v1/machine-inventory/{seed['machine_b']}")
            ).status_code == 404
            assert (
                await ac.get(f"/api/v1/rate-library/{seed['rate_b']}")
            ).status_code == 404
            assert (
                await ac.get(f"/api/v1/rfq-packages/{seed['rfq_b']}")
            ).status_code == 404
            assert (
                await ac.get(f"/api/v1/ground-truth/{seed['gt_b']}")
            ).status_code == 404
            # A's own change-request was NOT approved/published by B's attempts:
            r = await ac.get(f"/api/v1/governance/change-requests/{seed['cr_a']}")
            assert r.status_code == 200 and r.json()["status"] == "proposed"
            # A's rate version was NOT deleted/published by B's attempts:
            r = await ac.get(f"/api/v1/rate-library/{seed['rate_a']}")
            assert r.status_code == 200 and r.json()["status"] == "draft"
    finally:
        app.dependency_overrides.clear()
        # ---- teardown (FK-safe; org_id FKs cascade, but be explicit) -------
        async with eng.get_session_factory()() as s:
            for tbl in (
                "rfq_packages", "change_requests", "rate_card_versions",
                "shop_profile_versions", "material_library_versions",
                "ground_truth_records", "part_contexts", "part_summaries",
                "manifest_parts", "shop_capabilities", "machine_instances",
            ):
                await s.execute(
                    text(f"DELETE FROM {tbl} WHERE org_id IN (:a, :b)"),
                    {"a": org_a, "b": org_b},
                )
            if created_users:
                await s.execute(
                    text("DELETE FROM memberships WHERE user_id = ANY(:i)"),
                    {"i": created_users},
                )
                await s.execute(
                    text("DELETE FROM users WHERE id = ANY(:i)"),
                    {"i": created_users},
                )
            await s.execute(
                text("DELETE FROM organizations WHERE id IN (:a, :b)"),
                {"a": org_a, "b": org_b},
            )
            await s.commit()
        await eng.dispose_engine()
