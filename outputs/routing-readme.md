# CadVerify — Process Routing + Cycle-Time (Cost-Truth cycle, ROUTING+PHYSICS-BUILDER)

**Author:** Routing+Physics-Builder agent · **Status:** built + run on real parts ·
**Scope:** error buckets **2 (routing)** and **3 (cycle-time modeling)** from
`outputs/error-decomposition.md`. Network egress: zero. All numbers below are
**reproduced from real engine runs on real parts in this repo.**

> **Honesty banner.** Nothing here is a validated accuracy claim. The dollar
> figures are should-costs from a DEFAULT rate card (±35–60% by family) and the
> sheet-metal route is quoted in a default metal stock. The real ±X% is **PENDING
> the Zoox session** (real parts + real quotes). What *is* demonstrated and
> reproducible is that the **chosen process** is now one a manufacturing engineer
> would accept, and that every time estimate is **explainable from a physics
> model, not a magic constant.**

---

## The problem (from the decomposition, bucket 2)

The engine led a **2.0 mm constant-thickness flat panel** (`Art2SideCover.stl`)
with **MJF at $26/unit** and could *never* cost it as sheet metal. Two root causes,
both now fixed:

1. **`SHEET_METAL` was excluded from `COSTED_PROCESSES`** — a stamped/laser-cut
   panel could never receive a dollar should-cost; it was forced into AM/CNC.
2. **The sheet-metal DFM check was inverted and hard-failed every part.**
   `check_bends` flagged `dihedral < 90°`, but `ctx.dihedral_angles_rad` is the
   angle **between adjacent face normals** where **0° = a flat, coplanar region**.
   So every part with a flat face (i.e. *every* part) tripped `SHARP_BEND`
   (ERROR) → `sheet_metal verdict=fail, score=0.0`. The engine literally could
   not *see* the sheet-metal route. Measured before the fix:
   `Art2SideCover sheet_metal → fail (SHARP_BEND)`, same for the gasket, seal, ECU.

Separately, the DFM "best process" was **noise**: because scoring ranks by the
*absence* of violations, a benign panel ties every process at ~1.0 and the
"winner" was whatever sorted first — the 2 mm panel read as `wire_edm`, the box
covers as `binder_jetting`/`ded`. That is not routing; that is a coin flip.

---

## What was built

### 1. Correct bend detection (`analysis/processes/checks.py::check_bends`)
A sheet-metal "bend" is a **fold**; the DFM violation is a fold so tight the
radius drops below the gauge — a **knife edge**, which shows up as normal
divergence **> 150°** (included bend angle < 30°), *not* `< 90°`. Flat blanks
(0°) and clean 90° bends now pass, as they must. This is the single change that
lets the engine see sheet metal at all (`sheet_metal pass(1)` after the fix).

### 2. Positive geometric routing (`costing/routing.py::recommend_routing`)
Instead of "which process has the fewest complaints", the router asks the
question an engineer asks — **"what shape is this?"** — and names the process the
shape implies, **with the measured drivers that decided it**. Archetypes, in the
order an engineer eliminates options:

| archetype | geometric signature (measured) | → process |
|-----------|-------------------------------|-----------|
| **sheet_panel** | constant gauge ≤6 mm, thinnest extent ≈ wall, planar aspect ≥ 4:1 | **sheet metal / stamping** |
| **rotational** | axisymmetric round cross-section, turnable L/D | **CNC turning** |
| **thin_wall_enclosure** | thin wall but deep & hollow (not flat) | injection molding (vol) / AM (proto) |
| **prismatic_block** | compact, ≥50% of bbox filled, low aspect, metal | **CNC milling** |
| **bulk_solid** | none of the above | AM (polymer) / CNC (metal) |

The recommendation (archetype, process, confidence, **reasoning string**, and the
driver values) is surfaced on every report: `report.routing` (JSON) and a
`GEOMETRIC ROUTING →` block in the text card. It is advisory; the dollar
make-vs-buy still ranks by cost, and a reconciliation note fires when the
cost-cheapest pick differs from the geometric one (glass-box, pick on intent).

The `sheet_like` predicate is **geometry-gated** so it only fires on genuine flat
sheets — the ECU box (7.6 mm wall, 32.6 mm thinnest extent) and every rotational
solid are correctly **excluded**, so no existing route flips.

### 3. Sheet-metal cost model — an explainable cycle, not a magic $/cm³
`SHEET_METAL` is now in `COSTED_PROCESSES` as a new **fabrication** family
(`costing/cost_model.py::_sheet_cycle`). Every term is an inspectable driver:

