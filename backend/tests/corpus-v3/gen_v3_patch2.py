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

def cyl(r, h, center=(0,0,0), sections=64):
    m = trimesh.creation.cylinder(radius=r, height=h, sections=sections)
    m.apply_translation((center[0], center[1], center[2] + h/2))
    return m

# 5mm plate with one Ø2 through-hole: IM wall family should be quiet (5mm stock)
save(trimesh.boolean.difference([box(50,50,5), cyl(1, 15, center=(0,0,-5))], engine='manifold'),
     'trap-plate-5mm-through-hole-2mm.stl')

# 10 big ribs + 1 micro rib on a plate: small-edge fraction ~1.4% (< 5% floor)
parts = [box(100, 100, 5)]
for i in range(10):
    parts.append(box(5, 20, 5, center=(-45 + i*10, -30, 5)))
parts.append(box(0.3, 20, 5, center=(0, 30, 5)))
save(trimesh.util.concatenate(parts), 'trap-single-0p3mm-rib-among-many.stl')

(OUT/'trap-block-through-hole-4mm.stl').unlink(missing_ok=True)
(OUT/'trap-single-0p3mm-rib-on-big-plate.stl').unlink(missing_ok=True)
sums = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(OUT.glob('*.stl'))}
(OUT / 'SHA256SUMS.txt').write_text('\n'.join(f'{v}  {k}' for k, v in sums.items()) + '\n')
print('fixtures now:', len(sums))
