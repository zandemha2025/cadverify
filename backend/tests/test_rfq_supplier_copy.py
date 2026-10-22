"""What a supplier receives in an RFQ package (buyer-08, buyer-09, buyer-10, buyer-18).

By default: per part its name, part number, material, the quantity asked for and
its yearly volume, specs, the buyer's note and the CAD; for the package who asks,
the reply-by date and a plain list of files. None of our should-cost, price
lines, crossover, make-vs-buy reasoning or review state. Our cost estimate goes
only when the buyer turns "Include our cost estimate" on, and review state never.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.auth.require_api_key import AuthedUser
from src.db.models import CostDecision
from src.services import rfq_package_service as svc

PLATE_STEP = b"ISO-10303-21;\nHEADER;\nFILE_NAME('plate-with-boss.step');\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
PLATE_HASH = hashlib.sha256(PLATE_STEP).hexdigest()

# A saved should-cost like the tester's plate: prices at 1 and 250, line items,
# a crossover to die casting and an "if redesigned" route.
PLATE_RESULT = {
    "filename": "plate-with-boss.step",
    "material_class": "aluminum",
    "quantities": [1, 250, 1000],
    "geometry": {"bbox_mm": [300, 200, 10.8], "volume_cm3": 640.2, "face_count": 18},
    "estimates": [
        {"process": "cnc_3axis", "material": "6061-T6 Aluminum", "quantity": q, "unit_cost_usd": u,
         "dfm_ready": True, "confidence": {"validated": False, "method": "assumption-band", "label": "assumption"},
         "line_items": {"machine": 155.88, "material": 10.11, "spec_anodize_ii": 1.96, "spec_fai_as9102": 0.84},
         "drivers": [{"name": "spec_anodize_ii_cost", "value": 1.96, "unit": "$", "provenance": "DEFAULT",
                      "source": "Alibaba.com seller guide to anodizing (2026)"}]}
        for q, u in ((1, 665.55), (250, 193.18), (1000, 158.04))
    ] + [
        {"process": "die_casting", "material": "A356 Aluminum", "quantity": 1000, "unit_cost_usd": 130.9,
         "dfm_ready": False, "confidence": {"validated": False, "method": "assumption-band"}},
    ],
    "decision": {
        "make_now_process": "cnc_3axis", "make_now_material": "6061-T6 Aluminum", "crossover_qty": 241,
        "tooling_process": "die_casting",
        "note": "Die casting becomes cheaper at about 241 parts.",
        "recommendation": {
            "1": {"process": "cnc_3axis", "material": "6061-T6 Aluminum", "unit_cost_usd": 665.55, "dfm_ready": True},
            "250": {"process": "cnc_3axis", "material": "6061-T6 Aluminum", "unit_cost_usd": 193.18, "dfm_ready": True},
            "1000": {"process": "cnc_3axis", "material": "6061-T6 Aluminum", "unit_cost_usd": 158.04, "dfm_ready": True},
        },
        "if_redesigned": {"1000": {"process": "investment_casting", "material": "A356", "unit_cost_usd": 130.9}},
    },
}
SPECS = {"finishes": ["anodize_ii"], "ra_um": 1.6, "ra_unit": "um", "inspection": ["fai_as9102"],
         "certifications": ["as9100"]}
NOTE = "Please quote 250 pcs/yr each, 4 releases. Quote due Nov 5."
# What must never reach the supplier unless the buyer turns the cost estimate on.
OUR_NUMBERS = (b"193.18", b"665.55", b"158.04", b"155.88", b"130.9", b"241", b"Alibaba", b"crossover",
               b"Should-Cost", b"should-cost evidence", b"negotiation")
REVIEW_STATE = (b"Approved decisions", b"approval_status", b"unreviewed", b"not approved", b"Unvalidated",
                b"unvalidated", b"decision_unapproved", b"confidence_unvalidated", b"Stale decisions",
                b"Live supplier send", b"no_same_org_completed_batch_blob")


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


def _decision(**kw) -> CostDecision:
    d = CostDecision(
        id=kw.get("id", 7), ulid=kw.get("ulid", "01PLATE0000000000000000000"), org_id="org_buyer", user_id=5,
        mesh_hash=kw.get("mesh_hash", PLATE_HASH), params_hash="p", engine_version="t",
        filename="plate-with-boss.step", file_type="step", result_json=PLATE_RESULT,
        make_now_process="cnc_3axis", crossover_qty=241, quantities=[1, 250, 1000], label=None,
        approval_status="unreviewed", created_at=datetime(2026, 10, 22, 15, 5, tzinfo=timezone.utc),
    )
    for k in ("stale_at", "stale_reason", "approved_at", "approved_by_user_id", "approval_note",
              "user_disposition", "disposition_note", "disposition_basis", "disposition_updated_at",
              "disposition_updated_by_user_id"):
        setattr(d, k, None)
    return d


@pytest.fixture
def kept(tmp_path, monkeypatch):
    """The organization's kept source of the plate, as every check keeps it."""
    monkeypatch.setenv("SOURCE_ARTIFACT_BLOB_DIR", str(tmp_path / "src"))
    monkeypatch.delenv("OBJECT_STORE_LOCAL_ROOT", raising=False)
    monkeypatch.delenv("OBJECT_STORE_BACKEND", raising=False)
    from src.services import source_artifact_service as sources

    store = sources._store()
    store.put(sources.artifact_key("org_buyer", PLATE_HASH, ".step"), PLATE_STEP)
    return tmp_path


