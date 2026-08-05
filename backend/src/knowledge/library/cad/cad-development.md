---
title: "CAD development — building software that reasons about geometry"
domain: cad
audience: "Engineers building this platform and anything like it"
sources: [asme_y14_41, iso_astm_52900, machinerys_handbook]
provenance: DEFAULT
---

# CAD development

Written for the people building the engine rather than using it. Geometry
software has a small number of recurring hard problems, and most production bugs
in this domain are one of them wearing a disguise.

---

## The representations, and what each is good for

**B-rep (boundary representation)** — faces as exact mathematical surfaces
(plane, cylinder, cone, sphere, torus, NURBS), bounded by edges and vertices,
with topology recording what adjoins what. Exact. Queryable. The only
representation where "this face is a cylinder of radius 4.0" is a fact rather
than an inference.

**Mesh** — triangles. Approximate to the chordal deviation. Simple, universal,
fast, and lossy. Feature identity is destroyed at tessellation: a cylinder
becomes a strip of unrelated flats.

**CSG** — a tree of primitives and boolean operations. Compact and robustly
parameterisable; historically limited in the shapes it can express, and awkward
for imported geometry.

**Implicit / SDF** — a function returning signed distance to the surface.
Excellent for lattices, offsets, booleans and blends, all of which are trivial in
this representation and hard in B-rep. Needs conversion for most downstream use.

**Voxel** — a 3D grid. Simple and robust for booleans and process simulation;
memory scales with the cube of resolution.

The practical rule for a verification engine: **analyse from B-rep whenever you
have it, fall back to mesh when you must, and label which one you used.** The
difference is visible in every number you report.

---

## Kernels

| Kernel | Nature | Notes |
|---|---|---|
| **Parasolid** | Commercial | Powers a large share of the industry; the de-facto exchange baseline |
| **ACIS** | Commercial | Long-established, widely embedded |
| **CGM** | Commercial | Dassault's kernel |
| **OpenCascade (OCCT)** | Open source, LGPL | The realistic open choice: B-rep, STEP/IGES import, booleans, meshing |
| **CGAL** | Open source, mixed licence | Computational geometry algorithms; excellent, mathematically careful |
| **manifold / libigl / trimesh** | Open source | Mesh-level processing, fast and pragmatic |

Choosing OCCT gets you real B-rep and real STEP support. It also gets you its
robustness characteristics and its API, both of which have a learning curve
measured in months. Budget for that honestly.

---

## The hard problems, and how they actually bite

### 1. Floating-point tolerance is the whole game

Two surfaces "intersect" only within a tolerance. Every kernel has one, they
differ, and mismatched tolerances are the root cause of most import failures:
sliver faces, micro-gaps, unstitchable surfaces, booleans that fail with no
useful message.

Practical defences:
- Establish a **model tolerance** and use it everywhere, consistently.
- Never test geometric equality with `==`.
- Detect and report **sliver faces and micro-edges** on import; they are the
  symptom that predicts later failures.
- Scale matters: a 0.001 mm tolerance is fine on a 10 mm part and meaningless on
  a 10 m one. Consider relative tolerances.

### 2. Booleans fail, and they fail on real customer data

Boolean robustness is *the* classic geometry-software problem. Coincident faces,
tangential contact and near-degenerate configurations are exactly the cases real
CAD produces, because designers model coincident faces constantly.

Mitigations that actually help: perturb slightly and retry; fall back to a mesh
or voxel boolean when exact fails; and above all **detect and report failure**
rather than returning wrong geometry. A boolean that silently produces a garbage
solid is far worse than one that raises.

### 3. Feature recognition is inference, not fact

Turning a mesh or a featureless B-rep back into "this is a Ø8 hole, 20 deep" is
inference, and it is wrong sometimes. Design for that:

- **Report confidence.** A recognised feature is a hypothesis.
- **Prefer B-rep.** A cylindrical face with a known radius is a fact; a strip of
  triangles that might be a cylinder is not.
