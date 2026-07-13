"""End-to-end tests for cost-decision persistence (Phase 2 gap #3).

Covers: save-on-cost (returns id/url) + demo stays ephemeral + dedup + feature
flag; list/detail ownership (404 for others); PDF template content (cost +
crossover + assumptions + the HONEST confidence label, never "validated"); PDF
endpoint contract; JSON + CSV export; share round-trip + public sanitization
(no owner leak); compare.

Meshes are procedural (conftest fixtures); the costing layer is pure-local so no
Redis/Postgres/network is needed. WeasyPrint's system libs are unavailable in
CI, so PDF *content* is asserted at the HTML-render layer (what feeds WeasyPrint)
and the PDF *endpoint* is exercised with the renderer mocked — mirrors the
existing analysis-report PDF tests.
"""
from __future__ import annotations

import copy
import csv
import importlib
import io
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session
from src.db.models import CostDecision, UsageEvent


# ---------------------------------------------------------------------------
# Real cost-decision JSON (run the engine once)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_result_json():
    import trimesh

    from src.api.routes import _run_cost_engine
    from src.costing import EstimateOptions, estimate_decision, report_to_dict

    mesh = trimesh.creation.box(extents=(20.0, 20.0, 20.0))
    result, m, features = _run_cost_engine(mesh, "cube.stl")
    opts = EstimateOptions(
        quantities=[50, 5000],
        material_class="polymer",
        material_class_is_user=False,
        region="US",
        region_is_user=False,
        shop=None,
        rate_overrides={},
        n_cavities=1,
        n_cavities_is_user=False,
        complexity="moderate",
        complexity_is_user=False,
    )
    report = estimate_decision(result, m, features, opts)
    # JSON round-trip so the shape matches what routes/services actually read
    # back out of JSONB (object keys become strings, e.g. recommendation["50"]).
    import json

    return json.loads(json.dumps(report_to_dict(report)))


def _make_decision(
    ulid: str,
    result_json: dict,
    *,
    user_id: int = 42,
    label: str | None = None,
    share_short_id: str | None = None,
    is_public: bool = False,
) -> CostDecision:
    dec = CostDecision(
        ulid=ulid,
        user_id=user_id,
        api_key_id=1,
        mesh_hash="mesh_" + ulid,
        params_hash="params_" + ulid,
        engine_version="test",
        filename="cube.stl",
        file_type="stl",
        result_json=result_json,
        make_now_process=(result_json.get("decision") or {}).get("make_now_process"),
        crossover_qty=(result_json.get("decision") or {}).get("crossover_qty"),
        quantities=result_json.get("quantities"),
        label=label,
        is_public=is_public,
        share_short_id=share_short_id,
    )
    dec.id = 1
    dec.created_at = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    return dec


# ---------------------------------------------------------------------------
# Client / override helpers (mirror test_history_api.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    import main

    importlib.reload(main)  # conftest re-applies the auth/DB bypass on reload
    return TestClient(main.app), main.app


def _session_returning(*, scalar_one=None, all_rows=None, first=None):
    session = AsyncMock()
    session.add = MagicMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = scalar_one
    exec_result.scalars.return_value.all.return_value = all_rows or []
    exec_result.scalars.return_value.first.return_value = first
    session.execute.return_value = exec_result
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    return session


def _override(app, session, user_id=42):
    async def _fake_session():
        yield session

    def _fake_user():
        return AuthedUser(user_id=user_id, api_key_id=1, key_prefix="t", role="analyst")

    app.dependency_overrides[get_db_session] = _fake_session
    app.dependency_overrides[require_api_key] = _fake_user


# ---------------------------------------------------------------------------
# Save-on-cost
# ---------------------------------------------------------------------------


def _post_cost(client, path, name, data, **form):
    return client.post(
        path,
        files={"file": (name, data, "application/octet-stream")},
        data=form,
    )


def test_validate_cost_persists_and_returns_saved(client, cube_10mm, stl_bytes_of):
    cl, _ = client
    r = _post_cost(cl, "/api/v1/validate/cost", "cube.stl", stl_bytes_of(cube_10mm),
                   qty="50,5000", material_class="polymer", region="US")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "OK"
    # The flagship decision now leaves a durable artifact pointer.
    assert "saved" in body, "authed cost decision must persist and return {id,url}"
    assert body["saved"]["id"]
    assert body["saved"]["url"] == f"/api/v1/cost-decisions/{body['saved']['id']}"

    # Honesty preserved in the persisted dict: confidence is assumption-based,
    # never laundered into a validated/certified number.
    ci = body["estimates"][0]["confidence"]
    assert ci["validated"] is False
    assert "not yet validated" in ci["label"]


