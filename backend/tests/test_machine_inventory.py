"""Machine-inventory model + CRUD/CSV + shop-capabilities + service-environment.

Two layers, mirroring ``test_manifest_ingest.py``:

  * **pure** (no DB/IO): machine capability validation (good / bad process /
    negative scalar / bad IT grade / unknown material / capital_frac out of
    range / unknown capability), CSV parse (good / mixed / bad-header / empty /
    BOM), ``add_from_catalog`` prefill, and service-environment validation.
    Malformed inputs are REPORTED, never coerced.
  * **Postgres** (skipped unless DATABASE_URL is Postgres): CRUD + org isolation,
    CSV import, ``load_org_inventory`` → correct ``MachineCap`` list,
    ``load_shop_caps``, and part-context ``service_environment`` upsert/read/isolation.
"""
from __future__ import annotations

import csv
import io
import json
import os

import pytest

from src.services import machine_inventory_service as svc
from src.services import part_context_service as pcs


# ── pure: machine validation ─────────────────────────────────────────────────
def _good_machine() -> dict:
    return {
        "name": "Haas VF-2 #1",
        "process": "cnc_3axis",
        "count": 1,
        "max_workpiece_kg": 200.0,
        "hourly_rate_usd": 75.0,
        "capital_frac": 0.4,
        "capabilities": {"x": 762, "y": 406, "z": 508, "axes": 3,
                         "achievable_it_grade": 9},
        "materials": ["304 Stainless", "steel"],
    }


def test_good_machine_validates():
    svc.validate_machine(_good_machine())  # no raise


def test_empty_capabilities_is_valid():
    m = _good_machine()
    m["capabilities"] = {}  # a machine may declare only some gates
    svc.validate_machine(m)


def test_bad_process_reported():
    m = _good_machine()
    m["process"] = "cnc_9axis"
    with pytest.raises(ValueError, match="unknown process"):
        svc.validate_machine(m)


def test_missing_process_reported():
    m = _good_machine()
    m["process"] = None
    with pytest.raises(ValueError, match="process is required"):
        svc.validate_machine(m)


def test_negative_scalar_reported():
    m = _good_machine()
    m["capabilities"] = {"x": -5}
    with pytest.raises(ValueError, match="must be > 0"):
        svc.validate_machine(m)


def test_bad_it_grade_reported():
    m = _good_machine()
    m["capabilities"] = {"achievable_it_grade": "IT9"}
    with pytest.raises(ValueError, match="achievable_it_grade must be an integer"):
        svc.validate_machine(m)


def test_it_grade_out_of_range_reported():
    m = _good_machine()
    m["capabilities"] = {"achievable_it_grade": 42}
    with pytest.raises(ValueError, match="IT grade in 0"):
        svc.validate_machine(m)


def test_unknown_material_reported():
    m = _good_machine()
    m["materials"] = ["unobtainium"]
    with pytest.raises(ValueError, match="unknown material"):
        svc.validate_machine(m)


def test_known_material_name_and_class_accepted():
    m = _good_machine()
    m["materials"] = ["Inconel 718", "titanium"]  # a real name + a real class
    svc.validate_machine(m)


def test_capital_frac_out_of_range_reported():
    m = _good_machine()
    m["capital_frac"] = 1.5
    with pytest.raises(ValueError, match=r"capital_frac must be in \[0,1\]"):
        svc.validate_machine(m)


def test_negative_rate_reported():
    m = _good_machine()
    m["hourly_rate_usd"] = -1.0
    with pytest.raises(ValueError, match="hourly_rate_usd must be >= 0"):
        svc.validate_machine(m)


def test_unknown_capability_key_reported():
    m = _good_machine()
    m["capabilities"] = {"warp_drive_kw": 5}
    with pytest.raises(ValueError, match="unknown capability"):
        svc.validate_machine(m)


def test_bad_axes_reported():
    m = _good_machine()
    m["capabilities"] = {"axes": 7}
    with pytest.raises(ValueError, match="axes must be one of"):
        svc.validate_machine(m)


