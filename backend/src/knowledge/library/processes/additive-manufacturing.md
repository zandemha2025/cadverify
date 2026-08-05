---
title: "Additive manufacturing — powder bed, polymer, binder jet, DED and WAAM"
domain: processes
audience: "Designers considering AM; reviewers checking an AM business case"
sources: [iso_astm_52900, iso_astm_52910, iso_astm_52911, astm_f3301, astm_f2792_hip, dfam_practice]
provenance: DEFAULT
---

# Additive manufacturing

Covers `dmls`, `slm`, `ebm`, `sls`, `mjf`, `fdm`, `sla`, `dlp`, `binder_jetting`,
`ded`, `waam`.

## The sentence everything follows from

**In AM the process makes the material at the same time as it makes the shape.**

There is no bulk material with known properties waiting to be shaped. Properties
emerge from the thermal history of *this* build: orientation, scan strategy,
layer thickness, plate position, atmosphere, powder lot. Every AM surprise —
anisotropy, distortion, inconsistent fatigue life, a part that passed last month
and fails today — is a consequence of that sentence.

It is also why AM qualification is treated as a metallurgical qualification
rather than a dimensional one, and why auditors approach an AM shop the way they
would approach a small foundry.

---

## When AM is genuinely the right answer

Four legitimate reasons. If none applies, AM is probably the wrong process.

1. **Internal complexity no other process can make** — conformal cooling
   channels, internal manifolds, lattice structures.
2. **Part consolidation** — one printed part replacing an assembly of many,
   deleting fasteners, joints, inspection and inventory along with the parts.
3. **Lead time without tooling** — the case for spares, obsolescence and
   bridge production, and often the strongest commercial argument of the four.
4. **Buy-to-fly** — on expensive alloys, depositing 2 kg beats machining 2 kg out
   of a 20 kg billet.

**Not** legitimate: a simple prismatic part routed to metal powder bed because
the printer is available. Metal AM cost is dominated by build time and powder,
both scaling with volume; for simple geometry machining wins decisively — and AM
adds a qualification burden the part never needed.

---

## Metal powder bed (DMLS / SLM / EBM)

### What good looks like

- **Orientation chosen deliberately and recorded on the model**, not left to the
  operator or the nesting software. Properties vary with it, so it is a design
  output.
- **Self-supporting geometry wherever possible** — teardrop and diamond internal
  channels rather than circular ones, chamfers instead of horizontal overhangs.
- **Every enclosed volume drainable**, with two or more evacuation ports ≥ 2 mm
  positioned at real low points.
- **Machining stock modelled in** — typically 0.5–1.0 mm — on every sealing,
  bearing or fatigue-loaded surface.
- **Supports treated as a design problem**: reachable for removal, on surfaces
  that will be machined anyway, never inside a cavity nobody can get into.
- **Cross-sectional area kept modest per layer**, to limit residual stress.
- **Witness coupon locations planned into the build layout.**

### What bad looks like

- **Horizontal circular channels** needing internal supports that cannot be
  reached or removed.
- **Sealed hollow volumes** with permanently trapped powder — dead mass, a
  contamination source, and a rejectable condition invisible from outside.
- **Large flat plates printed horizontally** and cut off untreated: maximum
  residual stress, and the part curls off the plate.
- **As-built surfaces specified with fine Ra.** As-built L-PBF runs roughly
  Ra 6–20 µm, and down-skins are worse.
- **A lattice with no feasible inspection method**, declared conforming on the
  strength of the build log alone.
- **"HIP will fix it."** HIP closes internal gas porosity and lack-of-fusion. It
  does **not** close surface-connected defects, it changes microstructure, and it
  changes dimensions — so machining stock must survive it.

### Expert heuristics

**45° is a heuristic, not a physical constant.** It is a reasonable default for
self-supporting overhangs, but the real limit moves with alloy, layer thickness,
laser parameters and the down-skin finish you will accept. Well-characterised
machines print 30–40° routinely. Treat 45° as a default that a customer's own
process data should replace.

