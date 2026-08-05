---
title: "GD&T and tolerancing — 101 to expert, and the mistakes in between"
domain: foundations
audience: "Anyone specifying or reading a toleranced part"
sources: [asme_y14_5, iso_gps_1101, iso_2768, iso_286, iso_4287, aiag_msa]
provenance: DEFAULT
---

# GD&T and tolerancing

## Why it exists

Plus/minus dimensions describe a part as a set of independent measurements.
Parts do not assemble as a set of independent measurements — they assemble as
surfaces contacting other surfaces in an order. GD&T exists to state the
functional requirement directly: *where the surface must lie, relative to what,
when the part is located the way it actually locates.*

Two concrete gains over ±:

1. **Round tolerance zones instead of square ones.** A ±0.1 mm zone on X and Y
   is a square; the functional requirement is almost always a circle. Position
   with a diameter symbol gives ~57% more usable tolerance for the same
   assembly clearance. That is free money on every bolt pattern.
2. **A stated datum precedence.** Which surface seats first is a functional fact.
   ± dimensioning cannot express it, so it gets decided by whoever sets up the
   CMM — differently each time.

---

## The 101: the pieces

**Feature of size** — a feature with opposing points: a diameter, a width, a
slot. It has size, and therefore can carry material-condition modifiers.
A planar surface is not a feature of size.

**Datum feature** — a *physical* surface, bore or width used to establish the
coordinate system. **A datum feature can never be an axis, centreline or centre
plane.** Those are *derived*, and derived things cannot be touched by an
inspector. The axis is the *datum*; the cylinder is the *datum feature*.

**Datum reference frame (DRF)** — the coordinate system built by contacting
datum features in a stated precedence: primary constrains the most degrees of
freedom, secondary the next, tertiary the rest. **The precedence order is the
important part**, and it should reproduce how the part locates in its assembly.

**The control categories:**

| Category | Controls | Needs a datum? |
|---|---|---|
| Form — flatness, straightness, circularity, cylindricity | The surface against itself | No |
| Orientation — parallelism, perpendicularity, angularity | Angle to a datum | Yes, always |
| Location — position, concentricity, symmetry | Where it is | Yes |
| Profile — of a line, of a surface | The whole shape, size and location at once | Usually |
| Runout — circular, total | Combined form and location on rotation | Yes |

**Material condition modifiers** — MMC (Ⓜ) and LMC (Ⓛ). Applying MMC to a
position tolerance grants *bonus tolerance* as the feature departs from maximum
material condition: a hole drilled larger than its smallest allowed size has
more room to be off-position and still assemble. Legitimate whenever the
requirement is clearance, not alignment.

---

## The expert layer: what separates a good scheme from a legal one

### The datum scheme is a functional statement, not a measurement convenience

The single most consequential decision on the drawing. Choose datum features
because they are how the part *mounts*, in the order it mounts. If the CMM setup
does not mirror the functional datum structure, **every inspection result is
invalid regardless of machine accuracy** — parts pass and do not assemble, or
fail and would have worked fine.

Good primary datum features are large, stable, and actually contacted in
assembly. A tiny face chosen because it was convenient to probe is a bad primary
datum even though it is a legal one.

### Do not change datum reference frames between related features

Changing DRF between features on the same part introduces tolerance
accumulation equal to the location tolerance of the second frame relative to the
first. Features that must relate precisely to each other should reference the
**same** DRF. This one rule prevents a large share of real assembly failures.

### Profile is the most underused control

Profile of a surface controls form, orientation, location and size in a single
callout, applied to a whole shape rather than dimension by dimension. For
castings, formed parts and organic geometry it is usually the *only* sane way to
tolerance. Engineers avoid it because it looks unfamiliar; the parts pay for it.

### Composite position: two requirements, honestly separated