async def _build(monkeypatch, *, run=None, context=True, **options):
    d = _decision()
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    async def _exec(stmt, *a, **k):  # the records asked for; no catalog-run ZIP holds this part
        return _Rows([] if "batch_items" in str(stmt) else [d])

    session.execute = AsyncMock(side_effect=_exec)
    user = SimpleNamespace(full_name="Marcus Bell", email="marcus@kestrel.example", preferences={})
    org = SimpleNamespace(name="Kestrel Contract Manufacturing", is_personal=False)

    async def _get(model, key):
        return {"User": user, "Organization": org}.get(model.__name__)

    session.get = AsyncMock(side_effect=_get)
    monkeypatch.setattr(svc, "resolve_org", AsyncMock(return_value="org_buyer"))
    monkeypatch.setattr(svc, "_manifest_match", AsyncMock(return_value=None))
    monkeypatch.setattr(svc, "_part_context", AsyncMock(return_value={
        "program": "Secret program", "annual_volume": None, "part_specs": SPECS,
        "provenance": "user_declared"} if context else None))
    monkeypatch.setattr(svc, "_run_facts", AsyncMock(return_value=run or {}), raising=False)
    monkeypatch.setattr(svc, "precompute_cost_pdf", AsyncMock(return_value=None))
    package = await svc.create_package(
        session, AuthedUser(user_id=5, api_key_id=0, key_prefix="session", role="analyst"), [d.ulid],
        svc.RfqPackageOptions(title="RFQ-1022 plate", supplier_name="Midway Machining", note=NOTE, **options),
    )
    package.created_at = datetime(2026, 10, 22, 15, 10, tzinfo=timezone.utc)
    return package, session


async def _files(package, session, monkeypatch) -> dict[str, bytes]:
    from src.services.cost_pdf_service import render_cost_html

    async def _html_pdf(decision, gov=None, length_unit="mm"):  # the report's HTML, so its words can be read
        return render_cost_html(decision, gov, length_unit).encode()

    monkeypatch.setattr(svc, "cached_cost_pdf", _html_pdf)
    monkeypatch.setattr(svc, "_supplier_brief_pdf",
                        AsyncMock(side_effect=lambda p, items, unit: svc._supplier_brief_html(p, items, unit).encode()))
    with zipfile.ZipFile(io.BytesIO(await svc.build_zip(session, package))) as zf:
        return {n: zf.read(n) for n in zf.namelist()}


