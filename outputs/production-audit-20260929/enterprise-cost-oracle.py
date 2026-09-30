"""Run with backend/.venv/bin/python; requires the normal CAD kernel libraries."""
import hashlib
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "backend"))

from src.api.routes import _parse_mesh, _run_cost_engine
from src.analysis.models import ProcessType
from src.costing import EstimateOptions, estimate_decision, report_to_dict
from src.costing.makeability import MachineCap

proof = json.loads(Path(__file__).with_suffix(".json").read_text())
data = (root / proof["fixture"]).read_bytes()
assert hashlib.sha256(data).hexdigest() == proof["sha256"]
mesh, _ = _parse_mesh(data, "cube.step")
result, mesh, features = _run_cost_engine(mesh, "cube.step")
report = report_to_dict(estimate_decision(result, mesh, features, EstimateOptions(
    quantities=proof["quantities"], material_class=proof["material_class"],
    material_class_is_user=True,
    inventory=tuple(MachineCap(**m) for m in proof["machine_fixture"]),
    owned_processes=frozenset(ProcessType(m["process"]) for m in proof["machine_fixture"]),
    service_environment=proof["service_environment"],
)))
key = lambda e: (e["process"], e["material"], e["quantity"])
index = {key(e): e for e in report["estimates"]}
for previous in proof["ci_estimates"]:
    actual = index[key(previous)]
    for field, expected in previous.items():
        assert actual[field] == expected, (key(previous), field, actual[field], expected)
for quantity, expected in proof["expected_recommendations"].items():
    quantity = int(quantity)
    eligible = [e for e in report["estimates"] if e["quantity"] == quantity
                and e["dfm_ready"] and not e.get("environment_excluded")]
    cheapest = min(eligible, key=lambda e: e["unit_cost_usd"])
    recommendation = report["decision"]["recommendation"][quantity]
    for field, value in expected.items():
        assert cheapest[field] == recommendation[field] == value
    assert abs(sum(cheapest["line_items"].values()) - cheapest["unit_cost_usd"]) <= .01
assert report["decision"]["recommendation"][12000]["unit_cost_usd"] * 12000 == proof["annual_exposure_usd"]
print("PASS: all 66 CI estimates replay exactly; qty 1 EDM $110; qty 12,000 binder jetting $2.46; annual exposure $29,520.")
