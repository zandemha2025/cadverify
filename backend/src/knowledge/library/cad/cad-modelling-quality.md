---
title: "CAD modelling quality — what expert CAD designers actually do"
domain: cad
audience: "CAD designers, and engineers judging a model they did not build"
sources: [asme_y14_41, boothroyd_dfma, machinerys_handbook]
provenance: DEFAULT
---

# CAD modelling quality

A model has two jobs: describe the geometry, and **survive being changed**. Most
CAD teaching covers the first. Almost all real cost comes from the second.

---

## Model with design intent, not just shape

Design intent is the set of relationships that should hold when something
changes. A bolt circle that stays concentric when the flange grows. A wall that
stays uniform when the shell grows. A rib that stays centred on the boss.

The test is simple and brutal: **change a driving dimension by 20% and rebuild.**
A model built with intent adapts. A model built as a sequence of coordinates
explodes into rollback errors — and every future change becomes a remodel.

### The habits that produce it

- **Sketch on planes and axes, not on imported faces.** A sketch referencing a
  face is hostage to that face surviving every future edit. This one habit
  prevents the majority of rebuild failures.
- **Fully define sketches.** An under-defined sketch will move when you are not
  looking, usually in a way nobody notices until inspection.
- **Fewest features that express the intent.** A part with 400 features and
  30 real transitions is telling you it was built by accretion.
- **Name features and bodies.** A tree of `Extrude47`, `Cut12`, `Fillet203` is
  unreadable to the next person, who is frequently you.
- **Fillets and chamfers last**, in as few operations as possible. They are the
  most fragile features in any tree and the most expensive to rebuild.
- **One driving parameter per real design decision**, not the same number typed
  in nine places.
- **Model the manufacturing intent** — draft in the model rather than assumed,
  machining stock as an explicit body or feature, as-cast versus as-machined
  states distinguished.

---

## What good looks like

- Opens and rebuilds clean, with no errors and no warnings.
- The feature tree reads as a description of the part: base shape, functional
  features, detail features, cosmetic features — roughly in that order.
- Driving dimensions live in a small, named set, ideally a design table or
  equation set.
- External references are deliberate, few, and documented; nothing points at
  geometry that might disappear.
- Watertight, manifold, correctly oriented, no zero-thickness geometry, no
  self-intersections, no stray surface bodies.
- Units and the coordinate origin are explicit and sensible; the part sits at a
  meaningful origin in a meaningful orientation.
- Material assigned, so mass properties are real rather than decorative.
- If the model carries PMI, it is **semantic** and complete enough to define the
  part without a drawing.

## What bad looks like

- **Rollback errors on open**, or features suppressed to make it rebuild.
- **A tree far longer than the geometry justifies**, full of tiny corrective cuts
  — the signature of modelling by patching rather than by intent.
- **Sketches on imported or dumb-solid faces**, so any upstream change breaks
  everything downstream.
- **"Dumb solid" imports with history discarded**, then edited by direct
  modelling. Fine as a one-way transfer; a liability as a master model.
- **Mirrored bodies producing duplicate coincident faces**, which pass visually
  and fail as non-manifold.
- **Modelled thread helices** instead of a callout — slow to process, sometimes
  geometrically wrong, and never how a thread is actually made.
- **Zero-thickness geometry and knife edges** at tangent transitions.
- **The part modelled far from the origin**, at an arbitrary orientation, because
  it was positioned in an assembly first.
- **Cosmetic detail modelled at full fidelity** — logos, textures, knurls — that
  slows every downstream operation and means nothing to manufacturing.

---

## The signal nobody reads: a bad model is a cost forecast

A model that cannot be changed safely means every engineering change becomes a
remodel, and every revision carries a risk of silent geometry drift. That is real
programme cost, and it is entirely invisible in the shape.

Observable tells, in rough order of severity:

1. Rebuild errors present.
2. Feature count far above the geometric complexity.
3. External references pointing at deleted or renamed geometry.
4. Suppressed features doing load-bearing work.
5. No named parameters; every dimension a literal.
6. Multiple bodies with no clear purpose.

Any DFM engine that can see the CAD file and not just the geometry should be
reporting this, because it predicts the cost of the *next* revision.

---

## Assemblies

- **Constrain to a skeleton or layout**, not part-to-part in a chain. A chain of
  mates propagates every change through everything and takes half a day to
  diagnose when it breaks.
- **Avoid circular references** between parts.
- **Model the fit, not the nominal.** A shaft and bore modelled at the same
  diameter look correct and tell you nothing about whether they assemble.
- **Keep a real bill of materials** in the assembly, with part numbers that mean
  something outside CAD.
- **Simplified configurations for large assemblies** — the analysis model and the
  detail model are different objects with different jobs.

---

## Robustness rules worth enforcing automatically

These are cheap to check and catch most real defects:

| Check | Why |
|---|---|
| No rebuild errors or warnings | The model does not currently work |
| No under-defined sketches | Geometry that can move silently |
| No external refs to non-existent geometry | Guaranteed future breakage |
| Watertight, manifold, positive volume | Every derived number is otherwise undefined |
| No zero-thickness faces or knife edges | Fails downstream meshing and CAM |
| Units declared, part near origin | Prevents the 25.4× class of error |
| Material assigned | Mass properties otherwise fictional |
| Feature count within a sane band for the geometry | Detects modelling-by-accretion |

---

## Where CAD hygiene meets manufacturing

Three habits an expert CAD designer has that a competent one often does not:

**Model to the process.** A part destined for moulding gets draft modelled in
from the first extrude, not added at the end where it breaks every downstream
feature. A casting gets its as-cast and as-machined states as distinct,
maintained configurations.

**Model the datum scheme.** Datum features should be identifiable geometry in the
model, chosen for how the part mounts, and stable across revisions. If the datums
move between revisions, every inspection history becomes incomparable.

**Model what will be inspected.** If a characteristic must be measured, it must be
reachable — and that is a modelling decision, made long before anyone tries to
put a probe on it.