@pytest.mark.asyncio
async def test_a_supplier_package_carries_what_a_supplier_quotes_from_and_none_of_our_numbers(kept, monkeypatch):
    package, session = await _build(monkeypatch, run={"quantity": 250}, include_raw_cad=True,
                                    reply_by=date(2099, 11, 5))
    files = await _files(package, session, monkeypatch)
    assert set(files) == {
        "supplier-brief.pdf", "supplier-brief.md", "line-items.csv", "package_manifest.json",
        "parts/01-plate-with-boss/plate-with-boss.step",
    }
    # buyer-09: the kept source is the CAD, byte for byte.
    assert files["parts/01-plate-with-boss/plate-with-boss.step"] == PLATE_STEP
    # buyer-08 / buyer-10: nothing of our cost, crossover, reasoning or review state, in any file.
    for name, body in files.items():
        for word in OUR_NUMBERS + REVIEW_STATE:
            assert word not in body, (name, word)
    brief = files["supplier-brief.md"].decode()
    assert brief.startswith("# RFQ-1022 plate\n\nRequest for quote.")
    assert "- Requested by: Marcus Bell, Kestrel Contract Manufacturing, marcus@kestrel.example" in brief
    assert "- Supplier: Midway Machining" in brief and "- Reply by: 5 Nov 2099" in brief
    assert "- The supplier must hold: AS9100" in brief
    assert NOTE in brief
    for line in ("- Material: Aluminum", "- Quantity: 250", "- Finish: Anodize, Type II, Ra 1.6 µm",
                 "- Inspection: First article inspection, AS9102",
                 "- CAD: parts/01-plate-with-boss/plate-with-boss.step",
                 "- Size: 300 × 200 × 10.8 mm (measured from the CAD)"):
        assert line in brief, line
    assert "Secret program" not in brief  # the program name isn't asked of a supplier
    row = next(csv.DictReader(io.StringIO(files["line-items.csv"].decode())))
    assert (row["part"], row["material"], row["quantity"], row["cad_file"]) == (
        "plate-with-boss.step", "Aluminum", "250", "parts/01-plate-with-boss/plate-with-boss.step")
    assert row["supplier_must_hold"] == "AS9100" and "our_estimate_usd_each" not in row
    manifest = json.loads(files["package_manifest.json"])
    assert manifest["includes_cost_estimate"] is False and manifest["reply_by"] == "2099-11-05"
    assert manifest["requested_by"]["company"] == "Kestrel Contract Manufacturing"
    assert manifest["files"][-1] == "parts/01-plate-with-boss/plate-with-boss.step"
    # The brief PDF reads the same and is escaped.
    html = svc._supplier_brief_html(package, [svc.outbound.rfq_item(i) for i in package.items_json])
    assert "Request for quote" in html and "Approved" not in html


@pytest.mark.asyncio
async def test_our_cost_estimate_goes_only_when_the_buyer_turns_it_on_and_review_state_never(kept, monkeypatch):
    package, session = await _build(monkeypatch, run={"quantity": 250}, include_raw_cad=True,
                                    include_cost_estimate=True)
    files = await _files(package, session, monkeypatch)
    folder = "parts/01-plate-with-boss"
    assert {f"{folder}/should-cost-report.pdf", f"{folder}/cost-drivers.csv", f"{folder}/cost-decision.json"} <= set(files)
    brief = files["supplier-brief.md"].decode()
    assert "## Cost estimate" in brief and "not a quote" in brief
    assert "- Our estimate: $193.18 each at 250, 3-axis milling" in brief
    row = next(csv.DictReader(io.StringIO(files["line-items.csv"].decode())))
    assert row["our_estimate_usd_each"] == "193.18"
    report = files[f"{folder}/should-cost-report.pdf"].decode()
    assert "Cost estimate" in report and "negotiation" not in report
    for name, body in files.items():
        for word in REVIEW_STATE:
            assert word not in body, (name, word)
    assert json.loads(files["package_manifest.json"])["includes_cost_estimate"] is True


