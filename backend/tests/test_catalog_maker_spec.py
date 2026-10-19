"""Catalog machines carry their maker's published spec, labelled as such.

A machine added from the catalog without edits keeps the maker's workpiece
load and materials, so the fit can say yes; the API labels those values
(``field_provenance``) and the verdict names them (``maker_spec``). An edit
makes a value the shop's own, and a client can't claim a label the catalog
doesn't back.
"""
from __future__ import annotations

import types

import pytest

from src.costing.makeability import MachineCap, PartReq, fit_machine
from src.profiles.database import MACHINES
from src.profiles.models import MAKER_DESCRIBED, MAKER_SPEC
from src.services import machine_inventory_service as svc

CNC = {"cnc_3axis", "cnc_5axis", "cnc_turning", "wire_edm"}


def _saved(name: str, **edits) -> dict:
    """What POST /machine-inventory stores for a catalog pick, after ``edits``."""
    payload = svc.add_from_catalog(name)
    payload.update(edits)
    svc.validate_machine(payload)
    return svc._normalize(payload)


def _row(fields: dict):
    return types.SimpleNamespace(ulid="m1", created_at=None, updated_at=None, **fields)


def _cap(fields: dict) -> MachineCap:
    row = _row(fields)
    return MachineCap(
        process=row.process, name=row.name, count=row.count,
        max_workpiece_kg=row.max_workpiece_kg, hourly_rate_usd=row.hourly_rate_usd,
        capital_frac=row.capital_frac, materials=tuple(row.materials or ()),
        material_thickness_map=dict(row.material_thickness_map or {}),
        capabilities=svc._engine_capabilities(row),
    )


def _aluminum_block(process="cnc_3axis") -> PartReq:
    # bored-block-mm.iges: 20 x 15 x 10 mm, 2.72 cm3 of 6061 (7 g).
    return PartReq(process=process, bbox_mm=(10.0, 15.0, 20.0), mass_kg=0.007,
                   material_name="6061-T6 Aluminum", material_class="aluminum")


def test_every_catalog_machine_names_its_maker_page():
    for prof in MACHINES:
        assert prof.spec is not None, prof.name
        assert prof.spec.source_url.startswith("https://"), prof.name
        assert prof.spec.checked, prof.name
        assert prof.spec.materials_basis in {MAKER_SPEC, MAKER_DESCRIBED}, prof.name
        if prof.spec.max_workpiece_kg is None:
            # Never estimated: the note says the maker publishes none.
            assert "publishes no" in prof.spec.kg_note, prof.name


def test_cnc_catalog_machines_prefill_weight_and_material_classes():
    by_name = {o["name"]: o for o in svc.catalog_options()}
    for prof in MACHINES:
        if prof.process_type.value not in CNC:
            continue
        o = by_name[prof.name]
        assert o["max_workpiece_kg"] and o["max_workpiece_kg"] > 0, prof.name
        assert o["materials"] and set(o["materials"]) <= {"aluminum", "steel", "stainless", "titanium", "polymer"}
        assert set(o["field_provenance"]) == {"max_workpiece_kg", "materials"}
        assert o["spec"]["source_url"] == prof.spec.source_url
    vf2 = by_name["Haas VF-2"]
    assert vf2["max_workpiece_kg"] == 1361.0
    assert vf2["field_provenance"]["max_workpiece_kg"]["source"] == MAKER_SPEC
    assert vf2["field_provenance"]["materials"]["source"] == MAKER_DESCRIBED
    assert by_name["Haas ST-20"]["max_workpiece_kg"] == 68.0  # per chuck, no tailstock
    # A printer whose maker publishes no plate load: nothing prefilled for weight.
    x1c = by_name["Bambu Lab X1C"]
    assert x1c["max_workpiece_kg"] is None
    assert x1c["spec"]["max_workpiece_kg_note"] == "The maker publishes no build-plate load; the build volume governs."
    assert "max_workpiece_kg" not in x1c["field_provenance"]


def test_unedited_catalog_machine_gives_a_yes_and_says_whose_values():
    fields = _saved("Haas VF-2")
    fit = fit_machine(_aluminum_block(), _cap(fields))
    assert fit.passes, fit.failures
    assert fit.resource_hint["maker_spec"] == {"catalog": "Haas VF-2",
                                              "fields": ("max_workpiece_kg", "materials")}
    public = svc.machine_to_public(_row(fields))
    assert set(public["field_provenance"]) == {"max_workpiece_kg", "materials"}
    assert public["field_provenance"]["max_workpiece_kg"]["url"].startswith("https://www.haascnc.com/")
    assert public["provenance"] == "user"
    # Not a material the maker's description covers: a concrete no, not a guess.
    titanium = PartReq(process="cnc_3axis", bbox_mm=(10.0, 15.0, 20.0), mass_kg=0.012,
                       material_name="Ti6Al4V (Wrought)", material_class="titanium")
    assert not fit_machine(titanium, _cap(fields)).passes


