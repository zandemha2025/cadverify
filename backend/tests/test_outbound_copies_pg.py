"""Share links and RFQ packages against real Postgres: the organization's machine
inventory is read and kept out of every outbound copy.

Skipped unless DATABASE_URL points at Postgres migrated to head. Seeds one org
with three machines (two of them in its saved record, one only in its
inventory), a saved should-cost from that shop (tests/test_outbound_copies.py),
a check, and share links; then reads both public links, builds an RFQ package
through the API, views it, downloads its ZIP, and reads the saved package row:
none of them carries a machine name, a rate, the words owned / in-house /
marginal / calibrat, the shop's notes or approvers. The organization's own
record view still shows all of it.
"""
from __future__ import annotations

import copy
import io
import json
import os
import uuid
import zipfile
from unittest.mock import AsyncMock

import pytest

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not _PG, reason="requires live Postgres")]

from tests.test_outbound_copies import MACHINES, assert_nothing_private, shop_result  # noqa: E402,F401

SPARE = "Spare-Bay Wexford Lathe"  # in the inventory, not in the record


def _app():
    from fastapi import FastAPI

    from src.api.cost_decisions import public_cost_share_router, router as cost_router
    from src.api.rfq_packages import router as rfq_router
    from src.api.share import public_share_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(cost_router, prefix="/api/v1/cost-decisions")
    app.include_router(rfq_router, prefix="/api/v1/rfq-packages")
    app.include_router(public_cost_share_router, prefix="/s")
    app.include_router(public_share_router, prefix="/s")
    return app


async def _seed(result_json):
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng
    from src.db.models import Analysis, CostDecision, MachineInstance
    from src.services import share_links

    tag = uuid.uuid4().hex[:10]
    org = str(ULID())
    async with eng.get_session_factory()() as s:
        await s.execute(text("INSERT INTO organizations (id, name, slug) VALUES (:id, :n, :s)"),
                        {"id": org, "n": f"Outbound {tag}", "s": f"ob-{tag}"})
        uid = int((await s.execute(text(
            "INSERT INTO users (email, email_lower, role, auth_provider, current_org_id, plan) "
            "VALUES (:e, :e, 'analyst', 'password', :o, 'pilot') RETURNING id"),
            {"e": f"ob-{tag}@example.com", "o": org})).scalar_one())
        await s.execute(text("INSERT INTO memberships (id, org_id, user_id, org_role) VALUES (:id, :o, :u, 'admin')"),
                        {"id": str(ULID()), "o": org, "u": uid})
        s.add_all([MachineInstance(org_id=org, name=name, process=proc, count=1, capabilities={})
                   for name, proc in ((MACHINES[0], "fdm"), (MACHINES[1], "cnc_3axis"), (SPARE, "cnc_turning"))])
        rj = copy.deepcopy(result_json)
        # A text naming a machine the record's own machine check doesn't name.
        rj["notes"].append(f"Turned boss: quote on the {SPARE}.")
        h = uuid.uuid4().hex * 2
        d = CostDecision(user_id=uid, org_id=org, mesh_hash=h, params_hash=f"pp-{tag}", engine_version="t",
                         filename="bracket.stl", file_type="stl", result_json=rj,
                         make_now_process=rj["decision"]["make_now_process"],
                         crossover_qty=rj["decision"]["crossover_qty"], quantities=rj["quantities"],
                         approval_status="approved", approved_by_user_id=uid,
                         approval_note="Signed off at the cell-4 review", user_disposition="inhouse",
                         disposition_note="Run it on Bay-7 overnight",
                         disposition_basis={"process": "fdm", "material": "PLA", "quantity": 10})
        a = Analysis(user_id=uid, org_id=org, mesh_hash=h, process_set_hash="p", analysis_version="v",
                     filename="bracket.stl", file_type="stl", file_size_bytes=10, verdict="issues",
                     face_count=120, duration_ms=1.0,
                     result_json={"best_process": "fdm", "geometry": {"faces": 120},
                                  "process_scores": [{"process": "cnc_turning", "score": 0.6, "verdict": "issues",
                                                      "recommended_machine": SPARE, "issues": []}]})
        s.add_all([d, a])
        await s.flush()
        share_links.open_link(d, uid, 30, f"c{uuid.uuid4().hex[:11]}", shows={"include_cost": True})
        share_links.open_link(a, uid, 30, f"a{uuid.uuid4().hex[:11]}")
        await s.commit()
        return {"org": org, "user": uid, "decision": d.ulid, "d_share": d.share_short_id,
                "a_share": a.share_short_id}


