"""Lengths in the person's unit on exports (``src.services.length_units``) and the cost PDF."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.services import length_units as lu


def test_exact_conversions_with_units():
    assert lu.length(25.4, "in") == "1.000 in"
    assert lu.length(1306, "in") == "51.42 in"
    assert lu.length(12.5, "mm") == "12.5 mm"
    assert lu.dims([100, 50, 20], "in") == "3.937 × 1.969 × 0.787 in"
    assert lu.dims([100, 50, 20], "mm") == "100 × 50 × 20 mm"
    assert lu.dims([], "in") == "—"
    assert lu.area_cm2(6.4516, "in") == "1.00 in²"
    assert lu.volume_cm3(16.387064, "in") == "1.000 in³"
    assert lu.volume_cm3(None, "in") == "N/A"


def test_engine_text_converts_only_lengths():
    assert lu.in_text("too big: needs 1306 mm, has 1005 mm", "in") == "too big: needs 51.42 in, has 39.57 in"
    assert lu.in_text("bbox 10 × 20 × 30 mm at $45.00/hr, Ra 0.8 µm", "in") == "bbox 0.394 × 0.787 × 1.181 in at $45.00/hr, Ra 0.8 µm"
    assert lu.in_text("volume 16.387064 cm³", "in") == "volume 1.000 in³"
    assert lu.in_text("needs 1306 mm", "mm") == "needs 1306 mm"
    assert lu.in_text(None, "in") is None


@pytest.mark.asyncio
async def test_unit_for_a_person_defaults_to_mm():
    class _S:
        def __init__(self, prefs):
            self.prefs = prefs

        async def get(self, _model, _id):
            return SimpleNamespace(preferences=self.prefs) if self.prefs is not None else None

    assert await lu.length_unit_for(_S({"length_unit": "in"}), 1) == "in"
    assert await lu.length_unit_for(_S({"length_unit": "ft"}), 1) == "mm"
    assert await lu.length_unit_for(_S(None), 1) == "mm"


def test_cost_pdf_html_shows_the_chosen_unit_and_the_part_specs():
    from src.db.models import CostDecision
    from src.services.cost_pdf_service import render_cost_html

    result = {
        "filename": "b.step", "status": "OK", "material_class": "aluminum", "quantities": [10],
        "geometry": {"volume_cm3": 16.387064, "surface_area_cm2": 64.516, "bbox_mm": [25.4, 50.8, 76.2],
                     "watertight": True, "face_count": 12},
        "estimates": [], "engine_feasibility": [], "notes": ["Fits its 256 × 256 × 256 mm work area."],
        "assumptions": [], "decision": None,
        "specs": {"summary": ["Finish: Anodize, Type II", "Supplier must hold: AS9100"], "excluded_processes": ["fdm"]},
    }
    d = CostDecision(ulid="01PDFUNITS0000000000000000", org_id="o", user_id=1, mesh_hash="m" * 64, params_hash="p",
                     engine_version="t", filename="b.step", file_type="step", result_json=result)
    d.created_at = datetime(2026, 10, 22, tzinfo=timezone.utc)
    inch = render_cost_html(d, length_unit="in")
    assert "1.000 × 2.000 × 3.000 in" in inch and "1.000 in³" in inch and "10.00 in²" in inch
    assert "10.08 × 10.08 × 10.08 in work area" in inch
    assert "Part specs" in inch and "Supplier must hold: AS9100" in inch and "Ruled out by these specs" in inch
    mm = render_cost_html(d)
    assert "25.4 × 50.8 × 76.2 mm" in mm and "256 × 256 × 256 mm" in mm
