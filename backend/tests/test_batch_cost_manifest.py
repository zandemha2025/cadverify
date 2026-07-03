"""Unit tests for W3 cost-manifest parsing + the cost results CSV.

Manifest: the optional cost columns (quantities/region/material_class) are
validated against the same vectors POST /validate/cost accepts, with per-row
error messages; a DFM parse (validate_cost=False) ignores them entirely
(byte-identical). CSV: the cost branch shape + the honesty rule that a
DFM-blocked make-now route withholds its unit price while ``validated`` is copied
from the engine band.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.services import batch_service as bs


# ---------------------------------------------------------------------------
# Manifest parsing — cost columns
# ---------------------------------------------------------------------------


def test_cost_manifest_parses_optional_columns():
    csv = (
        "filename,quantities,region,material_class\n"
        "part1.stl,1;100;1000,EU,aluminum\n"
        "part2.stl,,,\n"                       # all cost columns blank → None
    )
    items = bs.parse_csv_manifest(csv, validate_cost=True)
    assert items[0]["filename"] == "part1.stl"
    assert items[0]["quantities"] == "1;100;1000"
    assert items[0]["region"] == "EU"
    assert items[0]["material_class"] == "aluminum"
    assert items[0]["shop"] is None
    # blank cells → engine defaults (None), not errors
    assert items[1]["quantities"] is None
    assert items[1]["region"] is None
    assert items[1]["material_class"] is None


def test_cost_manifest_rejects_bad_quantity_with_row_number():
    csv = "filename,quantities\ngood.stl,10;20\nbad.stl,10;abc\n"
    with pytest.raises(ValueError) as exc:
        bs.parse_csv_manifest(csv, validate_cost=True)
    assert "Row 3" in str(exc.value)
    assert "abc" in str(exc.value)


def test_cost_manifest_rejects_quantity_out_of_range():
    csv = "filename,quantities\nx.stl,0\n"      # 0 < 1
    with pytest.raises(ValueError) as exc:
        bs.parse_csv_manifest(csv, validate_cost=True)
    assert "Row 2" in str(exc.value)


def test_cost_manifest_rejects_too_many_quantities():
    csv = "filename,quantities\nx.stl,1;2;3;4;5;6;7\n"   # > _COST_MAX_QTYS (6)
    with pytest.raises(ValueError) as exc:
        bs.parse_csv_manifest(csv, validate_cost=True)
    assert "Row 2" in str(exc.value)
    assert "at most" in str(exc.value)


def test_cost_manifest_rejects_bad_region_and_material():
    with pytest.raises(ValueError) as exc:
        bs.parse_csv_manifest("filename,region\nx.stl,MARS\n", validate_cost=True)
    assert "region" in str(exc.value) and "Row 2" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        bs.parse_csv_manifest(
            "filename,material_class\nx.stl,unobtanium\n", validate_cost=True
        )
    assert "material_class" in str(exc.value) and "Row 2" in str(exc.value)


def test_dfm_manifest_ignores_cost_columns_byte_identical():
    """A DFM parse (validate_cost False) never looks at cost columns, so a stray
    'region' value does NOT error and no cost keys are added."""
    csv = "filename,region,priority\npart.stl,NOT_A_REGION,high\n"
    items = bs.parse_csv_manifest(csv)   # validate_cost defaults False
    assert items[0]["filename"] == "part.stl"
    assert items[0]["priority"] == "high"
    assert "region" not in items[0]      # cost columns untouched for DFM


# ---------------------------------------------------------------------------
# Cost results CSV — shape + withholding
# ---------------------------------------------------------------------------


def _cost_result(*, make_now="cnc_3axis", dfm_ready=True, unit=40.0, validated=False):
    return {
        "quantities": [50, 5000],
        "decision": {"make_now_process": make_now, "crossover_qty": 1200.0},
        "estimates": [
            {
                "process": make_now,
                "quantity": 50,
                "unit_cost_usd": unit,
                "dfm_ready": dfm_ready,
                "dfm_blockers": [] if dfm_ready else ["Wall too thin for CNC."],
                "confidence": {"validated": validated},
                "drivers": [],
            }
        ],
    }


def _bi(fname, status, err=None):
    return SimpleNamespace(id=1, filename=fname, status=status, error_message=err)


def _cd(ulid, result):
    return SimpleNamespace(
        ulid=ulid,
        make_now_process=(result.get("decision") or {}).get("make_now_process"),
        crossover_qty=(result.get("decision") or {}).get("crossover_qty"),
        quantities=result.get("quantities"),
        result_json=result,
    )


class _CsvResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _CsvSession:
    def __init__(self, rows):
        self._rows = rows
        self._served = False

    async def execute(self, stmt):
        # First page returns all rows; subsequent pages are empty (< page size
        # → the generator stops after one page).
        if self._served:
            return _CsvResult([])
        self._served = True
        return _CsvResult(self._rows)


@pytest.mark.asyncio
async def test_cost_csv_shape_and_withholding():
    rows = [
        (_bi("ok.stl", "completed"), _cd("CD1", _cost_result(dfm_ready=True, unit=40.0))),
        # blocked make-now route → unit price withheld (empty), validated still copied
        (_bi("blocked.stl", "completed"),
         _cd("CD2", _cost_result(dfm_ready=False, unit=99.0))),
        # failed item, no decision → all cost columns empty, error present
        (_bi("bad.stl", "failed", err="boom"), None),
    ]
    session = _CsvSession(rows)

    out = []
    async for chunk in bs.generate_results_csv(session, batch_id=1, job_type="cost"):
        out.append(chunk)
    text = "".join(out)
    lines = text.strip().split("\n")

    assert lines[0] == (
        "filename,status,make_now_process,crossover_qty,quantities,"
        "unit_cost_usd,validated,cost_decision_url,error"
    )
    # ok row: price present, validated False, url present
    ok = lines[1].split(",")
    assert ok[0] == "ok.stl" and ok[2] == "cnc_3axis"
    assert ok[4] == "50;5000"
    assert ok[5] == "40.0"                       # unit_cost_usd present
    assert ok[6] == "False"
    assert ok[7] == "/api/v1/cost-decisions/CD1"

    # blocked row: unit_cost_usd WITHHELD (empty), everything else still there
    blocked = lines[2].split(",")
    assert blocked[0] == "blocked.stl"
    assert blocked[5] == ""                       # price withheld on blocked route
    assert blocked[6] == "False"                  # validated still copied
    assert blocked[7] == "/api/v1/cost-decisions/CD2"

    # failed row: no decision → cost columns empty, error carried
    failed = lines[3].split(",")
    assert failed[0] == "bad.stl" and failed[1] == "failed"
    assert failed[2] == "" and failed[5] == "" and failed[7] == ""
    assert failed[-1] == "boom"