def test_an_edit_makes_the_value_the_shops_own():
    kg_edit = _saved("Haas VF-2", max_workpiece_kg=500.0)
    assert kg_edit["capabilities"]["maker_spec"]["fields"] == ["materials"]
    fit = fit_machine(_aluminum_block(), _cap(kg_edit))
    assert fit.passes and fit.resource_hint["maker_spec"]["fields"] == ("materials",)
    both = _saved("Haas VF-2", max_workpiece_kg=500.0, materials=["aluminum", "steel", "stainless"])
    assert "maker_spec" not in both["capabilities"]
    assert svc.machine_to_public(_row(both))["field_provenance"] == {}
    fit = fit_machine(_aluminum_block(), _cap(both))
    assert fit.passes and "maker_spec" not in fit.resource_hint
    # Same materials in another order is still the maker's list.
    reordered = _saved("Haas VF-2", materials=["steel", "aluminum"])
    assert reordered["capabilities"]["maker_spec"]["fields"] == ["max_workpiece_kg", "materials"]


def test_a_client_cannot_claim_a_maker_label():
    # Claiming the VF-2 for values the maker doesn't publish earns no label.
    forged = svc._normalize({"name": "Mill", "process": "cnc_3axis", "max_workpiece_kg": 9999.0,
                             "materials": ["titanium"],
                             "capabilities": {"x": 762, "maker_spec": {"catalog": "Haas VF-2",
                                                                       "fields": ["max_workpiece_kg"]}}})
    assert "maker_spec" not in forged["capabilities"]
    # Another method isn't that machine; an unknown catalog name labels nothing.
    other = svc._normalize({**_saved("Haas VF-2"), "process": "cnc_5axis"})
    assert "maker_spec" not in other["capabilities"]
    unknown = svc._normalize({"process": "cnc_3axis", "max_workpiece_kg": 1361.0,
                              "capabilities": {"maker_spec": {"catalog": "Haas VF-9000"}}})
    assert "maker_spec" not in unknown["capabilities"]
    # A malformed label is reported, never stored.
    for bad in ("Haas VF-2", {"catalog": ""}, {"catalog": "Haas VF-2", "url": "https://evil.example"}):
        with pytest.raises(ValueError, match="maker_spec"):
            svc.validate_machine({"process": "cnc_3axis", "capabilities": {"maker_spec": bad}})
    # The server-computed display fields a template carries are accepted and dropped.
    template = svc.add_from_catalog("Haas VF-2")
    template["field_provenance"] = {"hourly_rate_usd": {"source": "maker_spec"}}
    svc.validate_machine(template)
    assert "field_provenance" not in svc._normalize(template)


@pytest.mark.asyncio
async def test_patch_keeps_or_drops_the_label_with_the_value(monkeypatch):
    stored = _row(_saved("Haas ST-20"))

    async def fake_get(session, org_id, ulid):
        return stored

    class _Session:
        async def flush(self):
            return None

    monkeypatch.setattr(svc, "get_machine", fake_get)
    await svc.update_machine(_Session(), "org", "m1", {"hourly_rate_usd": 80.0})
    assert stored.capabilities["maker_spec"]["fields"] == ["max_workpiece_kg", "materials"]
    await svc.update_machine(_Session(), "org", "m1", {"max_workpiece_kg": 136.0})
    assert stored.capabilities["maker_spec"]["fields"] == ["materials"]
    assert set(svc.machine_to_public(stored)["field_provenance"]) == {"materials"}


