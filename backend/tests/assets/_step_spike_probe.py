# STEP-ingestion spike probe — runs INSIDE the built deploy image against the
# LIVE code path (src/parsers/step_mesher.step_to_trimesh_from_bytes), the exact
# function routes.py::_parse_mesh invokes for .step/.stp uploads.
#
# This file lives under backend/tests/ (dockerignored) and is MOUNTED into the
# container at run time, so it never enters the image — the image stays
# byte-identical to the Fly.io deploy image. Prints machine-greppable markers.
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
