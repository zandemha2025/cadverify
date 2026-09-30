"""Run with backend/.venv/bin/python from the repository root."""
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import trimesh

here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parents[1] / "backend"))

from src.api.routes import _parse_mesh
from src.analysis.base_analyzer import analyze_geometry
from src.analysis.features import detect_all
from src.costing.routing import is_rotational

for control in json.loads((here / "shape-controls/142-controls.json").read_text()):
    data = (here / "shape-controls" / control["filename"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == control["sha256"]
    mesh, _ = _parse_mesh(data, control["filename"])
    assert mesh.is_volume
    assert abs(mesh.volume / control["analytic_volume_mm3"] - 1) < 0.0005
    points = mesh.vertices
    if "prolate" in control["filename"]:
        # Reverse the known rigid rotation; check the independent ellipsoid equation.
        points = points @ trimesh.transformations.rotation_matrix(0.73, [1, 2, 3])[:3, :3]
        residual = np.abs(np.sum((points / [10, 10, 20]) ** 2, axis=1) - 1)
    else:
        residual = np.abs(((np.linalg.norm(points[:, :2], axis=1) - 15) ** 2 + points[:, 2] ** 2) / 36 - 1)
    assert float(np.max(residual)) < 1e-9
    rotational, length, diameter = is_rotational(analyze_geometry(mesh), mesh, detect_all(mesh))
    assert rotational
    assert abs(length - control["axis_length_mm"]) < 0.001
    assert abs(diameter - control["diameter_mm"]) < 0.001
    print("PASS actual STEP:", control["filename"], len(mesh.faces), length, diameter, mesh.volume)

receipts = json.loads((here / "142-native-cost-receipts.json").read_text())
assert len(receipts) == 4
for row in receipts:
    if row["engine_version"] == "0.3.17":
        assert row["turning_estimates"] == []
    else:
        assert row["engine_version"] == "0.3.18"
        assert row["routing"]["recommended_process"] == "cnc_turning"
        expected = "axis 40mm × Ø20mm" if "prolate" in row["filename"] else "axis 12mm × Ø42mm"
        assert expected in row["routing"]["reasoning"]
        assert len(row["turning_estimates"]) == 6
        assert all(e["dfm_ready"] and "NOT_ROTATIONALLY_SYMMETRIC" not in e["dfm_blockers"] for e in row["turning_estimates"])
print("PASS saved native results: old turning absent; new measured axes and six DFM-ready estimates each.")
