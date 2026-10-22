"""What leaves the organization: share links and RFQ packages (``src.services.outbound``).

One record from a shop that has everything private: two named machines with
their own rates (one owns the route the engine picks, one doesn't fit), typed
rates and markup, a "Make it this way" choice on its own machine with a note,
an approval with a note, a calibration from its actuals, a band measured on its
own ground truth, and response-only blocks that name other parts. Every
outbound path (the public cost and check links, the RFQ package as built, as
viewed, as saved before this change, and every file in its ZIP) is serialized
and scanned byte by byte for the machine names, the rate values and the words
owned / in-house / marginal / calibrat. The organization's own views of the same
record still show all of it.
"""
from __future__ import annotations

import copy
import csv
import io
import json
import re
import shutil
import subprocess
import zipfile
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.auth.rate_limit import limiter
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session
from src.db.models import Analysis, CostDecision, RfqPackage
from src.services import outbound
from src.services import rfq_package_service as rfq

MACHINES = ("Bay-7 Kestrel FDM", "Cell-4 Haas Ozark")
LABOR, SLA_RATE, FDM_RATE, CNC_RATE, MARGIN = 41.73, 27.83, 17.37, 93.47, 0.1853
RATES = ("41.73", "27.83", "17.37", "93.47", "0.1853", "1.1853")
WORDS = ("owned", "in-house", "in_house", "inhouse", "marginal", "calibrat", "actuals", "sunk")
NOTES = ("Run it on Bay-7 overnight", "Signed off at the cell-4 review", "987654",
         "01CALIBSHOP", "OTHER-PART-7731", "NEIGHBOUR-5521", "Make in-house")


def assert_nothing_private(blob, where: str) -> None:
    """The byte scan every outbound payload must pass."""
    data = blob if isinstance(blob, str) else blob.decode("utf-8", "replace")
    scan = data
    for phrase in outbound.ENGINE_PHRASES:  # ScaleCAD's own words about its engine
        scan = scan.replace(phrase, "")
    low = scan.lower()
    for name in MACHINES:
        assert name.lower() not in low, f"{where}: machine name {name!r}"
    for rate in RATES:
        assert not re.search(rf"(?<![\d.]){re.escape(rate)}(?!\d)", scan), f"{where}: rate {rate}"
    for word in WORDS:
        assert word not in low, f"{where}: word {word!r} in …{low[max(0, low.find(word) - 120):low.find(word) + 60]}…"
    for note in NOTES:
        assert note.lower() not in low, f"{where}: {note!r}"


# ── the shop's record ─────────────────────────────────────────────────────────
def _shop_part():
    """A plastic bracket the shop's own printer makes cheapest at 10: the holed
    L bracket of test_in_house_preference with a thicker upright. (That bracket
    is one 5 mm gauge, so it reads as bent sheet and routes to sheet metal.)"""
    import trimesh

    plate = trimesh.creation.box(extents=[60, 40, 5])
    plate.apply_translation([0, 0, 2.5])
    upright = trimesh.creation.box(extents=[60, 8, 30])
    upright.apply_translation([0, 16, 15])
    m = trimesh.boolean.union([plate, upright], engine="manifold")
    for x in (-18, 18):
        hole = trimesh.creation.cylinder(radius=3, height=20, sections=48)
        hole.apply_translation([x, -5, 2.5])
        m = trimesh.boolean.difference([m, hole], engine="manifold")
    return m


