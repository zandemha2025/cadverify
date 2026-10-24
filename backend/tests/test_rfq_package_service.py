from __future__ import annotations

import csv
import io
import json
import shutil
import subprocess
import zipfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.auth.require_api_key import AuthedUser
from src.db.models import CostDecision, RfqPackage
from src.services import rfq_package_service as svc


class _Result:
    def __init__(self, *, rows=None, first=None):
        self._rows = rows or []
        self._first = first

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._first


def _decision(**overrides) -> CostDecision:
    now = datetime.now(timezone.utc)
    d = CostDecision(
        id=overrides.get("id", 1),
        ulid=overrides.get("ulid", "01RFQDECISION"),
        org_id=overrides.get("org_id", "org_1"),
        user_id=overrides.get("user_id", 11),
        mesh_hash=overrides.get("mesh_hash", "meshhash"),
        params_hash="paramhash",
        engine_version="test",
        filename=overrides.get("filename", "VALVE-100.step"),
        file_type="step",
        result_json=overrides.get(
            "result_json",
            {
                "estimates": [
                    {
                        "process": "cnc",
                        "material": "steel",
                        "quantity": 100,
                        "unit_cost_usd": 12.34,
                        "confidence": {"validated": False, "label": "assumption"},
                    }
                ],
                "decision": {"make_now_process": "cnc"},
            },
        ),
        make_now_process="cnc",
        crossover_qty=1000,
        quantities=[100],
        label=None,
        approval_status=overrides.get("approval_status", "unreviewed"),
        created_at=overrides.get("created_at", now),
    )
    d.stale_at = overrides.get("stale_at")
    d.stale_reason = overrides.get("stale_reason")
    d.approved_at = overrides.get("approved_at")
    d.approved_by_user_id = overrides.get("approved_by_user_id")
    d.approval_note = overrides.get("approval_note")
    d.user_disposition = overrides.get("user_disposition")
    d.disposition_note = overrides.get("disposition_note")
    d.disposition_updated_at = overrides.get("disposition_updated_at")
    d.disposition_updated_by_user_id = overrides.get(
        "disposition_updated_by_user_id"
    )
    return d


def test_line_items_csv_neutralizes_customer_controlled_formula_cells():
    from src.services.rfq_package_service import _line_items_csv

    csv_text = _line_items_csv(
        [
            {
                "decision": {"id": "01SAFE", "filename": "=HYPERLINK(\"https://attacker.invalid\")"},
                "request": {"name": "=HYPERLINK(\"https://attacker.invalid\")", "part_number": "+SUM(1,1)",
                            "description": " @RUN()", "quantity": 10},
                "raw_cad": {"included": True, "filename": "part.step"},
            }
        ]
    )
    row = next(csv.DictReader(io.StringIO(csv_text)))
    assert row["part"].startswith("'=")
    assert row["part_number"].startswith("'+")
    assert row["description"].startswith("' @")


@pytest.mark.asyncio
async def test_create_package_snapshots_warnings_without_raw_cad(monkeypatch):
    decision = _decision(stale_at=datetime.now(timezone.utc) - timedelta(days=1))
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock(return_value=_Result(rows=[decision]))

    monkeypatch.setattr(svc, "resolve_org", AsyncMock(return_value="org_1"))
    monkeypatch.setattr(
        svc,
        "_manifest_match",
        AsyncMock(return_value={"match": "normalized-stem, exact", "part": {"part_id": "VALVE-100"}}),
    )
    monkeypatch.setattr(svc, "_part_context", AsyncMock(return_value={"program": "Refinery"}))
    monkeypatch.setattr(
        svc,
        "_raw_cad_payload",
        AsyncMock(return_value=(None, None, {"included": False, "reason": "not_requested"})),
    )
    # Cache-warm at create is exercised in the integration/perf test; keep this
    # unit test off the WeasyPrint render path.
    monkeypatch.setattr(svc, "precompute_cost_pdf", AsyncMock(return_value=b"%PDF"))

    package = await svc.create_package(
        session,
        AuthedUser(user_id=11, api_key_id=0, key_prefix="session", role="analyst"),
        ["01RFQDECISION"],
        svc.RfqPackageOptions(title="Pump RFQ", supplier_name="Supplier A"),
    )

    assert package.title == "Pump RFQ"
    assert package.item_count == 1
    assert package.approved_count == 0
    assert package.stale_count == 1
    assert package.unvalidated_count == 1
    assert package.raw_cad_included is False
    assert package.live_supplier_send is False
    assert package.items_json[0]["declared_part"]["part"]["part_id"] == "VALVE-100"
    # For the buyer in ScaleCAD; none of them is in the supplier's files. Without
    # the cost estimate there is no confidence to warn about.
    assert {w["code"] for w in package.warnings_json} == {
        "decision_unapproved",
        "decision_stale",
        "quantity_missing",
    }
    assert package.metadata_json["include_cost_estimate"] is False
    session.add.assert_called_once_with(package)
    assert session.flush.await_count == 1


