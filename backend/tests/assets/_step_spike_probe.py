# STEP end-to-end spike probe — runs INSIDE the built deploy image against the
# LIVE code path, exercising the SAME two stages a real .step upload hits:
#   1) INGESTION: src/parsers/step_mesher.step_to_trimesh_from_bytes — the exact
#      function routes.py::_parse_mesh invokes for .step/.stp uploads.
#   2) DFM + COST: src.api.routes._run_cost_engine -> src.costing.estimate_decision
#      -> report_to_dict — the exact functions the public /validate/cost route
#      (routes.py::_run_cost_decision, demo path, no user/session) runs on the
#      parsed mesh. This is the full existing DFM+cost engine, not a stand-in.
#
# This file lives under backend/tests/ (dockerignored) and is MOUNTED into the
# container at run time, so it never enters the image — the image stays
# byte-identical to the Fly.io deploy image. Prints machine-greppable markers:
#   PARSE_OK / E2E_STEP_INGEST_OK  = ingestion boundary proven
#   DFM_OK / COST_OK / E2E_STEP_COST_OK = full DFM+cost engine proven on the mesh
from __future__ import annotations

import os
import sys

from src.parsers.step_mesher import is_step_supported, step_to_trimesh_from_bytes

print("is_step_supported:", is_step_supported())
if not is_step_supported():
    print("STEP_UNSUPPORTED_IN_IMAGE")
    sys.exit(1)

sample = os.environ.get("SAMPLE", "/samples/cube.step")
data = open(sample, "rb").read()
print("sample_path:", sample, "sample_bytes:", len(data))

mesh = step_to_trimesh_from_bytes(data, "cube.step")
print(
    "PARSE_OK vertices=%d triangles=%d watertight=%s volume_mm3=%.2f"
    % (len(mesh.vertices), len(mesh.faces), mesh.is_watertight, float(mesh.volume))
)
assert len(mesh.vertices) > 0 and len(mesh.faces) > 0, "empty mesh"
print("E2E_STEP_INGEST_OK")

# ── Stage 2: DFM + cost engine on the just-parsed mesh ──────────────────────
# Identical call sequence to the live public-demo cost route: _run_cost_engine
# (analyze_geometry + feature detection + per-process scoring) then
# estimate_decision (the should-cost/make-vs-buy engine) then report_to_dict.
# No env, no DB, no network — the costing layer opens zero sockets.
from src.api.routes import _run_cost_engine  # the exact live DFM wrapper
from src.costing import estimate_decision, EstimateOptions, report_to_dict

result, costed_mesh, features = _run_cost_engine(mesh, "cube.step")
print("DFM_OK process_scores=%d" % len(result.process_scores))
assert len(result.process_scores) > 0, "no process scores from DFM engine"

report = estimate_decision(result, costed_mesh, features, EstimateOptions())
report_dict = report_to_dict(report)
estimates = report_dict.get("estimates") or []
print("COST_OK status=%s estimates=%d" % (report.status, len(estimates)))
assert report.status == "OK", "cost engine did not return OK: %s" % report.status
assert estimates, "cost engine returned no estimates"
e0 = estimates[0]
print(
    "COST_SAMPLE process=%s qty=%s unit_cost_usd=%.4f dfm_verdict=%s"
    % (e0["process"], e0["quantity"], float(e0["unit_cost_usd"]), e0.get("dfm_verdict"))
)
print("E2E_STEP_COST_OK")
