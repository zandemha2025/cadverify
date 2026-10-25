"""The cited service-environment exclusions come out in one order on every worker.

``verification.env_exclusions`` follows the material list the environment gate is
handed. ``makeability.verify_part`` and ``estimate._build_verification`` built that
list from a set, so its order (and the first exclusion, the one the UI and the
catalog run show as the reason) changed with each interpreter's string-hash seed.
The same part, run in fresh interpreters under different PYTHONHASHSEED values,
must now give the same list, sorted by material as the decision note names them.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# A 3 mm steel plate in sour service: Mild Steel and Ductile Iron are both ruled
# out, and a sheet route brings a third material into the set. Without machines
# the estimate's own gate cites them; with one, verify_part's gate does.
CODE = """
import json
import trimesh
from src.api.routes import _run_cost_engine
from src.costing import EstimateOptions, estimate_decision, report_to_dict
from src.costing.makeability import MachineCap, ShopCaps

result, mesh, features = _run_cost_engine(trimesh.creation.box(extents=(120, 80, 3)), "plate.stl")
out = {}
for name, extra in (("no_machines", {}),
                    ("with_machine", {"inventory": (MachineCap(process="cnc_3axis", name="Mill"),),
                                      "shop_caps": ShopCaps(ops={})})):
    opts = EstimateOptions(quantities=[1, 100], material_class="steel", material_class_is_user=True,
                           service_environment={"sour_service": True}, **extra)
    rep = report_to_dict(estimate_decision(result, mesh.copy(), features, opts))
    out[name] = [f["axis"] for f in rep["verification"]["env_exclusions"]]
print(json.dumps(out))
"""


def test_env_exclusions_do_not_depend_on_the_hash_seed():
    runs = [json.loads(subprocess.check_output(
        [sys.executable, "-c", CODE], cwd=Path(__file__).resolve().parents[1],
        env=dict(os.environ, PYTHONHASHSEED=str(seed)), text=True,
    )) for seed in (0, 1, 2, 3)]
    assert all(r == runs[0] for r in runs), runs
    for name, axes in runs[0].items():
        assert {"Mild Steel", "Ductile Iron"} <= set(axes), (name, axes)
        assert axes == sorted(axes), (name, axes)
