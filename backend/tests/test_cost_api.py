"""POST /api/v1/validate/cost — endpoint contract + invariants, no external services.

Exercises the authenticated decision endpoint end-to-end through the real
FastAPI app (via TestClient + the conftest autouse auth/DB bypass). Meshes are
procedural (conftest fixtures) so nothing binary is committed. The endpoint has
no DB session dependency and the costing layer is pure-local, so the suite needs
no Redis/Postgres/network.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    import main

    importlib.reload(main)  # conftest re-applies the auth/DB bypass on reload
    return TestClient(main.app)


def _post(client, name, data, **form):
    return client.post(
        "/api/v1/validate/cost",
        files={"file": (name, data, "application/octet-stream")},
        data=form,
    )


def _open_shell_step_bytes() -> bytes:
    """A single open planar surface STEP (non-watertight when meshed) -> G1."""
    pytest.importorskip("gmsh", reason="gmsh not installed; STEP path unavailable")
    import os
    import tempfile

    import gmsh

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("sheet")
        gmsh.model.occ.addRectangle(0, 0, 0, 50, 30)
        gmsh.model.occ.synchronize()
        fd, path = tempfile.mkstemp(suffix=".step")
        os.close(fd)
        gmsh.write(path)
    finally:
        gmsh.finalize()
    try:
        with open(path, "rb") as fh:
            return fh.read()
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def test_cost_decision_on_clean_cube(client, cube_10mm, stl_bytes_of):
    r = _post(
        client,
        "cube.stl",
        stl_bytes_of(cube_10mm),
        qty="50,5000",
        material_class="polymer",
        region="US",
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "OK"
    assert body["reason"] is None

    # Coherent decision: a headline make-now process exists and it equals the
    # low-qty (q50) recommendation pick (the spec's coherence invariant).
    dec = body["decision"]
    assert dec and dec["make_now_process"]
    q_lo = min(body["quantities"])
    assert dec["recommendation"][str(q_lo)]["process"] == dec["make_now_process"]
    assert body["estimates"], "expected costed estimates"

    # Invariant: unit_cost == Σ line_items, and every $ driver is provenance-tagged.
    for e in body["estimates"]:
        assert abs(e["unit_cost_usd"] - round(sum(e["line_items"].values()), 2)) < 0.02
        for d in e["drivers"]:
            assert d["provenance"] in ("MEASURED", "USER", "DEFAULT")
            assert d["source"]
        # R1: lead-time capacity assumption is present + inspectable, and the
        # finite-capacity pool keeps even high-qty AM lead time sub-year.
        cap = e["lead_time"]["capacity"]
        assert cap["n_machines"] >= 1 and cap["machine_hours_per_day"] > 0
        assert cap["provenance"] in ("DEFAULT", "USER")
        assert e["lead_time"]["high_days"] < 365 * 2


def test_cost_geometry_invalid_is_clean_400(client, non_watertight_box, stl_bytes_of):
    r = _post(client, "torn.stl", stl_bytes_of(non_watertight_box))
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["code"] == "GEOMETRY_INVALID"
    assert "geometry" in body  # carries the measured summary + reason
    assert body["message"]


def test_cost_requires_auth(client, cube_10mm, stl_bytes_of):
    """With the auth bypass removed, a request without a Bearer key is 401."""
    import main
    from src.auth.require_api_key import require_api_key

    main.app.dependency_overrides.pop(require_api_key, None)
    try:
        r = _post(client, "cube.stl", stl_bytes_of(cube_10mm))
        assert r.status_code == 401, r.text
        assert r.json()["code"] in ("auth_missing", "auth_invalid")
    finally:
        # Re-install the bypass so later tests in the module keep working.
        from tests.conftest import _apply_auth_bypass

        _apply_auth_bypass(main.app)


def test_cost_rejects_bad_complexity(client, cube_10mm, stl_bytes_of):
    r = _post(client, "cube.stl", stl_bytes_of(cube_10mm), complexity="bogus")
    assert r.status_code == 400
    assert "complexity" in r.json()["message"].lower()


def test_cost_rejects_bad_qty(client, cube_10mm, stl_bytes_of):
    r = _post(client, "cube.stl", stl_bytes_of(cube_10mm), qty="-5")
    assert r.status_code == 400


def test_cost_rejects_bad_extension(client):
    r = _post(client, "foo.txt", b"bad")
    assert r.status_code == 400
    assert "Unsupported" in r.json()["message"]


def test_cost_user_provenance_on_overrides(client, cube_10mm, stl_bytes_of):
    """cavities/complexity off the DEFAULT flip the assumption provenance to USER."""
    r = _post(
        client,
        "cube.stl",
        stl_bytes_of(cube_10mm),
        cavities="4",
        complexity="complex",
    )
    assert r.status_code == 200, r.text
    assumptions = {a["name"]: a for a in r.json()["assumptions"]}
    assert assumptions["n_cavities"]["provenance"] == "USER"
    assert assumptions["complexity"]["provenance"] == "USER"


# ──────────────────────────────────────────────────────────────
# F1 — per-shop calibration threaded through the cost API, and F3 — ad-hoc
# rate/driver overrides that truly re-cost on the server.
# ──────────────────────────────────────────────────────────────
def _unit_costs(body):
    return {(e["process"], e["quantity"]): e["unit_cost_usd"] for e in body["estimates"]}


def test_list_shops_returns_local_profiles(client):
    """GET /shops exposes the bindable calibration profiles (F1)."""
    r = client.get("/api/v1/shops")
    assert r.status_code == 200, r.text
    shops = r.json()["shops"]
    ids = {s["id"] for s in shops}
    assert "midwest-precision-cnc" in ids
    for s in shops:
        assert s["id"] and s["name"] and s["region"]


def test_cost_shop_calibrates_number_and_tags_shop(client, cube_10mm, stl_bytes_of):
    """Binding a shop changes the unit cost vs the generic default AND the touched
    lines/assumptions are tagged SHOP with a 'calibrated to shop' note (F1)."""
    data = stl_bytes_of(cube_10mm)
    base = _post(client, "cube.stl", data, qty="50,5000")
    cal = _post(client, "cube.stl", data, qty="50,5000", shop="Midwest Precision CNC")
    assert base.status_code == 200 and cal.status_code == 200, cal.text
    b, c = base.json(), cal.json()

    # the SHOP-calibrated number differs from the generic default on every line
    base_u, cal_u = _unit_costs(b), _unit_costs(c)
    shared = set(base_u) & set(cal_u)
    assert shared and any(abs(base_u[k] - cal_u[k]) > 1e-6 for k in shared), (
        "shop calibration must move the number"
    )

    # SHOP-tagged assumptions + drivers + note are present (the wedge IN the API)
    assert any(a["provenance"] == "SHOP" for a in c["assumptions"]), c["assumptions"]
    assert any(
        d["provenance"] == "SHOP" for e in c["estimates"] for d in e["drivers"]
    )
    assert any("Calibrated to shop" in n for n in c["notes"])

    # invariant still holds under calibration: unit_cost == Σ line_items
    for e in c["estimates"]:
        assert abs(e["unit_cost_usd"] - round(sum(e["line_items"].values()), 2)) < 0.02


def test_cost_unknown_shop_is_clean_400(client, cube_10mm, stl_bytes_of):
    r = _post(client, "cube.stl", stl_bytes_of(cube_10mm), shop="No Such Shop")
    assert r.status_code == 400, r.text
    assert "Unknown shop" in r.json()["message"]


def test_cost_overrides_recost_and_tag_user(client, cube_10mm, stl_bytes_of):
    """An ad-hoc rate override re-costs on the server and is tagged USER (F3)."""
    data = stl_bytes_of(cube_10mm)
    base = _post(client, "cube.stl", data, qty="50")
    over = _post(client, "cube.stl", data, qty="50",
                 overrides='{"labor_rate": 250}')
    assert base.status_code == 200 and over.status_code == 200, over.text
    b, o = base.json(), over.json()
    # the number actually moved (a 250 $/hr labor rate is far off the default)
    assert _unit_costs(b) != _unit_costs(o), "override must re-cost the number"
    labor = {a["name"]: a for a in o["assumptions"]}["labor_rate"]
    assert labor["provenance"] == "USER"
    assert abs(labor["value"] - 250.0) < 1e-6
    # Σ invariant holds under override too
    for e in o["estimates"]:
        assert abs(e["unit_cost_usd"] - round(sum(e["line_items"].values()), 2)) < 0.02


def test_cost_bad_overrides_json_is_400(client, cube_10mm, stl_bytes_of):
    r = _post(client, "cube.stl", stl_bytes_of(cube_10mm), overrides="not-json")
    assert r.status_code == 400, r.text


def test_cost_unknown_override_key_is_400(client, cube_10mm, stl_bytes_of):
    """An unknown override key fails fast as a clean 400, never a 500."""
    r = _post(client, "cube.stl", stl_bytes_of(cube_10mm),
              overrides='{"bogus_key": 5}')
    assert r.status_code == 400, r.text
    assert "Invalid override" in r.json()["message"]


def test_cost_demo_supports_shop(client, cube_10mm, stl_bytes_of):
    """The public (no-auth) demo cost route accepts the same shop param."""
    r = client.post(
        "/api/v1/validate/cost/demo",
        files={"file": ("cube.stl", stl_bytes_of(cube_10mm), "application/octet-stream")},
        data={"qty": "50", "shop": "midwest-precision-cnc"},
    )
    assert r.status_code == 200, r.text
    assert any("Calibrated to shop" in n for n in r.json()["notes"])


# ──────────────────────────────────────────────────────────────
# STEP ingestion (Cycle 5 §A) — gmsh-meshed STEP through the cost path.
# STEP input is synthesized by gmsh at test time (no committed binary).
# ──────────────────────────────────────────────────────────────
def test_cost_decision_on_step_box(client, box_step_bytes):
    """A real single-solid STEP (gmsh box) costs end-to-end with invariants."""
    r = _post(client, "box.step", box_step_bytes, qty="50,5000", material_class="aluminum")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "OK"
    assert body["geometry"]["watertight"] is True
    assert body["geometry"]["face_count"] > 0
    dec = body["decision"]
    assert dec and dec["make_now_process"]
    assert body["estimates"], "expected costed estimates"
    for e in body["estimates"]:
        # Invariant: unit_cost == Σ line_items.
        assert abs(e["unit_cost_usd"] - round(sum(e["line_items"].values()), 2)) < 0.02
        # Every driver carries a provenance tag.
        for d in e["drivers"]:
            assert d["provenance"] in ("MEASURED", "USER", "DEFAULT")
            assert d["source"]
    # Every assumption carries a provenance tag too.
    for a in body["assumptions"]:
        assert a["provenance"] in ("MEASURED", "USER", "DEFAULT")


def test_cost_step_non_watertight_is_clean_400(client):
    """An open-shell STEP (non-watertight) -> G1 structured 400 GEOMETRY_INVALID."""
    step = _open_shell_step_bytes()
    r = _post(client, "sheet.step", step)
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["code"] == "GEOMETRY_INVALID"
    assert "geometry" in body
    assert body["message"]


def test_cost_step_bad_magic_is_400(client):
    """STEP suffix without the ISO-10303-21 header is rejected before parsing."""
    r = _post(client, "fake.step", b"this is not a step file at all, no magic")
    assert r.status_code == 400, r.text
    assert "STEP" in r.json()["message"]


def test_cost_renamed_compound_suffix_is_400(client, box_step_bytes):
    """A renamed file (compound suffix .stp.bak -> .bak) is an unsupported type."""
    r = _post(client, "part.stp.bak", box_step_bytes)
    assert r.status_code == 400, r.text
    assert "Unsupported" in r.json()["message"]


def test_cost_zero_network_egress(client, cube_10mm, stl_bytes_of):
    """The cost request opens no NETWORK sockets (CAD-as-IP). We block AF_INET /
    AF_INET6 around the in-process request (an internet socket == egress) while
    allowing the local AF_UNIX socketpair the asyncio event loop needs for its
    self-pipe. If the endpoint tried to reach the network it would raise here."""
    import socket

    real = socket.socket
    blocked = {socket.AF_INET, socket.AF_INET6}

    def _guard(family=socket.AF_INET, *a, **k):
        if family in blocked:
            raise AssertionError("network socket opened during /validate/cost")
        return real(family, *a, **k)

    socket.socket = _guard
    try:
        r = _post(client, "cube.stl", stl_bytes_of(cube_10mm), qty="50")
    finally:
        socket.socket = real
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "OK"


# ──────────────────────────────────────────────────────────────
# Observability / reliability hardening (Cycle 5 §C) — structured logs,
# bounded work, structured errors, concurrency, zero-egress on the STEP path.
# ──────────────────────────────────────────────────────────────
def test_cost_emits_structured_log_without_cad(client, cube_10mm, stl_bytes_of, monkeypatch):
    """validate_cost emits exactly one structured 'cost_estimate' event with the
    non-PII outcome fields and NEVER the raw filename or mesh bytes (CAD-as-IP)."""
    import structlog
    from structlog.testing import capture_logs

    from src.api import routes

    # Hand the handler a fresh, unresolved logger proxy so it binds to the
    # capture_logs processor chain (the module-level proxy may already be cached
    # by an earlier test under cache_logger_on_first_use=True).
    monkeypatch.setattr(routes, "slog", structlog.get_logger("cadverify.cost"))

    secret_name = "proprietary_widget_v7.stl"
    data = stl_bytes_of(cube_10mm)
    with capture_logs() as logs:
        r = _post(client, secret_name, data, qty="50,5000", region="US")
    assert r.status_code == 200, r.text

    events = [e for e in logs if e.get("event") == "cost_estimate"]
    assert len(events) == 1, f"expected one cost_estimate event, got {logs}"
    ev = events[0]
    # Correct, non-PII payload.
    assert ev["status"] == "OK"
    assert ev["suffix"] == ".stl"
    assert ev["n_qty"] == 2
    assert ev["region"] == "US"
    assert isinstance(ev["file_sha8"], str) and len(ev["file_sha8"]) == 8
    assert "duration_ms" in ev
    # No CAD / PII leakage anywhere in any captured event.
    import json as _json

    blob = _json.dumps(logs, default=str)
    assert secret_name not in blob, "raw filename leaked into logs"
    assert data.decode("latin-1") not in blob, "raw mesh bytes leaked into logs"


def test_cost_geometry_invalid_still_logs(client, non_watertight_box, stl_bytes_of, monkeypatch):
    """The clean-refusal (400 GEOMETRY_INVALID) path also emits one outcome event."""
    import structlog
    from structlog.testing import capture_logs

    from src.api import routes

    monkeypatch.setattr(routes, "slog", structlog.get_logger("cadverify.cost"))
    with capture_logs() as logs:
        r = _post(client, "torn.stl", stl_bytes_of(non_watertight_box))
    assert r.status_code == 400, r.text
    events = [e for e in logs if e.get("event") == "cost_estimate"]
    assert len(events) == 1
    assert events[0]["status"] == "GEOMETRY_INVALID"


def test_cost_parse_timeout_is_clean_504(client, cube_10mm, stl_bytes_of, monkeypatch):
    """A parse that runs over ANALYSIS_TIMEOUT_SEC returns a structured 504
    ANALYSIS_TIMEOUT (no event-loop hang), not a 500. Covers the bounded-parse
    reliability requirement (§C.3.1) for both STL and the gmsh STEP path."""
    import time as _time

    from src.api import routes
    from src.parsers import mesh_cache

    monkeypatch.setenv("ANALYSIS_TIMEOUT_SEC", "0.1")
    # This test proves a real PARSE that overruns the budget 504s — so it must
    # start from a COLD cache. Otherwise the parsed-mesh cache (a process-wide
    # singleton another test may have warmed with this same cube) short-circuits
    # before the parse and legitimately returns 200. The single-flight warm-hit
    # shortcut makes that cache hit effective; clearing here restores the
    # cold-cache precondition the timeout assertion depends on.
    mesh_cache.get_cache().clear()

    real_parse = routes._parse_mesh

    def _slow_parse(data, filename):
        _time.sleep(1.5)  # exceed the 0.1s budget -> wait_for cancels -> 504
        return real_parse(data, filename)

    monkeypatch.setattr(routes, "_parse_mesh", _slow_parse)

    r = _post(client, "cube.stl", stl_bytes_of(cube_10mm), qty="50")
    assert r.status_code == 504, r.text
    assert r.json()["code"] == "ANALYSIS_TIMEOUT"


def test_cost_step_unavailable_is_structured_501(client, cube_10mm, stl_bytes_of, monkeypatch):
    """If gmsh is absent, the STEP branch degrades to a stable structured 501
    NOT_IMPLEMENTED (not a 500 / UNKNOWN_ERROR). Simulated by forcing the
    capability flag off so the test holds even where gmsh is installed."""
    from src.api import routes

    monkeypatch.setattr(routes, "is_step_supported", lambda: False)
    # Any bytes carrying the STEP magic header pass the magic guard and reach
    # the capability check; content is irrelevant since we 501 before parsing.
    step_magic = b"ISO-10303-21;\nHEADER;\nENDSEC;\n"
    r = _post(client, "part.step", step_magic)
    assert r.status_code == 501, r.text
    assert r.json()["code"] == "NOT_IMPLEMENTED"


def test_cost_concurrent_step_requests_both_ok(client, box_step_bytes):
    """Two simultaneous STEP costs both return 200 — _GMSH_LOCK serializes the
    process-global gmsh context across the executor threads (no segfault / no
    're-initialized' error). Skips cleanly when gmsh is unavailable."""
    from concurrent.futures import ThreadPoolExecutor

    def _do():
        return _post(client, "box.step", box_step_bytes, qty="50", material_class="aluminum")

    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(_do) for _ in range(2)]
        results = [f.result() for f in futures]

    for r in results:
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "OK"


def test_cost_step_zero_network_egress(client, box_step_bytes):
    """The STEP cost path (gmsh meshing + cost) opens no network sockets — gmsh
    meshes locally via a temp file + in-process OCC. Mirrors the STL egress guard
    (§C.3.5) for the new ingestion path."""
    import socket

    real = socket.socket
    blocked = {socket.AF_INET, socket.AF_INET6}

    def _guard(family=socket.AF_INET, *a, **k):
        if family in blocked:
            raise AssertionError("network socket opened during STEP /validate/cost")
        return real(family, *a, **k)

    socket.socket = _guard
    try:
        r = _post(client, "box.step", box_step_bytes, qty="50", material_class="aluminum")
    finally:
        socket.socket = real
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "OK"