@pytest.mark.asyncio
async def test_raw_cad_payload_only_reads_same_org_completed_batch_blob(tmp_path, monkeypatch):
    blob_root = tmp_path / "blobs"
    file_path = blob_root / "batch-1" / "VALVE-100.step"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"STEPDATA")
    monkeypatch.setenv("BATCH_BLOB_DIR", str(blob_root))

    decision = _decision(id=99, org_id="org_1")
    item = SimpleNamespace(filename="VALVE-100.step")
    batch = SimpleNamespace(ulid="batch-1")
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_Result(first=(item, batch)))

    filename, data, meta = await svc._raw_cad_payload(session, decision, True)

    assert filename == "VALVE-100.step"
    assert data == b"STEPDATA"
    assert meta["included"] is True
    assert meta["source"] == "same_org_batch_zip_blob"


@pytest.mark.asyncio
async def test_build_zip_contains_honest_package_files(monkeypatch):
    decision = _decision()
    disposition_at = datetime.now(timezone.utc)
    item = {
        "decision": {
            "id": decision.ulid,
            "filename": decision.filename,
            "approval_status": "approved",
            "approved_by_user_id": 11,
            "approved_at": "2026-07-13T05:00:00+00:00",
            "approval_note": "Reviewed against governed rates",
            "user_disposition": "make_in_house",
            "user_disposition_label": "Make in-house",
            "disposition_note": "Release to cell 4",
            "disposition_basis": {"process": "cnc", "material": "steel", "quantity": 100},
            "disposition_updated_at": disposition_at.isoformat(),
            "disposition_updated_by_user_id": 12,
            "is_stale": False,
            "unvalidated_confidence": True,
            "make_now_process": "cnc",
            "crossover_qty": 1000,
        },
        "cost_decision": decision.result_json,
        "declared_part": {"match": "normalized-stem, exact", "part": {"part_id": "VALVE-100"}},
        "part_context": {"program": "Refinery"},
        "raw_cad": {"included": False, "reason": "not_requested"},
    }
    package = RfqPackage(
        ulid="01RFQPACKAGE",
        org_id="org_1",
        user_id=11,
        title="Pump RFQ",
        supplier_name="Supplier A",
        item_count=1,
        approved_count=1,
        stale_count=0,
        unvalidated_count=1,
        raw_cad_included=False,
        live_supplier_send=False,
        items_json=[item],
        warnings_json=[{"code": "confidence_unvalidated", "message": "assumption band"}],
        metadata_json={"note": "Send for budgetary review", "include_cost_estimate": True},
        created_at=datetime.now(timezone.utc),
    )
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_Result(first=decision))
    monkeypatch.setattr(svc, "cached_cost_pdf", AsyncMock(return_value=b"%PDF-test"))
    monkeypatch.setattr(
        svc, "_supplier_brief_pdf", AsyncMock(return_value=b"%PDF-supplier-brief")
    )

    data = await svc.build_zip(session, package)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
        assert names == {
            "package_manifest.json", "supplier-brief.md", "supplier-brief.pdf", "line-items.csv",
            "parts/01-VALVE-100/cost-decision.json", "parts/01-VALVE-100/cost-drivers.csv",
            "parts/01-VALVE-100/should-cost-report.pdf",
        }
        manifest = json.loads(zf.read("package_manifest.json"))
        assert manifest["includes_cost_estimate"] is True
        assert manifest["parts"][0]["cad_file"] is None
        assert "supplier-brief.pdf" in manifest["files"]
        assert zf.read("supplier-brief.pdf") == b"%PDF-supplier-brief"
        brief = zf.read("supplier-brief.md").decode()
        assert "Request for quote." in brief and "- CAD: not in this package" in brief
        assert "Send for budgetary review" in brief
        drivers_name = next(name for name in names if name.endswith("/cost-drivers.csv"))
        driver_rows = list(
            csv.DictReader(io.StringIO(zf.read(drivers_name).decode("utf-8")))
        )
        assert len(driver_rows) == 1
        # No review state travels, even with the cost estimate. A package saved
        # with the full governance (before supplier copies) is cleaned:
        # approvers, the recorded in-house outcome and internal notes stay.
        assert "approval_status" not in driver_rows[0]
        for internal in ("approved_by_user_id", "approved_at", "approval_note", "user_disposition",
                         "user_disposition_label", "disposition_basis", "disposition_note",
                         "disposition_updated_at", "disposition_updated_by_user_id"):
            assert internal not in driver_rows[0]
        everything = b"".join(zf.read(n) for n in names if not n.endswith(".pdf"))
        for private in (b"Reviewed against governed rates", b"Release to cell 4", b"make_in_house",
                        b"Make in-house", b"disposition", b"approved", b"approval"):
            assert private not in everything, private

    # The report states no review status (the package was approved when captured).
    pdf_decision, pdf_gov = svc.cached_cost_pdf.call_args.args
    assert pdf_decision.approval_status is None and pdf_gov["approval_status"] is None
    assert pdf_gov["is_stale"] is False
    assert pdf_decision.approval_note is None and pdf_decision.disposition_note is None
    assert pdf_decision.user_disposition is None and pdf_decision.disposition_basis is None
    assert pdf_gov["requested"] is None  # "Make in-house" is not a request to a supplier
    from src.services import outbound

    assert pdf_decision.result_json == outbound.cost_record(item["cost_decision"])
    assert decision.approval_status == "unreviewed", "rendering must not mutate the live row"

    # The package stays downloadable after the record is removed.
    session.execute.return_value = _Result(first=None)
    with zipfile.ZipFile(io.BytesIO(await svc.build_zip(session, package))) as zf:
        assert any(name.endswith("/should-cost-report.pdf") for name in zf.namelist())
    # Without the cost estimate none of it is there.
    package.metadata_json = {"note": "Send for budgetary review"}
    with zipfile.ZipFile(io.BytesIO(await svc.build_zip(session, package))) as zf:
        assert sorted(zf.namelist()) == ["line-items.csv", "package_manifest.json", "supplier-brief.md",
                                         "supplier-brief.pdf"]


