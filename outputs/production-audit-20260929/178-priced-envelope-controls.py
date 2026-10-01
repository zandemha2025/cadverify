"""Real 320 mm solids exceed the priced 250×250×325 mm DMLS envelope."""
import hashlib
import json
import math
from pathlib import Path

import gmsh

out = Path(__file__).parent / "shape-controls"
controls = []
for shape in ["sphere", "cube"]:
    path = out / f"178-priced-envelope-{shape}.step"
    if not path.exists():  # Preserve previously generated STEP bytes and their header dates.
        gmsh.initialize()
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.model.add(f"priced-envelope-{shape}")
            if shape == "sphere":
                gmsh.model.occ.addSphere(0, 0, 0, 160)
            else:
                gmsh.model.occ.addBox(0, 0, 0, 320, 320, 320)
            gmsh.model.occ.synchronize()
            gmsh.write(str(path))
        finally:
            gmsh.finalize()
    controls.append({"filename": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                     "dimensions_mm": [320, 320, 320],
                     "volume_mm3": 4 * math.pi * 160 ** 3 / 3 if shape == "sphere" else 320 ** 3,
                     "default_dmls_dfm_envelope_mm": [400, 400, 400],
                     "default_dmls_cost_envelope_mm": [250, 250, 325]})
(out / "178-priced-envelope-control.json").write_text(json.dumps(controls, indent=2) + "\n")
print(json.dumps(controls))