async def _cleanup(w):
    from sqlalchemy import text

    import src.db.engine as eng

    async with eng.get_session_factory()() as s:
        await s.execute(text("DELETE FROM audit_log WHERE user_id = :u OR org_id = :o"), {"u": w["user"], "o": w["org"]})
        await s.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": w["org"]})
        await s.execute(text("DELETE FROM users WHERE id = :u"), {"u": w["user"]})
        await s.commit()
    # The pool belongs to this test's event loop; the next test opens its own.
    await eng.dispose_engine()


async def test_outbound_copies_keep_the_org_inventory_out(shop_result, monkeypatch, tmp_path):  # noqa: F811
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text

    import src.db.engine as eng
    from src.auth.require_api_key import AuthedUser, require_api_key
    from src.services import rfq_package_service as rfq
    from src.services.cost_pdf_service import render_cost_html

    monkeypatch.setenv("RATE_LIMIT_DISABLED", "1")
    monkeypatch.setenv("PDF_CACHE_DIR", str(tmp_path / "pdf"))
    monkeypatch.setattr(rfq, "precompute_cost_pdf", AsyncMock(return_value=None))

    async def _html_pdf(decision, gov=None):
        return render_cost_html(decision, gov).encode()

    monkeypatch.setattr(rfq, "cached_cost_pdf", _html_pdf)
    monkeypatch.setattr(rfq, "_supplier_brief_pdf", AsyncMock(return_value=b"%PDF brief"))

    w = await _seed(shop_result)
    app = _app()
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=w["user"], api_key_id=0, key_prefix="session", role="analyst")
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            cost_link = await client.get(f"/s/cost/{w['d_share']}")
            assert cost_link.status_code == 200, cost_link.text
            assert_nothing_private(cost_link.content, "GET /s/cost")
            assert SPARE not in cost_link.text
            assert all(SPARE not in n for n in cost_link.json()["cost"]["notes"])
            check_link = await client.get(f"/s/{w['a_share']}")
            assert check_link.status_code == 200, check_link.text
            assert SPARE not in check_link.text
            assert check_link.json()["process_scores"][0]["recommended_machine"] is None

            made = await client.post("/api/v1/rfq-packages", json={
                "decision_ids": [w["decision"]], "title": "Bracket RFQ", "supplier_name": "Supplier A"})
            assert made.status_code == 201, made.text
            assert_nothing_private(made.content, "POST /rfq-packages")
            pid = made.json()["package"]["id"]
            viewed = await client.get(f"/api/v1/rfq-packages/{pid}")
            assert viewed.status_code == 200
            assert_nothing_private(viewed.content, "GET /rfq-packages/{id}")
            assert SPARE not in viewed.text
            zipped = await client.get(f"/api/v1/rfq-packages/{pid}/download.zip")
            assert zipped.status_code == 200
            with zipfile.ZipFile(io.BytesIO(zipped.content)) as zf:
                for name in zf.namelist():
                    body = zf.read(name)
                    assert_nothing_private(body, name)
                    assert SPARE.encode() not in body, name

            # The organization's own view of the record keeps everything.
            record = (await client.get(f"/api/v1/cost-decisions/{w['decision']}")).json()
            assert record["result"]["verification"]["best_machine"] == MACHINES[0]
            assert any(SPARE in n for n in record["result"]["notes"])
            assert record["disposition_note"] == "Run it on Bay-7 overnight"

        async with eng.get_session_factory()() as s:
            saved = (await s.execute(text("SELECT items_json FROM rfq_packages WHERE ulid = :p"),
                                     {"p": pid})).scalar_one()
        assert_nothing_private(json.dumps(saved), "rfq_packages.items_json")
        assert SPARE not in json.dumps(saved)
    finally:
        await _cleanup(w)
