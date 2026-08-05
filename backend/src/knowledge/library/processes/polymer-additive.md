---
title: "Polymer additive manufacturing — FDM, SLA/DLP, SLS and MJF"
domain: processes
audience: "Anyone specifying, quoting or reviewing a printed polymer part"
sources: [shop_practice_polymer_am, iso_astm_52900, iso_astm_52910, dfam_practice]
provenance: DEFAULT
---

# Polymer additive manufacturing

Four technologies with almost nothing in common except that they build in layers.
Treating them as one process — "3D printing" — is the root of most bad decisions
in this space, because their constraints are not merely different, they are
opposite. FDM's limit is the extrusion bead. SLA's limit is peel force. SLS's
limit is heat bleeding into powder. Binder-adjacent MJF adds a chemistry step.

| | FDM | SLA / DLP | SLS / MJF |
|---|---|---|---|
| Builds by | Extruding a bead | Curing resin with light | Fusing powder with heat |
| Supports | Required, printed, removable | Required, and they scar the surface | **None** — the powder supports |
| The real limit | Bead width and layer adhesion | Peel force on each layer | Heat bleed into surrounding powder |
| Anisotropy | Severe — Z is weak | Mild | Mild |
| Surface | Visible layer lines | The best available | Uniformly matte, slightly porous |
| Fails by | Delamination, warping | Cupping, post-cure drift | Fused assemblies, trapped powder |
| Best at | Cheap, fast, large, iterative | Fine detail and finish | Complex geometry and functional parts |

---

## FDM

### The physics

A bead of molten polymer is laid down and welded to its neighbours by remaining
briefly above glass transition. Two consequences drive everything:

**Walls are built from whole beads.** A wall that is not an integer multiple of
the extrusion width gets a gap or an over-extruded seam. This is why the minimum
wall is quoted differently by everyone — it is a property of the nozzle, not the
material. Three perimeters (about 1.2 mm on a 0.4 mm nozzle) is the practical
floor for a wall that holds its shape; 2–3 mm for anything loaded.

**Z is the weak axis, structurally.** In-plane strength comes from continuous
filament; Z strength comes only from the polymer diffusion achieved at the layer
interface in the moment it stayed hot. A geometry that is safe in one orientation
fails in another — and orientation is usually recorded nowhere on the drawing.

### What good looks like

- Loads running in-plane, never across layers.
- Openings arched or chamfered at the crown so nothing has to bridge.
- Overhangs chamfered to 45°, so no support and no witness marks.
- Holes modelled oversize or designed to be reamed — they print undersize, every
  time, in the same direction.
- Radiused footprint corners and a ribbed rather than solid base on tall parts.
- Fit clearances designed in: roughly 0.2 mm total for a press fit, 0.3–0.4 mm
  for a sliding fit, against a dimensional capability around ±0.3 mm.

### What bad looks like

- A threaded boss printed vertically and loaded in tension.
- A 40 mm flat-topped rectangular window expected to bridge cleanly.
- An H7 bore modelled at nominal, expected to accept a dowel.
- A 200 × 200 mm flat ABS plate with sharp corners printed flat, lifting off the
  bed at every corner.
- A horizontal boss underside on a cosmetic face — supported, then scarred.

### The expert move

Orientation is the whole design. It simultaneously sets strength direction,
support burden, which surfaces get scarred, and print time. Decide it
deliberately and record it, because if you do not, the operator will decide it
for you and the part's properties will change between batches with nothing
recording why.

---

## SLA and DLP

### The physics

Resin cures where light hits it, and each cured layer must then be **peeled** off
the vat film. Peel force, not resolution, is the binding constraint — which
surprises everyone, because resin printers resolve far finer features than their
minimum wall suggests.

**SLA** traces with a laser spot; **DLP** cures a whole layer from a projected
pixel grid. That difference matters: a DLP machine's minimum feature is a fixed
fraction of its build area, so scaling up the build volume directly costs
detail. "Resin printing" does not have one resolution.

### What good looks like

- 2 mm shell on hollowed parts, internally ribbed, tilted 20–30° rather than flat
  to the vat.
