# Assembly Feasibility Spike — can CadVerify show a real part in its real assembly?

**Date:** 2026-07-09 · **Base commit:** `65ab693` · **gmsh:** 4.15.2 (embedded OpenCASCADE)
**Verdict up front:** YES — gmsh/OCC extracts individual parts, their correct
world positions, AND the full logical product tree from a real STEP assembly, and
we rendered a real part highlighted inside its real assembly context. The current
product code's refusal of assemblies is a **policy choice, not a capability gap.**

---

## 1. The real assembly used

### Primary source attempted — NIST MTC "Box Assembly" (honest negative result)
- **URL:** `https://www.nist.gov/system/files/documents/noindex/2025/09/04/NIST-MTC-Assembly.zip`
- **sha256:** `9aeb53e54f682ea1732857d06a7f0513c71667a2d84407396325fa6ce5340bbc` (matches expected)
- **Project:** NIST "Design, Manufacturing, and Inspection Data for a Box Assembly" (`https://smstestbed.nist.gov/tdp/mtc/`)
- **What's inside (30 files):** Siemens NX `.prt`, a `.jt`, SolidWorks `.SLDASM`/`.SLDPRT`, and one ACIS `.SAT`.
- **Blocker:** **There is NO STEP/IGES export anywhere in the zip.** Every format shipped is a
  native/proprietary kernel format that gmsh's `occ.importShapes` cannot read (it reads STEP/IGES/BREP only).
  This is itself a real-world finding: a marquee public "assembly data package" shipped **zero** neutral
  interchange geometry. Ingesting it would require a SolidWorks/NX/ACIS reader (licensed CAD or OCP-with-plugins), not available here.

### Assembly actually probed — AS1 (real STEP AP203 assembly)
- **File:** `as1-tu-203.stp` · **sha256:** `d40db2ed6f741d2955329f9751c7e3e0a14cbfeb4e11d8338cf110765b9042f9`
- **Provenance (from the STEP header, real):** authored in Siemens **UG/NX**, exported through
  **Theorem Solutions' AP203 E2 preprocessor** (`FILE_NAME` + `FILE_DESCRIPTION` fields). It is the
  canonical industry AS1 reference assembly — a genuine multi-part mechanical assembly (base plate +
  two L-brackets + a rod + fastener stack), **not synthetic geometry I generated.**
- **License:** ships inside the gmsh 4.15.2 distribution's public `examples/api/` (used industry-wide as the
  STEP-conformance reference model). Openly redistributable; copied verbatim, unmodified.
- **Why it's a valid stand-in:** it has >=2 sub-parts in **defined relative positions** (18 positioned solids),
  a **nested sub-assembly** hierarchy, and **named products** — the exact structure the founder's feature needs.
  Copied to `data/real-corpus/as1-tu-203.stp` (gitignored corpus).

---

## 2. What gmsh/OCC actually extracted (every number from the real run)

Probe script: `scripts/spike/probe_assembly.py` -> `outputs/human-sim/assembly-real/extract/extraction.json`.
Import path is byte-for-byte the product code's (`occ.importShapes` + `synchronize`), then instead of
flattening to one blob it enumerates `getEntities(3)`.

| Metric | Result |
|---|---|
| Solids (`getEntities(3)`) | **18 distinct volumes** |
| Unique part designs | **5** (plate, l-bracket, rod, bolt, nut) |
| Instances | nut x8, bolt x6, l-bracket x2, rod x1, plate x1 = 18 |
| Per-part world position | distinct bbox + centroid + OCC center-of-mass for every solid |
| Per-part volume (`occ.getMass`) | plate 530575 mm3, l-bracket 96858, rod 15709, bolt 3201, nut 664 |
| Per-part tessellation | each solid meshed separately; **195904 triangles total** |
| Names / hierarchy | full `/`-separated label path per solid via `getEntityName` |
| Physical groups | none (product tree lives in the label path, not physical groups) |
| Assembly bbox | [-10, 0, -4] ... [190, 150, 80] mm, diagonal 263.7 mm |

**(a) Individual parts — YES.** 18 separate meshable solids, one mesh each (not a flattened blob).

**(b) Correct relative positions — YES.** STEP bakes each part's placement transform into world
coordinates, so parts occupy distinct regions. Verified by centroids: the two rod-end nuts sit at
x~176.5 and x~3.5 (opposite ends of the rod at x~90); the two l-brackets mirror at x~19.6 and x~160.4.
The rendered image (below) shows the rod correctly threaded through both brackets with nuts on the ends —
positions are physically coherent, straight from OCC with **zero manual placement.**

**(c) Names / hierarchy — YES, and richer than expected.** Each solid's `getEntityName` returns its full
logical path, e.g.
`Shapes/as1/L-BRACKET-ASSEMBLY::2/l-bracket-assembly/NUT-BOLT-ASSEMBLY::3/nut-bolt-assembly/BOLT/bolt`.
The `::N` suffixes are **instance indices**, so the entire nested product tree is reconstructable:

