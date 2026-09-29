"""Corpus v3 fixture generator (GLM seat 2026-09-14).

Generates adversarial STL fixtures for the v3 gate. Every fixture is built so
its expected verdict derives from CODE thresholds and cited vendor standards.
Run: python gen_v3_fixtures.py  (writes .stl files next to this script)
"""
import numpy as np, trimesh, hashlib, json
from pathlib import Path

OUT = Path(__file__).resolve().parent

def save(mesh, name):
    mesh.export(OUT / name)
    print(name, mesh.faces.shape[0], 'faces, watertight=', mesh.is_watertight)

def box(dx, dy, dz, center=(0,0,0)):
    m = trimesh.creation.box(extents=(dx,dy,dz))
    m.apply_translation((center[0], center[1], center[2] + dz/2))
    return m

def loft_box(dx, dy, dz, taper_mm):
    """Box whose vertical walls draft inward: top face smaller by 2*taper in x/y."""
    bx, by = dx/2, dy/2
    tx, ty = bx - taper_mm, by - taper_mm
    v = np.array([
        [-bx,-by,0],[bx,-by,0],[bx,by,0],[-bx,by,0],
        [-tx,-ty,dz],[tx,-ty,dz],[tx,ty,dz],[-tx,ty,dz]], dtype=float)
    f = [[0,2,1],[0,3,2],[4,5,6],[4,6,7],
         [0,1,5],[0,5,4],[1,2,6],[1,6,5],
         [2,3,7],[2,7,6],[3,0,4],[3,4,7]]
    return trimesh.Trimesh(vertices=v, faces=f, process=True)

def cyl(r, h, center=(0,0,0), axis='z', sections=64):
    m = trimesh.creation.cylinder(radius=r, height=h, sections=sections)
    if axis == 'x':
        m.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2, [0,1,0]))
    m.apply_translation((center[0], center[1], center[2] + (h/2 if axis=='z' else 0)))
    return m

def ramp_block(L, W, H, beta_deg):
    """Block with flat top at z=H and underside ramped beta above horizontal."""
    t = L * np.tan(np.radians(beta_deg))
    v = np.array([
        [0,0,t],[L,0,0],[L,W,0],[0,W,t],          # underside ramp (z from t -> 0)
        [0,0,H],[L,0,H],[L,W,H],[0,W,H]], dtype=float)  # top
    f = [[0,2,1],[0,3,2],[4,5,6],[4,6,7],
         [0,1,5],[0,5,4],[1,2,6],[1,6,5],
         [2,3,7],[2,7,6],[3,0,4],[3,4,7]]
    return trimesh.Trimesh(vertices=v, faces=f, process=True)

# --- 1. sealed hollow squat cylinder: trapped volume + real SLA cupping surface
outer = cyl(20, 15)
inner = cyl(17, 9, center=(0,0,3))
sealed = trimesh.boolean.difference([outer, inner], engine='manifold')
save(sealed, 'trap-sealed-cavity-cupping.stl')

# --- 2/3. build-volume rotation pair (FDM envelope 300,300,350)
save(box(350, 200, 100), 'trap-buildvolume-rotated-fit-350x200x100.stl')
save(box(350, 310, 100), 'trap-buildvolume-true-exceed-350x310x100.stl')

# --- 4. turning envelope rotated fit: r40 h300 along X (254,254,533)
save(cyl(40, 300, center=(0,0,0), axis='x'), 'trap-turning-volume-rotated-x300.stl')

# --- 5/6. injection-molding draft boundary pair (min 1.0 deg, height 40)
save(loft_box(40, 40, 40, 40*np.tan(np.radians(0.5))), 'trap-draft-0p5deg.stl')
save(loft_box(40, 40, 40, 40*np.tan(np.radians(1.5))), 'control-draft-1p5deg.stl')

# --- 7/8. CNC undercut pair
stem = box(20, 20, 40); cap = box(60, 60, 10, center=(0,0,40))
save(trimesh.util.concatenate([stem, cap]), 'trap-tshape-undercut.stl')
base = cyl(30, 10); upper = cyl(15, 40, center=(0,0,10))
save(trimesh.util.concatenate([base, upper]), 'control-stepped-shaft-noundercut.stl')

# --- 9/10. sharp internal corner floors: 1 pocket vs 16 pockets
blk = box(60, 60, 20)
p1 = trimesh.boolean.difference([blk, box(20, 20, 12, center=(0,0,8))], engine='manifold')
save(p1, 'trap-pocket-single-sharp-corner.stl')
cuts = []
for ix in (-22.5, -7.5, 7.5, 22.5):
    for iy in (-22.5, -7.5, 7.5, 22.5):
        cuts.append(box(10, 10, 12, center=(ix, iy, 8)))
