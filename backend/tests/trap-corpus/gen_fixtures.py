"""Qwen seat: ProofShape trap-corpus v1.2 expansion generator.

Laws honored:
- Every fixture is a watertight single solid UNLESS the trap is the watertight
  failure itself (trap-degenerate-duplicate-face) or the sealed-cavity class
  (nested shell = same convention as v1.1 trap-trapped-hollow-sphere).
- Expected verdicts derive from CODE thresholds in
  backend/src/analysis/processes: FDM wall 0.8 / overhang 45 / small 0.4 /
  build (300,300,350) / aspect 8 / drain 3.0; SLA wall 0.4 / overhang 19 /
  small 0.05 / build (200,125,210) / drain 3.5.
- Wall thickness = inward ray cast from face centroids (context.py).
- small_features trips only if >=5% of unique edges are below threshold.
- overhang trips on faces with angle_from_up > 90 + threshold, excluding
  near-flat faces resting on the build plate (z within 0.1%-bbox of z-min).
"""
import numpy as np, trimesh, os, math

OUT = 'fixtures'
os.makedirs(OUT, exist_ok=True)

def save(mesh, name):
    p = os.path.join(OUT, name)
    mesh.export(p)
    return p

def box(x, y, z, center=(0,0,0)):
    m = trimesh.creation.box(extents=(x,y,z))
    m.apply_translation(center)
    return m

def shell_box(outer, wall):
    """Outer cube + inverted inner cube (two components, watertight)."""
    o = box(outer, outer, outer)
    i = box(outer-2*wall, outer-2*wall, outer-2*wall)
    i.invert()
    return trimesh.util.concatenate([o, i])

def lathe(profile, n=36):
    """Surface of revolution around Z. profile = [(r,z), ...] ordered along the
    cross-section boundary. r~0 entries become pole vertices (fan)."""
    verts, faces = [], []
    rings = []
    for (r, z) in profile:
        if r < 1e-6:
            rings.append(('pole', len(verts))); verts.append([0.0, 0.0, z])
        else:
            idx0 = len(verts)
            for k in range(n):
                a = 2*math.pi*k/n
                verts.append([r*math.cos(a), r*math.sin(a), z])
            rings.append(('ring', idx0))
    for s in range(len(rings)-1):
        ta, ia = rings[s]; tb, ib = rings[s+1]
        if ta == 'ring' and tb == 'ring':
            for k in range(n):
                k2 = (k+1) % n
                faces.append([ia+k, ia+k2, ib+k2])
                faces.append([ia+k, ib+k2, ib+k])
        elif ta == 'pole' and tb == 'ring':
            for k in range(n):
                faces.append([ia, ib+(k+1)%n, ib+k])
        else:  # ring -> pole
            for k in range(n):
                faces.append([ib, ia+k, ia+(k+1)%n])
    m = trimesh.Trimesh(np.array(verts), np.array(faces), process=True)
    trimesh.repair.fix_winding(m)
    if m.volume < 0: m.invert()
    return m

def prism_xz(profile, depth, y_center=0.0):
    """Extrude an XZ polygon along Y."""
    from shapely.geometry import Polygon
    pts = [(x, z) for (x, z) in profile]
    tri = trimesh.creation.extrude_polygon(Polygon(pts), depth)
    # rotate so the 2D profile's second axis becomes Z and extrusion depth becomes Y
    tri.apply_transform(trimesh.transformations.rotation_matrix(math.pi/2, [1,0,0]))
    tri.apply_translation((0, y_center + depth/2, 0))
    return tri

# ---------- borderline wall pair (FDM 0.8 threshold) ----------
save(box(6, 6, 0.79, center=(0,0,0.395)), 'trap-wall-0.79mm-plate.stl')   # FDM trips, SLA clear; aspect 7.6
save(box(6, 6, 0.81, center=(0,0,0.405)), 'control-wall-0.81mm-plate.stl') # both clear; aspect 7.4

# ---------- borderline small-feature pair (FDM 0.4 edge threshold) ----------
for size, name in [(0.39, 'trap-small-rib-0.39mm.stl'), (0.41, 'control-small-rib-0.41mm.stl')]:
    base = box(12, 12, 3, center=(0,0,1.5))
    rib = box(size, 12, 4, center=(0,0,3+2))
    m = trimesh.boolean.union([base, rib], engine='manifold')
    save(m, name)

# ---------- borderline aspect pair (FDM 8:1) ----------
save(box(2,2,16.3, center=(0,0,8.15)), 'trap-aspect-8.1.stl')
save(box(2,2,15.8, center=(0,0,7.9)),  'control-aspect-7.9.stl')

# ---------- borderline overhang set (FDM max 45 from vertical / SLA min 19 above horizontal) ----------
def overhang_prism(deg, name):
    a = math.radians(deg)  # deg measured FROM VERTICAL (code semantics)
    x_tip, z_top, z_under = 7.0, 8.0, 6.5
    run = x_tip - 4.0
    z_meet = z_under - run / math.tan(a)
    prof = [(0,0),(4,0),(4,z_meet),(x_tip,z_under),(x_tip,z_top),(4,z_top),(0,z_top)]
    save(prism_xz(prof, 6.0), name)