@pytest.fixture(scope="module")
def shop_result():
    from src.costing import EstimateOptions, estimate_decision, report_to_dict
    from src.costing.makeability import MachineCap
    from src.services.calibration_service import overlay
    from tests.test_costing_model import _analyze

    inventory = (
        MachineCap(process="fdm", name=MACHINES[0], count=2, max_workpiece_kg=None,
                   hourly_rate_usd=FDM_RATE, capital_frac=0.4, materials=("PLA", "PETG"),
                   capabilities={"x": 256, "y": 256, "z": 256}),
        # Fits the envelope but isn't qualified for the plastic: named in the
        # machine check, never priced.
        MachineCap(process="cnc_3axis", name=MACHINES[1], count=1, max_workpiece_kg=200,
                   hourly_rate_usd=CNC_RATE, capital_frac=None, materials=("aluminum",),
                   capabilities={"x": 500, "y": 400, "z": 400}),
    )
    result, mesh, feats = _analyze(_shop_part())
    opts = EstimateOptions(
        quantities=[10, 100, 1000], inventory=inventory,
        rate_overrides={"labor_rate": LABOR, "machine_rate.SLA": SLA_RATE, "margin": MARGIN},
    )
    rep = json.loads(json.dumps(report_to_dict(estimate_decision(result, mesh, feats, opts)), default=str))
    rep = overlay(rep, {"sla": {"hours": 1.12, "cost": 1.07, "hours_parts": 9, "cost_parts": 11},
                        "cnc_3axis": {"hours": 0.9, "cost": 1.1, "hours_parts": 5, "cost_parts": 5}},
                  calibration_id="01CALIBSHOP", applied_at="2026-10-01T00:00:00+00:00")
    # A band measured on the shop's own ground truth (its calibration).
    for e in rep["estimates"]:
        if e["process"] == "sls":
            e["confidence"] = {**e["confidence"], "method": "measured-residual", "validated": True,
                               "n_samples": 14, "label": "",
                               "basis": "empirical 80% interval from 14 measured residual(s) for process "
                                        "'sls', sourced from REAL ground-truth quotes"}
    # Response-only blocks that name other parts, in case one was ever saved.
    rep["identity"] = {"matches": [{"declared_name": "OTHER-PART-7731.step", "mesh_hash": "f" * 64}]}
    rep["uncertainty"] = {"analogy": {"neighbours": ["NEIGHBOUR-5521.step"]}}
    rep["saved"] = {"id": "01SAVED", "url": "/api/v1/cost-decisions/01SAVED"}
    rep = json.loads(json.dumps(rep))
    # The record really carries everything the copies must leave out.
    raw = json.dumps(rep)
    assert all(m in raw for m in MACHINES) and "on a machine you own" in raw
    assert "your_actuals" in raw and "01CALIBSHOP" in raw and "41.73" in raw
    assert rep["decision"]["options"] and rep["decision"]["recommendation"]["10"]["in_house"] is True
    return rep


def _decision(result_json, **extra) -> CostDecision:
    d = CostDecision(
        id=7, ulid="01OUTBOUNDSHOP0000000000AA", org_id="org_shop", user_id=42, api_key_id=1,
        mesh_hash="m" * 64, params_hash="p" * 64, engine_version="test",
        filename="bracket.stl", file_type="stl", label="Bracket rev C",
        result_json=copy.deepcopy(result_json),
        make_now_process=result_json["decision"]["make_now_process"],
        crossover_qty=result_json["decision"]["crossover_qty"],
        quantities=result_json["quantities"],
        approval_status="approved", approved_by_user_id=987654,
        approval_note="Signed off at the cell-4 review",
        user_disposition="inhouse", disposition_note="Run it on Bay-7 overnight",
        disposition_basis={"process": "fdm", "material": "PLA", "quantity": 10},
        share_short_id="shopshare0001", is_public=True, **extra,
    )
    d.created_at = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
    d.approved_at = datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc)
    d.disposition_updated_at = datetime(2026, 10, 21, 9, 5, tzinfo=timezone.utc)
    d.disposition_updated_by_user_id = 987654
    d.share_created_by = 42
    return d


def _app(session) -> FastAPI:
    from src.api.cost_decisions import public_cost_share_router, router as cost_router
    from src.api.rfq_packages import router as rfq_router
    from src.api.share import public_share_router

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(cost_router, prefix="/api/v1/cost-decisions")
    app.include_router(public_cost_share_router, prefix="/s")
    app.include_router(public_share_router, prefix="/s")
    app.include_router(rfq_router, prefix="/api/v1/rfq-packages")

    async def _session():
        yield session

    app.dependency_overrides[get_db_session] = _session
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=42, api_key_id=1, key_prefix="t", role="analyst")
    return app


def _session_returning(row):
    session = AsyncMock()
    session.add = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    result.scalars.return_value.first.return_value = row
    result.scalars.return_value.all.return_value = [row]
    session.execute.return_value = result
    return session