@pytest.mark.asyncio
async def test_the_quantity_asked_for_comes_from_the_part_and_the_buyer_can_set_it(monkeypatch):
    # The run's quantity (buyer-18), when the part declares no yearly volume.
    package, _ = await _build(monkeypatch, run={"quantity": 250, "part_number": "KCM-1022"})
    req = package.items_json[0]["request"]
    assert (req["quantity"], req["quantity_source"], req["part_number"]) == (250, "run", "KCM-1022")
    # Not in a run: the quantity the record was priced at besides ScaleCAD's own ladder.
    package, _ = await _build(monkeypatch)
    assert package.items_json[0]["request"]["quantity"] == 250
    assert package.items_json[0]["request"]["quantity_source"] == "record"
    # The buyer's own figure in the builder wins.
    package, _ = await _build(monkeypatch, quantities={"01PLATE0000000000000000000": 400})
    assert package.items_json[0]["request"]["quantity"] == 400
    assert package.items_json[0]["request"]["quantity_source"] == "package"
    with pytest.raises(Exception) as err:
        await _build(monkeypatch, quantities={"01PLATE0000000000000000000": 0})
    assert getattr(err.value, "status_code", None) == 400


@pytest.mark.asyncio
async def test_a_part_with_no_kept_file_says_so_to_the_buyer_and_the_package_still_builds(tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCE_ARTIFACT_BLOB_DIR", str(tmp_path / "empty"))
    monkeypatch.delenv("OBJECT_STORE_LOCAL_ROOT", raising=False)
    package, session = await _build(monkeypatch, include_raw_cad=True)
    assert package.raw_cad_included is False
    warn = [w for w in package.warnings_json if w["code"] == "raw_cad_unavailable"]
    assert warn and warn[0]["message"] == ("plate-with-boss.step: no CAD in the package, ScaleCAD has no copy "
                                           "of the file. Attach it yourself.")
    files = await _files(package, session, monkeypatch)
    assert "- CAD: not in this package" in files["supplier-brief.md"].decode()
    assert not any(n.endswith(".step") for n in files)


@pytest.mark.asyncio
async def test_a_reply_by_date_in_the_past_is_refused_in_plain_words(monkeypatch):
    with pytest.raises(Exception) as err:
        await _build(monkeypatch, reply_by=date(2000, 1, 1))
    assert err.value.status_code == 400 and "reply-by date has passed" in err.value.detail


@pytest.mark.asyncio
async def test_by_default_none_of_our_cost_or_review_state_leaves(monkeypatch):
    """buyer-08 / buyer-10 with the options the builder always had: no cost files, no figures."""
    package, session = await _build(monkeypatch)
    files = await _files(package, session, monkeypatch)
    assert not [n for n in files if "cost" in n or n.endswith("should-cost-report.pdf")], sorted(files)
    for name, body in files.items():
        for word in OUR_NUMBERS + REVIEW_STATE:
            assert word not in body, (name, word)


@pytest.mark.asyncio
async def test_the_kept_cad_goes_in_the_package_for_a_record_outside_any_batch(kept, monkeypatch):
    """buyer-09: the part page says the source is kept, so the package has it."""
    package, session = await _build(monkeypatch, include_raw_cad=True)
    assert package.raw_cad_included is True
    files = await _files(package, session, monkeypatch)
    cad = [n for n in files if n.endswith(".step")]
    assert cad == ["parts/01-plate-with-boss/plate-with-boss.step"] and files[cad[0]] == PLATE_STEP
    assert not any("unavailable" in n or "not-included" in n for n in files)


def test_a_run_quantity_is_the_yearly_quantity_of_every_part_the_list_doesnt_name():
    """buyer-18: "Quantity, each unless listed" carries onto each part."""
    from src.jobs.batch_tasks import part_facts

    assert part_facts({}, {"quantity": 250}) == {"quantity": 250}
    assert part_facts({"quantity": 40, "part_number": "A-1"}, {"quantity": 250}) == {"quantity": 40, "part_number": "A-1"}
    assert part_facts({"current_price_usd": 9.5}, {"quantity": 250}) == {"current_price_usd": 9.5, "quantity": 250}
    assert part_facts({}, {}) == {}
