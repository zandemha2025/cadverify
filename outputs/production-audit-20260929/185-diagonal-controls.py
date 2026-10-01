"""Real STEP controls: identical solid bars, aligned and rotated 45 degrees."""
import hashlib
import json
import math
from pathlib import Path

import gmsh

out = Path(__file__).parent
controls = []
for length in (250, 400):
    for rotated in (False, True):
        name = f"185-diagonal-{length}-{'rotated' if rotated else 'aligned'}"
        path = out / f"{name}.step"
        gmsh.initialize()
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.model.add(name)
            solid = gmsh.model.occ.addBox(-length / 2, -6, -6, length, 12, 12)
            if rotated:
                gmsh.model.occ.rotate([(3, solid)], 0, 0, 0, 0, 0, 1, math.pi / 4)
            gmsh.model.occ.synchronize()
            gmsh.write(str(path))
        finally:
            gmsh.finalize()
        controls.append({"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                         "solid_dimensions_mm": [length, 12, 12], "volume_mm3": length * 12 * 12,
                         "rotation_z_deg": 45 if rotated else 0,
                         "xy_extent_at_45_deg_mm": (length + 12) / math.sqrt(2)})
(out / "185-diagonal-controls.json").write_text(json.dumps(controls, indent=2) + "\n")
print(json.dumps(controls, indent=2))