def test_bad_motion_mode_reported():
    m = _good_machine()
    m["capabilities"] = {"motion_mode": "sideways"}
    with pytest.raises(ValueError, match="motion_mode"):
        svc.validate_machine(m)


def test_all_problems_collected_in_one_message():
    m = _good_machine()
    m["process"] = "nope"
    m["capital_frac"] = 2
    m["capabilities"] = {"x": -1}
    with pytest.raises(ValueError) as ei:
        svc.validate_machine(m)
    msg = str(ei.value)
    assert "unknown process" in msg and "capital_frac" in msg and "must be > 0" in msg


# ── pure: CSV parse ───────────────────────────────────────────────────────────
def _csv(rows: list[dict], header: list[str] | None = None) -> str:
    header = header or list(svc.MACHINE_REQUIRED_COLUMNS + svc.MACHINE_OPTIONAL_COLUMNS)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow([r.get(h, "") for h in header])
    return buf.getvalue()


def test_good_csv_yields_all_rows():
    caps = json.dumps({"x": 762, "y": 406, "z": 508, "axes": 3})
    text = _csv([
        {"process": "cnc_3axis", "name": "VF-2", "count": "1",
         "max_workpiece_kg": "200", "hourly_rate_usd": "75",
         "capital_frac": "0.4", "materials": "304 Stainless|steel",
         "capabilities": caps, "notes": "floor A"},
        {"process": "cnc_5axis", "name": "DMU-50",
         "capabilities": json.dumps({"axes": 5, "motion_mode": "simultaneous_5"})},
    ])
    rows, errors = svc.parse_machine_csv(text)
    assert errors == []
    assert len(rows) == 2
    a = rows[0]
    assert a["process"] == "cnc_3axis"
    assert a["count"] == 1
    assert a["max_workpiece_kg"] == 200.0
    assert a["capital_frac"] == 0.4
    assert a["materials"] == ["304 Stainless", "steel"]
    assert a["capabilities"]["x"] == 762
    # blank optional numerics normalise to None / defaults — nothing fabricated
    b = rows[1]
    assert b["max_workpiece_kg"] is None
    assert b["count"] == 1  # default


def test_mixed_csv_reports_precise_per_line_errors():
    text = _csv([
        {"process": "cnc_3axis", "name": "ok-1"},              # line 2 valid
        {"process": "", "name": "no-proc"},                    # line 3 missing process
        {"process": "cnc_3axis", "count": "two"},              # line 4 bad count
        {"process": "cnc_3axis", "capital_frac": "1.5"},       # line 5 out of range
        {"process": "cnc_3axis", "capabilities": "{not json}"},  # line 6 bad JSON
        {"process": "cnc_3axis", "materials": "unobtainium"},  # line 7 unknown material
        {"process": "cnc_3axis", "name": "ok-2"},              # line 8 valid
    ])
    rows, errors = svc.parse_machine_csv(text)
    assert [r["name"] for r in rows] == ["ok-1", "ok-2"]
    by_line = {e["line"]: e["reason"] for e in errors}
    assert set(by_line) == {3, 4, 5, 6, 7}
    assert "process is required" in by_line[3]
    assert "count not an integer" in by_line[4]
    assert "capital_frac" in by_line[5]
    assert "not valid JSON" in by_line[6]
    assert "unknown material" in by_line[7]


def test_missing_required_column_is_header_error():
    text = "name,notes\nVF-2,floor\n"  # no process column
    rows, errors = svc.parse_machine_csv(text)
    assert rows == []
    assert len(errors) == 1 and errors[0]["line"] == 1
    assert "process" in errors[0]["reason"]


def test_empty_file_reports_error():
    rows, errors = svc.parse_machine_csv("")
    assert rows == [] and errors[0]["line"] == 0
    rows, errors = svc.parse_machine_csv("   \n")
    assert rows == [] and len(errors) == 1


def test_bom_prefixed_header_tolerated():
    text = "﻿" + _csv([{"process": "cnc_3axis", "name": "VF-2"}])
    rows, errors = svc.parse_machine_csv(text)
    assert errors == [] and len(rows) == 1


