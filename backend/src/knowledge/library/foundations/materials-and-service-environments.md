---
title: "Materials and service environments — selecting for the world the part lives in"
domain: foundations
audience: "Designers and reviewers making or checking a material call"
sources: [nace_mr0175, asm_handbook, asme_bpvc_viii, iso_10993, api_6a]
provenance: DEFAULT
---

# Materials and service environments

The order matters and it is almost always got wrong: **environment gates
material; material gates process; process gates geometry.** Optimising geometry
first and checking the environment last produces an elegant part that cracks.

---

## The alloy families, in one page

**Carbon and low-alloy steels** (A105, 4130, 4140, A182 F22) — cheap, strong,
weldable, well understood. Corrode. Have a ductile-to-brittle transition, so
they need impact qualification for cold service. Their strength comes from
hardness, which is exactly what sour service forbids, so the sour-service answer
is usually "quenched and tempered *down* to ≤ 22 HRC".

**Austenitic stainless** (304L, 316L) — excellent general corrosion resistance,
fully ductile to cryogenic temperatures (no DBTT), non-magnetic, easy to weld.
Two weaknesses that get missed: **chloride stress-corrosion cracking** in hot
chloride service, and **sensitisation** if held at 425–815 °C, which happens in
the heat-affected zone of every weld unless you use L or stabilised grades.

**Duplex and super duplex** (2205, 2507) — a mixed austenitic/ferritic
microstructure giving roughly double the yield strength of 316L with much better
chloride SCC resistance. The catch is a narrow processing window: hold them too
long at temperature and intermetallic phases precipitate, destroying toughness
and corrosion resistance. Welding duplex is a controlled process, not a skill.

**Martensitic and 13Cr grades** (13Cr, super 13Cr, F6NM/S41500) — strength and
moderate corrosion resistance for oil and gas tubulars and valve trim. Their
sour-service envelopes are narrow and specific; check the actual qualification,
not the family reputation.

**Nickel alloys** (Inconel 625/718, Incoloy 825, Hastelloy C-276) — the answer
when the environment beats everything else: severe sour service, seawater, high
temperature. Expensive as material and much more expensive as machining —
machinability indices in the teens against 45 for 316L and 100+ for free-cutting
steel. A nickel-alloy part is not "a stainless part in a different material";
its cost model is different in every term.

**Titanium** (Ti-6Al-4V) — excellent strength-to-weight, seawater-immune,
biocompatible. Burns during machining if you get feeds and coolant wrong, and
galls readily. Cost is dominated by material and by low removal rates.

**Aluminium** (6061-T6, 7075-T6, A356) — light, cheap, wonderfully machinable,
no DBTT. Low temperature ceiling and modest strength. 7075 is stronger and much
worse in corrosion and weldability than 6061 — a substitution that looks free and
is not.

**Cobalt-chrome** (ASTM F75) — wear and biocompatibility for implants. Hard,
slow to machine, and usually cast or printed then finished.

**Engineering polymers** (PEEK, PA12, PP, ABS, PLA) — chosen for chemical
resistance, weight, insulation or cost. Watch temperature limits, creep under
sustained load, moisture absorption in nylons, and UV degradation.

---

## The environments, and the mechanism each one attacks with

Knowing the mechanism is what lets you reason about a case the table does not
cover.

### Sour service (H₂S) — NACE MR0175 / ISO 15156

The mechanism is **hydrogen**, not corrosion. The H₂S corrosion reaction
generates atomic hydrogen; sulphide poisons the recombination reaction, so
instead of bubbling off as H₂ gas the hydrogen enters the steel. Once inside it
embrittles, and under tensile stress the metal cracks — with no general
corrosion to warn you first.

Three named consequences:

- **SSC** (sulphide stress cracking) — susceptibility rises steeply with
  hardness, which is why the control is a hardness ceiling of **22 HRC / 248 HBW**
  applied to base metal, weld metal **and heat-affected zone**. Surveying only
  the base metal measures the safe part.
- **HIC / SWC** (hydrogen-induced and stepwise cracking) — hydrogen collects at
  elongated inclusions and laminations in rolled plate and blisters. Needs **no
  applied stress at all**. Controlled by inclusion shape control, low sulphur,
  and HIC-tested plate.
- **SOHIC** — a hybrid, stress-oriented, near welds.

**The critical framing: sour-service compliance is a property of the material
*in its environment*, never of the material alone.** ISO 15156-3 qualifies each
CRA within stated limits of H₂S partial pressure, chloride, pH, temperature and
elemental sulphur. Outside those limits, the same alloy is not qualified. Storing
"NACE compliant" as a boolean is the most common documentation defect in the
industry, and an auditor will go straight at it.

### Chloride stress-corrosion cracking