- Two drain holes of 3.5–4 mm at the true low points of every hollow section.
- Orientation chosen so support witness marks land on non-critical faces.
- Clearances of about 0.1 mm on mating features, 0.15 mm on rotating fits,
  measured **after** full post-cure.

### What bad looks like

- A downward-facing cup with no drain: resin is trapped, a suction cavity forms
  on every peel cycle, and the shell cracks. This failure has a name — cupping —
  because it is that common.
- A solid 80 mm block printed flat against the vat: maximum peel force per layer,
  wasted resin, and exotherm during cure.
- A lens or sealing surface printed downward, supported, then sanded — destroying
  the finish SLA was chosen for.
- Dimensional acceptance on a green part, before post-cure.

### The thing that catches people out

**Resin keeps moving after the build.** Roughly 0.2–0.5% shrinkage during
printing, another 0.1–0.3% during UV post-cure, and slow continued change under
ambient UV thereafter. An SLA part is an excellent geometry prototype and a poor
long-term dimensional reference — a distinction routinely lost between the
person who printed it and the person who measures it six months later.

---

## SLS and MJF

### The physics

The whole powder bed sits just below melting; a laser (SLS) or a deposited
fusing agent plus infrared (MJF) pushes selected regions over the line. The
powder itself is the support, which is why genuinely complex geometry is free
here in a way it is nowhere else.

The cost of that: **heat bleeds into the powder around every solid region.**
Everything difficult about SLS follows from that one fact.

### What good looks like

- 2.5–3 mm walls where loaded, 0.8 mm floor for non-structural geometry — sized
  as much to survive bead-blast depowdering as to print.
- 0.5–0.7 mm clearance anywhere two surfaces must move or separate.
- Internal channels at least 2 mm, with escape holes of 3.5–4 mm, or two of at
  least 2 mm on parts over about 50 mm.
- Print-in-place mechanisms designed with real clearance and blown clear
  immediately.

### What bad looks like

- 0.2 mm clearance on a print-in-place mechanism. Heat bleed partially sinters the
  powder in the gap, and the assembly comes out as a single welded lump —
  invisible until depowdering.
- Ø0.8 mm cooling holes: powder cakes into a plug that no blasting removes. The
  part looks correct and the hole is not there.
- A 1.5 mm serpentine channel 200 mm long with one port.
- 0.6 mm fins expected to survive blasting.

### The invisible variable

**Where the part sat in the bed changes what it is.** A densely packed bed runs
hotter than a sparse one; the centre runs hotter than the edges. Identical
geometry printed in two different nests is not identical — in properties, colour
or dimensions. Bureaux nest for yield, which optimises directly against that
consistency. If repeatability matters, fix and record the nest position, and
expect to pay for it.

### MJF specifics

MJF parts come out grey and mildly porous, because the fusing agent is itself
dark. Dyeing is standard but penetrates only near the surface, so any face
machined afterwards reveals grey substrate. The porosity that takes dye also
takes moisture and contaminants — which matters far more for medical,
food-contact and sealing duty than for appearance.

---

## Choosing between them

| If the requirement is | Choose | Because |
|---|---|---|
| Cheap, fast, large, iterative | FDM | Lowest cost per volume; no post-processing chemistry |
| Fine detail, smooth surface, optical clarity | SLA / DLP | Nothing else in polymer comes close |
| Functional parts, complex geometry, no supports | SLS / MJF | The powder bed supports everything |
| Living hinges, snap fits, real toughness | SLS / MJF (nylon) | Genuinely ductile; FDM delaminates, SLA is brittle |
| Anything load-bearing across the build direction | **None of them** | Reconsider orientation, or reconsider AM |

## What experienced people ask first

1. **What is the load, and in what direction?** Answers the orientation question,
   which answers most of the rest.
2. **Is there an enclosed volume?** Then it must drain — powder or resin — and
   the ports have to be modelled now.
3. **Does anything have to move, fit or seal?** Then clearance and post-cure
   drift are design inputs, not surprises.
4. **How many, and how repeatable?** One part is a print. A thousand repeatable
   parts needs fixed orientation, fixed nest position, and recorded parameters —
   which is a qualification problem, not a printing one.
5. **What surface does the customer actually touch?** That surface must not be
   the supported one, and that is decided at orientation.
