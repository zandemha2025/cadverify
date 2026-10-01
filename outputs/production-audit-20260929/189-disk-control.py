"""Real STEP disk with an analytic placement in a 200 mm cube."""
import hashlib
import json
import math
from pathlib import Path

import gmsh

out = Path(__file__).parent
path = out / "189-disk-220x8.step"
assert not path.exists(), "Keep the original STEP control bytes"
gmsh.initialize()
try:
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("189-disk-220x8")
    gmsh.model.occ.addCylinder(0, 0, -4, 0, 0, 8, 110)
    gmsh.model.occ.synchronize()
    gmsh.write(str(path))
finally:
    gmsh.finalize()
proof = {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
         "diameter_mm": 220, "height_mm": 8, "volume_mm3": math.pi*110**2*8,
         "axis_direction": [1/math.sqrt(3)]*3,
         "tilted_extent_each_axis_mm": 220*math.sqrt(2/3)+8/math.sqrt(3)}
assert proof["tilted_extent_each_axis_mm"] < 200
(out / "189-disk-control.json").write_text(json.dumps(proof, indent=2)+"\n")
print(json.dumps(proof, indent=2))