Austenitic stainless cracks in hot chloride environments. It needs chloride,
tensile stress and temperature — remove any one and it stops. This constraint
routinely *collides* with the sour-service constraint: the alloy that satisfies
one can fail the other, which is why duplex and nickel alloys dominate combined
sour-and-chloride duty.

### Cryogenic service

BCC metals — carbon steel, low-alloy steel, martensitic and ferritic stainless —
have a **ductile-to-brittle transition**: below it they fail by cleavage with no
plastic warning. FCC metals — austenitic stainless, aluminium, nickel, copper —
do not have this transition at all.

So the cryogenic answer is either an FCC alloy, or a BCC alloy with **Charpy
impact testing at the minimum design metal temperature** — per heat, including
welds and HAZ. Room-temperature tensile data proves nothing here.

Second-order but real: **differential thermal contraction**. Austenitic stainless
contracts roughly twice as much as invar over the same span. Fits must be
computed at service temperature, not at 20 °C.

### Elevated temperature

Above roughly 40% of the absolute melting temperature the design basis changes
from yield strength to **stress-to-rupture over a design life** — creep. Bolted
joints relax. Austenitic stainless **sensitises** in the 425–815 °C range, so use
L or stabilised grades. Thermal cycling drives **thermal fatigue** at any
constrained section.

### Seawater and subsea

- **Galvanic corrosion** — dissimilar metals in an electrolyte. The **area ratio**
  matters more than the couple: a small anode against a large cathode corrodes
  fast. A stainless fastener in an aluminium plate is fine; an aluminium fastener
  in a stainless plate is not.
- **Crevice and pitting** — stagnant electrolyte in a tight gap goes locally
  acidic and chloride-concentrated and attacks alloys that resist the bulk
  environment easily. Design crevices *out*: full-penetration welds instead of
  lap joints, continuous seals, drain paths.
- **HISC** — cathodic protection saves the structure from corrosion and generates
  hydrogen at the surface, which can crack high-strength steel and duplex at
  stress concentrations. The protection creates the problem.

Selection shorthand for chloride resistance is **PREN** (≈ %Cr + 3.3×%Mo +
16×%N): 316L around 24, 2205 around 35, 2507 above 40. It is a ranking index for
pitting, not a qualification — it says nothing about SCC, temperature limits or
weldability.

### Erosive and abrasive flow

Material loss goes with particle velocity to a power typically between 2 and 3,
so **velocity is the dominant design variable**. Impact angle matters and it
inverts by material class: ductile targets erode fastest at shallow angles,
brittle ones at normal incidence — which is why "just use a harder material" is
not automatically right. And **erosion-corrosion** is synergistic: erosion strips
the passive film, corrosion attacks bare metal, and the pair removes material far
faster than either alone.

### Implantable and patient-contacting

Biocompatibility is a property of the **finished device including its
manufacturing residues** — cutting fluid, unfused powder, passivation chemistry,
polishing compound. This makes *cleanability geometry*: no blind crevices, no
trapped AM powder, everything drainable. It also means a process change can
invalidate a biological evaluation without touching the alloy.

---

## How to read a material profile in this engine

The material YAML (`backend/src/profiles/materials/*.yaml`) carries:

- `mechanical` — density, strength, hardness, thermal conductivity,
  **machinability index** (a strong cost driver), max temperature.
- `dfm` — minimum wall overall and **per process**, plus `cost_per_kg_usd` split
  by form (wrought / powder / sheet). Powder costs multiples of wrought for the
  same alloy: Inconel 625 at roughly 45 $/kg wrought against roughly 380 $/kg as
  powder. Any additive-versus-machining comparison that ignores form pricing is
  wrong before it starts.
- `compliance` — `nace_mr0175`, `biocompatible`, `sour_service`,
  `aerospace_pedigree`, `itar`.

**The compliance flags are screening aids, not qualifications.** They narrow a
candidate set. They do not assert that a specific part in a specific environment
is compliant — that is a qualified person's signature against a controlled
document, and the engine should say so every time it uses one.

---

## The substitution trap

"Equivalent material" is the phrase that precedes most material failures. Two
alloys with the same nominal chemistry are not equivalent if they differ in:

- **Product form** — a forging, a rolled plate and a billet have different grain
  structures, different property directionality, and different inclusion
  populations. Forging's whole value is grain flow following the part contour;
  machining the same shape from billet cuts through it and exposes end grain.
- **Heat treatment condition** — the same steel at two hardnesses is two
  materials, and in sour service one of them is disqualified.
- **Pedigree and traceability** — mill certification traced to heat number is a
  requirement, not paperwork, from API 6A PSL-2 upward and throughout aerospace.
- **Qualification envelope** — the environmental limits the alloy was qualified
  within.

An engine that treats material as a string, or compliance as a boolean, will
approve substitutions that a metallurgist would refuse. Treat material as
**alloy + form + condition + traceability + qualified envelope**.