def test_validate_cost_demo_is_ephemeral(client, cube_10mm, stl_bytes_of):
    cl, _ = client
    r = _post_cost(cl, "/api/v1/validate/cost/demo", "cube.stl", stl_bytes_of(cube_10mm),
                   qty="50,5000", material_class="polymer")
    assert r.status_code == 200, r.text
    # Demo path must NOT persist (honest to its docstring).
    assert "saved" not in r.json()


def test_validate_cost_flag_off_does_not_persist(
    client, cube_10mm, stl_bytes_of, monkeypatch
):
    monkeypatch.setenv("COST_PERSIST_ENABLED", "false")
    cl, _ = client
    r = _post_cost(cl, "/api/v1/validate/cost", "cube.stl", stl_bytes_of(cube_10mm),
                   qty="50,5000", material_class="polymer")
    assert r.status_code == 200, r.text
    assert "saved" not in r.json()


def test_validate_cost_persist_failure_is_graceful_and_observable(
    client, cube_10mm, stl_bytes_of, caplog
):
    """A broken persist must still degrade gracefully (200, no `saved`) —
    but the failure must no longer be silent: a WARNING log line carrying
    the exception, plus a queryable `usage_events` row (CORE-hygiene #2)."""
    cl, app = client
    session = _session_returning()
    # First flush (the real persist attempt) blows up; second flush (our own
    # best-effort usage-event write) succeeds so we can assert it happened.
    session.flush = AsyncMock(side_effect=[RuntimeError("db exploded"), None])
    _override(app, session)

    with caplog.at_level("WARNING", logger="cadverify.cost_decision_service"):
        r = _post_cost(cl, "/api/v1/validate/cost", "cube.stl", stl_bytes_of(cube_10mm),
                       qty="50,5000", material_class="polymer", region="US")

    # Graceful degrade unchanged: still 200, still a full decision, just unsaved.
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "OK"
    assert "saved" not in body

    # Observable #1: a WARNING log line naming the exception (was silent before).
    warnings = [rec for rec in caplog.records if rec.levelname == "WARNING"]
    assert any("Cost-decision persistence failed" in rec.getMessage() for rec in warnings)
    assert any("db exploded" in rec.getMessage() for rec in warnings)

    # Observable #2: a usage_events row so the failure rate is queryable, not
    # just grep-able in logs.
    added_events = [
        c.args[0] for c in session.add.call_args_list
        if isinstance(c.args[0], UsageEvent)
    ]
    assert len(added_events) == 1
    assert added_events[0].event_type == "cost_persist_failed"
    assert added_events[0].user_id == 42

    # The session was rolled back before the usage-event write (the failed
    # flush left the transaction unusable otherwise).
    assert session.rollback.await_count >= 1


async def _run_persist(session, result_json, user_id=42):
    from src.services.cost_decision_service import persist_cost_decision

    user = AuthedUser(user_id=user_id, api_key_id=1, key_prefix="t", role="analyst")
    return await persist_cost_decision(
        session,
        user,
        mesh_hash="abc",
        params_hash="p1",
        engine_version="test",
        filename="cube.stl",
        file_type="stl",
        result_json=result_json,
    )


def test_persist_dedup_returns_existing(real_result_json):
    import asyncio

    existing = _make_decision("01EXISTING000000000000000", real_result_json)
    session = _session_returning(first=existing)  # dedup lookup finds a row
    session.add = MagicMock()

    got = asyncio.get_event_loop().run_until_complete(
        _run_persist(session, real_result_json)
    )
    assert got is existing
    session.add.assert_not_called()  # no duplicate insert


def test_persist_denormalizes_columns(real_result_json):
    import asyncio

    session = _session_returning(first=None)
    added = {}

    def _add(obj):
        added["obj"] = obj

    session.add = _add

    got = asyncio.get_event_loop().run_until_complete(
        _run_persist(session, real_result_json)
    )
    assert got.make_now_process == real_result_json["decision"]["make_now_process"]
    assert got.crossover_qty == real_result_json["decision"]["crossover_qty"]
    assert got.quantities == real_result_json["quantities"]


# ---------------------------------------------------------------------------
# List / detail (ownership)
# ---------------------------------------------------------------------------