def test_blank_lines_skipped():
    text = "process\ncnc_3axis\n\ncnc_5axis\n"
    rows, errors = svc.parse_machine_csv(text)
    assert [r["process"] for r in rows] == ["cnc_3axis", "cnc_5axis"]
    assert errors == []


# ── pure: add_from_catalog ────────────────────────────────────────────────────
def test_add_from_catalog_prefill():
    payload = svc.add_from_catalog("Haas VF-2")
    assert payload["process"] == "cnc_3axis"
    assert payload["capabilities"]["x"] == 762.0
    assert payload["capabilities"]["axes"] == 3
    assert payload["provenance"] == "catalog_template"
    # a prefilled catalog template validates against the same schema (sans the
    # non-model 'provenance' hint, which validate_machine ignores)
    svc.validate_machine(payload)


def test_add_from_catalog_5axis_motion_mode():
    payload = svc.add_from_catalog("DMG MORI DMU 50")
    assert payload["capabilities"]["axes"] == 5
    assert payload["capabilities"]["motion_mode"] == "simultaneous_5"


def test_add_from_catalog_unknown_raises():
    with pytest.raises(ValueError, match="no catalog machine profile"):
        svc.add_from_catalog("Nonexistent 9000")


def test_catalog_options_nonempty():
    opts = svc.catalog_options()
    assert len(opts) >= 10
    assert all("process" in o for o in opts)


# ── pure: shop-op validation ──────────────────────────────────────────────────
def test_shop_ops_valid():
    svc.validate_shop_ops({"heat_treat": True, "hip": {"dia_mm": 300, "height_mm": 600}})


def test_shop_ops_bad_value_reported():
    with pytest.raises(ValueError, match="boolean or a limits object"):
        svc.validate_shop_ops({"hip": "yes"})


def test_shop_ops_negative_limit_reported():
    with pytest.raises(ValueError, match="positive number"):
        svc.validate_shop_ops({"hip": {"dia_mm": -5}})


# ── pure: service-environment validation ──────────────────────────────────────
def test_service_environment_valid():
    pcs.validate_service_environment(
        {"max_temp_c": 200, "min_temp_c": -40, "pressure_bar": 150,
         "corrosive": True, "sour_service": True, "medium": "sour gas",
         "standard": "NACE MR0175"}
    )


def test_service_environment_none_ok():
    pcs.validate_service_environment(None)


def test_service_environment_unknown_key_rejected():
    with pytest.raises(ValueError, match="unknown service_environment field"):
        pcs.validate_service_environment({"temperature": 200})


def test_service_environment_bad_types_rejected():
    with pytest.raises(ValueError, match="max_temp_c must be a number"):
        pcs.validate_service_environment({"max_temp_c": "hot"})
    with pytest.raises(ValueError, match="corrosive must be a boolean"):
        pcs.validate_service_environment({"corrosive": "yes"})
    with pytest.raises(ValueError, match="pressure_bar must be >= 0"):
        pcs.validate_service_environment({"pressure_bar": -1})


def test_validate_context_rejects_bad_env():
    with pytest.raises(ValueError, match="unknown service_environment field"):
        pcs.validate_context({"service_environment": {"bogus": 1}})


# ── real-app routing guards (defect A) ───────────────────────────────────────
# The org inventory router mounts a bare @router.get("") LIST. When it shared the
# /api/v1/machines prefix with the pre-existing global AM reference-catalog GET in
# src/api/routes.py, Starlette's first-match-wins silently shadowed the org LIST —
# and the collision escaped review because the DB tests only mount the sub-router
# in ISOLATION. These guards compose the REAL app (main.app) so any future
# re-claim of an existing route fails loudly.
def _real_app():
    import importlib
    import main

    # Some endpoint tests install dependency overrides or reload ``main`` with
    # altered auth modes. These guards are about the composed route table itself,
    # so always inspect a fresh app instance.
    return importlib.reload(main).app


def _join_route(prefix: str, path: str) -> str:
    if not prefix:
        return path or ""
    if not path:
        return prefix
    return f"{prefix.rstrip('/')}/{path.lstrip('/')}"


