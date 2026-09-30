"""Run with backend/.venv/bin/python and the normal CAD library environment."""
import hashlib
import json
from pathlib import Path
import sys

here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parents[1] / "backend"))
from src.api.routes import _parse_mesh
from src.analysis.features import detect_all, has_rotational_surface_evidence

proof = json.loads((here / "circular-feature-regression.json").read_text())
for control in proof["controls"]:
    data = (here / "shape-controls" / control["filename"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == control["sha256"]
    mesh, _ = _parse_mesh(data, control["filename"])
    assert abs(mesh.volume / control["analytic_volume_mm3"] - 1) < 0.0005
    assert max(abs(mesh.extents - control["expected_extents_mm"])) < 0.001
    features = detect_all(mesh)
    assert sum(f.kind.value == "flat" for f in features) == control["expected_flats"]
    assert not any(f.kind.value.startswith("cylinder_") for f in features)
    if control["expected_rotational_evidence"] is not None:
        assert has_rotational_surface_evidence(features, mesh.area) == control["expected_rotational_evidence"]
    print("PASS:", control["filename"], "analytic dimensions/volume and surface classification")