overhang_prism(46, 'trap-overhang-46deg.stl')        # FDM trips; SLA clears (44 above horizontal)
overhang_prism(44, 'control-overhang-44deg.stl')     # FDM clears; SLA clears (46 above horizontal)
def overhang_prism_short(deg, name):
    a = math.radians(deg)
    x_tip, z_top, z_under = 5.0, 8.0, 6.5
    z_meet = z_under - (x_tip - 4.0) / math.tan(a)
    prof = [(0,0),(4,0),(4,z_meet),(x_tip,z_under),(x_tip,z_top),(4,z_top),(0,z_top)]
    save(prism_xz(prof, 6.0), name)
overhang_prism_short(20.0, 'trap-sla-overhang-20deg.stl') # both clear; underside is 70 above horizontal

# ---------- multi-defect: L-bracket (thin wall + 50deg overhang + small rib) ----------
base = box(12,10,2, center=(5.4,0,1))
wall = box(0.6,10,10, center=(0.3,0,7))
fin = prism_xz([(0.6, 7-5.4/math.tan(math.radians(50))),(6.0,7),(6.0,9),(0.6,9)], 6.0)
ribs = [box(0.35,8,3, center=(0.6+0.175,0,z)) for z in (3.5, 6.0, 8.5)]
m = trimesh.boolean.union([base, wall, fin] + ribs, engine='manifold')
save(m, 'trap-multi-lbracket-thin-steep-small.stl')

# ---------- multi-defect: tall bar + 46deg lip (aspect + overhang) ----------
bar = box(2,2,16.5, center=(0,0,8.25))
lip = prism_xz([(0.5, 15.5-3.5/math.tan(math.radians(46))),(4,15.5),(4,16.5),(0.5,16.5)], 2.0)
m = trimesh.boolean.union([bar, lip], engine='manifold')
save(m, 'trap-multi-tallbar-46lip.stl')

# ---------- organic control: gentle-taper goblet, watertight, walls>=2, slopes<=14deg ----------
prof = [(0,0),(9,0),(10,4),(8.8,10),(9,16),(8.3,22),(7.5,26),(0,27)]
save(lathe(prof, 36), 'control-organic-goblet.stl')

# ---------- organic multi-defect: pinched neck (thin + steep + micro edges) ----------
prof = [(0,0),(8,0),(10,4),(8.5,10),(9,16),(6,19),(0.35,20.6),(0.35,21.4),(3,23),(5,26),(0,27)]
save(lathe(prof, 36), 'trap-organic-pinched-neck.stl')

# ---------- organic sealed cavity (nested shells, trapped volume) ----------
outer_prof = [(0,0),(7,2),(9,8),(8,16),(5,23),(2,27),(0,28)]
outer = lathe(outer_prof, 36)
inner_prof = [(0,4),(4,4.5),(5.5,9),(4.5,16),(2.5,21),(0,23)]
inner = lathe(inner_prof, 36); inner.invert()
save(trimesh.util.concatenate([outer, inner]), 'trap-organic-sealed-cavity.stl')

# ---------- assembly-adjacent single body: dumbbell with 0.6mm neck ----------
s1 = trimesh.creation.icosphere(subdivisions=2, radius=4); s1.apply_translation((0,0,4))
s2 = trimesh.creation.icosphere(subdivisions=2, radius=4); s2.apply_translation((12,0,4))
neck = trimesh.creation.cylinder(radius=0.3, height=12, sections=12)
neck.apply_transform(trimesh.transformations.rotation_matrix(math.pi/2, [0,1,0]))
neck.apply_translation((6,0,4))
m = trimesh.boolean.union([s1, s2, neck], engine='manifold')
save(m, 'trap-assembly-adjacent-dumbbell-0.6neck.stl')

# ---------- watertight-failure trap: duplicate face ----------
c = box(10,10,10)
dup = trimesh.Trimesh(c.vertices, np.vstack([c.faces, c.faces[:1]]), process=False)
save(dup, 'trap-degenerate-duplicate-face.stl')

# ---------- hollow box WITH drain hole: false-positive resistance ----------
# cup: open-top hollow (single component, no ceiling) + 4mm drain through base
outer = box(24,24,24, center=(0,0,12))
cavity = box(20,20,20, center=(0,0,14))
cyl = trimesh.creation.cylinder(radius=2.0, height=6, sections=24)
cyl.apply_translation((0,0,1))
m = trimesh.boolean.difference([outer, cavity, cyl], engine='manifold')
save(m, 'control-hollow-cup-drain-4mm.stl')
# sealed hollow with a too-small 2mm drain: KNOWN-GAP (code is containment-blind to drain size)
outer = box(24,24,24)
inner = box(20,20,20)
cyl = trimesh.creation.cylinder(radius=1.0, height=6, sections=24)
cyl.apply_translation((0,0,11))
m = trimesh.boolean.difference([outer, inner, cyl], engine='manifold')
save(m, 'trap-hollow-drain-2mm-KNOWN-GAP.stl')

# ---------- borderline build volume pair (FDM 300 limit) ----------
save(box(300.1,290,300, center=(0,0,150)), 'trap-build-300.1mm.stl')
save(box(299,290,299,  center=(0,0,149.5)), 'control-build-299mm.stl')

print('generated:', len(os.listdir(OUT)), 'files')
