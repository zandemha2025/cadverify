"""What a share link shows a supplier, and package links (buyer-12, buyer-13, it-22).

A record's link made from the Share dialog shows the part, its specs, the
quantity and the buyer's note; the CAD only when ticked; our cost estimate only
when turned on. A link made before these options shows no cost (fails closed).
A package is shared as one link: the request for quote part by part, each
part's CAD and the whole ZIP, until it ends or is switched off.

Skipped unless DATABASE_URL is PostgreSQL at schema head (0063+).
"""
from __future__ import annotations

import io
import os
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not _PG, reason="requires live Postgres")]

from tests.test_rfq_supplier_copy_pg import PLATE, SINGLE, _cleanup, _seed  # noqa: E402

OUR_COST = (b"193.18", b"241", b"estimates", b"recommendation", b"crossover", b"approval", b"unreviewed")


def _app():
    from fastapi import FastAPI

    from src.api.cost_decisions import public_cost_share_router, router as cost_router
    from src.api.data_control import router as data_router
    from src.api import rfq_packages
    from src.api.rfq_packages import router as rfq_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(cost_router, prefix="/api/v1/cost-decisions")
    app.include_router(rfq_router, prefix="/api/v1/rfq-packages")
    app.include_router(data_router, prefix="/api/v1")
    app.include_router(public_cost_share_router, prefix="/s")
    if hasattr(rfq_packages, "public_package_router"):
        app.include_router(rfq_packages.public_package_router, prefix="/s")
    return app


@pytest.fixture
def kept(tmp_path, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_DISABLED", "1")
    monkeypatch.setenv("SOURCE_ARTIFACT_BLOB_DIR", str(tmp_path / "kept"))
    monkeypatch.delenv("OBJECT_STORE_LOCAL_ROOT", raising=False)
    monkeypatch.delenv("OBJECT_STORE_BACKEND", raising=False)


async def _client(w):
    from httpx import ASGITransport, AsyncClient

    from src.auth.require_api_key import AuthedUser, require_api_key

    app = _app()
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=w["user"], api_key_id=0, key_prefix="session", role="analyst")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def test_a_record_link_shows_the_part_and_our_cost_only_when_turned_on(kept):
    w = await _seed()
    try:
        async with await _client(w) as client:
            # The Share dialog's defaults: 7 days, no cost, no CAD.
            made = await client.post(f"/api/v1/cost-decisions/{w['single']}/share", json={})
            assert made.status_code == 200, made.text
            link = made.json()
            ends = datetime.fromisoformat(link["share_expires_at"]) - datetime.now(timezone.utc)
            assert timedelta(days=6, hours=23) < ends <= timedelta(days=7)
            assert link["share_shows"] == {"include_cost": False, "include_cad": False, "note": None, "quantity": None}
            page = await client.get(link["share_url"])
            assert page.status_code == 200, page.text
            body = page.json()
            assert body["includes_cost_estimate"] is False and "cost" not in body and body["cad"] is None
            assert (body["name"], body["material"], body["quantity"], body["yearly_volume"]) == (
                "single.stl", "Aluminum", 1200, 1200)
            assert "Inspection: First article inspection, AS9102" in body["specs"] and body["must_hold"] == ["AS9100"]
            for word in OUR_COST:
                assert word not in page.content, word
            assert (await client.get(f"{link['share_url']}/cad")).status_code == 404

            # A supplier's link: the CAD, a note, 250 and a date of the buyer's own.
            day = (datetime.now(timezone.utc) + timedelta(days=12)).date()
            again = (await client.post(f"/api/v1/cost-decisions/{w['single']}/share", json={
                "include_cad": True, "note": "Quote by 5 Nov, FAI on the first lot.", "quantity": 250,
                "expires_on": day.isoformat()})).json()
            assert again["share_url"] != link["share_url"]  # a new link; the old one stops working
            assert (await client.get(link["share_url"])).status_code == 404
            assert again["share_expires_at"].startswith(f"{day.isoformat()}T23:59:59")
            body = (await client.get(again["share_url"])).json()
            assert (body["quantity"], body["note"]) == (250, "Quote by 5 Nov, FAI on the first lot.")
            assert body["cad"] == {"filename": "single.stl", "bytes": len(SINGLE), "url": f"{again['share_url']}/cad"}
            cad = await client.get(body["cad"]["url"])
            assert cad.status_code == 200 and cad.content == SINGLE
            assert cad.headers["content-disposition"] == 'attachment; filename="single.stl"'

            # Our cost estimate only when the buyer turns it on.
            priced = (await client.post(f"/api/v1/cost-decisions/{w['single']}/share",
                                        json={"include_cost": True})).json()
            body = (await client.get(priced["share_url"])).json()
            assert body["includes_cost_estimate"] is True and body["cost"]["estimates"][0]["unit_cost_usd"] == 193.18

            # A link made before these options shows no cost: it fails closed.
            from sqlalchemy import text

            import src.db.engine as eng

            async with eng.get_session_factory()() as s:
                await s.execute(text("UPDATE cost_decisions SET share_options = NULL WHERE ulid = :u"),
                                {"u": w["single"]})
                await s.commit()
            legacy = await client.get(priced["share_url"])
            assert legacy.status_code == 200 and "cost" not in legacy.json()
            for word in OUR_COST:
                assert word not in legacy.content, word

            # Out-of-range choices are refused in words.
            bad = await client.post(f"/api/v1/cost-decisions/{w['single']}/share", json={"expires_in_days": 14})
            assert bad.status_code == 422
            past = await client.post(f"/api/v1/cost-decisions/{w['single']}/share", json={"expires_on": "2020-01-01"})
            assert past.status_code == 422 and "has passed" in past.text
    finally:
        await _cleanup(w)