def _iter_routes_with_paths(app_or_router, prefix: str = ""):
    routes = getattr(getattr(app_or_router, "router", None), "routes", None)
    if routes is None:
        routes = getattr(app_or_router, "routes", [])
    for route in routes:
        include_context = getattr(route, "include_context", None)
        original_router = getattr(route, "original_router", None)
        if include_context is not None and original_router is not None:
            child_prefix = _join_route(prefix, getattr(include_context, "prefix", ""))
            yield from _iter_routes_with_paths(original_router, child_prefix)
            continue

        route_path = getattr(route, "path", None) or getattr(route, "path_format", None)
        if route_path is not None and getattr(route, "methods", None):
            yield route, _join_route(prefix, route_path)


def _routes_for(app, path: str):
    return [r for r, route_path in _iter_routes_with_paths(app) if route_path == path]


def test_machine_inventory_list_reachable_on_real_app():
    """GET /api/v1/machine-inventory resolves to the ORG inventory LIST handler
    (src.api.machine_inventory) on the composed app — not the AM reference catalog."""
    app = _real_app()
    inv = [
        r
        for r in _routes_for(app, "/api/v1/machine-inventory")
        if "GET" in (r.methods or set())
    ]
    assert len(inv) == 1, "org inventory LIST must be registered exactly once"
    assert inv[0].endpoint.__module__ == "src.api.machine_inventory"


def test_machines_path_is_still_reference_catalog():
    """GET /api/v1/machines remains the global AM reference catalog — the org
    inventory no longer collides with (and shadows) it."""
    app = _real_app()
    ref = [
        r
        for r in _routes_for(app, "/api/v1/machines")
        if "GET" in (r.methods or set())
    ]
    assert len(ref) == 1, "reference-catalog GET /api/v1/machines must be unique"
    assert ref[0].endpoint.__module__ == "src.api.routes"


def test_no_duplicate_route_registration_in_real_app():
    """PERMANENT guard: no (method, path) pair is registered twice ANYWHERE in the
    composed app. This is the check that would have caught the machine-inventory
    collision; it must fail if any future router re-claims an existing route."""
    from collections import Counter

    app = _real_app()
    pairs: list = []
    for r, path in _iter_routes_with_paths(app):
        methods = getattr(r, "methods", None)
        if not methods or not path:
            continue
        for m in methods:
            if m in ("HEAD", "OPTIONS"):  # framework-added, never a real collision
                continue
            pairs.append((m, path))
    dupes = {k: n for k, n in Counter(pairs).items() if n > 1}
    assert not dupes, f"duplicate (method, path) route registrations: {dupes}"


# ── optional end-to-end (real Postgres) ──────────────────────────────────────
_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)


async def _seed_org_user(s, oid: str, label: str) -> int:
    from ulid import ULID
    from sqlalchemy import text

    await s.execute(
        text(
            "INSERT INTO organizations (id, name, slug, created_at) "
            "VALUES (:id, :n, :sl, now())"
        ),
        {"id": oid, "n": f"Org {label} {oid[-8:]}", "sl": f"org-{oid[-8:].lower()}"},
    )
    email = f"mach-{oid[-8:]}-{label}@example.com"
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
    await s.execute(
        text(
            "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
            "VALUES (:id, :o, :u, 'admin', now())"
        ),
        {"id": str(ULID()), "o": oid, "u": uid},
    )
    return uid


async def _cleanup(oids: list[str], uids: list[int]) -> None:
    from sqlalchemy import text
    import src.db.engine as eng

    async with eng.get_session_factory()() as s:
        await s.execute(
            text("DELETE FROM machine_instances WHERE org_id = ANY(:o)"), {"o": oids}
        )
        await s.execute(
            text("DELETE FROM shop_capabilities WHERE org_id = ANY(:o)"), {"o": oids}
        )
        await s.execute(
            text("DELETE FROM part_contexts WHERE org_id = ANY(:o)"), {"o": oids}
        )
        if uids:
            await s.execute(
                text("DELETE FROM memberships WHERE user_id = ANY(:i)"), {"i": uids}
            )
            await s.execute(text("DELETE FROM users WHERE id = ANY(:i)"), {"i": uids})
        await s.execute(
            text("DELETE FROM organizations WHERE id = ANY(:o)"), {"o": oids}
        )
        await s.commit()


