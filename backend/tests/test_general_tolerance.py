"""A general tolerance on the part's specs (buyer-06, buyer-15)."""
from __future__ import annotations


def test_a_general_tolerance_is_declared_said_and_kept_out_of_the_price():
    """buyer-06 / buyer-15: a general tolerance (ISO 2768 class or ± in the part's units) is a
    spec the supplier reads; the engine doesn't price it, so changing it marks nothing stale."""
    import types

    import pytest as _pytest

    from src.costing import part_specs as ps
    from src.services import part_context_service as pcs

    iso = ps.normalize_part_specs({"general_tolerance": {"iso2768": "m"}})
    assert iso == {"general_tolerance": {"iso2768": "m"}}
    assert ps.spec_summary(iso)[-1] == "General tolerance: ISO 2768-m (medium)"
    inch = ps.normalize_part_specs({"general_tolerance": {"plus_minus": 0.005, "unit": "in"}})
    assert ps.tolerance_text(inch) == "±0.005 in (0.127 mm)"
    for bad in ({"iso2768": "x"}, {"plus_minus": -1}, {"plus_minus": 0.1, "unit": "ft"},
                {"plus_minus": 20}, {"iso2768": "m", "plus_minus": 0.1}, "m"):
        with _pytest.raises(ValueError):
            ps.validate_part_specs({"general_tolerance": bad})
    # The engine prices with the specs minus the tolerance; the stale check ignores it.
    row = types.SimpleNamespace(part_specs={"finishes": ["anodize_ii"], "general_tolerance": {"iso2768": "f"}},
                                service_environment=None)
    assert ps.stored_specs(row) == {"finishes": ["anodize_ii"]}
    only_tol = types.SimpleNamespace(part_specs={"general_tolerance": {"iso2768": "f"}}, service_environment=None)
    assert ps.stored_specs(only_tol) is None
    other = types.SimpleNamespace(part_specs={"finishes": ["anodize_ii"], "general_tolerance": {"iso2768": "c"}},
                                  service_environment=None)
    assert pcs.changed_input_reasons(pcs.engine_inputs(row), pcs.engine_inputs(other)) == []


_PG = __import__("os").environ.get("DATABASE_URL", "").startswith("postgresql")


@__import__("pytest").mark.skipif(not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)")
@__import__("pytest").mark.asyncio
async def test_search_finds_a_part_by_its_specs_in_its_own_org_only():
    """buyer-06: "anodize", "AS9100" and a tolerance found nothing in search. GET
    /api/v1/part-context lists the org's parts with their specs in words; another org's don't show."""
    import uuid

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng
    from tests.test_part_context_api import _act_as, _build_app

    tag = uuid.uuid4().hex[:10]
    org_a, org_b = str(ULID()), str(ULID())
    async with eng.get_session_factory()() as s:
        uids = []
        for oid, label in ((org_a, "a"), (org_b, "b")):
            await s.execute(text("INSERT INTO organizations (id, name, slug, created_at) VALUES (:id, :n, :sl, now())"),
                            {"id": oid, "n": f"{label} {tag}", "sl": f"{oid[-8:].lower()}"})
            email = f"tol-{tag}-{label}@example.com"
            uid = int((await s.execute(text(
                "INSERT INTO users (email, email_lower, role, auth_provider) VALUES (:e, :el, 'analyst', 'password') RETURNING id"),
                {"e": email, "el": email.lower()})).first()[0])
            await s.execute(text("INSERT INTO memberships (id, org_id, user_id, org_role, created_at) VALUES (:id, :o, :u, 'admin', now())"),
                            {"id": str(ULID()), "o": oid, "u": uid})
            uids.append(uid)
        await s.commit()
    mesh = f"mesh-{tag}"
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        _act_as(app, uids[0])
        r = await c.put(f"/api/v1/part-context/{mesh}", json={"program": "Wellhead", "part_specs": {
            "finishes": ["anodize_ii"], "certifications": ["as9100"], "general_tolerance": {"iso2768": "m"}}})
        assert r.status_code == 200, r.text
        r = await c.get("/api/v1/part-context")
        assert r.status_code == 200, r.text
        part = next(p for p in r.json()["parts"] if p["mesh_hash"] == mesh)
        assert part["program"] == "Wellhead"
        assert "Finish: Anodize, Type II" in part["specs"]
        assert "Supplier must hold: AS9100" in part["specs"]
        assert "General tolerance: ISO 2768-m (medium)" in part["specs"]
        _act_as(app, uids[1])
        r = await c.get("/api/v1/part-context")
        assert all(p["mesh_hash"] != mesh for p in r.json()["parts"])
