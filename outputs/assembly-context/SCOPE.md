# CadVerify — Assembly Context Layer (TRUE BLUE, not surface-level)

**Thesis (founder):** the assembly ("environment") and the whole ("total") are inputs to
*every* analysis, not a viewer feature. CadVerify today analyzes each part in ISOLATION.
This layer makes the part's context a real input to the verdict, cost, DFM, material, and
fit — and renders it inside the existing Verify design (the look Claude Design made).

**Bar:** TRUE BLUE all the way. No surface-level demo. Every claim backed by a real run on
a real assembly. Where a tier genuinely needs heavier tooling, we LABEL it an honest gate —
we never fake depth. Real where we can be, honest where we can't.

**De-risked (spike, real AS1 STEP assembly, committed):** gmsh/OCC already yields per-part
solids + baked world positions (bbox/centroid/mass) + the nested product tree. So assembly
ingest is a policy choice, not a capability gap.

---

## Phases (each REAL end-to-end + human-sim verified before it counts as done)

### P1 — Real assembly ingestion (backend)
Parse a STEP assembly → structured `{ parts: [{ mesh, world_transform/position, name,
tree_path, geometry_summary }], tree }`. Per-part meshes (not one flattened blob). Detect
assembly-vs-single-part on upload (replace the current blanket "refuse assemblies"). Tested
against the real AS1 assembly (18 solids) + a single-part control (must stay byte-identical).
Honest limits surfaced: AP203 drops mates/GD&T; native .SLDASM/.prt need a licensed reader.

### P2 — Part-in-context render IN THE VERIFY DESIGN
The assembly renders in the SAME Verify stage component (real-shell material, x-ray, orbit,
seat interactions) — one part highlighted as "the part", the rest dimmed as its context.
NOT a bare three.js harness. Pick the part-of-interest from the tree. Matches Claude Design.

### P3 — Context-fed ANALYSIS (the true-blue core; each dimension genuinely wired)
- **Derived service world** — infer/suggest the world from the part's position/role in the
  assembly (exterior vs internal, etc.); honest that it's a suggestion the user confirms, not
  a fabricated fact. Feeds the existing material-survival gate.
- **Real total economics** — units-per-parent × parents-per-year from the real tree drives
  annual volume → the existing cost/crossover engine (make the declared part-context real).
- **Real clearance / interference** — pure geometry: does the part intersect/contact its
  neighbors? Real pairwise checks on the extracted meshes. No fakery.
- **Interface DFM** — flag features/faces that mate with neighbors (constraints only visible
  in context). Feed the existing DFM engine.
- Run the existing per-part DFM/cost engine on EACH part unchanged, then add the context.

### P4 — Honest gated tier (built-ready, labeled, NOT faked)
Tolerance stack-up + mate semantics (needs AP242 + OCP/B-rep kernel); assembly-sequence
manufacturability; native-CAD ingest (licensed reader). Prepared + clearly labeled as gates.

---

## Discipline
Every phase: real build → adversarial verify → Fable re-verifies the crux on a REAL assembly
→ human-sim in the real UI (screenshot proof) → integrate. Nothing merges as "true" without a
real run. A hardcore engineer must look at it and believe it — or it isn't done.