```
as1
|- plate                              (x1)
|- rod-assembly                       -> rod (x1), nut (x2)
`- l-bracket-assembly (x2)
   |- l-bracket                       (x1 each)
   `- nut-bolt-assembly (x3 each)     -> bolt, nut
```

This is the **logical assembly tree** the founder's "parent assembly" label is currently faking — it is
real and machine-readable, not just a text tag.

### What is genuinely missing / hard (honest)
- **Mate constraints** (coincident/concentric/distance): **NOT in AP203.** They are *consumed* into the baked
  transforms during export. You get final positions, never the parametric relationships. Recovering "why" a
  part sits where it does (for re-solving fit) is not possible from this STEP.
- **Part designation as a clean field:** you get the label *string* and must parse it (strip ` & & 256`,
  split on `/`, read `::N`). Robust across CAD exporters? Needs validation on more files — label conventions vary.
- **GD&T / PMI / tolerances:** AP242 only, needs cadquery/OCP (not installable here) — same boundary the
  product's `step_mesher.py` already documents.
- **Fit / clearance checks:** doable in principle (per-part meshes + world coords -> pairwise bbox/mesh
  interference), but not attempted here; would need a collision/min-distance pass.
- **Watertightness per part:** each solid is a closed BREP -> should mesh watertight per-part (the product's
  per-solid `process=True` merge would apply); not separately re-verified in this spike.

---

## 3. The render — a real part in its real assembly

Harness: `scripts/spike/render_assembly.mjs` (headless three.js via playwright-core + chromium-1194,
`/opt/pw-browsers`). It loads the 18 per-part OBJs **in their untransformed world coordinates** (so the
image is a direct proof of gmsh's positions) and screenshots two modes.

- **`01-full-assembly.png`** — the whole AS1 assembly, each part its own color. The base plate, the two
  vertical L-brackets, the rod threaded through both, and the nut/bolt fasteners are all correctly seated.
  This is a real multi-part assembly reconstructed purely from the STEP -> per-solid mesh pipeline.
- **`02-part-highlighted-in-context.png`** — **one L-bracket rendered in vivid red (the "part"), the rest of
  the assembly in neutral grey (the "environment/context").** This is the real-world analogue of the
  synthetic door-handle-in-parent concept image: a single real part shown correctly positioned inside its
  real assembly. The focus part is
  `Shapes/as1/L-BRACKET-ASSEMBLY::1/l-bracket-assembly/L-BRACKET/l-bracket` (solid tag 10).

Both screenshots are real renders of real extracted geometry — no compositing, no fake placement.

---

## 4. Feasibility verdict + recommended build path

**Can CadVerify ingest real assemblies and show a part correctly in its context? YES.** The load-bearing
pieces all work on real STEP: per-part solids, correct world positions, and the logical name tree — all from
the OCC kernel gmsh already embeds. The single-part limitation today (`step_mesher.py` flattens to one mesh;
the G1 gate refuses assemblies) is a **deliberate scope boundary, not a missing capability.**

**Straightforwardly doable (weeks, reuses existing kernel):**
1. Add an assembly-aware parse path beside `_mesh_step_file`: enumerate `getEntities(3)`, and for each solid
   capture `getEntityName`, bbox, `occ.getCenterOfMass`, `occ.getMass`, and a per-solid tessellation.
2. Parse the label path -> a `{part_id, instance, parent_chain}` product tree (the founder's real "parent assembly").
3. Emit one GLB per part (or one GLB with named nodes preserving world transforms) -> the viewer highlights the
   focus part and dims the rest (exactly `02-part-highlighted-in-context.png`).
4. Run the existing DFM/cost engine **per sub-solid** (each is already a `trimesh.Trimesh`) — makeability of the
   part *and* every sibling, unchanged engine.

**Harder / needs new work:** fit & clearance (pairwise mesh interference/min-distance pass — new but tractable);
robust label parsing across exporters (validate on >=5 real assemblies from different CAD systems).

**Missing / out of scope without OCP or licensed CAD:** mate-constraint recovery (gone from AP203 by design),
GD&T/PMI/tolerances (AP242 + OCP), and ingesting native `.SLDASM`/`.prt`/`.SAT` (as the NIST zip proves is the
common real-world distribution reality — an upstream STEP-export requirement or a licensed reader is needed).

**Recommended first ship:** STEP-assembly ingest -> per-part mesh + world-position + label tree -> viewer with
"part highlighted in its environment" + per-part DFM. That delivers the founder's "handle on the door on the
car" using only capabilities proven real in this spike. Mate/GD&T/native-format support is a later, gated tier.

---

### Reproduce
```
backend/.venv/bin/python scripts/spike/probe_assembly.py data/real-corpus/as1-tu-203.stp outputs/human-sim/assembly-real/extract
node scripts/spike/render_assembly.mjs
```
Artifacts: `extract/extraction.json`, `extract/part_*.obj`, `01-full-assembly.png`, `02-part-highlighted-in-context.png`.
