"""Run with backend/.venv/bin/python from the repository root."""
import hashlib
import json
import math
from pathlib import Path
import sys

here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parents[1] / "backend"))

from src.api.routes import _parse_mesh
from src.analysis.base_analyzer import analyze_geometry
from src.analysis.features import detect_all
from src.analysis.models import ProcessType
from src.costing.cost_model import cost_breakdown, _cnc_cycle
from src.costing.drivers import extract_drivers
from src.costing.rates import build_rate_card
from src.costing.routing import select_material

process = ProcessType.CNC_TURNING
rates = build_rate_card()
material = select_material(process, "aluminum", rates)
receipts = {row["filename"]: row for row in json.loads((here / "143-native-cost-receipts.json").read_text())}
for control in json.loads((here / "shape-controls/142-controls.json").read_text()):
    data = (here / "shape-controls" / control["filename"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == control["sha256"]
    mesh, _ = _parse_mesh(data, control["filename"])
    drivers = extract_drivers(analyze_geometry(mesh), mesh, detect_all(mesh))
    assert drivers.rotational
    stock = math.pi * (control["diameter_mm"] / 2) ** 2 * control["axis_length_mm"] / 1000 * 1.1
    expected_material = stock * 2.7 / 1000 * 5 * 1.05
    estimate = cost_breakdown(process, drivers, material, "aluminum", 1, rates, "US")
    assert abs(estimate.line_items["material"] - expected_material) < 0.0001
    cycle, finish, source = _cnc_cycle(process, drivers, "aluminum", rates)
    assert abs((cycle - finish) - (stock - mesh.volume / 1000) / (30 * 60)) < 1e-8
    assert "1.10 stock allowance" in source
    receipt = receipts[control["filename"]]
    assert receipt["source_sha256"] == control["sha256"]
    assert receipt["previous"]["engine_version"] == "0.3.18"
    assert receipt["current"]["engine_version"] == "0.3.19"
    assert receipt["unchanged_other_estimates_count"] == 60
    estimates = receipt["current"]["turning_estimates"]
    assert len(estimates) == 6
    for saved in estimates:
        assert abs(saved["line_items"]["material"] - expected_material) < 0.0001
        assert abs(sum(saved["line_items"].values()) - saved["unit_cost_usd"]) < 0.01
        assert saved["dfm_ready"]
    saved_one = next(e for e in estimates if e["quantity"] == 1)
    independent_machine = ((stock - mesh.volume / 1000) / (30 * 60) + mesh.area / 100 / 800) * 65
    assert abs(saved_one["line_items"]["machine"] - independent_machine) < 0.0001
    print("PASS actual STEP stock:", control["filename"], stock, expected_material, cycle - finish)
print("PASS saved native material/machine calculations and six quantity totals per STEP.")
