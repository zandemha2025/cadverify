---
title: "The environment atlas — all eighteen worlds a part may have to survive"
domain: foundations
audience: "Anyone declaring or reviewing a part's service environment"
sources: [nace_mr0175, asme_bpvc_viii, asme_b31_12, astm_e595, astm_e185, nsf_61, fda_food_contact, iso_17665_11135_11137, iso_9223, ipc_2221, asm_handbook, as9100, iso_10993, api_6a]
provenance: DEFAULT
---

# The environment atlas

The machine-readable definitions live in `packs/environments.yaml`. This is the
navigable version: what each environment attacks with, and the one thing people
get wrong about it.

**The rule underneath all of them:** environment gates material, material gates
process, process gates geometry. Reversing that order produces an elegant part
that fails in service.

**And the rule about the rule:** an environment is a *set of parameters*, not a
label. "Sour service" without an H₂S partial pressure is not a declaration, it is
a word. Every environment below has parameters that must be stated for anything
downstream to mean anything.

---

## Corrosion family

| Environment | Attacks with | The common mistake |
|---|---|---|
| **Sour service (H₂S)** | Hydrogen entering the steel — SSC, HIC, SOHIC | Treating NACE compliance as a property of the alloy rather than of the alloy *in a stated environment* |
| **Subsea / seawater** | Galvanic cells, crevice and pitting attack, HISC under cathodic protection | Forgetting that the area ratio matters more than the couple — a small anode against a large cathode corrodes fast |
| **Atmospheric / coastal** | Time-of-wetness plus chloride and SO₂ deposition | Saying "coastal" instead of stating an ISO 9223 category, which cannot be designed against |
| **Hydrogen service** | Embrittlement, accelerated fatigue crack growth, permeation | Reaching for a stronger alloy — hydrogen compatibility runs **inverse** to strength |

The one to internalise: **sour service and chloride SCC constraints collide.** The
alloy that satisfies one can fail the other, which is why duplex and nickel
alloys dominate combined duty rather than austenitic stainless.

## Thermal family

| Environment | Attacks with | The common mistake |
|---|---|---|
| **Cryogenic** | Ductile-to-brittle transition in BCC metals; differential contraction | Proving toughness with room-temperature tensile data instead of Charpy impact at the minimum design metal temperature |
| **Elevated temperature** | Creep, sensitisation of austenitic stainless, thermal fatigue | Designing to yield strength when the basis should be stress-to-rupture over a design life |
| **Vacuum and space** | Outgassing, cold welding, thermal cycling with no convection, radiation | Screening structural polymers but not the labels, tapes, lubricants and conformal coatings |

The one to internalise: **FCC metals have no ductile-to-brittle transition and
BCC metals do.** That single fact decides most cryogenic material selection.

## Biological family

| Environment | Attacks with | The common mistake |
|---|---|---|
| **Implantable / patient-contact** | Adverse biological response, fretting wear debris | Arguing biocompatibility from the raw alloy certificate, ignoring manufacturing residues |
| **Potable water** | Leaching, biofilm, dezincification | Certifying the material rather than the finished component — the coating and elastomer are part of it |
| **Food / pharma contact** | Migration into product, microbial harbourage, cleaning chemistry | Treating it as a material question when the geometry is the hazard |
| **Repeated sterilisation** | Steam hydrolysis, EO residue, cumulative radiation dose | Qualifying one cycle for a device that will see hundreds |

The one to internalise: in all four, **the requirement attaches to the finished,
processed component** — not to the material it is made from. Cleaning chemistry,
surface finish and manufacturing residues are all part of the argument.

## Structural family

| Environment | Attacks with | The common mistake |
|---|---|---|
| **Flight-critical / fracture-critical** | High-cycle fatigue; an assumed initial defect population | Assuming a process whose defect statistics are not actually characterised |
| **Nuclear / ionising radiation** | Irradiation embrittlement, IASCC, activation, polymer degradation | Ignoring cobalt content, which dominates plant dose rates for decades |
| **Vibration and cyclic loading** | Fatigue from surface condition, resonance, fretting, fastener loosening | Specifying a stronger material with a sharper fillet — which is usually worse |
| **Electrical and thermal** | Clearance and creepage breakdown, thermal path resistance, CTE mismatch, EMI apertures | Anodising a chassis and expecting it to conduct — anodising is an insulator |

The one to internalise: **fatigue life is governed by surface finish, residual
stress and stress concentration, not by static strength.** This is why as-built
AM surfaces have such poor fatigue performance, and why EDM recast layers and
grinding burn matter so much.

## Mechanical and wear family

| Environment | Attacks with | The common mistake |
|---|---|---|
| **Pressure-containing** | Under-minimum wall after all allowances; stress concentration at transitions | Letting a bilateral tolerance eat into the calculated minimum wall |
| **HPHT downhole** | Combined pressure and temperature derating; rapid gas decompression of seals; combined corrosion | Qualifying at each condition separately instead of at the combined envelope |
| **Erosive / abrasive flow** | Solid-particle erosion; erosion-corrosion synergy | Selecting on hardness alone — the alloy must also re-passivate |

The one to internalise: **velocity is the dominant erosion variable**, entering at
a power typically between 2 and 3. Geometry that slows the flow and avoids
impingement beats any material change.

---

## Environments stack, and their solutions conflict

The single most useful thing to understand here. Real parts rarely live in one
environment:

- A subsea wellhead component is **sour + chloride + pressure-containing +
  seawater + HPHT** simultaneously.
- A reusable surgical instrument is **implantable + repeated sterilisation +
  vibration**.
- A hydrogen refuelling valve is **hydrogen + pressure-containing + cyclic
  loading + atmospheric**.

Each constraint narrows the material set, and the intersection is often small or
empty. When it is empty, the honest answer is that the requirement set is
infeasible — and saying so early is worth more than any optimisation.

This is also why nickel alloys dominate the hardest duties despite their cost and
their terrible machinability: they are frequently the only alloy family sitting
in the intersection.

---

## What a good environment declaration contains

Not a label. Parameters:

- **Chemistry** — H₂S partial pressure, CO₂, chloride concentration, in-situ pH,
  elemental sulphur, the actual medium.
- **Temperature** — minimum design metal temperature and maximum operating,
  separately.
- **Pressure** — internal, external, and the cycling profile.
- **Loading** — static, cyclic, or vibratory, with the spectrum.
- **Exposure** — corrosivity category, radiation dose over life, sterilisation
  cycle count over life.
- **Design life**, and whether intervention is possible.
- **Consequence of failure**, which sets the whole evidence burden.

Anything the engine screens on must trace back to one of these. A compliance flag
with no environment behind it is exactly the red flag the corpus warns about —
and it is the most common documentation defect in the field.