grid = trimesh.boolean.difference([box(120, 120, 20)] + cuts, engine='manifold')
save(grid, 'trap-pocket-grid-16-sharp-corners.stl')

# --- 11/12/13. sheet gauge: formed channel vs flat plate vs foil
u_out = box(40, 30, 30)
u_in = box(36, 34, 27, center=(0, 1, 3))  # leaves 2mm walls, open +y? keep simple: open top
u_in2 = box(36, 30, 27, center=(0, 0, 3))
uchan = trimesh.boolean.difference([u_out, u_in2], engine='manifold')
save(uchan, 'trap-uchannel-2mm-formed.stl')
save(box(50, 50, 2), 'control-plate-2mm-flat.stl')
save(box(50, 50, 0.2), 'trap-plate-0p2mm-foil.stl')

# --- 14/15. deep hole pair (CNC max depth/diameter 10)
blk2 = box(40, 40, 50)
deep = trimesh.boolean.difference([blk2, cyl(2, 44, center=(0,0,6))], engine='manifold')
save(deep, 'trap-deephole-4mmx44mm.stl')
okhole = trimesh.boolean.difference([box(40, 40, 30), cyl(4, 16, center=(0,0,14))], engine='manifold')
save(okhole, 'control-hole-8mmx16mm.stl')

# --- 16/17. wire-EDM prismatic: filleted plate vs pyramid top
plate = box(60, 60, 5)
edges = []
for (x, y, rot) in [(30,0,'y'),(-30,0,'y'),(0,30,'x'),(0,-30,'x')]:
    c = trimesh.creation.cylinder(radius=4, height=60, sections=64)
    if rot == 'y':
        c.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2, [0,1,0]))
    else:
        c.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2, [1,0,0]))
    c.apply_translation((x, y, 5))
    edges.append(c)
filleted = trimesh.boolean.union([plate] + edges, engine='manifold')
save(filleted, 'trap-filleted-plate-prismatic.stl')
pyr = trimesh.creation.cone(radius=42.4, height=20, sections=4)
pyr.apply_transform(trimesh.transformations.rotation_matrix(np.pi/4, [0,0,1]))
pyr.apply_translation((0, 0, 20))
pyrtop = trimesh.util.concatenate([box(60, 60, 20), pyr])
save(pyrtop, 'trap-pyramid-top-nonprismatic.stl')

# --- 18/19/20. turning: symmetry control + L/D pair
save(cyl(30, 60), 'control-cylinder-r30h60-turning.stl')
save(cyl(10, 220), 'trap-shaft-ld11.stl')
save(cyl(10, 180), 'control-shaft-ld9.stl')

# --- 21. uniform-wall molding control (3mm walls, 4mm drain)
hbox = trimesh.boolean.difference([box(60, 60, 60), box(54, 54, 54, center=(0,0,3))], engine='manifold')
hbox = trimesh.boolean.difference([hbox, cyl(2, 6, center=(0,0,-1))], engine='manifold')
save(hbox, 'control-hollow-box-uniform-3mm-wall.stl')

# --- 22/23. shrinkage modulus pair (sand/investment, V/SA threshold 15)
save(box(100, 100, 100), 'trap-cube-100mm-bulky.stl')
save(box(80, 80, 80), 'control-cube-80mm.stl')

# --- 24. fragile core: sealed pipe OD20 ID4 L100
pipe = trimesh.boolean.difference([cyl(10, 100), cyl(2, 100)], engine='manifold')
save(pipe, 'trap-fragile-core-pipe.stl')

# --- 25. one small rib on a big plate (5% small-feature floor)
ribplate = trimesh.util.concatenate([box(100, 100, 5), box(0.3, 20, 5, center=(0,0,5))])
save(ribplate, 'trap-single-0p3mm-rib-on-big-plate.stl')

# --- 26/27/28. SLA overhang semantics: ramp undersides
save(ramp_block(40, 40, 45, 30), 'trap-sla-overhang-30deg-from-horizontal.stl')
save(ramp_block(40, 40, 40, 80), 'control-sla-overhang-80deg-from-horizontal.stl')
save(ramp_block(40, 40, 40, 10), 'trap-sla-overhang-10deg-from-horizontal.stl')

# checksums
sums = {}
for f in sorted(OUT.glob('*.stl')):
    sums[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()
(OUT / 'SHA256SUMS.txt').write_text('\n'.join(f'{v}  {k}' for k, v in sums.items()) + '\n')
print('wrote SHA256SUMS for', len(sums), 'fixtures')
