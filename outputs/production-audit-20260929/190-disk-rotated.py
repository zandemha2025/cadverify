"""Reuse the original disk B-rep, rotating and translating without changing size."""
import hashlib
import json
from pathlib import Path

import gmsh

out = Path(__file__).parent
source = out / "189-disk-220x8.step"
target = out / "190-disk-rotated.step"
assert not target.exists(), "Keep the first control bytes"
source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
assert source_hash == "be9c7d7416c282a51dfa30810ba328fc9663818f08f70ccf61b0f4fd81d028af"
gmsh.initialize()
try:
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("190-disk-rotated")
    shapes = gmsh.model.occ.importShapes(str(source))
    gmsh.model.occ.rotate(shapes, 0, 0, 0, 1, 2, 3, .71)
    gmsh.model.occ.translate(shapes, 100, -200, 300)
    gmsh.model.occ.synchronize()
    volume = sum(gmsh.model.occ.getMass(dim, tag) for dim, tag in shapes if dim == 3)
    gmsh.write(str(target))
finally:
    gmsh.finalize()
assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
proof = {"source": source.name, "source_sha256": source_hash,
         "file": target.name, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
         "angle_rad": .71, "axis": [1, 2, 3], "translation_mm": [100, -200, 300],
         "brep_volume_mm3": volume}
(out / "190-disk-rotated.json").write_text(json.dumps(proof, indent=2) + "\n")
print(json.dumps(proof, indent=2))