A bolt pattern usually has two independent requirements — the pattern must sit
somewhere relative to the part, and the holes must be right relative to *each
other*. Composite position states both: a loose upper segment locating the
pattern, a tight lower segment controlling the pattern internally. Collapsing
them into one tight tolerance over-constrains the part and costs real money.

### Bonus tolerance is not free

MMC is correct for clearance. It is *wrong* where the requirement is alignment,
sealing or balance, because there the largest hole is not the most forgiving —
it is the worst case. And form controls — profile, circularity, cylindricity —
**cannot** take MMC or LMC at all; they always apply regardless of feature size.

### Rule #1 vs independency: the international trap

Under ASME Y14.5, **Rule #1** means the size tolerance of a regular feature of
size also controls its form — at MMC the feature must fit a perfect-form
boundary. Under ISO GPS, the default is **independency**: form is not controlled
by size unless the envelope requirement (Ⓔ) is invoked.

The same drawing therefore accepts different parts depending on which standard
governs. State the standard *and its edition* explicitly in the title block —
and never mix ASME symbols with an ISO invocation.

---

## General tolerances: the quiet cost centre

`ISO 2768-m` (or `-f`, `-c`, `-v`) sets a blanket class for every dimension
without an explicit tolerance. Used well, it lets you tolerance three features
tightly and leave the other hundred and eighty alone.

Two failures, both common:

- **Nobody applies a class at all**, so the shop guesses, differently each time.
- **A tight class is applied to everything**, which is the blanket-tight-drawing
  failure with a standard's name on it.

## Tolerance stack-up: do it, at least once, on the thing that matters

- **Worst-case** — arithmetic sum of extremes. Guarantees assembly, over-tightens
  everything. Correct for safety-critical interfaces and short stacks.
- **Statistical (RSS)** — root-sum-square. Realistic for long stacks with
  independent, centred, in-control processes. Wrong when those assumptions do
  not hold, which is more often than people admit.

The stack-up is what turns "this tolerance feels tight" into a number with a
basis — the difference between a specification and a preference.

## Surface finish is a specification, not an adjective

`Ra 0.8` alone is not a specification. Ra depends on the filter: the same
surface yields different values under different cut-offs and evaluation lengths.
State the parameter, value, cut-off and evaluation length.

And check that the routed process can reach it. An as-built L-PBF surface is
roughly Ra 6–20 µm and a sand casting is far rougher; specifying Ra 0.8 on
either is specifying a finishing operation that somebody has to notice and price.

---

## The mistakes, ranked by cost

1. **Datum scheme that does not match the assembly.** Invalidates all downstream
   measurement. Silent.
2. **Datums on centrelines and axes.** Not inspectable, and ambiguous when
   several features share the centreline.
3. **Blanket tight tolerance.** The biggest avoidable cost on most machined
   parts.
4. **Mixed or unstated standard.** Cross-border disputes with both parties
   reading the same document correctly.
5. **Tolerance tighter than the gage.** Fails MSA forever; discovered at PPAP.
6. **Changing DRF between related features.** Silent stack-up.
7. **MMC applied to alignment or sealing requirements.** Bonus tolerance where
   bonus makes it worse.
8. **Orientation controls with no datum.** Meaningless — parallelism to nothing.
9. **Surface finish with no basis or beyond process capability.** Unmeasurable
   or unmakeable.
10. **Tolerances inherited from the previous part with no basis.** The most
    common of all, and the hardest to see.

---

## The MBD note

Under a model-based workflow the tolerances live on the model as PMI. Only
**semantic** PMI — machine-readable, with face links, as carried by STEP AP242 —
survives to automated characteristic extraction. AP203 and AP214 carry PMI as
polylines: pictures of tolerances, not tolerances.

The failure mode is specific and expensive: characteristics that exist on the
authoring model, do not survive the exchange, and therefore never appear on the
AS9102 balloon map — so they are never inspected. This is the number-one
first-article defect in MBD workflows. See
[MBD, PMI and drawings](../cad/mbd-pmi-and-drawings.md).
