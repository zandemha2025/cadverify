#!/usr/bin/env python3
"""Generate the adversarial-geometry STEP fixtures used by EXTRA_PARTS live passes.

l_bracket_bent.step — 3 mm sheet bent into an L (two fused flanges). The live
engine must route it through the sheet-metal (bend and cut) process.

stepped_shaft.stp — coaxial turned steps with a through bore. Prices via
turning once a metal is picked (default no-material picks stay polymer).

Run with the backend venv that carries gmsh:

    backend/.venv312/bin/python scripts/e2e/make-edge-fixtures.py [outdir]
"""
import os
import sys

import gmsh


def _finish(name: str, path: str) -> None:
    gmsh.model.occ.synchronize()
    gmsh.write(path)
    bbox = gmsh.model.getBoundingBox(-1, -1)
    print(f"{name}: {path} bbox=({bbox[3]-bbox[0]:.0f} x {bbox[4]-bbox[1]:.0f} x {bbox[5]-bbox[2]:.0f}) mm")
    gmsh.model.remove()


def l_bracket(out: str) -> str:
    gmsh.model.add("l_bracket_bent")
    t, leg, width = 3.0, 30.0, 60.0
    bottom = gmsh.model.occ.addBox(0, 0, 0, width, t, leg)   # sheet flange, full width
    upright = gmsh.model.occ.addBox(0, 0, 0, t, leg, leg)    # bent-up flange
    gmsh.model.occ.fuse([(3, bottom)], [(3, upright)])
    path = os.path.join(out, "l_bracket_bent.step")
    _finish("l_bracket_bent", path)
    return path


def stepped_shaft(out: str) -> str:
    gmsh.model.add("stepped_shaft")
    major = gmsh.model.occ.addCylinder(0, 0, 0, 0, 0, 40, 7.5)    # ⌀15 x 40
    minor = gmsh.model.occ.addCylinder(0, 0, 40, 0, 0, 15, 5.0)   # ⌀10 x 15
    fused = gmsh.model.occ.fuse([(3, major)], [(3, minor)])[0][0][1]
    bore = gmsh.model.occ.addCylinder(0, 0, -1, 0, 0, 57, 1.0)    # ⌀2 through
    gmsh.model.occ.cut([(3, fused)], [(3, bore)])
    path = os.path.join(out, "stepped_shaft.stp")
    _finish("stepped_shaft", path)
    return path


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp"
    os.makedirs(out, exist_ok=True)
    gmsh.initialize()
    try:
        l_bracket(out)
        stepped_shaft(out)
    finally:
        gmsh.finalize()


if __name__ == "__main__":
    main()