def _brief_package(**meta) -> RfqPackage:
    item = {
        "decision": {"id": "01X", "filename": "VALVE-B <rev 2>.step", "approval_status": "approved"},
        "cost_decision": {},
        "request": {"name": "VALVE-B <rev 2>.step", "part_number": "VB-2", "material": "Stainless steel",
                    "quantity": 40, "yearly_volume": 160},
        "part_context": None,
        "raw_cad": {"included": True, "filename": "VALVE-B_rev_2.step"},
    }
    return RfqPackage(
        ulid="01RFQPACKAGEHTML", org_id="org_1", user_id=11, title="Pump <script>alert(1)</script>",
        supplier_name="Supplier & Sons", item_count=1, approved_count=1, stale_count=1, unvalidated_count=1,
        raw_cad_included=True, live_supplier_send=False, items_json=[item],
        warnings_json=[{"code": "decision_stale", "message": "VALVE-A.step is stale."}],
        metadata_json={"note": "Quote against A & B", "reply_by": "2026-11-05",
                       "requested_by": {"name": "Ann Buyer", "company": "Acme & Co", "email": "ann@acme.example"},
                       **meta},
        created_at=datetime(2026, 10, 22, tzinfo=timezone.utc),
    )


def test_supplier_brief_html_is_a_request_for_quote_and_escapes_text():
    package = _brief_package()
    rendered = svc._supplier_brief_html(package, package.items_json)

    assert "Pump &lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "Supplier &amp; Sons" in rendered
    assert "Quote against A &amp; B" in rendered
    assert "Ann Buyer, Acme &amp; Co, ann@acme.example" in rendered
    assert "<th>Reply by</th><td>5 Nov 2026</td>" in rendered
    assert "VALVE-B &lt;rev 2&gt;.step" in rendered
    for line in ("Part number: VB-2", "Material: Stainless steel", "Quantity: 40", "Yearly volume: 160 a year",
                 "CAD: parts/01-VALVE-B_rev_2/VALVE-B_rev_2.step"):
        assert f"<li>{line}</li>" in rendered, line
    assert "<script>" not in rendered
    # The buyer's warnings and the record's review state are not the supplier's business.
    for internal in ("stale", "Approved", "approved", "Unvalidated", "Decisions included", "Live supplier send"):
        assert internal not in rendered, internal


