---
title: "Forging and sheet metal — deformation processes"
domain: processes
audience: "Designers routing to forged or fabricated parts"
sources: [asm_handbook, din_6935, shop_practice_sheet_metal, api_6a]
provenance: DEFAULT
---

# Forging and sheet metal

Covers `forging`, `sheet_metal`. Both deform solid material rather than melting
or cutting it, which gives them a shared property no other family has: **the
material's internal structure changes with the shape.**

---

## Forging

### Why anyone forges

Not to make a shape — machining makes shapes better. You forge for **grain flow**.
Deformation aligns the metal's grain with the part contour, and a grain structure
that follows the load path is dramatically more resistant to fatigue and stress
corrosion than one cut through it.

This is why forged wellhead components, rotorcraft hubs and landing-gear parts
carry grain-flow requirements and macroetch inspections — and why a
"machined-from-billet equivalent" is **not** equivalent. It is the same shape with
a different and worse internal structure, and substituting one for the other as a
cost saving is a genuine integrity decision, not a purchasing one.

### What good looks like

- **Grain flow following the principal stress path**, and critical features not
  machined across it.
- **Generous draft** — typically 3–7° — and radii substantially larger than a
  machined equivalent would need.
- **Webs and ribs the die can actually fill**, with section thickness increasing
  toward the areas that must fill last.
- **Machining stock on functional surfaces**, with datums that survive from
  forging through to machining.
- **A parting line chosen deliberately**, in a low-stress region, with flash
  removal accounted for.

### What bad looks like

- **Sharp fillets and thin draft.** Metal flow stalls at sharp corners; laps and
  cold shuts form there, and the die cracks from the same stress concentration.
  A 1 mm fillet at 1° draft on a hot-forged steel flange is a die-life problem
  and a part-integrity problem at once.
- **Deep narrow ribs** the die cannot fill.
- **Critical threads machined across exposed end grain.**
- **A billet substitution accepted as equivalent** with no grain-flow argument.

### The audit angle

For API 6A pressure-containing forgings the auditor will look for macroetch
sections demonstrating grain flow, forging reduction ratio, heat treatment
records, and — for sour service — hardness surveys within the 22 HRC ceiling
across base metal, weld and HAZ. Rib defects and incomplete die fill in a
pressure-containing forging are rejects, not cosmetic issues.

---

## Sheet metal

### The defining constraint

**One thickness, throughout.** A sheet-metal part is a single gauge, formed. The
moment the model has a local thickening, a machined pocket or a variable wall, it
is not a sheet-metal part — and if it is routed as one, the entire cost model is
wrong and the quote will come back as machining.

Stiffness comes from **geometry**: flanges, ribs, joggles, beads, hems. Never
from thickness variation.

### What good looks like

- **Uniform gauge**, with stiffness from formed features.
- **Consistent bend radii** across the part, ideally one radius, so one tool does
  every bend. Tool changes cost more than bends.
- **Inside bend radius at about one material thickness** as a default; mild steel
  commonly manages 0.5×t, hard tempers and high-strength alloys need more.
- **Flanges long enough to form** — the published range is 3×t to 4×t plus bend
  radius, and which end of it applies depends on the shop's press-brake tooling.
- **Holes clear of the bend deformation zone** — 2×t, or 1.5×t plus bend radius;
  slots want 3×t.
- **Relief notches at the end of every partial bend**, at least one material
  thickness wide and deeper than the bend radius.
- **Bends in one direction where possible**, and a bend sequence that does not
  require the operator to reach through a formed feature.
- **Tolerances that respect bend stack-up** — accumulated across several bends
  it grows fast.

### What bad looks like

- **A 'sheet metal' bracket with a 6 mm boss** modelled into one face.
- **R0 sharp bends** in CAD. Bends have radii; the flat pattern computed from a
  sharp bend is wrong, so the part comes out the wrong size.
- **Threaded inserts 1 mm from a bend line.** The hole pulls oval and the flange
  distorts; the failure looks cosmetic and is functional.
- **Partial flanges with no relief.** The material tears or drags a distorted web
  — the single most common flat-pattern defect, and the one most often absent
  when a solid model is shelled and unfolded afterwards.
- **Tight tolerances across multiple bends**, where the stack-up exceeds the
  tolerance before the first part is made.
- **Every bend a different radius**, forcing tool changes nobody priced.

### The K-factor, briefly

Bending stretches the outside and compresses the inside; the neutral axis sits
somewhere between. The **K-factor** locates it as a fraction of thickness —
roughly 0.33–0.44 for mild steel and 0.40–0.50 for stainless, though it moves
with radius, thickness and tooling.

Bend allowance follows: `BA = π × (IR + K×T) × A/180`.

Why a designer should care: the flat pattern depends on the K-factor, and the
K-factor depends on the shop's tooling and material. **The flat pattern is the
fabricator's to compute, not the designer's to dictate.** Sending a flat pattern
derived from a default K-factor and expecting formed dimensions to land is a
recurring, avoidable error.

### Grain direction

Bending **across** the rolling direction tolerates a tighter radius than bending
**along** it. A bend that works on one coil cracks on the next when the blank
nesting rotates. If a bend is near the material's forming limit, the drawing
needs to constrain grain direction — and constraining it costs nesting yield,
which is a real trade rather than a free note.

### Where cost lives

The number of bends and the number of tool changes, not the area. Then nesting
yield on volume. Then any tolerance that the brake cannot hold, which silently
converts the part into a machined one.

---

## The shared lesson

Both processes change the material as they change the shape. In forging that is
the entire point and the reason to pay for it. In sheet metal it is the reason
bends have limits, springback exists, and the flat pattern belongs to the shop.

Neither process can be reasoned about as "a shape" alone — which is exactly why
a purely geometric analysis of either one is incomplete, and why the material
condition and the shop's own tooling have to be part of the verdict.