```
cycle = cut + bend + handling
  cut    = outline_perimeter_mm ÷ cut_speed        (perimeter MEASURED from the
           speed falls with gauge (thicker = slower) mesh: outer outline + cutouts)
  bend   = bend_count × seconds-per-brake-hit       (bend_count = distinct fold
                                                      orientations; 0 for a blank)
  handle = fixed load/unload/locate per part
```

Material is the **rectangular blank** (footprint × gauge × scrap), the stock you
actually buy — measured, not the net part volume. No per-unit hard tooling at
this volume, so it is a **make-now** process (stamping dies are a separate future
high-volume route). All constants (`cut_speed_mm_min`, `ref_gauge_mm`,
`sec_per_bend`, `handling_hr`, `machine_rate`, `min_charge`) live in the rate
card as **DEFAULT and overridable**.

Captured cycle for the panel (real run):
`cut 857mm ÷ 4000mm/min (laser, ×2/2.0mm gauge) = 0.21min + bends 0×20s = 0.00min
+ handling 1.2min = 0.0236 hr`. Every minute is traceable.

---

## Before / after on real parts (reproduced, polymer DEFAULT unless noted)

| part (real STL) | bbox mm | wall | BEFORE make-now | AFTER archetype → make-now | sheet $ / DFM |
|-----------------|---------|------|-----------------|-----------------------------|---------------|
| **Art2SideCover** (thin panel) | 2×120×280 | 1.9 | `mjf $26.12` (DFM-best = `wire_edm` noise; sheet metal **DFM-FAILED**) | **sheet_panel → `sheet_metal $5.46`** (5052-Al) | $5.46 / **pass** |
| **Ancel_Seal** (flat seal) | 1.4×81×171 | 0.8 | `mjf $11.71` | **sheet_panel → `sheet_metal $4.94`** | $4.94 / pass |
| **ECU firewall mount** (box) | 32.6×62×160 | 7.6 | `mjf $44.13` | **bulk_solid → `mjf $44.13`** (correctly **not** sheet) | — |
| **ThrottleBody FD3S** (rotational) | 35.6×133×143 | 9.8 | `cnc_turning $62.61` (no reasoning) | **rotational → `cnc_turning $62.61`** + reasoning surfaced | — |
| **Parktronik** (rotational, Al) | 27×34×34 | 2.1 | `mjf $7.40` (polymer default) | **rotational → `cnc_turning $15.73`** (Al) | — |

Headline: the **thin flat panel routes to sheet-metal** with a real, explainable
should-cost (≈3–5× below the old MJF lead, the direction the decomposition
predicted), the **box does not**, **rotational parts go to turning**, and **no
superalloy lands on a polymer part** — all with the reasoning surfaced.

The panel routes to sheet metal **regardless of material class** (polymer →
5052-Al auto-selected, steel → mild steel), because the geometry — a constant
2 mm plate — is what dictates the process; the metal stock is a stated default.

---

## Invariants preserved (no regression)

- `unit_cost == Σ(line_items)` asserted (gate G3) — including the new sheet line.
- Every driver carries provenance + a non-empty source (gate G6).
- G1 (refuse broken geometry), make-vs-buy coherence (headline == low-qty pick,
  DFM-ready), crossover, finite-capacity lead time — all intact.
- The DFM scoring / `best_process` path and the eval taxonomy were **not** touched;
  the new router is a separate, additive layer consumed only by the cost report.
- Full backend test suite: **green** (procedural + real-parts gates; see
  `routing-log.md`).

## Honesty / limitations

- **Geometry can't recover intent.** A printed cover and a stamped panel can be
  the same STL. The router states "this reads as sheet metal" with confidence and
  surfaces both the sheet route and the AM fallback; the buyer picks on intent.
  For a genuinely-printed cover, MJF is right and the note says so.
- **Bend detection is coarse** (distinct planar fold orientations from a solid
  STL). It is correct for flat blanks (0 bends) and L/U sections; it is not a true
  unfolder and does not measure bend radius. Tagged DEFAULT, overridable.
- **No validated accuracy.** The $5.46 panel and all cycle times are DEFAULT-rate
  should-costs (±35–60%). The real ±X% is PENDING real quotes (Zoox session).
- **Reproduce:** `python -m src.costing.cli <part.stl> --material-class steel`
  prints the routing block + sheet cycle; the probes in
  `scratchpad/route_probe.py` / `after_probe.py` reproduce the before/after table.
