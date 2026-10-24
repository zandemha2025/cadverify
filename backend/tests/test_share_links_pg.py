"""Share links that end and can be switched off, against real Postgres.

Skipped unless DATABASE_URL points at Postgres migrated to head. Covers: the
7-day default and the other choices (API callers' no end date included), the
public page's 410 for an expired or switched-off link (no record data), who may
switch a link off (its maker or an org admin), re-sharing, the "my links" list,
and that another org's record is the same 404.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not _PG, reason="requires live Postgres")]

from tests.test_data_deletion_pg import _act, _app, _cleanup, _count, _world, stores  # noqa: E402,F401


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


async def test_link_lifecycle_and_who_may_switch_it_off(stores):  # noqa: F811 - the imported fixture
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text

    import src.db.engine as eng

    w = await _world(stores)
    Q = w.parts["Q"]
    app = _app()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            _act(app, w.users["owner"])
            # The seeded links are on; switch them off to start clean.
            assert (await client.delete(f"/api/v1/analyses/{Q['analysis']}/share")).status_code == 200
            assert (await client.delete(f"/api/v1/cost-decisions/{Q['decision']}/share")).status_code == 200
            off = await client.get(f"/s/{Q['a_share']}")
            assert off.status_code == 410
            assert off.json()["detail"]["code"] == "share_switched_off"
            assert set(off.json()["detail"]) == {"code", "message", "ended_at"}  # no record data
            assert (await client.get(f"/s/cost/{Q['d_share']}")).json()["detail"]["code"] == "share_switched_off"

            # Default: 7 days.
            made = await client.post(f"/api/v1/analyses/{Q['analysis']}/share")
            assert made.status_code == 200, made.text
            link = made.json()
            assert link["share_status"] == "active" and link["share_url"] != f"/s/{Q['a_share']}"
            ends = _when(link["share_expires_at"]) - datetime.now(timezone.utc)
            assert timedelta(days=6, hours=23) < ends <= timedelta(days=7)
            # Idempotent while on.
            assert (await client.post(f"/api/v1/analyses/{Q['analysis']}/share")).json()["share_url"] == link["share_url"]
            public = await client.get(link["share_url"])
            assert public.status_code == 200 and public.json()["link_expires_at"] == link["share_expires_at"]
            # The old, switched-off link is simply unknown now.
            assert (await client.get(f"/s/{Q['a_share']}")).status_code == 404

            # Explicit longer choices; anything else is refused.
            rec = await client.post(f"/api/v1/cost-decisions/{Q['decision']}/share", json={"expires_in_days": None})
            assert rec.status_code == 200 and rec.json()["share_expires_at"] is None
            assert (await client.post(f"/api/v1/analyses/{w.parts['P']['analysis']}/share",
                                      json={"expires_in_days": 45})).status_code == 422

            # A colleague (member) can't switch off the owner's link; an admin can.
            _act(app, w.users["colleague"])
            r = await client.delete(f"/api/v1/analyses/{Q['analysis']}/share")
            assert r.status_code == 403 and r.json()["detail"]["code"] == "share_not_yours"
            assert (await client.get(link["share_url"])).status_code == 200
            _act(app, w.users["admin"])
            assert (await client.delete(f"/api/v1/analyses/{Q['analysis']}/share")).status_code == 200
            assert (await client.get(link["share_url"])).json()["detail"]["code"] == "share_switched_off"
            # Switching off twice is fine.
            assert (await client.delete(f"/api/v1/analyses/{Q['analysis']}/share")).status_code == 200

            # Another org can neither share nor switch off this org's records.
            _act(app, w.users["outsider"])
            assert (await client.post(f"/api/v1/analyses/{Q['analysis']}/share")).status_code == 404
            assert (await client.delete(f"/api/v1/cost-decisions/{Q['decision']}/share")).status_code == 404

            # A 90-day link that has run out says "expired".
            _act(app, w.users["owner"])
            again = (await client.post(f"/api/v1/analyses/{Q['analysis']}/share", json={"expires_in_days": 90})).json()
            ends = _when(again["share_expires_at"]) - datetime.now(timezone.utc)
            assert timedelta(days=89, hours=23) < ends <= timedelta(days=90)
            async with eng.get_session_factory()() as s:
                await s.execute(text("UPDATE analyses SET share_expires_at = now() - interval '1 minute' WHERE ulid=:u"),
                                {"u": Q["analysis"]})
                await s.commit()
            gone = await client.get(again["share_url"])
            assert gone.status_code == 410 and gone.json()["detail"]["code"] == "share_expired"
            # An expired link isn't "public" in the record any more; sharing again makes a new one.
            renewed = (await client.post(f"/api/v1/analyses/{Q['analysis']}/share")).json()
            assert renewed["share_url"] != again["share_url"] and renewed["share_status"] == "active"
        assert await _count("SELECT count(*) FROM audit_log WHERE action='share.revoked' AND org_id=:o",
                            o=w.orgs["A"]) >= 3
    finally:
        await _cleanup(w)


async def test_my_links_list(stores):  # noqa: F811 - the imported fixture
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text

    import src.db.engine as eng

    w = await _world(stores)
    P, Q = w.parts["P"], w.parts["Q"]
    async with eng.get_session_factory()() as s:
        # A link made before end dates existed: no maker, no made-at (falls back to the record's owner).
        await s.execute(text("UPDATE cost_decisions SET share_created_by = NULL, share_created_at = NULL, "
                             "share_expires_at = now() + interval '30 days' WHERE ulid = :d"), {"d": Q["decision"]})
        await s.execute(text("UPDATE analyses SET share_revoked_at = now(), is_public = false WHERE ulid = :a"),
                        {"a": P["analysis"]})
        await s.commit()
    app = _app()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            _act(app, w.users["owner"])
            body = (await client.get("/api/v1/share-links")).json()
            assert body["scope"] == "mine" and body["is_admin"] is False
            assert body["choices"] == [1, 7, 30, 90] and body["default_days"] == 7
            by_id = {item["id"]: item for item in body["links"]}
            assert len(body["links"]) == 6  # P, C, Q: a check link and a record link each
            assert by_id[P["analysis"]]["status"] == "off" and by_id[P["analysis"]]["can_switch_off"] is False
            legacy = by_id[Q["decision"]]
            assert legacy["end_date_added"] is True and legacy["mine"] is True and legacy["can_switch_off"] is True
            assert by_id[Q["analysis"]]["name"] == Q["name"] and by_id[Q["analysis"]]["kind"] == "check"
            assert by_id[Q["decision"]]["kind"] == "record" and by_id[Q["decision"]]["url"].startswith("/s/cost/")
            assert all(item["part_key"] for item in body["links"])

            _act(app, w.users["colleague"])
            assert (await client.get("/api/v1/share-links")).json()["links"] == []
            assert (await client.get("/api/v1/share-links?scope=org")).status_code == 403

            _act(app, w.users["admin"])
            org = (await client.get("/api/v1/share-links?scope=org")).json()
            assert org["is_admin"] is True and len(org["links"]) == 6
            assert all(item["can_switch_off"] == (item["status"] == "active") for item in org["links"])
            assert {item["made_by"] for item in org["links"]} == {f"dd-{w.tag}-owner@example.com"}

            _act(app, w.users["outsider"])
            ids = {item["id"] for item in (await client.get("/api/v1/share-links?scope=org")).json()["links"]}
            assert ids == {w.parts["BP"]["analysis"], w.parts["BP"]["decision"]}
    finally:
        await _cleanup(w)