def _build_app():
    from fastapi import FastAPI
    from src.api.machine_inventory import router as m_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(m_router, prefix="/api/v1/machine-inventory")
    return app


def _act_as(app, user_id: int) -> None:
    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id, api_key_id=0, key_prefix="session", role="analyst"
    )


@_requires_pg
@pytest.mark.asyncio
async def test_crud_and_org_isolation():
    from httpx import ASGITransport, AsyncClient
    from ulid import ULID
    import src.db.engine as eng

    org_a, org_b = str(ULID()), str(ULID())
    uids: list[int] = []
    async with eng.get_session_factory()() as s:
        a1 = await _seed_org_user(s, org_a, "A")
        b1 = await _seed_org_user(s, org_b, "B")
        uids += [a1, b1]
        await s.commit()

    app = _build_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            _act_as(app, a1)
            body = {
                "name": "VF-2 #1", "process": "cnc_3axis", "count": 2,
                "max_workpiece_kg": 200, "hourly_rate_usd": 75, "capital_frac": 0.4,
                "capabilities": {"x": 762, "y": 406, "z": 508, "axes": 3,
                                 "achievable_it_grade": 9},
                "materials": ["304 Stainless"],
            }
            r = await ac.post("/api/v1/machine-inventory", json=body)
            assert r.status_code == 201, r.text
            mid = r.json()["id"]
            assert r.json()["provenance"] == "user"

            # a malformed field is a 400, never coerced
            bad = dict(body)
            bad["capital_frac"] = 5
            rb = await ac.post("/api/v1/machine-inventory", json=bad)
            assert rb.status_code == 400
            assert "capital_frac" in rb.json()["detail"]

            # read back
            g = await ac.get(f"/api/v1/machine-inventory/{mid}")
            assert g.json()["count"] == 2

            # patch (partial; merged result re-validated)
            p = await ac.patch(f"/api/v1/machine-inventory/{mid}", json={"count": 3})
            assert p.status_code == 200 and p.json()["count"] == 3

            # list
            lst = (await ac.get("/api/v1/machine-inventory")).json()
            assert [m["id"] for m in lst["machines"]] == [mid]

            # cross-tenant: org B sees nothing, cannot read A's machine
            _act_as(app, b1)
            assert (await ac.get("/api/v1/machine-inventory")).json()["machines"] == []
            assert (await ac.get(f"/api/v1/machine-inventory/{mid}")).status_code == 404
            assert (
                await ac.patch(f"/api/v1/machine-inventory/{mid}", json={"count": 9})
            ).status_code == 404
            assert (
                await ac.delete(f"/api/v1/machine-inventory/{mid}")
            ).status_code == 404

            # owner deletes
            _act_as(app, a1)
            assert (await ac.delete(f"/api/v1/machine-inventory/{mid}")).status_code == 200
            assert (await ac.get("/api/v1/machine-inventory")).json()["machines"] == []
    finally:
        await _cleanup([org_a, org_b], uids)
        await eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_csv_import_and_load_org_inventory():
    from httpx import ASGITransport, AsyncClient
    from ulid import ULID
    import src.db.engine as eng

    org_a, org_b = str(ULID()), str(ULID())
    uids: list[int] = []
    async with eng.get_session_factory()() as s:
        a1 = await _seed_org_user(s, org_a, "A")
        b1 = await _seed_org_user(s, org_b, "B")
        uids += [a1, b1]
        await s.commit()

    app = _build_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            _act_as(app, a1)
            caps = json.dumps({"x": 500, "y": 500, "z": 500, "axes": 5,
                               "motion_mode": "simultaneous_5"})
            text = _csv([
                {"process": "cnc_3axis", "name": "VF-2", "count": "1",
                 "hourly_rate_usd": "75", "materials": "steel|304 Stainless",
                 "capabilities": json.dumps({"x": 762, "y": 406, "z": 508})},
                {"process": "cnc_5axis", "name": "DMU-50", "capabilities": caps},
                {"process": "bogus", "name": "bad"},  # reported, skipped
            ])
            r = await ac.post(
                "/api/v1/machine-inventory/import",
                files={"file": ("m.csv", text.encode(), "text/csv")},
            )
            assert r.status_code == 200, r.text
            summ = r.json()
            assert summ["imported"] == 2
            assert summ["skipped"] == 1
            assert summ["total"] == 3
            assert summ["errors"][0]["line"] == 4

            # hydrate to the Phase-B MachineCap contract
            async with eng.get_session_factory()() as s2:
                caps_list = await svc.load_org_inventory(s2, org_a)
            assert len(caps_list) == 2
            by_proc = {c.process: c for c in caps_list}
            vf = by_proc["cnc_3axis"]
            assert vf.name == "VF-2"
            assert vf.count == 1
            assert vf.hourly_rate_usd == 75.0
            assert vf.materials == ("steel", "304 Stainless")
            assert vf.capabilities["x"] == 762
            assert isinstance(vf.material_thickness_map, dict)
            dmu = by_proc["cnc_5axis"]
            assert dmu.capabilities["axes"] == 5

            # org B is empty -> byte-identical empty inventory
            async with eng.get_session_factory()() as s3:
                assert await svc.load_org_inventory(s3, org_b) == []
    finally:
        await _cleanup([org_a, org_b], uids)
        await eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_shop_capabilities_and_load_shop_caps():
    from httpx import ASGITransport, AsyncClient
    from ulid import ULID
    import src.db.engine as eng

    org_a = str(ULID())
    uids: list[int] = []
    async with eng.get_session_factory()() as s:
        a1 = await _seed_org_user(s, org_a, "A")
        uids.append(a1)
        await s.commit()

    app = _build_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            _act_as(app, a1)
            # unset -> empty
            assert (await ac.get("/api/v1/machine-inventory/shop-capabilities")).json()["ops"] == {}
            ops = {"heat_treat": True, "hip": {"dia_mm": 300, "height_mm": 600}}
            r = await ac.put("/api/v1/machine-inventory/shop-capabilities", json={"ops": ops})
            assert r.status_code == 200
            assert r.json()["ops"]["hip"]["dia_mm"] == 300
            # malformed op -> 400
            rb = await ac.put(
                "/api/v1/machine-inventory/shop-capabilities", json={"ops": {"hip": "yes"}}
            )
            assert rb.status_code == 400

            async with eng.get_session_factory()() as s2:
                caps = await svc.load_shop_caps(s2, org_a)
            assert caps.ops["heat_treat"] is True
    finally:
        await _cleanup([org_a], uids)
        await eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_part_context_service_environment_upsert_read_isolation():
    from ulid import ULID
    import src.db.engine as eng

    org_a, org_b = str(ULID()), str(ULID())
    uids: list[int] = []
    mesh = str(ULID())
    async with eng.get_session_factory()() as s:
        a1 = await _seed_org_user(s, org_a, "A")
        b1 = await _seed_org_user(s, org_b, "B")
        uids += [a1, b1]
        await s.commit()

    try:
        env = {"max_temp_c": 200, "pressure_bar": 150, "sour_service": True,
               "standard": "NACE MR0175"}
        async with eng.get_session_factory()() as s:
            await pcs.upsert_context(
                s, org_a, mesh, {"program": "GF", "service_environment": env},
                created_by=a1,
            )
            await s.commit()

        async with eng.get_session_factory()() as s:
            row = await pcs.get_context(s, org_a, mesh)
            assert row.service_environment["max_temp_c"] == 200
            assert row.service_environment["sour_service"] is True
            ser = pcs.serialize_context(row)
            assert ser["service_environment"]["standard"] == "NACE MR0175"
            assert ser["provenance"] == "user"
            # cross-tenant: org B never sees A's context
            assert await pcs.get_context(s, org_b, mesh) is None

        # a bad env is rejected at upsert (never coerced)
        async with eng.get_session_factory()() as s:
            with pytest.raises(ValueError, match="unknown service_environment"):
                await pcs.upsert_context(
                    s, org_a, mesh, {"service_environment": {"bogus": 1}}
                )
    finally:
        await _cleanup([org_a, org_b], uids)
        await eng.dispose_engine()
