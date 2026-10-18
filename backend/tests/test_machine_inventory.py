"""Machine-inventory model + CRUD/CSV + shop-capabilities + service-environment.

Two layers, mirroring ``test_manifest_ingest.py``:

  * **pure** (no DB/IO): machine capability validation (good / bad process /
    negative scalar / bad IT grade / unknown material / capital_frac out of
    range / unknown capability), CSV parse (good / mixed / bad-header / empty /
    BOM), ``add_from_catalog`` prefill, and service-environment validation.
    Malformed inputs are REPORTED, never coerced.
  * **Postgres** (skipped unless DATABASE_URL is Postgres): CRUD + org isolation,
    CSV import, ``load_org_inventory`` → correct ``MachineCap`` list,
    ``load_shop_caps``, and part-context ``service_environment`` upsert/read/isolation.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re

import pytest

from src.services import machine_inventory_service as svc
from src.services import part_context_service as pcs


# ── pure: machine validation ─────────────────────────────────────────────────
def _good_machine() -> dict:
    return {
        "name": "Haas VF-2 #1",
        "process": "cnc_3axis",
        "count": 1,
        "max_workpiece_kg": 200.0,
        "hourly_rate_usd": 75.0,
        "capital_frac": 0.4,
        "capabilities": {"x": 762, "y": 406, "z": 508, "axes": 3,
                         "achievable_it_grade": 9},
        "materials": ["304 Stainless", "steel"],
    }


def test_good_machine_validates():
    svc.validate_machine(_good_machine())  # no raise


def test_machine_numeric_and_enum_inputs_reject_unsafe_values():
    for value in (float("nan"), float("inf"), -float("inf"), 10**1000):
        for patch in ({"hourly_rate_usd": value}, {"max_workpiece_kg": value},
                      {"capital_frac": value}, {"capabilities": {"x": value}},
                      {"material_thickness_map": {"steel": value}}):
            with pytest.raises(ValueError):
                svc.validate_machine({**_good_machine(), **patch})
    with pytest.raises(ValueError, match="2147483647"):
        svc.validate_machine({**_good_machine(), "count": 2**31})
    svc.validate_machine({**_good_machine(), "count": 2**31 - 1})
    for field in ("motion_mode", "chamber_type"):
        with pytest.raises(ValueError, match=field):
            svc.validate_machine({**_good_machine(), "capabilities": {field: []}})


def test_machine_csv_reports_oversized_fields_and_invalid_numbers():
    rows, errors = svc.parse_machine_csv("process,name\ncnc_3axis," + "x" * 150000)
    assert rows == [] and errors and "CSV" in errors[0]["reason"]
    rows, errors = svc.parse_machine_csv(
        "process,count,hourly_rate_usd\ncnc_3axis,2147483648,75\n"
        "cnc_3axis,1,Infinity\ncnc_3axis,2,95\n")
    assert len(rows) == 1 and rows[0]["count"] == 2
    assert [e["line"] for e in errors] == [2, 3]


def test_empty_capabilities_is_valid():
    m = _good_machine()
    m["capabilities"] = {}  # a machine may declare only some gates
    svc.validate_machine(m)


def test_bad_process_reported():
    m = _good_machine()
    m["process"] = "cnc_9axis"
    with pytest.raises(ValueError, match="unknown process"):
        svc.validate_machine(m)


def test_missing_process_reported():
    m = _good_machine()
    m["process"] = None
    with pytest.raises(ValueError, match="process is required"):
        svc.validate_machine(m)


def test_negative_scalar_reported():
    m = _good_machine()
    m["capabilities"] = {"x": -5}
    with pytest.raises(ValueError, match="must be > 0"):
        svc.validate_machine(m)


def test_bad_it_grade_reported():
    m = _good_machine()
    m["capabilities"] = {"achievable_it_grade": "IT9"}
    with pytest.raises(ValueError, match="achievable_it_grade must be an integer"):
        svc.validate_machine(m)


def test_it_grade_out_of_range_reported():
    m = _good_machine()
    m["capabilities"] = {"achievable_it_grade": 42}
    with pytest.raises(ValueError, match="IT grade in 0"):
        svc.validate_machine(m)


def test_unknown_material_reported():
    m = _good_machine()
    m["materials"] = ["unobtainium"]
    with pytest.raises(ValueError, match="unknown material"):
        svc.validate_machine(m)


def test_known_material_name_and_class_accepted():
    m = _good_machine()
    m["materials"] = ["Inconel 718", "titanium"]  # a real name + a real class
    svc.validate_machine(m)


def test_placeholder_shorthands_accepted():
    # WA-2: the add-machine form placeholder literally suggests "6061, 316L, PP"
    # (plus 304/ss304) — those bare shorthands must validate, not 400.
    for token in ("6061", "316L", "304", "ss304", "PP", "pp", "316l"):
        m = _good_machine()
        m["materials"] = [token]
        svc.validate_machine(m)  # no raise


def test_shorthands_normalize_to_registry_names():
    # Accepted shorthands are STORED as the real registry material, not the bare
    # token the user typed (so downstream matching sees a real material).
    payload = svc._normalize(
        {**_good_machine(), "materials": ["6061", "316L", "304", "PP"]}
    )
    assert payload["materials"] == [
        "6061-T6 Aluminum",
        "SS316L",
        "304 Stainless",
        "PP (Molded)",
    ]


def test_garbage_material_still_reported_with_vocab_hint():
    # A genuinely unknown material stays an honest 400 — and the message now
    # points at the accepted vocabulary instead of only saying "unknown".
    m = _good_machine()
    m["materials"] = ["unobtainium"]
    with pytest.raises(ValueError, match="unknown material") as exc:
        svc.validate_machine(m)
    msg = str(exc.value)
    assert "accepted:" in msg and "shorthand" in msg


def test_capital_frac_out_of_range_reported():
    m = _good_machine()
    m["capital_frac"] = 1.5
    with pytest.raises(ValueError, match=r"capital_frac must be in \[0,1\]"):
        svc.validate_machine(m)


def test_negative_rate_reported():
    m = _good_machine()
    m["hourly_rate_usd"] = -1.0
    with pytest.raises(ValueError, match="hourly_rate_usd must be >= 0"):
        svc.validate_machine(m)


def test_unknown_capability_key_reported():
    m = _good_machine()
    m["capabilities"] = {"warp_drive_kw": 5}
    with pytest.raises(ValueError, match="unknown capability"):
        svc.validate_machine(m)


def test_bad_axes_reported():
    m = _good_machine()
    m["capabilities"] = {"axes": 7}
    with pytest.raises(ValueError, match="axes must be one of"):
        svc.validate_machine(m)


def test_bad_motion_mode_reported():
    m = _good_machine()
    m["capabilities"] = {"motion_mode": "sideways"}
    with pytest.raises(ValueError, match="motion_mode"):
        svc.validate_machine(m)


def test_all_problems_collected_in_one_message():
    m = _good_machine()
    m["process"] = "nope"
    m["capital_frac"] = 2
    m["capabilities"] = {"x": -1}
    with pytest.raises(ValueError) as ei:
        svc.validate_machine(m)
    msg = str(ei.value)
    assert "unknown process" in msg and "capital_frac" in msg and "must be > 0" in msg


# ── pure: CSV parse ───────────────────────────────────────────────────────────
def _csv(rows: list[dict], header: list[str] | None = None) -> str:
    header = header or list(svc.MACHINE_REQUIRED_COLUMNS + svc.MACHINE_OPTIONAL_COLUMNS)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow([r.get(h, "") for h in header])
    return buf.getvalue()


def test_good_csv_yields_all_rows():
    caps = json.dumps({"x": 762, "y": 406, "z": 508, "axes": 3})
    text = _csv([
        {"process": "cnc_3axis", "name": "VF-2", "count": "1",
         "max_workpiece_kg": "200", "hourly_rate_usd": "75",
         "capital_frac": "0.4", "materials": "304 Stainless|steel",
         "capabilities": caps, "notes": "floor A"},
        {"process": "cnc_5axis", "name": "DMU-50",
         "capabilities": json.dumps({"axes": 5, "motion_mode": "simultaneous_5"})},
    ])
    rows, errors = svc.parse_machine_csv(text)
    assert errors == []
    assert len(rows) == 2
    a = rows[0]
    assert a["process"] == "cnc_3axis"
    assert a["count"] == 1
    assert a["max_workpiece_kg"] == 200.0
    assert a["capital_frac"] == 0.4
    assert a["materials"] == ["304 Stainless", "steel"]
    assert a["capabilities"]["x"] == 762
    # blank optional numerics normalise to None / defaults — nothing fabricated
    b = rows[1]
    assert b["max_workpiece_kg"] is None
    assert b["count"] == 1  # default


def test_mixed_csv_reports_precise_per_line_errors():
    text = _csv([
        {"process": "cnc_3axis", "name": "ok-1"},              # line 2 valid
        {"process": "", "name": "no-proc"},                    # line 3 missing process
        {"process": "cnc_3axis", "count": "two"},              # line 4 bad count
        {"process": "cnc_3axis", "capital_frac": "1.5"},       # line 5 out of range
        {"process": "cnc_3axis", "capabilities": "{not json}"},  # line 6 bad JSON
        {"process": "cnc_3axis", "materials": "unobtainium"},  # line 7 unknown material
        {"process": "cnc_3axis", "name": "ok-2"},              # line 8 valid
    ])
    rows, errors = svc.parse_machine_csv(text)
    assert [r["name"] for r in rows] == ["ok-1", "ok-2"]
    by_line = {e["line"]: e["reason"] for e in errors}
    assert set(by_line) == {3, 4, 5, 6, 7}
    assert "process is required" in by_line[3]
    assert "count not an integer" in by_line[4]
    assert "capital_frac" in by_line[5]
    assert "not valid JSON" in by_line[6]
    assert "unknown material" in by_line[7]


def test_missing_required_column_is_header_error():
    text = "name,notes\nVF-2,floor\n"  # no process column
    rows, errors = svc.parse_machine_csv(text)
    assert rows == []
    assert len(errors) == 1 and errors[0]["line"] == 1
    assert "process" in errors[0]["reason"]


def test_empty_file_reports_error():
    rows, errors = svc.parse_machine_csv("")
    assert rows == [] and errors[0]["line"] == 0
    rows, errors = svc.parse_machine_csv("   \n")
    assert rows == [] and len(errors) == 1


def test_bom_prefixed_header_tolerated():
    text = "﻿" + _csv([{"process": "cnc_3axis", "name": "VF-2"}])
    rows, errors = svc.parse_machine_csv(text)
    assert errors == [] and len(rows) == 1


def test_blank_lines_skipped():
    text = "process\ncnc_3axis\n\ncnc_5axis\n"
    rows, errors = svc.parse_machine_csv(text)
    assert [r["process"] for r in rows] == ["cnc_3axis", "cnc_5axis"]
    assert errors == []


# ── pure: add_from_catalog ────────────────────────────────────────────────────
def test_add_from_catalog_prefill():
    payload = svc.add_from_catalog("Haas VF-2")
    assert payload["process"] == "cnc_3axis"
    assert payload["capabilities"]["x"] == 762.0
    assert payload["capabilities"]["axes"] == 3
    assert payload["provenance"] == "catalog_template"
    # a prefilled catalog template validates against the same schema (sans the
    # non-model 'provenance' hint, which validate_machine ignores)
    svc.validate_machine(payload)


def test_add_from_catalog_5axis_motion_mode():
    payload = svc.add_from_catalog("DMG MORI DMU 50")
    assert payload["capabilities"]["axes"] == 5
    assert payload["capabilities"]["motion_mode"] == "simultaneous_5"


def test_add_from_catalog_unknown_raises():
    with pytest.raises(ValueError, match="no catalog machine profile"):
        svc.add_from_catalog("Nonexistent 9000")


def test_catalog_options_nonempty():
    opts = svc.catalog_options()
    assert len(opts) >= 10
    assert all("process" in o for o in opts)


# ── pure: shop-op validation ──────────────────────────────────────────────────
def test_shop_ops_valid():
    svc.validate_shop_ops({"heat_treat": True, "hip": {"dia_mm": 300, "height_mm": 600}})


def test_shop_ops_bad_value_reported():
    with pytest.raises(ValueError, match="boolean or a limits object"):
        svc.validate_shop_ops({"hip": "yes"})


def test_shop_ops_negative_limit_reported():
    with pytest.raises(ValueError, match="positive number"):
        svc.validate_shop_ops({"hip": {"dia_mm": -5}})


# ── catalog prefill must save unedited (11 of 19 used to 400 on materials) ────
def test_every_catalog_entry_saves_unedited():
    from src.api.machine_inventory import MachineBody
    from src.profiles.database import MACHINES

    opts = svc.catalog_options()
    assert len(opts) == len(MACHINES)
    for prof, payload in zip(MACHINES, opts):
        # Exactly what POST /machine-inventory hands the service, provenance
        # marker included.
        fields = MachineBody(**payload).model_dump()
        svc.validate_machine(fields)  # no raise
        assert svc._normalize(fields)["materials"] == payload["materials"]
        # No catalog material silently vanishes: each is registry vocabulary or
        # an explicit, reviewed translation/omission named in the notes.
        _, skipped = svc._catalog_materials(prof)
        for name in prof.materials:
            key = (prof.process_type.value, name)
            assert key in svc._CATALOG_MATERIALS or svc._canonical_material(name), name
        for name in skipped:
            assert name in payload["notes"]


def test_catalog_material_translations_are_registry_materials_for_that_process():
    from src.profiles.database import get_material_by_name

    for (proc, name), target in svc._CATALOG_MATERIALS.items():
        if target is None:
            continue
        mat = get_material_by_name(target)
        assert mat is not None and mat.name == target, (name, target)
        assert proc in {p.value for p in mat.process_types}, (proc, name, target)


def test_hp_jet_fusion_prefill_uses_registry_materials():
    payload = svc.add_from_catalog("HP Jet Fusion 5200")
    assert payload["materials"] == ["PA12 (Nylon 12)", "PA11", "PP (MJF)"]
    assert "TPU" in payload["notes"]  # no MJF TPU in the registry: named, not guessed
    svc.validate_machine(payload)


def test_catalog_lathe_prefill_is_the_turning_envelope():
    payload = svc.add_from_catalog("Haas ST-20")
    assert payload["capabilities"] == {"swing_dia": 254.0, "between_centers": 533.0}
    svc.validate_machine(payload)


def test_turning_envelope_has_one_representation():
    from src.costing.makeability import _machine_envelope

    svc.validate_machine({"process": "cnc_turning",
                          "capabilities": {"swing_dia": 254, "between_centers": 533}})
    with pytest.raises(ValueError, match="unknown capability 'swing_dia_mm'"):
        svc.validate_machine({"process": "cnc_turning",
                              "capabilities": {"swing_dia_mm": 254}})
    # The engine no longer reads a key the API can never store.
    assert _machine_envelope({"swing_dia_mm": 254}) == ("rect", None)
    assert _machine_envelope({"swing_dia": 254, "between_centers": 533})[0] == "turning"


class _FakeSession:
    def __init__(self):
        self.added = []

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        return None

    async def commit(self):
        return None

    async def execute(self, stmt):
        # A machine write also marks the org's saved decisions stale (one UPDATE).
        import types

        self.executed = getattr(self, "executed", []) + [stmt]
        return types.SimpleNamespace(rowcount=0)


def _stored_lathe(**over):
    import types

    base = dict(name="ST-20", process="cnc_turning", count=1, max_workpiece_kg=100.0,
                hourly_rate_usd=None, capital_frac=None,
                capabilities={"swing_dia": 254.0, "between_centers": 533.0},
                materials=["304 Stainless"], material_thickness_map=None, notes=None,
                updated_at=None)
    base.update(over)
    return types.SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_rate_only_edit_preserves_every_other_field(monkeypatch):
    row = _stored_lathe(material_thickness_map={"steel": 20.0})
    before = {k: getattr(row, k) for k in svc._MUTABLE_FIELDS if k != "hourly_rate_usd"}

    async def fake_get(session, org_id, ulid):
        return row

    monkeypatch.setattr(svc, "get_machine", fake_get)
    out = await svc.update_machine(_FakeSession(), "org", "m1", {"hourly_rate_usd": 80.0})
    assert out.hourly_rate_usd == 80.0
    assert {k: getattr(out, k) for k in before} == before


@pytest.mark.asyncio
async def test_unrelated_edit_not_blocked_by_legacy_thickness_map(monkeypatch):
    # Stored before thickness-map keys were validated; the form never shows it.
    row = _stored_lathe(material_thickness_map={"unobtainium": 3.0})

    async def fake_get(session, org_id, ulid):
        return row

    monkeypatch.setattr(svc, "get_machine", fake_get)
    out = await svc.update_machine(_FakeSession(), "org", "m1", {"hourly_rate_usd": 80.0})
    assert out.material_thickness_map == {"unobtainium": 3.0}
    # ...but writing it is validated.
    with pytest.raises(ValueError, match="unknown material 'unobtainium'"):
        await svc.update_machine(_FakeSession(), "org", "m1",
                                 {"material_thickness_map": {"unobtainium": 3.0}})


# ── material_thickness_map keys use the material vocabulary ───────────────────
def test_thickness_map_unknown_material_reported():
    with pytest.raises(ValueError, match="material_thickness_map has unknown material 'unobtainium'"):
        svc.validate_machine({**_good_machine(), "material_thickness_map": {"unobtainium": 3}})
    with pytest.raises(ValueError, match="unknown material '@6061'"):  # @ marks a class only
        svc.validate_machine({**_good_machine(), "material_thickness_map": {"@6061": 3}})
    with pytest.raises(ValueError, match="twice"):
        svc.validate_machine({**_good_machine(),
                              "material_thickness_map": {"6061": 3, "6061-T6 Aluminum": 4}})


def test_thickness_map_keys_stored_as_the_names_the_engine_looks_up():
    fields = {**_good_machine(),
              "material_thickness_map": {"6061": 3, "Steel": 20, "@aluminum": 4, "SS316L": 6}}
    svc.validate_machine(fields)
    assert svc._normalize(fields)["material_thickness_map"] == {
        "6061-T6 Aluminum": 3, "steel": 20, "@aluminum": 4, "SS316L": 6,
    }


# ── shop-op names are case/separator-insensitive ──────────────────────────────
def test_shop_op_names_normalized_and_collisions_reported():
    assert svc._normalize_shop_ops({"HIP": True, "Stress Relief": True, "heat-treat": True}) == {
        "hip": True, "stress_relief": True, "heat_treat": True,
    }
    with pytest.raises(ValueError, match="duplicates"):
        svc.validate_shop_ops({"HIP": True, "hip": {"dia_mm": 300}})


@pytest.mark.asyncio
async def test_uppercase_shop_op_satisfies_engine_requirement(monkeypatch):
    import types

    from src.costing.makeability import MachineCap, PartReq, fit_machine

    session = _FakeSession()

    async def no_row(s, org_id):
        return None

    monkeypatch.setattr(svc, "get_shop_capabilities", no_row)
    stored = await svc.upsert_shop_capabilities(session, "org", {"HIP": True})
    assert stored.ops == {"hip": True}

    async def legacy_row(s, org_id):  # saved before names were canonicalized
        return types.SimpleNamespace(ops={"HIP": True})

    monkeypatch.setattr(svc, "get_shop_capabilities", legacy_row)
    shop = await svc.load_shop_caps(session, "org")
    assert shop.ops == {"hip": True}

    machine = MachineCap(process="dmls", name="M400", max_workpiece_kg=50.0,
                         materials=("Ti6Al4V",),
                         capabilities={"x": 400, "y": 400, "z": 400})
    part = PartReq(process="dmls", bbox_mm=(50, 50, 50), mass_kg=1.0,
                   material_name="Ti6Al4V", material_class="titanium",
                   required_secondary_ops=("hip",))
    assert fit_machine(part, machine, shop).passes


# ── unknown top-level fields are reported like unknown capability keys ────────
def test_unknown_top_level_field_reported():
    with pytest.raises(ValueError, match="unknown field 'colour'"):
        svc.validate_machine({**_good_machine(), "colour": "red"})
    with pytest.raises(ValueError, match="provenance must be"):
        svc.validate_machine({**_good_machine(), "provenance": "measured"})
    for marker in (None, "user", "catalog_template"):
        svc.validate_machine({**_good_machine(), "provenance": marker})  # no raise
    # provenance is never stored
    assert "provenance" not in svc._normalize({**_good_machine(), "provenance": "user"})


@pytest.mark.asyncio
async def test_unknown_field_on_patch_reported(monkeypatch):
    async def fake_get(session, org_id, ulid):
        return _stored_lathe()

    monkeypatch.setattr(svc, "get_machine", fake_get)
    with pytest.raises(ValueError, match="unknown field 'hourly_rate'"):
        await svc.update_machine(_FakeSession(), "org", "m1", {"hourly_rate": 80.0})


def _validation_app(monkeypatch, session=None):
    """The real router with auth/org/storage stubbed out, so request parsing and
    validation run for real without a database."""
    from fastapi import FastAPI

    import src.api.machine_inventory as api
    from src.auth.kill_switch import require_kill_switch_open
    from src.auth.rate_limit import limiter
    from src.auth.require_api_key import AuthedUser, require_api_key
    from src.db.engine import get_db_session

    async def org(session, user_id):
        return "org-test"

    async def stored(session, org_id, ulid):
        return _stored_lathe()

    async def no_db():
        yield session if session is not None else _FakeSession()

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(api, "resolve_org", org)
    monkeypatch.setattr(svc, "get_machine", stored)
    monkeypatch.setattr(api.part_summary_service, "mark_org_makeability_stale_safe", noop)
    monkeypatch.setattr(api, "_emit_machine_audit", noop)
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(api.router, prefix="/api/v1/machine-inventory")
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=1, api_key_id=0, key_prefix="session", role="analyst")
    app.dependency_overrides[get_db_session] = no_db
    app.dependency_overrides[require_kill_switch_open] = lambda: None
    return app


@pytest.mark.asyncio
async def test_every_catalog_entry_posts_unedited_over_http(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    session = _FakeSession()
    app = _validation_app(monkeypatch, session)
    opts = svc.catalog_options()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        for payload in opts:
            r = await ac.post("/api/v1/machine-inventory", json=payload)
            assert r.status_code == 201, (payload["name"], r.text)
            assert r.json()["provenance"] == "user"
    assert len(session.added) == len(opts)
    for row, payload in zip(session.added, opts):
        assert row.materials == payload["materials"]
        assert row.capabilities == payload["capabilities"]


@pytest.mark.asyncio
async def test_unknown_top_level_fields_are_a_400_over_http(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    app = _validation_app(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/api/v1/machine-inventory",
                          json={"process": "cnc_3axis", "colour": "red"})
        assert r.status_code == 400, r.text
        assert "unknown field 'colour'" in r.json()["detail"]
        r = await ac.patch("/api/v1/machine-inventory/m1", json={"hourly_rate": 80})
        assert r.status_code == 400, r.text
        assert "unknown field 'hourly_rate'" in r.json()["detail"]
        r = await ac.put("/api/v1/machine-inventory/shop-capabilities",
                         json={"opps": {"hip": True}})
        assert r.status_code == 400, r.text
        assert "unknown field 'opps'" in r.json()["detail"]


# ── printer details (additive capability keys) ────────────────────────────────
def _printer(**caps) -> dict:
    return {
        "name": "Bambu Lab X1C", "process": "fdm", "count": 1,
        "capabilities": {"x": 256, "y": 256, "z": 256, **caps},
        "materials": ["PLA", "PETG"],
    }


_FDM_DETAILS = {"nozzle_dia_mm": 0.4, "min_layer_um": 80, "max_layer_um": 280,
                "enclosure": "heated", "max_chamber_c": 60,
                "stocked_materials": ["pla", "PETG"]}


def test_printer_details_validate_on_a_filament_printer():
    svc.validate_machine(_printer(**_FDM_DETAILS))  # no raise
    for enclosure in ("none", "enclosed"):
        svc.validate_machine(_printer(enclosure=enclosure))
    # Resin printers carry a layer range and stocked resin, nothing filament-only.
    svc.validate_machine({"process": "sla", "capabilities": {
        "min_layer_um": 25, "max_layer_um": 300, "stocked_materials": ["Standard Resin"]}})
    # Metal powder bed and binder jetting carry a layer range.
    for process in ("dmls", "slm", "ebm", "binder_jetting", "sls", "mjf"):
        svc.validate_machine({"process": process, "capabilities": {"min_layer_um": 20, "max_layer_um": 100}})


def test_printer_details_on_the_wrong_method_are_reported():
    cases = [
        ("cnc_3axis", {"nozzle_dia_mm": 0.4}, "'nozzle_dia_mm' applies to fdm machines only (got cnc_3axis)"),
        ("sla", {"enclosure": "heated"}, "'enclosure' applies to fdm machines only (got sla)"),
        ("ded", {"max_layer_um": 300}, "'max_layer_um' applies to"),
        ("mjf", {"stocked_materials": ["PA12 (Nylon 12)"]}, "'stocked_materials' applies to dlp, fdm, sla"),
        ("cnc_turning", {"max_chamber_c": 60}, "'max_chamber_c' applies to fdm"),
    ]
    for process, caps, msg in cases:
        with pytest.raises(ValueError, match=re.escape(msg)):
            svc.validate_machine({"process": process, "capabilities": caps})
    # The older min_layer_um key stays accepted on any machine (no stored row breaks).
    svc.validate_machine({"process": "cnc_3axis", "capabilities": {"min_layer_um": 40}})


def test_printer_details_are_checked_against_each_other_and_the_registry():
    bad = [
        ({"nozzle_dia_mm": 0}, "'nozzle_dia_mm' must be > 0"),
        ({"nozzle_dia_mm": "0.4"}, "'nozzle_dia_mm' must be a finite number"),
        ({"min_layer_um": 300, "max_layer_um": 100}, "max_layer_um (100) must be >= min_layer_um (300)"),
        ({"enclosure": "warm"}, "enclosure must be one of ['enclosed', 'heated', 'none']"),
        ({"enclosure": "enclosed", "max_chamber_c": 60}, "max_chamber_c needs enclosure 'heated'"),
        ({"max_chamber_c": 60}, "max_chamber_c needs enclosure 'heated'"),
        ({"enclosure": "heated", "max_chamber_c": -5}, "'max_chamber_c' must be > 0"),
        ({"stocked_materials": "PLA"}, "stocked_materials must be a list"),
        ({"stocked_materials": ["PA12-CF"]}, "stocked_materials has unknown material 'PA12-CF'"),
        ({"stocked_materials": [""]}, "stocked_materials entries must be non-empty strings"),
    ]
    for caps, msg in bad:
        with pytest.raises(ValueError, match=re.escape(msg)):
            svc.validate_machine(_printer(**caps))


def test_stocked_materials_are_stored_under_canonical_names():
    out = svc._normalize(_printer(stocked_materials=["pla", "Polymer", "petg"]))
    assert out["capabilities"]["stocked_materials"] == ["PLA", "polymer", "PETG"]
    # Nothing else in the bag changes.
    assert {k: v for k, v in out["capabilities"].items() if k != "stocked_materials"} == {"x": 256, "y": 256, "z": 256}


def test_catalog_prefill_carries_the_layer_range_on_layered_printers_only():
    by_name = {o["name"]: o for o in svc.catalog_options()}
    assert by_name["Bambu Lab X1C"]["capabilities"]["min_layer_um"] == 40.0
    assert by_name["Bambu Lab X1C"]["capabilities"]["max_layer_um"] == 400.0
    assert by_name["HP Jet Fusion 5200"]["capabilities"]["max_layer_um"] == 80.0
    assert "max_layer_um" not in by_name["Haas VF-2"]["capabilities"]
    for o in svc.catalog_options():  # and every prefill still validates unedited
        svc.validate_machine(o)


@pytest.mark.asyncio
async def test_printer_details_round_trip_over_http(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    session = _FakeSession()
    app = _validation_app(monkeypatch, session)
    stored = _stored_lathe(ulid="m1", created_at=None)

    async def get_stored(session, org_id, ulid):
        return stored

    monkeypatch.setattr(svc, "get_machine", get_stored)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/api/v1/machine-inventory", json=_printer(**_FDM_DETAILS))
        assert r.status_code == 201, r.text
        caps = r.json()["capabilities"]
        assert caps == {"x": 256, "y": 256, "z": 256, **_FDM_DETAILS,
                        "stocked_materials": ["PLA", "PETG"]}
        assert session.added[-1].capabilities == caps

        # A detail on a method that can't carry it is a 400, never dropped.
        r = await ac.post("/api/v1/machine-inventory",
                          json={"process": "cnc_3axis", "capabilities": {"nozzle_dia_mm": 0.4}})
        assert r.status_code == 400, r.text
        assert "applies to fdm machines only" in r.json()["detail"]

        # PATCH: the stored lathe can't take a nozzle; turned into a printer it can.
        r = await ac.patch("/api/v1/machine-inventory/m1",
                           json={"capabilities": {"swing_dia": 254, "nozzle_dia_mm": 0.4}})
        assert r.status_code == 400, r.text
        r = await ac.patch("/api/v1/machine-inventory/m1", json={
            "process": "fdm", "materials": ["PLA"],
            "capabilities": {"x": 256, "y": 256, "z": 256, "nozzle_dia_mm": 0.6, "enclosure": "none"}})
        assert r.status_code == 200, r.text
        assert r.json()["capabilities"]["nozzle_dia_mm"] == 0.6
        assert r.json()["capabilities"]["enclosure"] == "none"
        assert stored.capabilities == r.json()["capabilities"]


def test_printer_details_import_from_csv():
    caps = json.dumps({"x": 256, "y": 256, "z": 256, "nozzle_dia_mm": 0.4,
                       "enclosure": "enclosed", "stocked_materials": ["PLA"]})
    bad = json.dumps({"nozzle_dia_mm": 0.4})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["process", "name", "capabilities"])
    w.writerow(["fdm", "X1C", caps])
    w.writerow(["cnc_3axis", "VF-2", bad])
    rows, errors = svc.parse_machine_csv(buf.getvalue())
    assert [r["name"] for r in rows] == ["X1C"]
    assert rows[0]["capabilities"]["stocked_materials"] == ["PLA"]
    assert errors and errors[0]["line"] == 3 and "applies to fdm machines only" in errors[0]["reason"]


# ── pure: service-environment validation ──────────────────────────────────────
def test_service_environment_valid():
    pcs.validate_service_environment(
        {"max_temp_c": 200, "min_temp_c": -40, "pressure_bar": 150,
         "corrosive": True, "sour_service": True, "medium": "sour gas",
         "standard": "NACE MR0175"}
    )


def test_service_environment_none_ok():
    pcs.validate_service_environment(None)


def test_service_environment_unknown_key_rejected():
    with pytest.raises(ValueError, match="unknown service_environment field"):
        pcs.validate_service_environment({"temperature": 200})


def test_service_environment_bad_types_rejected():
    with pytest.raises(ValueError, match="max_temp_c must be a number"):
        pcs.validate_service_environment({"max_temp_c": "hot"})
    with pytest.raises(ValueError, match="corrosive must be a boolean"):
        pcs.validate_service_environment({"corrosive": "yes"})
    with pytest.raises(ValueError, match="pressure_bar must be >= 0"):
        pcs.validate_service_environment({"pressure_bar": -1})


def test_validate_context_rejects_bad_env():
    with pytest.raises(ValueError, match="unknown service_environment field"):
        pcs.validate_context({"service_environment": {"bogus": 1}})


# ── real-app routing guards (defect A) ───────────────────────────────────────
# The org inventory router mounts a bare @router.get("") LIST. When it shared the
# /api/v1/machines prefix with the pre-existing global AM reference-catalog GET in
# src/api/routes.py, Starlette's first-match-wins silently shadowed the org LIST —
# and the collision escaped review because the DB tests only mount the sub-router
# in ISOLATION. These guards compose the REAL app (main.app) so any future
# re-claim of an existing route fails loudly.
def _real_app():
    import importlib
    import main

    # Some endpoint tests install dependency overrides or reload ``main`` with
    # altered auth modes. These guards are about the composed route table itself,
    # so always inspect a fresh app instance.
    return importlib.reload(main).app


def _join_route(prefix: str, path: str) -> str:
    if not prefix:
        return path or ""
    if not path:
        return prefix
    return f"{prefix.rstrip('/')}/{path.lstrip('/')}"


def _iter_routes_with_paths(app_or_router, prefix: str = ""):
    routes = getattr(getattr(app_or_router, "router", None), "routes", None)
    if routes is None:
        routes = getattr(app_or_router, "routes", [])
    for route in routes:
        include_context = getattr(route, "include_context", None)
        original_router = getattr(route, "original_router", None)
        if include_context is not None and original_router is not None:
            child_prefix = _join_route(prefix, getattr(include_context, "prefix", ""))
            yield from _iter_routes_with_paths(original_router, child_prefix)
            continue

        route_path = getattr(route, "path", None) or getattr(route, "path_format", None)
        if route_path is not None and getattr(route, "methods", None):
            yield route, _join_route(prefix, route_path)


def _routes_for(app, path: str):
    return [r for r, route_path in _iter_routes_with_paths(app) if route_path == path]


def test_machine_inventory_list_reachable_on_real_app():
    """GET /api/v1/machine-inventory resolves to the ORG inventory LIST handler
    (src.api.machine_inventory) on the composed app — not the AM reference catalog."""
    app = _real_app()
    inv = [
        r
        for r in _routes_for(app, "/api/v1/machine-inventory")
        if "GET" in (r.methods or set())
    ]
    assert len(inv) == 1, "org inventory LIST must be registered exactly once"
    assert inv[0].endpoint.__module__ == "src.api.machine_inventory"


def test_machines_path_is_still_reference_catalog():
    """GET /api/v1/machines remains the global AM reference catalog — the org
    inventory no longer collides with (and shadows) it."""
    app = _real_app()
    ref = [
        r
        for r in _routes_for(app, "/api/v1/machines")
        if "GET" in (r.methods or set())
    ]
    assert len(ref) == 1, "reference-catalog GET /api/v1/machines must be unique"
    assert ref[0].endpoint.__module__ == "src.api.routes"


def test_no_duplicate_route_registration_in_real_app():
    """PERMANENT guard: no (method, path) pair is registered twice ANYWHERE in the
    composed app. This is the check that would have caught the machine-inventory
    collision; it must fail if any future router re-claims an existing route."""
    from collections import Counter

    app = _real_app()
    pairs: list = []
    for r, path in _iter_routes_with_paths(app):
        methods = getattr(r, "methods", None)
        if not methods or not path:
            continue
        for m in methods:
            if m in ("HEAD", "OPTIONS"):  # framework-added, never a real collision
                continue
            pairs.append((m, path))
    dupes = {k: n for k, n in Counter(pairs).items() if n > 1}
    assert not dupes, f"duplicate (method, path) route registrations: {dupes}"


# ── optional end-to-end (real Postgres) ──────────────────────────────────────
_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)


async def _seed_org_user(s, oid: str, label: str) -> int:
    from ulid import ULID
    from sqlalchemy import text

    await s.execute(
        text(
            "INSERT INTO organizations (id, name, slug, created_at) "
            "VALUES (:id, :n, :sl, now())"
        ),
        {"id": oid, "n": f"Org {label} {oid[-8:]}", "sl": f"org-{oid[-8:].lower()}"},
    )
    email = f"mach-{oid[-8:]}-{label}@example.com"
    uid = int(
        (
            await s.execute(
                text(
                    "INSERT INTO users (email, email_lower, role, auth_provider) "
                    "VALUES (:e, :el, 'analyst', 'password') RETURNING id"
                ),
                {"e": email, "el": email.lower()},
            )
        ).first()[0]
    )
    await s.execute(
        text(
            "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
            "VALUES (:id, :o, :u, 'admin', now())"
        ),
        {"id": str(ULID()), "o": oid, "u": uid},
    )
    return uid


@_requires_pg
@pytest.mark.asyncio
async def test_machine_import_row_failure_preserves_adjacent_rows():
    from ulid import ULID
    import src.db.engine as eng

    try:
        async with eng.get_session_factory()() as s:
            oid = str(ULID())
            uid = await _seed_org_user(s, oid, "import-savepoint")
            summary = await svc.import_machines(s, oid, uid, [
                {**_good_machine(), "name": "first"},
                # Exercise a real storage refusal independently of CSV validation.
                {**_good_machine(), "name": "invalid", "count": 2**31},
                {**_good_machine(), "name": "last"},
            ])
            assert (summary["imported"], summary["skipped"], summary["total"]) == (2, 1, 3)
            assert "INSERT" not in summary["errors"][0]["reason"]
            assert "asyncpg" not in summary["errors"][0]["reason"]
            assert {m.name for m in await svc.load_org_inventory(s, oid)} == {"first", "last"}
            await s.rollback()
    finally:
        await eng.dispose_engine()


async def _cleanup(oids: list[str], uids: list[int]) -> None:
    from sqlalchemy import text
    import src.db.engine as eng

    async with eng.get_session_factory()() as s:
        await s.execute(
            text("DELETE FROM machine_instances WHERE org_id = ANY(:o)"), {"o": oids}
        )
        await s.execute(
            text("DELETE FROM shop_capabilities WHERE org_id = ANY(:o)"), {"o": oids}
        )
        await s.execute(
            text("DELETE FROM part_contexts WHERE org_id = ANY(:o)"), {"o": oids}
        )
        if uids:
            await s.execute(
                text("DELETE FROM memberships WHERE user_id = ANY(:i)"), {"i": uids}
            )
            await s.execute(text("DELETE FROM users WHERE id = ANY(:i)"), {"i": uids})
        await s.execute(
            text("DELETE FROM organizations WHERE id = ANY(:o)"), {"o": oids}
        )
        await s.commit()


def _build_app():
    from fastapi import FastAPI
    from src.api.machine_inventory import router as m_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(m_router, prefix="/api/v1/machine-inventory")
    return app


def _act_as(app, user_id: int) -> None:
    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id, api_key_id=0, key_prefix="session", role="analyst"
    )


@_requires_pg
@pytest.mark.asyncio
async def test_crud_and_org_isolation():
    from httpx import ASGITransport, AsyncClient
    from ulid import ULID
    import src.db.engine as eng

    org_a, org_b = str(ULID()), str(ULID())
    uids: list[int] = []
    async with eng.get_session_factory()() as s:
        a1 = await _seed_org_user(s, org_a, "A")
        b1 = await _seed_org_user(s, org_b, "B")
        uids += [a1, b1]
        await s.commit()

    app = _build_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            _act_as(app, a1)
            body = {
                "name": "VF-2 #1", "process": "cnc_3axis", "count": 2,
                "max_workpiece_kg": 200, "hourly_rate_usd": 75, "capital_frac": 0.4,
                "capabilities": {"x": 762, "y": 406, "z": 508, "axes": 3,
                                 "achievable_it_grade": 9},
                "materials": ["304 Stainless"],
            }
            r = await ac.post("/api/v1/machine-inventory", json=body)
            assert r.status_code == 201, r.text
            mid = r.json()["id"]
            assert r.json()["provenance"] == "user"

            # a malformed field is a 400, never coerced
            bad = dict(body)
            bad["capital_frac"] = 5
            rb = await ac.post("/api/v1/machine-inventory", json=bad)
            assert rb.status_code == 400
            assert "capital_frac" in rb.json()["detail"]

            # read back
            g = await ac.get(f"/api/v1/machine-inventory/{mid}")
            assert g.json()["count"] == 2

            # patch (partial; merged result re-validated)
            p = await ac.patch(f"/api/v1/machine-inventory/{mid}", json={"count": 3})
            assert p.status_code == 200 and p.json()["count"] == 3

            # list
            lst = (await ac.get("/api/v1/machine-inventory")).json()
            assert [m["id"] for m in lst["machines"]] == [mid]

            # cross-tenant: org B sees nothing, cannot read A's machine
            _act_as(app, b1)
            assert (await ac.get("/api/v1/machine-inventory")).json()["machines"] == []
            assert (await ac.get(f"/api/v1/machine-inventory/{mid}")).status_code == 404
            assert (
                await ac.patch(f"/api/v1/machine-inventory/{mid}", json={"count": 9})
            ).status_code == 404
            assert (
                await ac.delete(f"/api/v1/machine-inventory/{mid}")
            ).status_code == 404

            # owner deletes
            _act_as(app, a1)
            assert (await ac.delete(f"/api/v1/machine-inventory/{mid}")).status_code == 200
            assert (await ac.get("/api/v1/machine-inventory")).json()["machines"] == []
    finally:
        await _cleanup([org_a, org_b], uids)
        await eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_csv_import_and_load_org_inventory():
    from httpx import ASGITransport, AsyncClient
    from ulid import ULID
    import src.db.engine as eng

    org_a, org_b = str(ULID()), str(ULID())
    uids: list[int] = []
    async with eng.get_session_factory()() as s:
        a1 = await _seed_org_user(s, org_a, "A")
        b1 = await _seed_org_user(s, org_b, "B")
        uids += [a1, b1]
        await s.commit()

    app = _build_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            _act_as(app, a1)
            caps = json.dumps({"x": 500, "y": 500, "z": 500, "axes": 5,
                               "motion_mode": "simultaneous_5"})
            text = _csv([
                {"process": "cnc_3axis", "name": "VF-2", "count": "1",
                 "hourly_rate_usd": "75", "materials": "steel|304 Stainless",
                 "capabilities": json.dumps({"x": 762, "y": 406, "z": 508})},
                {"process": "cnc_5axis", "name": "DMU-50", "capabilities": caps},
                {"process": "bogus", "name": "bad"},  # reported, skipped
            ])
            r = await ac.post(
                "/api/v1/machine-inventory/import",
                files={"file": ("m.csv", text.encode(), "text/csv")},
            )
            assert r.status_code == 200, r.text
            summ = r.json()
            assert summ["imported"] == 2
            assert summ["skipped"] == 1
            assert summ["total"] == 3
            assert summ["errors"][0]["line"] == 4

            # hydrate to the Phase-B MachineCap contract
            async with eng.get_session_factory()() as s2:
                caps_list = await svc.load_org_inventory(s2, org_a)
            assert len(caps_list) == 2
            by_proc = {c.process: c for c in caps_list}
            vf = by_proc["cnc_3axis"]
            assert vf.name == "VF-2"
            assert vf.count == 1
            assert vf.hourly_rate_usd == 75.0
            assert vf.materials == ("steel", "304 Stainless")
            assert vf.capabilities["x"] == 762
            assert isinstance(vf.material_thickness_map, dict)
            dmu = by_proc["cnc_5axis"]
            assert dmu.capabilities["axes"] == 5

            # org B is empty -> byte-identical empty inventory
            async with eng.get_session_factory()() as s3:
                assert await svc.load_org_inventory(s3, org_b) == []
    finally:
        await _cleanup([org_a, org_b], uids)
        await eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_shop_capabilities_and_load_shop_caps():
    from httpx import ASGITransport, AsyncClient
    from ulid import ULID
    import src.db.engine as eng

    org_a = str(ULID())
    uids: list[int] = []
    async with eng.get_session_factory()() as s:
        a1 = await _seed_org_user(s, org_a, "A")
        uids.append(a1)
        await s.commit()

    app = _build_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            _act_as(app, a1)
            # unset -> empty
            assert (await ac.get("/api/v1/machine-inventory/shop-capabilities")).json()["ops"] == {}
            ops = {"heat_treat": True, "hip": {"dia_mm": 300, "height_mm": 600}}
            r = await ac.put("/api/v1/machine-inventory/shop-capabilities", json={"ops": ops})
            assert r.status_code == 200
            assert r.json()["ops"]["hip"]["dia_mm"] == 300
            # malformed op -> 400
            rb = await ac.put(
                "/api/v1/machine-inventory/shop-capabilities", json={"ops": {"hip": "yes"}}
            )
            assert rb.status_code == 400

            async with eng.get_session_factory()() as s2:
                caps = await svc.load_shop_caps(s2, org_a)
            assert caps.ops["heat_treat"] is True
    finally:
        await _cleanup([org_a], uids)
        await eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_part_context_service_environment_upsert_read_isolation():
    from ulid import ULID
    import src.db.engine as eng

    org_a, org_b = str(ULID()), str(ULID())
    uids: list[int] = []
    mesh = str(ULID())
    async with eng.get_session_factory()() as s:
        a1 = await _seed_org_user(s, org_a, "A")
        b1 = await _seed_org_user(s, org_b, "B")
        uids += [a1, b1]
        await s.commit()

    try:
        env = {"max_temp_c": 200, "pressure_bar": 150, "sour_service": True,
               "standard": "NACE MR0175"}
        async with eng.get_session_factory()() as s:
            await pcs.upsert_context(
                s, org_a, mesh, {"program": "GF", "service_environment": env},
                created_by=a1,
            )
            await s.commit()

        async with eng.get_session_factory()() as s:
            row = await pcs.get_context(s, org_a, mesh)
            assert row.service_environment["max_temp_c"] == 200
            assert row.service_environment["sour_service"] is True
            ser = pcs.serialize_context(row)
            assert ser["service_environment"]["standard"] == "NACE MR0175"
            assert ser["provenance"] == "user"
            # cross-tenant: org B never sees A's context
            assert await pcs.get_context(s, org_b, mesh) is None

        # a bad env is rejected at upsert (never coerced)
        async with eng.get_session_factory()() as s:
            with pytest.raises(ValueError, match="unknown service_environment"):
                await pcs.upsert_context(
                    s, org_a, mesh, {"service_environment": {"bogus": 1}}
                )
    finally:
        await _cleanup([org_a, org_b], uids)
        await eng.dispose_engine()
