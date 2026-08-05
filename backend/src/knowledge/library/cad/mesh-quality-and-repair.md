---
title: "Mesh quality and repair — analysing geometry you did not author"
domain: cad
audience: "Engineers and developers computing anything from a tessellated model"
sources: [asme_y14_41, iso_astm_52900]
provenance: DEFAULT
---

# Mesh quality and repair

Most parts arriving at a verification engine are meshes, and most of them are
imperfect. What you do about that determines whether every number downstream is
meaningful or fictional.

---

## What "valid" means

A mesh usable for engineering analysis is:

- **Watertight** — no boundary (naked) edges. Every edge bounds exactly two
  faces.
- **Manifold** — no edge shared by three or more faces; no vertex joining two
  otherwise-separate surface sheets.
- **Consistently oriented** — all normals outward, so the enclosed volume is
  positive and well defined.
- **Non-self-intersecting** — no triangle passing through another.
- **Single-component**, or with components that are genuinely intended.

Fail any of these and **volume, mass, wall thickness and centre of gravity are
undefined**. Every cost number derived from them is fiction — which is precisely
what a provenance-carrying engine must refuse to produce.

---

## The defects, and where they come from

| Defect | Typical origin | Consequence |
|---|---|---|
| **Naked edges / holes** | Failed B-rep→mesh conversion; damaged file | Volume undefined |
| **Non-manifold edges** | Mirrored bodies; booleans that left coincident faces | Ambiguous inside/outside |
| **Inverted normals** | Some exporters; subtracted features | Negative or wrong volume |
| **Self-intersections** | Aggressive booleans; offset surfaces | Downstream operations fail unpredictably |
| **Degenerate triangles** | Zero area from coincident vertices | Normals undefined; analysis crashes |
| **Duplicate vertices** | Triangle soup with unshared vertices (classic STL) | Topology cannot be built at all |
| **Coarse tessellation** | Export at a loose chordal deviation | Small features vanish; radii and walls measured wrong |
| **Over-tessellation** | Export at an unnecessarily fine deviation | Enormous files, slow analysis, no accuracy gained |
| **Floating debris** | Stray fragments left from modelling | Bounding box wrong; component count wrong |

---

## The tessellation accuracy problem

A mesh approximates curved surfaces with flat triangles. The **chordal
deviation** — maximum distance between the true surface and its triangle — bounds
every measurement you take.

Concretely: a Ø10 mm cylinder tessellated at 0.1 mm deviation reads as a
polygon. Its measured radius is systematically small, a wall-thickness ray cast
against it lands on a flat, and a fillet smaller than the deviation may not
appear at all.

Three consequences for an engine:

1. **Never report more precision than the tessellation supports.** A wall
   thickness of "2.03 mm" from a mesh with 0.1 mm chordal error is three digits
   of confidence backed by one.
2. **Analyse from B-rep when you have it.** Exact surfaces give exact radii, exact
   angles, and reliable feature recognition. Falling back to mesh is a
   degradation and should be labelled.
3. **When you must decimate for performance, say so.** The "decimated-mesh
   notice" is not a UI nicety — it is the honest statement that the analysed
   geometry is not the delivered geometry.

---

## Repair, and its ethics

Repair is sometimes necessary and always a **modification**. The rules that keep
it honest:

1. **Never repair silently.** A repaired model is a changed model. Anything
   computed from it must say a repair happened.
2. **Record what changed** — hole count filled, area added or removed, volume
   before and after. If repair changed volume by 4%, every mass and material cost
   moved by 4%.
3. **Prefer minimal repair.** Filling a small hole is benign. Re-meshing the
   whole part to force manifoldness produces a different part.
4. **Refuse when repair would be a guess.** A mesh with a large missing region has
   no unique correct closure. Filling it invents geometry, and inventing geometry
   is precisely the failure a verification engine exists to prevent.
5. **Keep the original.** Always. The repaired mesh is a derived artifact.

The repair ladder, cheapest and safest first:

```
merge duplicate vertices      → recovers topology from triangle soup
remove degenerate triangles   → removes zero-area faces
orient normals consistently   → fixes inside/outside
fill small holes              → closes genuine gaps
remove floating components    → deletes debris (check it IS debris)
resolve self-intersections    → geometry changes; be careful
remesh                        → last resort; a different part
```

---

## Practical thresholds

Defaults, to be replaced by measured behaviour on real customer data:

| Check | Suggested threshold | Rationale |
|---|---|---|
| Naked edges | 0 for analysis | Volume otherwise undefined |
| Non-manifold edges | 0 | Inside/outside otherwise ambiguous |
| Degenerate triangles | 0 | Normals otherwise undefined |
| Hole size auto-fillable | < 1% of surface area, and small vs minimum wall | Larger closures are guesses |
| Chordal deviation | < 10% of the smallest feature of interest | Below this, features disappear |
| Volume change after repair | Report above 0.1%; flag above 1% | Directly moves every mass-based cost |
| Floating components | Report all | Could be debris or could be the part |

---

## What to tell the user, and when

The honest states this earns:

- **"This model was not watertight; we repaired N holes and volume changed by
  X%."** Shown before any number derived from it.
- **"Analysed from a decimated mesh at Y mm deviation; features below that size
  may not be detected."** Attached to the finding list, not buried.
- **"Wall thickness measured on a tessellation; precision is bounded by the
  chordal deviation."** Attached to the number itself.
- **"We could not repair this model reliably. Here is what is wrong and what we
  would need."** The correct answer when repair would be invention.

Every one of these is a designed state rather than an error message. A user who
learns that the engine tells them when it is standing on soft ground will believe
it when it says the ground is solid — which is the entire trust proposition.

---

## For engine developers

- Compute topology **once**, from merged vertices, and cache it. Most mesh
  operations are topology queries wearing a geometry costume.
- Watertightness is cheap to check (count edges with a single incident face) and
  must gate everything that follows.
- Signed volume via the divergence theorem also validates normal orientation:
  negative volume means inverted normals, and it is free.
- Wall thickness by ray casting or sphere fitting is sensitive to tessellation
  and to sampling density — record both, and never report more digits than they
  support.
- Feature recognition on meshes is fundamentally harder than on B-rep, because
  the primitives were destroyed at tessellation. Prefer B-rep when available and
  be explicit when falling back.
