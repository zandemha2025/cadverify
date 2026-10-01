"""Real STEP bar with a transverse hole: shape alone cannot exclude five-axis."""
import hashlib
import json
import math
from pathlib import Path

import gmsh

out = Path(__file__).parent / 'shape-controls'
path = out / '166-transverse-hole-bar.step'
gmsh.initialize()
try:
    gmsh.option.setNumber('General.Terminal', 0)
    gmsh.model.add('transverse-hole-bar')
    bar = gmsh.model.occ.addBox(-40, -6, -6, 80, 12, 12)
    bore = gmsh.model.occ.addCylinder(0, -7, 0, 0, 14, 0, 2)
    gmsh.model.occ.cut([(3, bar)], [(3, bore)])
    gmsh.model.occ.synchronize()
    gmsh.write(str(path))
finally:
    gmsh.finalize()
control = {'filename': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
           'dimensions_mm': [80, 12, 12], 'bore_diameter_mm': 4,
           'bore_axis': 'Y', 'volume_mm3': 11520 - math.pi * 4 * 12}
(out / '166-routing-controls.json').write_text(json.dumps(control, indent=2) + '\n')
print(json.dumps(control))
