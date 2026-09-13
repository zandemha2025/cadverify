"""Emulates backend/src/analysis/processes/checks.py mechanics per fixture."""
import numpy as np, trimesh, os, json, math

def load(p):
    m = trimesh.load(p)
    return m

def wall_measure(m, eps=None):
    """Inward ray from face centroids along -normal; nearest hit past eps."""
    n = m.face_normals; c = m.triangles_center
    if eps is None:
        eps = max(m.bounding_box.extents) * 1e-6
    origins = c - n * eps  # start just inside the material
    locs, idx_ray, idx_tri = m.ray.intersects_location(origins, -n, multiple_hits=True)
    wt = np.full(len(c), np.inf)
    tmin = eps * 10
    for r, loc in zip(idx_ray, locs):
        t = np.linalg.norm(loc - origins[r])
        if t > tmin and t < wt[r]:
            wt[r] = t
    return wt

def angles_up(m):
    return np.degrees(np.arccos(np.clip(m.face_normals[:,2], -1, 1)))

def small_edges(m, thr):
    el = m.edges_unique_length
    s = el[el < thr]
    return (len(s)/len(el)*100 if len(el) else 0, float(s.min()) if len(s) else None, len(el))

def overhang(m, thr_deg, diag):
    a = angles_up(m)
    mask = a > (90 + thr_deg)
    z = m.triangles_center[:,2]
    ztol = max(0.1, diag*1e-3)
    on_plate = (z <= z.min()+ztol) & (a >= 175)
    mask &= ~on_plate
    return mask.sum(), mask.sum()/max(len(a),1)*100

rows = []
for f in sorted(os.listdir('fixtures')):
    p = os.path.join('fixtures', f)
    m = load(p)
    bodies = m.split(only_watertight=False)
    nb = len(bodies) if isinstance(bodies, list) else 1
    diag = float(np.linalg.norm(m.bounding_box.extents)) if m.bounding_box is not None else 0
    wt = wall_measure(m)
    finite = np.isfinite(wt)
    wtmin = float(wt[finite].min()) if finite.any() else None
    pct08 = float((finite & (wt < 0.8)).sum()/len(wt)*100)
    pct04 = float((finite & (wt < 0.4)).sum()/len(wt)*100)
    s4, smin4, nedges = small_edges(m, 0.4)
    s05, smin05, _ = small_edges(m, 0.05)
    ofdm, ofdm_pct = overhang(m, 45, diag)
    osla, osla_pct = overhang(m, 19, diag)
    dims = sorted(m.bounding_box.extents)
    aspect = dims[2]/max(dims[0],1e-9)
    bv_fdm = any(d > l for d, l in zip(m.bounding_box.extents, (300,300,350)))
    bv_sla = any(d > l for d, l in zip(m.bounding_box.extents, (200,125,210)))
    # trapped: components>1, inner body centroid contained in largest
    trapped = False
    if nb > 1:
        vols = [abs(b.volume) if b.is_watertight else 0 for b in bodies]
        main = bodies[int(np.argmax(vols))]
        for i, b in enumerate(bodies):
            if b is main: continue
            try:
                if main.is_watertight and main.contains([b.centroid])[0]:
                    trapped = True
            except Exception: pass
    rows.append(dict(file=f, watertight=bool(m.is_watertight), components=nb,
        vol=float(m.volume) if m.is_watertight else None,
        dims=[round(float(d),2) for d in m.bounding_box.extents],
        wall_min=round(wtmin,3) if wtmin else None,
        pct_below_0_8=round(pct08,1), pct_below_0_4=round(pct04,1),
        small_pct_0_4=round(s4,1), small_pct_0_05=round(s05,1),
        oh_fdm_faces=int(ofdm), oh_fdm_pct=round(ofdm_pct,1),
        oh_sla_faces=int(osla), oh_sla_pct=round(osla_pct,1),
        aspect=round(aspect,2), bv_fdm=bv_fdm, bv_sla=bv_sla, trapped=trapped,
        faces=len(m.faces), edges=nedges))
    r = rows[-1]
    print(f"{f:44s} wt={str(r['watertight']):5s} nb={nb} wall_min={r['wall_min']} pct<0.8={r['pct_below_0_8']:5} small%={r['small_pct_0_4']:5} ohFDM={r['oh_fdm_faces']:5} ohSLA={r['oh_sla_faces']:5} asp={r['aspect']:6} bvF={int(r['bv_fdm'])} trapped={int(trapped)}")

json.dump(rows, open('verification_measurements.json','w'), indent=1)
