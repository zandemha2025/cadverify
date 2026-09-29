import numpy as np, trimesh, hashlib
from pathlib import Path
OUT = Path('/home/sandbox/staging/backend/tests/corpus-v3')

def save(mesh, name):
    mesh.export(OUT / name)
    print(name, mesh.faces.shape[0], 'faces, watertight=', mesh.is_watertight)

def box(dx, dy, dz, center=(0,0,0)):
    m = trimesh.creation.box(extents=(dx,dy,dz))
    m.apply_translation((center[0], center[1], center[2] + dz/2))
    return m

def cyl(r, h, center=(0,0,0), axis='z', sections=64):
    m = trimesh.creation.cylinder(radius=r, height=h, sections=sections)
    if axis == 'x':
        m.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2, [0,1,0]))
    m.apply_translation((center[0], center[1], center[2] + (h/2 if axis=='z' else 0)))
    return m

# unioned stepped shaft (big base -> smaller top): no internal artifact faces
save(trimesh.boolean.union([cyl(30,10), cyl(15,40,center=(0,0,10))], engine='manifold'),
     'control-stepped-shaft-noundercut.stl')

# unioned T-shape: stem + wide cap -> real undercut annulus under the cap
save(trimesh.boolean.union([box(20,20,40), box(60,60,10,center=(0,0,40))], engine='manifold'),
     'trap-tshape-undercut.stl')

# fragile core: solid rod containing a sealed 4mm x 100mm channel (two bodies)
rod = cyl(10, 100)
void = cyl(2, 100)
save(trimesh.util.concatenate([rod, void]), 'trap-fragile-core-pipe.stl')

# SLA steep-ramp control, non-inverting: L=10, H=80, beta=80
def ramp_block(L, W, H, beta_deg):
    t = L * np.tan(np.radians(beta_deg))
    assert t < H, (t, H)
    v = np.array([[0,0,t],[L,0,0],[L,W,0],[0,W,t],
                  [0,0,H],[L,0,H],[L,W,H],[0,W,H]], dtype=float)
    f = [[0,2,1],[0,3,2],[4,5,6],[4,6,7],
         [0,1,5],[0,5,4],[1,2,6],[1,6,5],
         [2,3,7],[2,7,6],[3,0,4],[3,4,7]]
    return trimesh.Trimesh(vertices=v, faces=f, process=True)
save(ramp_block(10, 40, 80, 80), 'control-sla-overhang-80deg-from-horizontal.stl')

# single small rib on a DENSELY tessellated big plate: small-edge fraction < 5%
plate = box(100, 100, 5)
plate = plate.subdivide_to_size(2.0)
rib = box(0.3, 20, 5, center=(0,0,5))
save(trimesh.util.concatenate([plate, rib]), 'trap-single-0p3mm-rib-on-big-plate.stl')

# shrinkage control: 60mm solid cube (V/SA = 10 < 12 sand, < 15 investment)
save(box(60, 60, 60), 'control-cube-60mm.stl')

# uniform solid block with one Ø4 through-hole: hole-surface rays inflate t_max
save(trimesh.boolean.difference([box(20,20,20), cyl(2, 30, center=(0,0,-5))], engine='manifold'),
     'trap-block-through-hole-4mm.stl')

sums = {}
for f in sorted(OUT.glob('*.stl')):
    sums[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()
(OUT / 'SHA256SUMS.txt').write_text('\n'.join(f'{v}  {k}' for k, v in sums.items()) + '\n')
print('wrote SHA256SUMS for', len(sums), 'fixtures')
