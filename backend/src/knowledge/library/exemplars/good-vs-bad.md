---
title: "Good vs bad — the exemplar gallery"
domain: exemplars
audience: "Everyone; the fastest way to calibrate judgement"
sources: [boothroyd_dfma, shop_practice_machining, shop_practice_moulding, sfsa_casting, dfam_practice, asme_y14_5]
provenance: DEFAULT
---

# Good vs bad

Paired examples. Each pair is the *same requirement* solved well and solved
badly, because "good design" in isolation is not teachable — the contrast is.

---

## 1. A bracket that mounts a sensor

**Bad.** A solid block, machined from 6061, features on five faces, R0 internal
corners, ±0.05 mm in the title block on all 47 dimensions, no flat surface large
enough to clamp, sensor mounting holes toleranced individually with ±.

**Good.** Sheet metal, 2 mm 5052, one gauge throughout, stiffness from two
flanges and a bead. Three bends, all the same radius, all in one direction.
Sensor holes on a composite position tolerance to a datum scheme taken from the
actual mounting interface. Everything else at ISO 2768-m. A designed relief notch
at each partial bend.

**What changed:** process family, then part definition. The geometry barely
matters — the decision that saved the money was made before any feature was
drawn.

---

## 2. A housing at 50,000 units/year

**Bad.** 4 mm nominal wall "for strength", a solid 8 mm boss standing on the
floor for the screw, zero draft on the textured outer shell, four side actions to
preserve a cosmetic groove, ribs the same thickness as the wall behind the Class-A
face.

**Good.** 2.5 mm uniform wall. Cored boss at 1.5 mm wall, standing 0.5 mm off the
floor, supported by three gussets. 1.5° draft on plain faces, 3° on the textured
shell. The cosmetic groove reshaped to shut off through the wall, deleting every
slide. Ribs at 1.5 mm with R0.8 base fillets, spaced 5 mm apart.

**What changed:** the wall halved the cycle time, and the shut-off deleted a
five-figure tooling line item plus a recurring maintenance failure mode. Neither
change is visible as "better geometry" to a non-specialist.

---

## 3. A pressure-containing body for sour service

**Bad.** 4140 quenched and tempered to 32 HRC because the stress analysis wanted
the strength. Material recorded as "4140, NACE compliant." Hardness certificate
covering base metal. Sharp fillets at the nozzle intersection. Wall thickness
toleranced bilaterally, so the lower limit is below the calculated minimum. NDE
scheduled before final machining.

**Good.** 4140 quenched and tempered to ≤ 22 HRC, with the section sized for the
lower strength. Environment recorded explicitly — H₂S partial pressure, pH,
chloride, temperature — and the specific ISO 15156-3 qualification recorded
against it. Hardness surveyed on base metal, weld metal and HAZ, with PWHT
records. Generous blend radii at the nozzle. Wall toleranced so the **lower
limit** still satisfies the pressure calculation, with corrosion allowance on
top. Volumetric NDE after all welding, PWHT and machining.

**What changed:** the design accepted a lower-strength material and grew the
section, which is the correct trade in sour service and the one people resist.
Everything else is evidence discipline, decided at design time.

---

## 4. A manifold routed to metal AM

**Bad.** Internal channels modelled as horizontal circular bores, so every one
needs internal supports nobody can reach. Sealed plenum with no evacuation port.
Printed as a large flat plate lying down, cut off the plate untreated. O-ring
groove specified at Ra 0.8 as-built. Business case built on print cost alone.

**Good.** Channels shaped as teardrops so the crown self-supports. Two 4 mm
evacuation ports at the low points of every enclosed volume. Oriented to minimise
cross-sectional area per layer, stress relieved **on the plate** before removal.
Sealing faces printed 1 mm oversize and finish-machined after HIP. Coupon
positions reserved in the build layout. Business case including stress relief,
plate removal, support removal, HIP, machining and CT inspection.