async def test_a_package_is_shared_as_one_link_until_it_is_switched_off(kept):
    w = await _seed()
    try:
        async with await _client(w) as client:
            pkg = (await client.post("/api/v1/rfq-packages", json={
                "decision_ids": [w["single"], w["rechecked"]], "title": "RFQ-1022", "supplier_name": "Midway",
                "note": "Quote due 5 Nov.", "include_raw_cad": True})).json()["package"]
            assert pkg["share_status"] is None and pkg["is_public"] is False
            made = await client.post(f"/api/v1/rfq-packages/{pkg['id']}/share", json={"expires_in_days": 30})
            assert made.status_code == 200, made.text
            link = made.json()
            assert link["share_url"].startswith("/s/pkg/") and link["share_status"] == "active"
            ends = datetime.fromisoformat(link["share_expires_at"]) - datetime.now(timezone.utc)
            assert timedelta(days=29, hours=23) < ends <= timedelta(days=30)

            page = await client.get(link["share_url"])
            assert page.status_code == 200, page.text
            view = page.json()
            assert view["kind"] == "package" and view["title"] == "RFQ-1022" and view["note"] == "Quote due 5 Nov."
            assert view["requested_by"]["name"] == "Marcus Bell" and view["includes_cost_estimate"] is False
            assert [(p["name"], p["quantity"]) for p in view["parts"]] == [("single.stl", 1200), ("plate-with-boss.step", 250)]
            for word in OUR_COST:
                assert word not in page.content, word
            plate = view["parts"][1]["cad"]
            assert plate["url"] == f"{link['share_url']}/cad/2"
            assert (await client.get(plate["url"])).content == PLATE
            zipped = await client.get(view["zip_url"])
            assert zipped.status_code == 200
            with zipfile.ZipFile(io.BytesIO(zipped.content)) as zf:
                assert zf.read("parts/02-plate-with-boss/plate-with-boss.step") == PLATE

            # It is in Share links, as a package.
            links = (await client.get("/api/v1/share-links")).json()["links"]
            mine = [x for x in links if x["kind"] == "package"]
            assert [(x["name"], x["url"], x["status"]) for x in mine] == [("RFQ-1022", link["share_url"], "active")]

            assert (await client.delete(f"/api/v1/rfq-packages/{pkg['id']}/share")).status_code == 200
            off = await client.get(link["share_url"])
            assert off.status_code == 410 and off.json()["detail"]["code"] == "share_switched_off"
            assert (await client.get(f"{link['share_url']}/download.zip")).status_code == 410
            assert (await client.get(plate["url"])).status_code == 410
    finally:
        await _cleanup(w)
