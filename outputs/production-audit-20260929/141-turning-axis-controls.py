"""Run with backend/.venv/bin/python from the repository root."""
import hashlib
import json
from pathlib import Path
import sys

here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parents[1] / "backend"))

from src.api.routes import _parse_mesh
from src.analysis.base_analyzer import analyze_geometry
from src.analysis.features import detect_all
from src.costing.routing import is_rotational

for control in json.loads((here / "shape-controls/141-controls.json").read_text()):
    data = (here / "shape-controls" / control["filename"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == control["sha256"]
    mesh, _ = _parse_mesh(data, control["filename"])
    assert mesh.is_volume
    assert abs(mesh.volume - control["polygon_mesh_volume_mm3"]) < 0.002
    rotational, length, diameter = is_rotational(analyze_geometry(mesh), mesh, detect_all(mesh))
    assert rotational
    assert abs(length - control["length_mm"]) < 0.0001
    assert abs(diameter - 2 * control["radius_mm"]) < 0.0001
    print("PASS actual CAD:", control["filename"], length, diameter, mesh.volume)

receipts = json.loads((here / "141-native-cost-receipts.json").read_text())
current = [row for row in receipts if row["engine_version"] == "0.3.17"]
assert len(current) == 2
prices = []
for row in current:
    assert "axis 40mm × Ø10mm" in row["routing"]["reasoning"]
    prices.append([(estimate["quantity"], estimate["unit_cost_usd"]) for estimate in row["turning_estimates"]])
assert len(prices[0]) == 6 and prices[0] == prices[1]
print("PASS six saved native turning prices:", prices[0])