- **Make it inspectable.** A user must be able to see what was recognised and
  disagree with it.
- **Never let low-confidence recognition drive a high-confidence number.** If hole
  detection is uncertain, the cost derived from hole count inherits that
  uncertainty and must say so.

### 4. Wall thickness has no single correct definition

Ray casting, sphere fitting, medial axis and shrink-wrap all give different
answers on the same part, and all are defensible. Sphere fitting is more robust
on organic shapes; ray casting is faster and more intuitive on prismatic ones;
both are sensitive to sampling density and to tessellation.

So: **state the method, state the sampling, and do not report more digits than
either supports.** "Minimum wall 0.9 mm (sphere-fit, 50k samples, mesh at 0.05 mm
deviation)" is a number someone can argue with. "0.87 mm" is not.

### 5. Units and orientation are unsolved by the file formats

STL carries no units. Many meshes carry no orientation convention. Assume
nothing, sanity-check scale against the part class, and treat any user
declaration as USER provenance rather than as fact.

### 6. Large models break naive algorithms

Anything that is O(n²) over faces or triangles works beautifully in tests and
falls over on a real 5-million-triangle assembly. Spatial acceleration structures
— BVH, octree, k-d tree — are not an optimisation here, they are the difference
between working and not.

---

## Architectural principles for a verification engine

**Determinism above all.** Same input, same version, same output — always. Random
sampling with an unseeded RNG makes a verification unreproducible, and an
unreproducible verification is worthless as a record. Seed everything, and record
the seed.

**Version the engine, and stamp results with it.** When a threshold or an
algorithm changes, previously issued verdicts must remain interpretable. A result
carrying `engine 1.4.2` can be reasoned about years later; one that does not
cannot.

**Separate measurement from judgement.** Measuring a 0.9 mm wall is geometry.
Deciding 0.9 mm is too thin for this process in this material is knowledge — and
it changes independently, on a different schedule, from a different source. Keep
them in different layers, which is exactly why the design rules in this corpus
live in YAML rather than in the analyzers.

**Every number carries provenance, structurally.** Not as a display convention but
as a type: a number without a source should be impossible to construct. That is
the only way "the copilot cannot hallucinate numbers" is a property of the system
rather than a hope about the prompt.

**Fail loudly and specifically.** "Analysis failed" is unusable. "Mesh has 47
naked edges; wall thickness cannot be computed" is actionable. A failed part must
show why and never silently disappear from a batch.

**Cache on content, not on filename.** Hash the geometry. The same part arriving
under three filenames is one analysis.

**Degrade honestly.** When you decimate for performance, say so. When you fall
back from B-rep to mesh, say so. When repair changed the volume, say by how much.
The user's trust in your confident numbers is built entirely out of your
willingness to flag the unconfident ones.

---

## Testing geometry code

- **Golden parts with known answers.** A 10 mm cube has a volume of 1000 mm³. A
  part with a known 2.0 mm wall must return 2.0 mm. Trivial, and it catches an
  embarrassing share of real regressions.
- **Property-based tests.** Volume is invariant under rotation and translation.
  Scaling by k scales volume by k³. Repair must not increase volume beyond a
  bound. These catch classes of bug that examples miss.
- **A deliberately awful corpus.** Non-manifold, inverted, self-intersecting,
  unit-ambiguous, over- and under-tessellated. Real customer data is worse than
  anything you would author, and the engine's behaviour on bad input is most of
  its perceived quality.
- **Determinism tests.** Run twice, assert byte-identical results. This catches
  unseeded randomness and iteration-order dependence, both of which are common
  and both of which are invisible until a customer notices two different answers.
- **Performance guards on realistic sizes.** A test suite of 1000-triangle parts
  tells you nothing about the 5-million-triangle assembly that will arrive on the
  first day of the pilot.
