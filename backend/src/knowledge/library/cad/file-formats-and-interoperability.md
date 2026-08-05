---
title: "CAD file formats and interoperability — what survives the exchange"
domain: cad
audience: "Anyone sending or receiving CAD data across an organisational boundary"
sources: [asme_y14_41, asme_y14_5, iso_astm_52900]
provenance: DEFAULT
---

# File formats and interoperability

Every exchange is a **translation**, and every translation loses something. The
discipline is knowing what, and checking.

---

## The format landscape

### Exact geometry (B-rep)

| Format | Carries | Use it for |
|---|---|---|
| **STEP AP242** | Solid B-rep, assemblies, **semantic PMI**, tessellation, kinematics | The modern default for anything crossing an organisational boundary |
| **STEP AP203** | Solid B-rep, assembly structure; PMI only as polylines | Legacy aerospace; avoid for new work |
| **STEP AP214** | AP203 plus colour, layers, some presentation; PMI as polylines | Legacy automotive; use only if the partner cannot take AP242 |
| **IGES** | Surfaces and curves, no reliable topology | Legacy only. Frequently arrives as a bag of surfaces that must be stitched |
| **Parasolid (x_t)** | Exact B-rep, kernel-native | Excellent fidelity between Parasolid-based systems |
| **ACIS (sat)** | Exact B-rep, kernel-native | Same, for ACIS-based systems |
| **JT** | Lightweight, LOD tessellation, optional B-rep and PMI | Visualisation and large assembly review; automotive standard |
| **Native** (`.sldprt`, `.prt`, `.CATPart`) | Everything, including feature history | Only within one CAD system and version |

### Tessellated geometry (meshes)

| Format | Carries | Watch out for |
|---|---|---|
| **STL** | Triangles only | **No units.** No colour, no metadata, no topology guarantees |
| **3MF** | Triangles, **units**, colour, materials, metadata | The technically correct STL replacement |
| **OBJ / PLY** | Triangles, colour, texture | Graphics origins; no engineering metadata |
| **AMF** | Triangles, units, materials, lattices | Little adoption in practice |

---

## The rule that decides most cases

**Send exact geometry when the receiver must manufacture, measure or modify it.
Send tessellated geometry only when the receiver only needs to look at it, or is
running a mesh-native process.**

A mesh is exact only to its chordal deviation. Measuring a radius, a wall
thickness or an angle on a tessellation returns a value wrong by that deviation,
and small features can vanish entirely. A DFM verdict computed on a coarse mesh
is a verdict about the mesh.

---

## STEP AP242 and why the version matters

AP242 unified AP203 (aerospace) and AP214 (automotive) and added the thing that
actually changes workflows: **semantic PMI**.

- **Graphic PMI** — the annotation is stored as polylines. It is a *picture* of a
  tolerance. A human can read it; no software can act on it.
- **Semantic PMI** — the tolerance is stored as a structured object with its
  type, value, modifiers, datum references, **and links to the faces it applies
  to**. Software can extract, balloon, and drive inspection from it.

AP203 and AP214 carry only graphic PMI. AP242 carries semantic PMI.

This is not an academic distinction. In a model-based workflow it produces the
most expensive routine failure in CAD interoperability: **characteristics that
exist on the authoring model, do not survive the exchange, and therefore never
appear on the AS9102 balloon map — so they are never inspected.** The part ships
having never been checked against requirements that were genuinely specified.

Caveat worth stating plainly: PMI interoperability is still incomplete in
practice. Coverage varies by vendor, by AP242 edition, and by specific PMI
capability. "We support AP242" does not mean "every tolerance you author will
arrive intact."

---

## What breaks in translation, and how it shows up

| Failure | Looks like | Catch it by |
|---|---|---|
| **Tolerance mismatch between kernels** | Sliver faces, tiny gaps, failed stitching | Check face and edge counts before and after; look for faces below an area threshold |
| **Surfaces arriving unstitched** | An IGES "solid" that is a bag of surfaces | Verify it is a closed solid with positive volume, not a surface body |
| **Self-intersections after translation** | Downstream operations fail with no clear cause | Geometry validation, every time |
| **Unit ambiguity** | Overall size wrong by a factor near 25.4 | Sanity-check bounding box against the part class |
| **Lost PMI** | GD&T visible as graphics or gone entirely | **Count characteristics before and after** — the only reliable check |
| **Lost assembly structure** | A flat pile of solids, no product structure | Compare component count and hierarchy depth |
| **Lost metadata** | Material, part number, revision gone | Carry them out-of-band as well as in-file |
| **Coarse tessellation on export** | Faceted cylinders, chord marks on curves | Set and record the deviation; never accept a default |

---

## The STL problem, specifically

STL is the lowest common denominator in additive manufacturing and it carries
**no units**. A part authored in inches and interpreted as millimetres is wrong
by 25.4× — and it passes every geometric check, because the geometry is
internally consistent. It is simply the wrong size, and every derived cost is
wrong by 25.4³ on material.

It also carries no topology guarantee. Triangle soup with unshared vertices,
inconsistent normals, and naked edges is a legal STL file.

Defensive practice:

1. **Sanity-check scale** against what the part plausibly is, and ask when it
   looks wrong. Record the answer as USER provenance, not as fact.
2. **Validate manifoldness before computing anything.** Report a repair when one
   happened — a silently repaired model is a changed model.
3. **Record the source tessellation deviation** when you have it, and label any
   measurement taken from a mesh accordingly.
4. **Prefer 3MF** where you control both ends. It carries units, and it is the
   format STL should have been.

---

## The exchange checklist

Before sending:

- [ ] AP242 for anything crossing a boundary, unless the receiver genuinely cannot
- [ ] Semantic PMI, if the workflow depends on PMI at all
- [ ] Units declared explicitly, in-file and out
- [ ] Revision and part number in the filename **and** in the file metadata
- [ ] Geometry validated: closed, manifold, positive volume, no self-intersections
- [ ] A characteristic count recorded, so the receiver can verify nothing was lost

On receiving:

- [ ] Solid, not a surface body
- [ ] Volume, mass and bounding box plausible for the part class
- [ ] Face, edge and body counts compared against the sender's
- [ ] Semantic PMI count compared against the sender's
- [ ] No sliver faces or micro-gaps below the modelling tolerance
- [ ] Assembly structure intact, if there was one

---

## The governance point

The received file is a **derived artifact**. The released native model is the
master. When a supplier manufactures from a STEP file that was emailed six months
ago while the released model moved on, the two now differ and nobody noticed —
this is a routine and expensive configuration-management failure, and it is a
major finding in every regulated industry.

Hash and version every derived artifact against the released source it came from,
so a divergence is detectable rather than discovered.