def test_list_cost_decisions(client, real_result_json):
    cl, app = client
    rows = [_make_decision(f"01ROW{str(i).zfill(20)}", real_result_json) for i in range(3)]
    _override(app, _session_returning(all_rows=rows))

    r = cl.get("/api/v1/cost-decisions")
    assert r.status_code == 200
    body = r.json()
    assert len(body["cost_decisions"]) == 3
    item = body["cost_decisions"][0]
    assert item["make_now_process"]
    assert "crossover_qty" in item
    assert item["quantities"] == [50, 5000]
    assert item["approval_status"] == "unreviewed"
    assert item["approved_at"] is None
    assert item["is_stale"] is False
    assert item["stale_reason"] is None
    assert body["has_more"] is False


def test_list_pagination_has_more(client, real_result_json):
    cl, app = client
    rows = [_make_decision(f"01P{str(i).zfill(22)}", real_result_json) for i in range(11)]
    _override(app, _session_returning(all_rows=rows))
    r = cl.get("/api/v1/cost-decisions?limit=10")
    assert r.status_code == 200
    body = r.json()
    assert len(body["cost_decisions"]) == 10
    assert body["has_more"] is True
    assert body["next_cursor"] is not None


def test_list_requires_auth(client):
    cl, app = client
    # Remove the autouse bypass so the real require_api_key runs.
    app.dependency_overrides.pop(require_api_key, None)
    r = cl.get("/api/v1/cost-decisions", headers={})
    assert r.status_code == 401


def test_detail_owner_ok(client, real_result_json):
    cl, app = client
    dec = _make_decision("01DETAIL0000000000000000A", real_result_json, user_id=42)
    _override(app, _session_returning(scalar_one=dec), user_id=42)
    r = cl.get("/api/v1/cost-decisions/01DETAIL0000000000000000A")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "01DETAIL0000000000000000A"
    assert body["result"]["status"] == "OK"
    assert body["make_now_process"]
    assert body["approval_status"] == "unreviewed"
    assert body["is_stale"] is False