def test_supplier_brief_pdf_text_reads_as_a_request_for_quote(tmp_path):
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        pytest.skip("pdftotext is required for RFQ supplier-brief PDF coverage")
    package = _brief_package()
    pdf_path = tmp_path / "supplier-brief.pdf"
    pdf_path.write_bytes(svc._render_supplier_brief_pdf_sync(package, package.items_json))
    extracted = subprocess.run(
        [pdftotext, str(pdf_path), "-"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert "Request for quote" in extracted
    assert "Ann Buyer, Acme & Co, ann@acme.example" in extracted
    assert "5 Nov 2026" in extracted and "Quote against A & B" in extracted
    assert "Quantity: 40" in extracted and "Material: Stainless steel" in extracted
    for internal in ("approved", "Approved", "stale", "Unvalidated", "should-cost", "Live supplier send"):
        assert internal not in extracted, internal


def _sized_item(decision: CostDecision) -> dict:
    return {
        "decision": {"id": decision.ulid, "filename": decision.filename, "approval_status": "unreviewed",
                     "is_stale": False, "unvalidated_confidence": True, "make_now_process": "cnc", "crossover_qty": 1000},
        "cost_decision": {**decision.result_json, "geometry": {"bbox_mm": [300, 200, 100], "volume_cm3": 120.0}},
        "declared_part": None,
        "part_context": None,
        "raw_cad": {"included": False, "reason": "not_requested"},
    }


def _sized_package(item: dict, metadata: dict) -> RfqPackage:
    return RfqPackage(
        ulid="01RFQSIZES", org_id="org_1", user_id=11, title="Bracket RFQ", supplier_name=None,
        item_count=1, approved_count=0, stale_count=0, unvalidated_count=1, raw_cad_included=False,
        live_supplier_send=False, items_json=[item], warnings_json=[], metadata_json=metadata,
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_supplier_copy_leads_with_the_requesters_inches_and_keeps_mm(monkeypatch):
    decision = _decision()
    package = _sized_package(_sized_item(decision), {"length_unit": "in", "length_unit_basis": "requester",
                                                     "include_cost_estimate": True})
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_Result(first=decision))
    monkeypatch.setattr(svc, "cached_cost_pdf", AsyncMock(return_value=b"%PDF-test"))
    monkeypatch.setattr(svc, "_supplier_brief_pdf", AsyncMock(return_value=b"%PDF-brief"))

    with zipfile.ZipFile(io.BytesIO(await svc.build_zip(session, package))) as zf:
        brief = zf.read("supplier-brief.md").decode()
        rows = list(csv.DictReader(io.StringIO(zf.read("line-items.csv").decode())))
        records = [json.loads(zf.read("parts/01-VALVE-100/cost-decision.json"))]
    size = "11.81 × 7.874 × 3.937 in (300 × 200 × 100 mm)"
    assert f"- Size: {size} (measured from the CAD)" in brief
    assert rows[0]["size"] == size
    # The should-cost report and the brief PDF are rendered in the package's unit.
    assert svc.cached_cost_pdf.call_args.kwargs["length_unit"] == "in"
    assert svc._supplier_brief_pdf.call_args.args[2] == "in"
    # The JSON records stay in mm: data, not prose.
    assert records[0]["geometry"]["bbox_mm"] == [300, 200, 100]
    assert size in svc._supplier_brief_html(package, [outbound_item(package)], "in")


def outbound_item(package: RfqPackage) -> dict:
    from src.services import outbound

    return outbound.rfq_item(package.items_json[0])


@pytest.mark.asyncio
async def test_supplier_copy_in_mm_shows_mm_once_and_old_packages_use_the_requesters_choice(monkeypatch):
    decision = _decision()
    monkeypatch.setattr(svc, "cached_cost_pdf", AsyncMock(return_value=b"%PDF-test"))
    monkeypatch.setattr(svc, "_supplier_brief_pdf", AsyncMock(return_value=b"%PDF-brief"))

    session = AsyncMock()
    session.execute = AsyncMock(return_value=_Result(first=decision))
    with zipfile.ZipFile(io.BytesIO(await svc.build_zip(session, _sized_package(_sized_item(decision), {"length_unit": "mm"})))) as zf:
        assert "- Size: 300 × 200 × 100 mm (measured from the CAD)\n" in zf.read("supplier-brief.md").decode()

    # Saved before the unit was kept on the package: the requester's (package.user_id) current choice.
    session.get = AsyncMock(return_value=SimpleNamespace(preferences={"length_unit": "in"}))
    await svc.build_zip(session, _sized_package(_sized_item(decision), {"include_cost_estimate": True}))
    session.get.assert_awaited()
    assert session.get.await_args.args[1] == 11
    assert svc.cached_cost_pdf.call_args.kwargs["length_unit"] == "in"


@pytest.mark.asyncio
async def test_create_package_saves_the_requesters_unit(monkeypatch):
    decision = _decision()
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock(return_value=_Result(rows=[decision]))
    session.get = AsyncMock(return_value=SimpleNamespace(preferences={"length_unit": "in"}))
    monkeypatch.setattr(svc, "resolve_org", AsyncMock(return_value="org_1"))
    monkeypatch.setattr(svc, "_manifest_match", AsyncMock(return_value=None))
    monkeypatch.setattr(svc, "_part_context", AsyncMock(return_value=None))
    monkeypatch.setattr(svc, "_raw_cad_payload", AsyncMock(return_value=(None, None, {"included": False, "reason": "not_requested"})))
    monkeypatch.setattr(svc, "precompute_cost_pdf", AsyncMock(return_value=b"%PDF"))
    before = set(svc._WARM_TASKS)

    monkeypatch.setattr(svc, "_run_facts", AsyncMock(return_value={}))
    package = await svc.create_package(
        session, AuthedUser(user_id=42, api_key_id=0, key_prefix="session", role="analyst"), ["01RFQDECISION"],
        svc.RfqPackageOptions(include_cost_estimate=True))
    assert package.metadata_json["length_unit"] == "in"
    assert package.metadata_json["length_unit_basis"] == "requester"
    assert session.get.await_args_list[0].args[1] == 42  # the requester's unit
    for task in set(svc._WARM_TASKS) - before:
        await task
    assert svc.precompute_cost_pdf.call_args.args[2] == "in"