# ── share links ───────────────────────────────────────────────────────────────
def test_public_cost_link_carries_nothing_of_the_shop(shop_result, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_DISABLED", "1")
    d = _decision(shop_result)
    # The most a link shows: the sharer turned "Include our cost estimate" on.
    d.share_options = {"include_cost": True}
    r = TestClient(_app(_session_returning(d))).get("/s/cost/shopshare0001")
    assert r.status_code == 200, r.text
    assert_nothing_private(r.content, "GET /s/cost")
    assert r.json()["includes_cost_estimate"] is True
    body = r.json()["cost"]
    assert "verification" not in body and "calibration" not in body
    assert {"options", "rule", "calibration_note"}.isdisjoint(body["decision"])
    # The route on the shop's printer isn't in the copy; the outside routes are,
    # with their prices, bands and lead times, and the pick is the cheapest of them.
    assert all(e["process"] != "fdm" for e in body["estimates"])
    assert {e["process"] for e in body["estimates"]} >= {"mjf", "sls", "sla", "cnc_3axis"}
    pick = body["decision"]["recommendation"]["10"]
    assert pick["process"] == body["make_now_process"] != "fdm"
    # Calibrated prices go back to the engine's: Σ line items is the price again.
    for e in body["estimates"]:
        assert "your_actuals" not in e["line_items"] and "calibration" not in e
        assert abs(sum(e["line_items"].values()) - e["unit_cost_usd"]) < 0.02, e["process"]
        assert e["confidence"]["method"] == "assumption-band" and e["confidence"]["validated"] is False
    sla = next(e for e in body["estimates"] if e["process"] == "sla" and e["quantity"] == 10)
    raw_sla = next(e for e in shop_result["estimates"] if e["process"] == "sla" and e["quantity"] == 10)
    assert sla["unit_cost_usd"] == raw_sla["calibration"]["before"]["unit_cost_usd"]
    # Typed rates and markup: tagged as the sender's, value hidden.
    labor = next(a for a in body["assumptions"] if a["name"] == "labor_rate")
    assert labor["provenance"] == "USER" and labor["value"] is None
    assert labor["source"] == outbound.HIDDEN_INPUT
    # The owner's record is unchanged.
    assert d.result_json == shop_result


def test_public_check_link_carries_nothing_of_the_shop(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_DISABLED", "1")
    a = Analysis(
        id=3, ulid="01OUTBOUNDCHECK00000000AA", org_id="org_shop", user_id=42, mesh_hash="m" * 64,
        process_set_hash="p", analysis_version="v", filename="bracket.stl", file_type="stl",
        file_size_bytes=10, verdict="issues", face_count=120, duration_ms=12.0,
        share_short_id="shopcheck0001", is_public=True,
        result_json={
            "best_process": "fdm",
            "geometry": {"faces": 120, "volume_mm3": 19200.0, "bounding_box_mm": [60, 40, 30],
                         "is_watertight": True},
            "universal_issues": [{"code": "THIN_WALL", "severity": "warning",
                                  "message": "Wall 0.6 mm thinner than 0.8 mm."}],
            "process_scores": [
                {"process": "fdm", "score": 0.9, "verdict": "issues",
                 "recommended_material": "PLA", "recommended_machine": MACHINES[0],
                 "issues": [{"code": "OVERHANG", "severity": "warning",
                             "message": f"Overhang needs support on machine '{MACHINES[0]}'."}]},
                {"process": "cnc_3axis", "score": 0.7, "verdict": "issues",
                 "recommended_material": "Aluminum 6061", "recommended_machine": "Haas VF-2",
                 "issues": [{"code": "DEEP_POCKET", "severity": "warning", "message": "Pocket 4×D deep.",
                             "fix_suggestion": "Open the pocket to 3×D."}]},
            ],
            "priority_fixes": [{"code": "THIN_WALL", "severity": "warning", "message": "Wall thin.",
                                "process": "all", "fix": "Thicken to 0.8 mm."}],
            # Blocks a check may carry that never belong on a public link.
            "verification": {"best_machine": MACHINES[1], "per_route": {}},
            "rule_pack": {"name": "Bay-7 in-house pack", "version": "3"},
            "orientation": {"key": "z+", "file_face_hash": "e" * 64},
        },
    )
    a.created_at = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
    a.share_created_by = 42
    # The organization's machine inventory (read from the database in the real
    # path; tests/test_outbound_copies_pg.py reads it for real).
    seen = {}

    async def _names(session, org_id):
        seen["org"] = org_id
        return MACHINES

    monkeypatch.setattr(outbound, "org_names", _names)
    r = TestClient(_app(_session_returning(a))).get("/s/shopcheck0001")
    assert seen["org"] == "org_shop"
    assert r.status_code == 200, r.text
    assert_nothing_private(r.content, "GET /s/{id}")
    body = r.json()
    assert {"verification", "rule_pack", "orientation", "mesh_hash"}.isdisjoint(body)
    fdm = next(p for p in body["process_scores"] if p["process"] == "fdm")
    assert fdm["recommended_machine"] is None and fdm["issues"][0]["message"] == outbound.WITHHELD
    cnc = next(p for p in body["process_scores"] if p["process"] == "cnc_3axis")
    # Findings and the generic catalog suggestion stay.
    assert cnc["recommended_machine"] == "Haas VF-2"
    assert cnc["issues"][0]["fix_suggestion"] == "Open the pocket to 3×D."
    assert body["universal_issues"][0]["message"] == "Wall 0.6 mm thinner than 0.8 mm."


# ── RFQ packages ──────────────────────────────────────────────────────────────
class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


async def _built_package(shop_result, monkeypatch, *, disposition="inhouse"):
    d = _decision(shop_result)
    if disposition == "outside":
        d.user_disposition = "outside"
        d.disposition_basis = {"process": "mjf", "material": "PA12 (Nylon 12)", "quantity": 100}
    session = AsyncMock()
    session.add = MagicMock()
    session.execute = AsyncMock(return_value=_Rows([d]))
    monkeypatch.setattr(rfq, "resolve_org", AsyncMock(return_value="org_shop"))
    monkeypatch.setattr(rfq, "_manifest_match", AsyncMock(return_value={
        "match": "normalized-stem, exact",
        "basis": {"decision_filename": "bracket.stl", "manifest_part_id": "BRK-100"},
        "part": {"id": "01MANIFEST", "part_id": "BRK-100", "description": "Mounting bracket",
                 "material_class": "polymer", "quantity": 100, "annual_volume": 1200,
                 "program": "Pump line", "region": "US", "source": "SAP export",
                 "notes": "Run it on Bay-7 overnight", "created_at": "2026-10-01T00:00:00"}}))
    monkeypatch.setattr(rfq, "_part_context", AsyncMock(return_value={
        "program": "Pump line", "parent_assembly": "PUMP-9", "units_per_parent": 2,
        "annual_volume": 1200, "service_environment": {"max_temp_c": 80, "corrosive": False},
        "provenance": "user_declared"}))
    monkeypatch.setattr(rfq, "precompute_cost_pdf", AsyncMock(return_value=b"%PDF"))
    monkeypatch.setattr(rfq, "_run_facts", AsyncMock(return_value={}))
    package = await rfq.create_package(
        session, AuthedUser(user_id=42, api_key_id=0, key_prefix="session", role="analyst"),
        [d.ulid], rfq.RfqPackageOptions(title="Bracket RFQ", supplier_name="Supplier A",
                                         note="Quote 100 and 1000, PA12 acceptable",
                                         # The most a supplier can receive: our cost estimate too.
                                         include_cost_estimate=True),
    )
    return package, d


async def _zip_files(package, monkeypatch) -> dict[str, bytes]:
    from src.services.cost_pdf_service import render_cost_html

    async def _html_pdf(decision, gov=None, length_unit="mm"):  # the report's HTML, so its words can be read
        return render_cost_html(decision, gov, length_unit).encode()

    monkeypatch.setattr(rfq, "cached_cost_pdf", _html_pdf)
    monkeypatch.setattr(rfq, "_supplier_brief_pdf",
                        AsyncMock(return_value=rfq._supplier_brief_html(package).encode()))
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_Rows([]))
    data = await rfq.build_zip(session, package)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return {n: zf.read(n) for n in zf.namelist()}


@pytest.mark.asyncio
async def test_rfq_package_as_built_viewed_and_downloaded_carries_nothing_of_the_shop(shop_result, monkeypatch):
    package, d = await _built_package(shop_result, monkeypatch)
    # As saved, as the API returns it on create and on view.
    assert_nothing_private(json.dumps(package.items_json), "items_json")
    view = rfq.serialize_package(package, include_items=True)
    assert_nothing_private(json.dumps(view), "GET /rfq-packages/{id}")
    item = view["items"][0]
    assert item["decision"]["approval_status"] == "approved"
    assert item["decision"]["requested"] is None  # "Make in-house" isn't asked of a supplier
    assert item["decision"]["make_now_process"] != "fdm"
    assert {"mesh_hash", "approved_by_user_id", "approval_note", "user_disposition",
            "disposition_note", "disposition_basis", "stale_reason"}.isdisjoint(item["decision"])
    assert item["declared_part"]["part"] == {
        "part_id": "BRK-100", "description": "Mounting bracket", "material_class": "polymer",
        "quantity": 100, "annual_volume": 1200, "program": "Pump line"}
    assert item["part_context"]["service_environment"] == {"max_temp_c": 80, "corrosive": False}
    # Every file in the ZIP, PDFs as their rendered HTML.
    files = await _zip_files(package, monkeypatch)
    assert any(n.endswith("/should-cost-report.pdf") for n in files)
    for name, body in files.items():
        assert_nothing_private(body, name)
    report = next(b for n, b in files.items() if n.endswith("/should-cost-report.pdf")).decode()
    assert "Recorded outcome" not in report and "Signed by user" not in report
    # No review state, even when the buyer sends the cost estimate.
    assert "Status:" not in report and "approved" not in report
    rows = list(csv.DictReader(io.StringIO(
        next(b for n, b in files.items() if n.endswith("/cost-drivers.csv")).decode())))
    assert rows and set(rows[0]) >= {"process", "unit_cost_usd"}
    assert "approval_status" not in rows[0]
    assert "approval_note" not in rows[0] and "user_disposition" not in rows[0]
    brief = files["supplier-brief.md"].decode()
    assert "Quote 100 and 1000, PA12 acceptable" in brief  # the buyer's note to the supplier
    # The live record is untouched by building the copy.
    assert d.result_json == shop_result and d.disposition_note == "Run it on Bay-7 overnight"


@pytest.mark.asyncio
async def test_rfq_package_names_the_route_bought_outside(shop_result, monkeypatch):
    package, _ = await _built_package(shop_result, monkeypatch, disposition="outside")
    item = rfq.serialize_package(package, include_items=True)["items"][0]
    want = {"process": "mjf", "material": "PA12 (Nylon 12)", "quantity": 100}
    assert item["decision"]["requested"] == want
    files = await _zip_files(package, monkeypatch)
    line = next(csv.DictReader(io.StringIO(files["line-items.csv"].decode())))
    assert (line["process"], line["quantity"], line["material"]) == ("Nylon powder printing (MJF)", "100", "PA12 (Nylon 12)")
    report = next(b for n, b in files.items() if n.endswith("/should-cost-report.pdf")).decode()
    # The report names the process in plain words (the shared process names).
    from src.analysis.process_names import process_label

    assert f"Requested:</strong> {process_label('mjf')} / PA12 (Nylon 12) / quantity 100" in report
    for name, body in files.items():
        assert_nothing_private(body, name)


@pytest.mark.asyncio
async def test_a_package_saved_before_supplier_copies_is_cleaned_on_every_read(shop_result, monkeypatch):
    d = _decision(shop_result)
    gov = {
        "approval_status": "approved", "approved_by_user_id": 987654,
        "approved_at": "2026-10-21T09:00:00+00:00", "approval_note": "Signed off at the cell-4 review",
        "user_disposition": "inhouse", "user_disposition_label": "Make in-house",
        "disposition_note": "Run it on Bay-7 overnight",
        "disposition_basis": {"process": "fdm", "material": "PLA", "quantity": 10},
        "disposition_updated_at": "2026-10-21T09:05:00+00:00", "disposition_updated_by_user_id": 987654,
        "is_stale": True, "stale_at": "2026-10-22T00:00:00+00:00", "stale_reason": "machine_inventory_changed",
    }
    legacy_item = {  # the shape the service saved before outbound copies
        "decision": {"id": d.ulid, "filename": d.filename, "file_type": "stl", "label": d.label,
                     "engine_version": "test", "mesh_hash": d.mesh_hash, "created_at": d.created_at.isoformat(),
                     "make_now_process": "fdm", "crossover_qty": 1330.0, "quantities": [10, 100, 1000],
                     "unvalidated_confidence": True, **gov},
        "cost_decision": shop_result,
        "declared_part": None, "part_context": None,
        "raw_cad": {"included": False, "reason": "not_requested"},
    }
    package = RfqPackage(
        ulid="01RFQLEGACY000000000000AA", org_id="org_shop", user_id=42, title="Old RFQ",
        supplier_name="Supplier A", item_count=1, approved_count=1, stale_count=1, unvalidated_count=1,
        raw_cad_included=False, live_supplier_send=False, items_json=[legacy_item],
        warnings_json=[{"code": "decision_stale", "decision_id": d.ulid,
                        "message": "bracket.stl predates governed assumption changes."}],
        metadata_json={"note": None}, created_at=datetime.now(timezone.utc),
    )
    view = rfq.serialize_package(package, include_items=True)
    assert_nothing_private(json.dumps(view), "legacy view")
    assert view["items"][0]["decision"]["is_stale"] is True
    for name, body in (await _zip_files(package, monkeypatch)).items():
        assert_nothing_private(body, f"legacy {name}")
    # Cleaning is idempotent: a copy read again is the same copy.
    again = outbound.rfq_item(view["items"][0])
    assert again == view["items"][0]


def test_supplier_report_pdf_text_carries_nothing_of_the_shop(shop_result):
    if not shutil.which("pdftotext"):
        pytest.skip("pdftotext is required to read the rendered PDF")
    from src.services.cost_pdf_service import _render_cost_pdf_sync, render_cost_html

    item = outbound.rfq_item({"decision": {"id": "01PDF", "filename": "bracket.stl", "file_type": "stl",
                                           "created_at": "2026-10-20T09:00:00+00:00",
                                           "approval_status": "approved"},
                              "cost_decision": shop_result})
    snap = rfq._snapshot_decision(item)
    html = render_cost_html(snap, outbound.rfq_governance(item["decision"]))
    pdf = _render_cost_pdf_sync(snap, html)
    text = subprocess.run(["pdftotext", "-", "-"], input=pdf, capture_output=True, check=True).stdout
    assert b"Cost estimate" in text and b"(MJF)" in text  # processes by name, not engine id
    assert b"negotiation" not in text
    assert_nothing_private(text.replace(b"\n", b" "), "should-cost-report.pdf text")


# ── the sanitizer's rules, one at a time ──────────────────────────────────────
def test_texts_that_name_the_shop_are_withheld_and_generic_ones_stay():
    t = outbound._Terms(["Spare-Bay Wexford Lathe"])
    assert outbound.text("post-process 0.5 hr × $35/hr × region-labor ×1") is not None
    assert outbound.text("post-process 0.5 hr × $41.73/hr × region-labor ×1") is None  # not a card rate
    assert outbound.text("CAD volume 15 cm³ × PLA density 1.24 g/cm³ × $25/kg") is not None
    assert outbound.text("× $25/kg (material-DB unit price) × 1.1853 markup") is None
    assert outbound.text("finished on the Spare-Bay Wexford Lathe", t) is None
    assert outbound.text("loaded shop-floor labor [shop: Acme Machining]") == "loaded shop-floor labor"
    assert outbound.text("±50% band; moved with your calibration (+7%)") == "±50% band"
    assert outbound.text("costed at MARGINAL rate") is None
    assert outbound.text("made in your building, so no shipping") is None
    # ScaleCAD's own wording about its engine is not the shop's.
    generic = ("Note: the cost-cheapest make-as-is pick at low qty is fdm, but the geometry-recommended "
               "process is mjf — both are costed above; pick on intent, not just the marginal $.")
    assert outbound.text(generic) == generic
    assert outbound.text("Validate against actual quotes before making a sourcing commitment.") is not None


def test_a_governed_library_rate_tagged_default_is_still_the_shops():
    from src.costing.rates import RATE_CARD_V0

    card = RATE_CARD_V0["global"]["labor_rate"]
    rec = {"assumptions": [
        {"name": "labor_rate", "value": card, "unit": "$/hr", "provenance": "DEFAULT", "source": "loaded labor"},
        {"name": "margin", "value": 0.22, "unit": "frac", "provenance": "DEFAULT", "source": "markup on cost"},
        {"name": "machine_capital_frac", "value": 0.35, "unit": "frac", "provenance": "DEFAULT",
         "source": "capital share removed for OWNED, in-house processes (fdm)"},
    ]}
    out = {a["name"]: a for a in outbound.cost_record(rec)["assumptions"]}
    assert out["labor_rate"]["value"] == card  # ScaleCAD's own default stays
    assert out["margin"]["value"] is None and out["margin"]["source"] == outbound.HIDDEN_INPUT
    assert "machine_capital_frac" not in out  # exists only when the shop owns machines


def test_generic_engine_output_leaves_whole():
    """A record with nothing of a shop in it loses nothing: no text withheld, no
    route dropped, the engine's decision as is. Guards the allowlists too: every
    driver, line item and assumption the engine writes is on them."""
    import trimesh

    from src.costing import EstimateOptions, estimate_decision, report_to_dict
    from tests.test_costing_model import _analyze
    from tests.test_in_house_preference import _bracket

    for mesh, material in ((_bracket(), "polymer"), (trimesh.creation.box(extents=[40, 30, 25]), "aluminum"),
                           (trimesh.creation.cylinder(radius=10, height=80, sections=64), "titanium")):
        result, m, feats = _analyze(mesh)
        rep = json.loads(json.dumps(report_to_dict(estimate_decision(
            result, m, feats, EstimateOptions(quantities=[1, 100, 10000], material_class=material,
                                              material_class_is_user=True))), default=str))
        for e in rep["estimates"]:
            assert {d["name"] for d in e["drivers"]} <= outbound.DRIVER_NAMES
            assert set(e["line_items"]) <= outbound.LINE_ITEMS
        assert {a["name"] for a in rep["assumptions"]} <= outbound.ASSUMPTION_NAMES
        out = outbound.cost_record(rep)
        blob = json.dumps(out)
        assert outbound.WITHHELD not in blob and outbound.HIDDEN_INPUT not in blob, material
        assert len(out["estimates"]) == len(rep["estimates"]) and out["notes"] == rep["notes"]
        assert out["decision"]["recommendation"] == {
            q: {k: r[k] for k in r} for q, r in rep["decision"]["recommendation"].items()}
        for k in ("make_now_process", "crossover_qty", "note", "tooling_process"):
            assert out["decision"][k] == rep["decision"][k], k
        assert outbound.cost_record(out) == out  # idempotent


# ── the organization's own views keep everything ──────────────────────────────
def test_in_org_views_still_show_everything(shop_result, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_DISABLED", "1")
    d = _decision(shop_result)
    cl = TestClient(_app(_session_returning(d)))
    record = cl.get(f"/api/v1/cost-decisions/{d.ulid}")
    assert record.status_code == 200, record.text
    body = record.json()
    assert body["result"] == shop_result and body["mesh_hash"] == d.mesh_hash
    assert body["result"]["verification"]["best_machine"] == MACHINES[0]
    assert body["result"]["decision"]["options"] and body["disposition_note"] == "Run it on Bay-7 overnight"
    exported = cl.get(f"/api/v1/cost-decisions/{d.ulid}/export.json").text
    for private in (*MACHINES, "on a machine you own", "your_actuals", "01CALIBSHOP", "41.73",
                    "Run it on Bay-7 overnight"):
        assert private in exported, private
    table = cl.get(f"/api/v1/cost-decisions/{d.ulid}/export.csv").text
    row = next(csv.DictReader(io.StringIO(table)))
    assert row["approval_note"] == "Signed off at the cell-4 review" and row["user_disposition"] == "inhouse"
    assert any(r["process"] == "fdm" for r in csv.DictReader(io.StringIO(table)))
    from src.services.cost_pdf_service import render_cost_html

    report = render_cost_html(d)
    assert MACHINES[0] in report and "Run it on Bay-7 overnight" in report and "Recorded outcome" in report


def test_share_and_package_paths_all_go_through_the_one_sanitizer():
    """Every outbound serializer is ``outbound``'s, so no path keeps its own deny list."""
    from src.services import cost_decision_service, share_service

    rec = SimpleNamespace(filename="x.stl", file_type="stl", label=None, created_at=None, quantities=[1],
                          verdict="pass", face_count=1, duration_ms=1.0,
                          result_json={"verification": {"best_machine": "M"}, "decision": None})
    assert cost_decision_service.sanitize_for_share(rec) == outbound.cost_share(rec)
    assert share_service.sanitize_analysis_for_share(rec) == outbound.check_share(rec)
    item = {"decision": {"id": "1", "filename": "x.stl"}, "cost_decision": rec.result_json}
    pkg = RfqPackage(ulid="P", org_id="o", user_id=1, title="t", items_json=[item], warnings_json=[],
                     metadata_json={}, item_count=1, approved_count=0, stale_count=0, unvalidated_count=0,
                     raw_cad_included=False, live_supplier_send=False)
    assert rfq.serialize_package(pkg, include_items=True)["items"] == [outbound.rfq_item(item)]