def test_approve_and_reopen_cost_decision(client, real_result_json):
    cl, app = client
    dec = _make_decision("01APPROVE000000000000000A", real_result_json, user_id=42)
    _override(app, _session_returning(scalar_one=dec), user_id=42)

    r = cl.post(
        "/api/v1/cost-decisions/01APPROVE000000000000000A/approve",
        json={"note": "Approved for RFQ packet"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["approval_status"] == "approved"
    assert body["approved_by_user_id"] == 42
    assert body["approved_at"] is not None
    assert body["approval_note"] == "Approved for RFQ packet"
    assert dec.result_json["status"] == "OK"  # signoff never mutates the artifact

    r = cl.delete("/api/v1/cost-decisions/01APPROVE000000000000000A/approve")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["approval_status"] == "unreviewed"
    assert body["approved_by_user_id"] is None
    assert body["approved_at"] is None
    assert body["approval_note"] is None


def test_approval_note_boundary_is_exact_and_overflow_is_rejected(
    client, real_result_json
):
    cl, app = client
    dec = _make_decision("01APPROVELIMIT000000000000A", real_result_json, user_id=42)
    _override(app, _session_returning(scalar_one=dec), user_id=42)
    exact_note = "L" * 1000

    accepted = cl.post(
        "/api/v1/cost-decisions/01APPROVELIMIT000000000000A/approve",
        json={"note": exact_note},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["approval_note"] == exact_note
    assert dec.approval_note == exact_note

    rejected = cl.post(
        "/api/v1/cost-decisions/01APPROVELIMIT000000000000A/approve",
        json={"note": "X" * 1001},
    )
    assert rejected.status_code == 422, rejected.text
    error = rejected.json()
    assert error["code"] == "VALIDATION_ERROR"
    assert "string_too_long" in error["message"]
    assert "('body', 'note')" in error["message"]
    assert "'max_length': 1000" in error["message"]
    assert dec.approval_note == exact_note


def test_approval_note_limit_is_documented_in_openapi(client):
    cl, _ = client
    schema = cl.get("/openapi.json").json()["components"]["schemas"]["ApprovalBody"]
    note_schema = next(
        item for item in schema["properties"]["note"]["anyOf"] if item.get("type") == "string"
    )
    assert note_schema["maxLength"] == 1000


@pytest.mark.asyncio
async def test_mark_org_decisions_stale_dispatches_update():
    from src.services import cost_decision_service as svc

    session = AsyncMock()
    result = MagicMock()
    result.rowcount = 7
    session.execute.return_value = result
    when = datetime(2026, 7, 7, 12, 0, 0, tzinfo=timezone.utc)

    count = await svc.mark_org_decisions_stale(
        session,
        "org_123",
        reason="rate_library_published:v2",
        stale_at=when,
    )

    assert count == 7
    session.execute.assert_awaited_once()


def test_detail_wrong_user_is_404(client):
    cl, app = client
    # user_id filter yields no row for another user -> 404 (never 403)
    _override(app, _session_returning(scalar_one=None), user_id=99)
    r = cl.get("/api/v1/cost-decisions/01SOMEONEELSE00000000000")
    assert r.status_code == 404


def test_detail_nonexistent_is_404(client):
    cl, app = client
    _override(app, _session_returning(scalar_one=None))
    r = cl.get("/api/v1/cost-decisions/01NOPE00000000000000000AA")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Export JSON / CSV
# ---------------------------------------------------------------------------


def test_export_json(client, real_result_json):
    cl, app = client
    dec = _make_decision("01JSON000000000000000000A", real_result_json)
    _override(app, _session_returning(scalar_one=dec))
    r = cl.get("/api/v1/cost-decisions/01JSON000000000000000000A/export.json")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert "attachment" in r.headers["content-disposition"]
    body = r.json()
    assert body["status"] == "OK"
    assert body["governance"] == {
        "approval_status": "unreviewed",
        "approved_by_user_id": None,
        "approved_at": None,
        "approval_note": None,
        "is_stale": False,
        "stale_at": None,
        "stale_reason": None,
    }


def test_export_csv_has_honest_columns(client, real_result_json):
    cl, app = client
    dec = _make_decision("01CSV0000000000000000000A", real_result_json)
    _override(app, _session_returning(scalar_one=dec))
    r = cl.get("/api/v1/cost-decisions/01CSV0000000000000000000A/export.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    text = r.text
    # Header + honesty columns present
    assert "unit_cost_usd" in text
    assert "confidence_validated" in text
    assert "confidence_label" in text
    # Assumption-based band value carried through, never "validated"
    assert "assumption-based, not yet validated" in text
    assert "False" in text  # confidence_validated column value


def test_exports_preserve_exact_approval_governance(client, real_result_json):
    cl, app = client
    dec = _make_decision("01GOVEXPORT00000000000000A", real_result_json)
    note = 'QA edit α/β — “quoted” <tag> & gears ⚙️\nLine 2: $3.80/unit'
    approved_at = datetime(2026, 7, 13, 4, 10, 5, tzinfo=timezone.utc)
    dec.approval_status = "approved"
    dec.approved_by_user_id = 42
    dec.approved_at = approved_at
    dec.approval_note = note
    _override(app, _session_returning(scalar_one=dec))

    json_response = cl.get(
        "/api/v1/cost-decisions/01GOVEXPORT00000000000000A/export.json"
    )
    assert json_response.status_code == 200
    governance = json_response.json()["governance"]
    assert governance["approval_status"] == "approved"
    assert governance["approved_by_user_id"] == 42
    assert governance["approved_at"] == approved_at.isoformat()
    assert governance["approval_note"] == note

    csv_response = cl.get(
        "/api/v1/cost-decisions/01GOVEXPORT00000000000000A/export.csv"
    )
    assert csv_response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(csv_response.text)))
    assert rows
    assert all(row["approval_status"] == "approved" for row in rows)
    assert all(row["approved_by_user_id"] == "42" for row in rows)
    assert all(row["approved_at"] == approved_at.isoformat() for row in rows)
    assert all(row["approval_note"] == note for row in rows)

    from src.services.cost_pdf_service import render_cost_html

    html = render_cost_html(dec)
    assert "Decision Governance" in html
    assert "Status:</strong> approved" in html
    assert "Signed by user:</strong> 42" in html
    assert approved_at.isoformat() in html
    assert "QA edit α/β — “quoted” &lt;tag&gt; &amp; gears ⚙️" in html
    assert "\nLine 2: $3.80/unit" in html


# ---------------------------------------------------------------------------
# PDF: endpoint contract + HONEST template content
# ---------------------------------------------------------------------------


def test_pdf_endpoint_contract(client, real_result_json, monkeypatch):
    cl, app = client
    dec = _make_decision("01PDF0000000000000000000A", real_result_json)
    _override(app, _session_returning(scalar_one=dec))

    async def _fake_pdf(ulid, user_id, session):
        return b"%PDF-1.7 fake", "cube.stl"

    from src.services import cost_pdf_service

    monkeypatch.setattr(cost_pdf_service, "get_or_generate_cost_pdf", _fake_pdf)

    r = cl.get("/api/v1/cost-decisions/01PDF0000000000000000000A/pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert "cube-cost-report.pdf" in r.headers["content-disposition"]
    assert r.content.startswith(b"%PDF")


def test_cost_pdf_template_is_honest(real_result_json):
    """The rendered cost report contains cost + crossover + assumptions and the
    HONEST confidence label — and never certifies the number as validated."""
    from src.services.cost_pdf_service import render_cost_html

    dec = _make_decision("01TPL0000000000000000000A", real_result_json)
    html = render_cost_html(dec)

    assert html and len(html) > 500
    # Required sections
    assert "Geometry" in html
    assert "Per-Process Estimates" in html
    assert "Line items" in html
    assert "Make-vs-Buy Crossover" in html
    assert "Crossover quantity" in html
    assert "Assumptions Log" in html
    # The actual crossover value renders
    assert str(real_result_json["decision"]["crossover_qty"]) in html
    # Provenance tags survive
    assert "DEFAULT" in html
    assert "MEASURED" in html
    # HONESTY: assumption band shown as such, never as a certified/validated number
    assert "assumption-based, not yet validated" in html
    assert "not a validated quote" in html
    # Guard: no "VALIDATED" certification stamp leaks in
    assert "VALIDATED" not in html


def test_cost_pdf_bbox_renders_multiply_sign(real_result_json):
    """W8-F1: the bounding box must render a literal × (U+00D7), never the raw
    HTML entity '&times;' (Jinja autoescape double-escapes entities in {{ }})."""
    from src.services.cost_pdf_service import render_cost_html

    html = render_cost_html(_make_decision("01BBOX000000000000000000A", real_result_json))
    assert "×" in html  # literal multiplication sign
    assert "&times;" not in html  # the double-escape bug is gone


@pytest.mark.asyncio
async def test_cost_pdf_content_addressed_cache(real_result_json, tmp_path, monkeypatch):
    """W9-F1: cached_cost_pdf renders ONCE then streams the stored bytes, and a
    change to the decision's honest content re-renders (content-addressed key),
    so a package download never re-renders and never serves a stale PDF."""
    import copy

    import src.services.cost_pdf_service as cps

    monkeypatch.setattr(cps, "PDF_CACHE_DIR", str(tmp_path))

    calls = {"n": 0}

    async def _fake_generate(decision, html_str=None):
        calls["n"] += 1
        return f"%PDF-render-{calls['n']}".encode()

    monkeypatch.setattr(cps, "generate_cost_pdf", _fake_generate)

    dec = _make_decision("01CACHE00000000000000000A", real_result_json)
    b1 = await cps.cached_cost_pdf(dec)
    b2 = await cps.cached_cost_pdf(dec)  # cache HIT — must not re-render
    assert calls["n"] == 1, "second call re-rendered instead of streaming cache"
    assert b1 == b2  # streamed the exact stored bytes

    # Mutate the decision's honest content → new fingerprint → fresh render
    rj2 = copy.deepcopy(real_result_json)
    rj2["estimates"][0]["unit_cost_usd"] = rj2["estimates"][0]["unit_cost_usd"] + 1.0
    dec2 = _make_decision("01CACHE00000000000000000A", rj2)
    b3 = await cps.cached_cost_pdf(dec2)
    assert calls["n"] == 2, "changed content must invalidate the cache"
    assert b3 != b1


# ---------------------------------------------------------------------------
# Share round-trip + sanitization
# ---------------------------------------------------------------------------


def test_share_create_and_revoke(client, real_result_json):
    cl, app = client
    dec = _make_decision("01SHARE00000000000000000A", real_result_json)
    _override(app, _session_returning(scalar_one=dec))

    r = cl.post("/api/v1/cost-decisions/01SHARE00000000000000000A/share")
    assert r.status_code == 200
    body = r.json()
    assert body["share_url"].startswith("/s/cost/")
    assert body["share_short_id"]
    assert dec.is_public is True

    r2 = cl.delete("/api/v1/cost-decisions/01SHARE00000000000000000A/share")
    assert r2.status_code == 200
    assert dec.is_public is False
    assert dec.share_short_id is None


def test_public_share_sanitized_no_owner_leak(client, real_result_json):
    cl, app = client
    dec = _make_decision(
        "01PUB0000000000000000000A",
        real_result_json,
        share_short_id="shortpub1234",
        is_public=True,
    )
    _override(app, _session_returning(scalar_one=dec))

    r = cl.get("/s/cost/shortpub1234")
    assert r.status_code == 200
    assert r.headers.get("x-robots-tag") == "noindex"
    body = r.json()
    # Decision content preserved + honest
    assert body["decision"]["make_now_process"]
    assert body["estimates"]
    assert body["estimates"][0]["confidence"]["validated"] is False
    # ZERO owner/user PII leaks
    for leaked in ("user_id", "api_key_id", "mesh_hash", "params_hash", "share_short_id", "id", "ulid", "email"):
        assert leaked not in body, f"public share leaked {leaked}"


def test_public_share_not_found_is_404(client):
    cl, app = client
    _override(app, _session_returning(scalar_one=None))
    r = cl.get("/s/cost/doesnotexist")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------


def _variant(base: dict, *, make_now: str, crossover, q50_cost: float, q5000_cost: float) -> dict:
    j = copy.deepcopy(base)
    j["decision"]["make_now_process"] = make_now
    j["decision"]["crossover_qty"] = crossover
    j["decision"]["recommendation"]["50"]["unit_cost_usd"] = q50_cost
    j["decision"]["recommendation"]["50"]["process"] = make_now
    j["decision"]["recommendation"]["5000"]["unit_cost_usd"] = q5000_cost
    j["decision"]["recommendation"]["5000"]["process"] = make_now
    return j


def test_compare_service_diff(real_result_json):
    from src.services.cost_decision_service import build_comparison

    ja = _variant(real_result_json, make_now="mjf", crossover=4658.0, q50_cost=4.51, q5000_cost=4.23)
    jb = _variant(real_result_json, make_now="cnc_3axis", crossover=None, q50_cost=21.11, q5000_cost=18.0)
    a = _make_decision("01CMPA000000000000000000A", ja)
    b = _make_decision("01CMPB000000000000000000A", jb)

    cmp = build_comparison(a, b)
    assert cmp["a"]["make_now_process"] == "mjf"
    assert cmp["b"]["make_now_process"] == "cnc_3axis"
    assert cmp["diff"]["make_now_process"] == ["mjf", "cnc_3axis"]
    assert cmp["diff"]["crossover_qty"] == [4658.0, None]
    # Per-qty unit cost deltas
    by_qty = {row["quantity"]: row for row in cmp["unit_cost_by_qty"]}
    assert by_qty[50]["delta_usd"] == round(21.11 - 4.51, 2)
    assert by_qty[5000]["delta_usd"] == round(18.0 - 4.23, 2)


def test_compare_endpoint(client, real_result_json):
    cl, app = client
    ja = _variant(real_result_json, make_now="mjf", crossover=4658.0, q50_cost=4.51, q5000_cost=4.23)
    jb = _variant(real_result_json, make_now="cnc_3axis", crossover=None, q50_cost=21.11, q5000_cost=18.0)
    a = _make_decision("01CEA0000000000000000000A", ja)
    b = _make_decision("01CEB0000000000000000000A", jb)

    # get_owned is called twice; return a then b.
    session = AsyncMock()
    results = []
    for row in (a, b):
        er = MagicMock()
        er.scalar_one_or_none.return_value = row
        results.append(er)
    session.execute.side_effect = results
    session.commit = AsyncMock()

    async def _fake_session():
        yield session

    def _fake_user():
        return AuthedUser(user_id=42, api_key_id=1, key_prefix="t", role="analyst")

    app.dependency_overrides[get_db_session] = _fake_session
    app.dependency_overrides[require_api_key] = _fake_user

    r = cl.get("/api/v1/cost-decisions/compare?ids=01CEA0000000000000000000A,01CEB0000000000000000000A")
    assert r.status_code == 200
    body = r.json()
    assert body["diff"]["make_now_process"] == ["mjf", "cnc_3axis"]
    assert "unit_cost_by_qty" in body


def test_compare_requires_two_ids(client, real_result_json):
    cl, app = client
    _override(app, _session_returning(scalar_one=None))
    r = cl.get("/api/v1/cost-decisions/compare?ids=onlyone")
    assert r.status_code == 400