**What changed:** the geometry was redesigned *for* the process rather than
translated *into* it — and the cost model included the post-processing that
usually exceeds the print.

---

## 5. A cast pump body

**Bad.** Uniform 8 mm wall everywhere including a heavy isolated hub in the
middle of a thin web. Four ribs meeting at a point under the bearing boss. A
200 mm long, Ø12 mm blind core with a single print. ±0.1 mm applied to as-cast
rib thickness. No machining stock on the mating faces.

**Good.** Wall tapering from 8 mm at the riser to 5 mm at the extremities, so
solidification runs to the feeder. Crossing ribs staggered into two T junctions
instead of one X, with radiused intersections. The cored passage given prints at
both ends and a straight extraction path. As-cast surfaces toleranced to the
casting class; 3 mm machining stock on the two mating faces, with machining
datums designed into the casting.

**What changed:** the designer thought about **solidification** rather than about
wall thickness. That is the difference between a casting engineer and someone
applying a wall-thickness rule to a casting.

---

## 6. The datum scheme

**Bad.** Datum A on the centreline of the main bore. Datum B on a small
convenient face nobody touches in assembly. Position tolerances on the bolt
pattern referenced to A|B, and the bore-to-face perpendicularity referenced to a
different frame.

**Good.** Datum A on the large mounting face that actually seats. Datum B on the
main bore (the physical cylinder, not its axis). Datum C on an anti-rotation
feature. All located features referenced to the same A|B|C frame, in the
precedence order the part actually assembles in. Composite position on the bolt
pattern, separating "where the pattern sits" from "how the holes relate to each
other."

**What changed:** the scheme became a functional statement instead of a
measurement convenience. This is the single most consequential decision on a
definition, and the bad version fails *silently* — inspection measures the wrong
thing correctly.

---

## 7. The CAD model itself

**Bad.** 412 features. 38 rollback errors, several suppressed to force a rebuild.
Sketches on imported faces. Every dimension a literal. Mirrored body leaving
duplicate coincident faces. Modelled thread helices. Part sitting 4 metres from
the origin at an arbitrary angle because it was positioned in the assembly first.

**Good.** 34 features, named, reading as: base shape → functional features →
detail → cosmetic. Sketches on planes and axes. A named parameter set driving the
real design decisions. Watertight, manifold, positive volume. Threads as
callouts. Part at the origin in a meaningful orientation. Material assigned.
Rebuilds clean after a 20% change to any driving dimension.

**What changed:** nothing about the shape. Everything about what the **next**
revision will cost — which is invisible to any analysis that only looks at
geometry.

---

## 8. The cost estimate

**Bad.** "This part costs $47." Built from net mass and cutting time. One setup
assumed. Annual volume used to amortise both setup and tooling. Material priced
as "Inconel 625" with no form. Learning curve applied to everything including
material.

**Good.** A range with a stated basis. Gross mass from the billet, not net.
Setups counted from accessibility and amortised over the **lot**, tooling over
the **programme**. Material priced as wrought or powder explicitly. Learning
applied to attended conversion only. Sensitivity shown: which single input, moved
10%, moves the answer most. Every input labelled MEASURED, SHOP, USER or DEFAULT.
And the crossover quantity stated, so the reader knows where the decision flips
rather than only which side of it they are on today.

**What changed:** the estimate became **falsifiable**. A hostile reviewer can now
argue with it productively, which is the only definition of credible that
survives contact with procurement.

---

## The pattern across all eight

In every pair, the good version is not more clever. It is:

1. **Decided earlier** — process and part-count before features.
2. **Aimed at the physics** — solidification, deflection, thermal history, flow.
3. **Honest about what is not known** — ranges, provenance, stated assumptions.
4. **Designed for the whole chain** — held, measured, inspected, changed, proven.

The bad version is almost always the result of solving the geometry problem
carefully while solving the wrong problem.