def test_verdict_block_names_the_maker_values_it_rests_on():
    from src.costing.estimate import _serialize_verification
    from src.costing.makeability import verify_part

    fields = _saved("Haas VF-2")
    verdict = verify_part({"cnc_3axis": _aluminum_block()}, [_cap(fields)])
    options = types.SimpleNamespace(inventory=(_cap(fields),), service_environment=None)
    block = _serialize_verification(verdict, options)
    route = block["per_route"]["cnc_3axis"]
    assert route["verdict"] == "makeable_in_house"
    assert route["maker_spec"] == {"catalog": "Haas VF-2", "fields": ["max_workpiece_kg", "materials"]}
    # A machine the shop declared itself carries no label: byte-identical block.
    own = {k: v for k, v in fields.items()}
    own["capabilities"] = {k: v for k, v in fields["capabilities"].items() if k != "maker_spec"}
    verdict = verify_part({"cnc_3axis": _aluminum_block()}, [_cap(own)])
    block = _serialize_verification(verdict, types.SimpleNamespace(inventory=(_cap(own),),
                                                                   service_environment=None))
    assert "maker_spec" not in block["per_route"]["cnc_3axis"]
    assert "maker_spec" not in (block["resource"] or {})


def test_catalog_fixes_from_the_maker_pages():
    by_name = {m.name: m for m in MACHINES}
    # The current DMU 50 is the 3rd generation: 650 x 520 x 475 mm, 300 kg.
    assert by_name["DMG MORI DMU 50"].build_volume == (650, 520, 475)
    assert by_name["Elegoo Saturn 4 Ultra"].build_volume[2] == 220
    assert "PEEK" not in by_name["Farsoon HT1001P"].materials
    assert "CoCr" not in by_name["Arcam Q20plus"].materials
    assert by_name["ExOne S-Max Pro"].materials == ["Sand"]
    assert "ABS" not in by_name["Prusa MK4S"].materials  # needs the enclosure with filtration


def _pla_bracket(mass_kg=0.05) -> PartReq:
    return PartReq(process="fdm", bbox_mm=(6.0, 40.0, 50.0), mass_kg=mass_kg,
                   material_name="PLA", material_class="polymer", min_feature_mm=2.0)


def test_catalog_printer_gives_a_yes_and_says_the_build_volume_governs_weight():
    from src.costing.estimate import _serialize_verification
    from src.costing.makeability import WEIGHT_BY_BUILD_VOLUME, verify_part

    x1c = _saved("Bambu Lab X1C")
    assert x1c["max_workpiece_kg"] is None
    fit = fit_machine(_pla_bracket(), _cap(x1c))
    assert fit.passes, fit.failures
    assert fit.resource_hint["notes"] == (WEIGHT_BY_BUILD_VOLUME,)
    assert fit.resource_hint["maker_spec"]["fields"] == ("materials",)
    verdict = verify_part({"fdm": _pla_bracket()}, [_cap(x1c)])
    assert verdict.verdict == "makeable_in_house"
    block = _serialize_verification(verdict, types.SimpleNamespace(inventory=(_cap(x1c),),
                                                                   service_environment=None))
    assert block["per_route"]["fdm"]["notes"] == [
        "weight: no plate load published or declared; build volume governs"]
    # The envelope still governs: a part bigger than the 256 mm cube is a no.
    big = PartReq(process="fdm", bbox_mm=(280.0, 300.0, 320.0), mass_kg=1.0,
                  material_name="PLA", material_class="polymer", min_feature_mm=2.0)
    big_fit = fit_machine(big, _cap(x1c))
    assert not big_fit.passes and big_fit.failures[0].gate == "envelope"


def test_a_declared_plate_load_is_still_checked_on_printers():
    declared = _saved("Bambu Lab X1C", max_workpiece_kg=0.5)
    over = fit_machine(_pla_bracket(mass_kg=0.8), _cap(declared))
    assert not over.passes
    assert [(f.gate, f.have) for f in over.failures] == [("mass", 0.5)]
    under = fit_machine(_pla_bracket(mass_kg=0.2), _cap(declared))
    assert under.passes and "notes" not in under.resource_hint


def test_cnc_and_bead_deposition_keep_the_weight_check():
    vf2 = _saved("Haas VF-2", max_workpiece_kg=None)
    fit = fit_machine(_aluminum_block(), _cap(vf2))
    assert not fit.passes
    assert [(f.gate, f.have) for f in fit.failures] == [("mass", None)]
    ded = MachineCap(process="ded", name="DED cell", materials=("titanium",),
                     capabilities={"x": 1000, "y": 1000, "z": 1000})
    part = PartReq(process="ded", bbox_mm=(50.0, 60.0, 80.0), mass_kg=2.0,
                   material_name="Ti6Al4V", material_class="titanium")
    ded_fit = fit_machine(part, ded)
    assert any(f.gate == "mass" and f.have is None for f in ded_fit.failures)
    assert not ded_fit.passes
