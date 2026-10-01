"""Generate identical rectangular-bar STEP controls in two orientations."""
import hashlib
import json
import math
from pathlib import Path

import gmsh

out = Path(__file__).parent / 'shape-controls'
controls = []
for rotated in [False, True]:
    name = '165-stock-bar-' + ('rotated' if rotated else 'aligned')
    gmsh.initialize()
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        gmsh.model.add(name)
        solid = gmsh.model.occ.addBox(-40, -6, -6, 80, 12, 12)
        if rotated:
            gmsh.model.occ.rotate([(3, solid)], 0, 0, 0, 0, 0, 1, math.pi / 4)
        gmsh.model.occ.synchronize()
        path = out / (name + '.step')
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    controls.append({'filename': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                     'dimensions_mm': [12, 12, 80], 'volume_mm3': 11520,
                     'rotation_deg': 45 if rotated else 0})
(out / '165-stock-controls.json').write_text(json.dumps(controls, indent=2) + '\n')
print(json.dumps(controls, indent=2))