**Design the supports, then the part.** On metal powder bed, support strategy
frequently drives more cost than geometry — support material is printed at full
laser time and removed by hand.

**Residual stress is designed in, not printed out.** Long unbroken scan vectors,
large flat cross-sections and abrupt section changes all accumulate it. Orient to
minimise cross-sectional area per layer, and stress relieve **on the plate**,
before cutting off.

**Height drives build time more than volume.** Cost scales with the number of
layers. A part lying down often prints in a fraction of the time of the same part
standing up — but orientation also sets the anisotropy direction and the support
burden, so the three trade against each other and the trade is the design work.

**Count the post-processing.** Stress relief, plate removal, support removal
(often manual), HIP, machining of interfaces, and inspection. **Post-processing
routinely exceeds print cost**, and it is the term missing from most AM business
cases.

---

## Polymer AM

**FDM** — cheap, fast, ubiquitous, and **anisotropic**: interlayer strength is a
fraction of in-plane strength, because Z strength comes only from polymer
diffusion at the interface during the moment it stays above glass transition.
Orient so principal tensile and bending loads run in-plane. A geometry that is
safe in one orientation fails in another, and orientation is usually recorded
nowhere.

**SLA / DLP** — the best surface finish and finest features in polymer AM.
Two things get missed: enclosed volumes trap **uncured resin** that cures later
and swells the part, so every cup needs a drain hole; and most resins **continue
cross-linking** after the build, so an SLA part is an excellent geometry
prototype and a poor long-term functional part.

**SLS / MJF** — no supports (the powder bed is the support), so genuinely complex
geometry is free. The constraint is powder removal: unsupported holes below about
1.5 mm tend to fill with partially-sintered powder that no bead-blast removes.
The part looks correct and the hole is not there.

---

## Binder jetting

Two-stage: print a green part from powder and binder, then **sinter** it.
Expect roughly **15–20% linear shrinkage** during sintering, only approximately
isotropic, with the part sagging under its own weight at temperature.

The consequence people miss: tolerance capability is far worse than the
printer's own resolution, which is the number everyone quotes. Long thin
geometry slumps; compact self-supporting geometry survives. Sinter setters are
part of the design, not an afterthought.

---

## DED and WAAM

Near-net, not net. Bead width and layer height are one to two orders of magnitude
larger than powder bed, and surface waviness follows. Design in several
millimetres of machining stock on every functional surface.

The economic case is buy-to-fly on **large** parts and the repair of high-value
components — not surface quality. Pretending otherwise wrecks the cost model.
WAAM in particular is a welding process wearing an AM label: it inherits weld
metallurgy, weld distortion, and weld qualification.

---

## The qualification reality

An auditor treats every build as a small metallurgy plant. They will ask:

1. **What exactly is frozen?** Machine, alloy and powder specification, layer
   thickness, beam parameters, scan strategy, atmosphere, plate temperature. A
   silent firmware or parameter update after qualification, with no
   requalification, is a major finding.
2. **Powder lifecycle.** Virgin/recycled blending rules, sieving, oxygen and
   moisture control, lot traceability, reuse limit. Powder lot is material
   traceability — treat it as a heat number. Oxygen pickup in recycled powder
   degrades ductility invisibly.
3. **Orientation and plate position.** Fixed and recorded, because properties
   vary with both.
4. **Witness coupons from the same build**, tested per build. Coupons from a
   separate qualification build do not accept later production builds.
5. **Post-processing records**, including HIP cycle parameters where fatigue or
   pressure duty requires it.
6. **A feasible volumetric inspection method** at the wall thickness and defect
   size of interest.

And in oil and gas specifically: API 6A has no general AM qualification path, so
AM in the pressure boundary needs a purchaser-agreed qualification basis, HIP and
full NDE. AM introduced for lead-time relief on a pressure part with no
qualification basis is a major finding and a genuine safety issue.
