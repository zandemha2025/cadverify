"""SPIKE probe: what can gmsh/OCC extract from a REAL STEP assembly?

Drives gmsh 4.15.2 exactly like backend/src/parsers/step_mesher.py, but instead
of flattening to ONE mesh, enumerates each sub-solid separately and records its
world-space position, name, and per-part tessellation. Emits JSON + per-part OBJ.

Usage: python probe_assembly.py <step_file> <out_dir>
No product code touched; throwaway spike artifact.
"""
from __future__ import annotations
import json, sys, os
from pathlib import Path
import gmsh

step_path = sys.argv[1]
out_dir = Path(sys.argv[2])
out_dir.mkdir(parents=True, exist_ok=True)

gmsh.initialize(interruptible=False)
gmsh.option.setNumber("General.Terminal", 0)
gmsh.option.setString("Geometry.OCCTargetUnit", "MM")

report = {"step_file": os.path.abspath(step_path)}

# Import exactly as the product code does.
gmsh.model.add("asm")
gmsh.model.occ.importShapes(step_path)
gmsh.model.occ.synchronize()

# --- Enumerate solids (dim 3) ---
vols = gmsh.model.getEntities(3)
report["num_solids"] = len(vols)

# Physical groups (product code never creates any; check if STEP import made any)
report["physical_groups_dim3"] = [
    {"tag": t, "name": gmsh.model.getPhysicalName(3, t)}
    for (d, t) in gmsh.model.getPhysicalGroups(3)
]

parts = []
for (dim, tag) in vols:
    name = gmsh.model.getEntityName(dim, tag)  # STEP label path
    x0, y0, z0, x1, y1, z1 = gmsh.model.getBoundingBox(dim, tag)
    try:
        mass = gmsh.model.occ.getMass(dim, tag)
    except Exception:
        mass = None
    try:
        cx, cy, cz = gmsh.model.occ.getCenterOfMass(dim, tag)
    except Exception:
        cx = cy = cz = None
    parts.append({
        "tag": tag,
        "occ_label": name,
        "bbox_min": [x0, y0, z0],
        "bbox_max": [x1, y1, z1],
        "bbox_size": [x1 - x0, y1 - y0, z1 - z0],
        "centroid_world": [cx, cy, cz],
        "volume_mm3": mass,
    })
report["parts"] = parts

# --- Global bbox for mesh sizing (as product code does) ---
gx0, gy0, gz0, gx1, gy1, gz1 = gmsh.model.getBoundingBox(-1, -1)
diag = ((gx1-gx0)**2 + (gy1-gy0)**2 + (gz1-gz0)**2) ** 0.5
report["assembly_bbox_min"] = [gx0, gy0, gz0]
report["assembly_bbox_max"] = [gx1, gy1, gz1]
report["assembly_diag_mm"] = diag
size_max = min(max(diag / 200.0, 0.05), 50.0)
gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 12.0)
gmsh.option.setNumber("Mesh.MeshSizeMax", size_max)

# --- Tessellate whole model once (2D shell), then split triangles per volume ---
gmsh.model.mesh.generate(2)

# For each solid, collect the surface triangles belonging to its boundary faces.
def node_coords_map():
    tags, coords, _ = gmsh.model.mesh.getNodes()
    c = coords.reshape(-1, 3)
    return {int(t): c[i] for i, t in enumerate(tags)}

allnodes = node_coords_map()

total_faces = 0
for p in parts:
    tag = p["tag"]
    # boundary surfaces of this volume
    bnd = gmsh.model.getBoundary([(3, tag)], oriented=False, recursive=False)
    tris = []
    used = {}
    for (bd, bt) in bnd:
        etypes, etags, enodes = gmsh.model.mesh.getElements(2, bt)
        for et, conn in zip(etypes, enodes):
            if et == 2:  # 3-node triangle
                conn = list(map(int, conn))
                for i in range(0, len(conn), 3):
                    tri = conn[i:i+3]
                    idx = []
                    for n in tri:
                        if n not in used:
                            used[n] = len(used)
                        idx.append(used[n])
                    tris.append(idx)
    # write OBJ per part (world coords preserved)
    inv = {v: k for k, v in used.items()}
    obj_path = out_dir / f"part_{tag}.obj"
    with open(obj_path, "w") as f:
        for i in range(len(used)):
            x, y, z = allnodes[inv[i]]
            f.write(f"v {x} {y} {z}\n")
        for a, b, c in tris:
            f.write(f"f {a+1} {b+1} {c+1}\n")
    p["num_triangles"] = len(tris)
    p["num_vertices"] = len(used)
    p["obj"] = obj_path.name
    total_faces += len(tris)

report["total_triangles"] = total_faces
gmsh.finalize()

with open(out_dir / "extraction.json", "w") as f:
    json.dump(report, f, indent=2)

print(json.dumps(report, indent=2))
