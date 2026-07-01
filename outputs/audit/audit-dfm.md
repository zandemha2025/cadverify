# CadVerify — DFM / Process-Routing Engine Audit

**Lens:** DFM / Manufacturing Process Engineer
**Date:** 2026-07-01
**Method:** Read the real engine code (`backend/src/analysis`, `backend/src/costing/routing.py`, `backend/src/parsers`), ran the cost CLI and the full 21-analyzer pipeline on real automotive STL parts from the corpus, instrumented issue counts per process, and tested orientation sensitivity. Every number below is reproduced from a run, not from notes.

> **Honest limit I hold:** I can verify the engine's *logic, consistency, and coverage*. I **cannot** certify that any threshold (0.8mm min wall, 1° draft, 10:1 hole depth, L/D 10:1) is the *right* number for a given shop/material — that needs a real manufacturing engineer and real quotes. Those are flagged **[NEEDS REAL-EXPERT VALIDATION]**.

---

## Bottom line

The DFM engine is a **real, deterministic geometry-rule engine** — not a mockup. Wall thickness, overhangs, draft, undercuts, rotational symmetry, hole depth, cylinder/hole feature detection, and sheet-gauge logic are all computed from the mesh with traceable citations. The routing classifier is genuinely improved over the earlier "turning-for-brackets / Inconel-for-plastic" bugs and now shares one axisymmetry definition with the DFM gate.

**But the single most important thing a process engineer sees — "76 flags · 21 critical" on a simple part — is not credible.** It is an artifact of summing DFM violations across all 21 processes, including 8 casting/molding/forging processes that *always* fail on a printed part. On the same part, the *recommended* process is often DFM-clean (0 flags). Showing 21 "critical" flags next to a "make this as-is" recommendation is a trust-destroyer that a buyer will catch in the first demo.

Coverage-wise, the engine is a **shape checker, not a DFM checker in the manufacturing sense**: there is **no tolerance/GD&T analysis reaching the user** (that subsystem is dead code in this environment), **no thread/tapped-hole/countersink/slot/pocket recognition**, and **no build/parting-orientation reasoning** (the STL's arbitrary Z is treated as the machining/pull/build axis).

---

## REAL — works, verified how

| Capability | Evidence | Notes |
|---|---|---|
| **21 process analyzers register and run** | `_REGISTRY` has exactly 21 entries; ran all on real parts | binder_jetting, cnc_3/5axis, cnc_turning, ded, die_casting, dlp, dmls, ebm, fdm, forging, injection_molding, investment_casting, mjf, sand_casting, sheet_metal, sla, slm, sls, waam, wire_edm |
| **Wall thickness** | `context.py::_compute_wall_thickness` — vectorized inward ray-cast with self-hit rejection; `np.minimum.at` scatter-min | Genuinely measured per-face. **Caveat:** >50k faces switches to a 5k-face *sample + KDTree propagation* (the 72,922-face manifold I ran hit this path — its wall thickness is approximated, not measured). |
| **Draft angle** | `checks.check_draft_angles` — sidewall faces (80–100° from Z), draft = \|90−angle\|, area-weighted % below threshold | Correct math *for a Z pull direction* (see FRAGILE re: orientation). |
| **Overhang / support** | `check_overhangs` — angle-from-Z-up > 90+threshold; self-supporting processes (SLS/MJF, threshold≥90) correctly skip it | SLS/MJF analyzers correctly omit the overhang check. |
| **Rotational symmetry** | `check_rotational_symmetry` — inertia-tensor eigenvalue ratios, tol 0.15 | Real. Correctly separates a round ring (routed to turning) from a bracket. |
| **Cylinder / hole / boss detection** | `features/cylinders.py` — face-adjacency graph → union-find smooth patches → SVD axis fit → radius/depth → hole-vs-boss by normal·radial sign | This is real, deterministic feature recognition (not ML, not fake). Depth measured from vertex extents, not centroids (a correct subtlety). |
| **Flat-facet detection** | `features/flats.py` — wraps `trimesh.facets` | Real but coarse — it's coplanar grouping, not semantic features. Drives the high "148 / 713 features" counts. |
| **Sheet-metal geometry drivers** | `drivers.py::_sheet_geometry` — gauge = thinnest extent, blank area = V/t, cut perimeter = rim_area/t, `sheet_like` predicate | Real measured drivers. Flat 1.4mm gasket → `sheet_like=True` → routed to sheet_metal (verified). |
| **Routing archetype classifier** | `routing.py::_classify_archetype` | Verified sane on clear cases: round ring → CNC turning; flat panel → sheet metal; thin-wall cover → injection molding; block → CNC 3-axis. |
| **F2 fix (headline ≠ DFM-failed process)** | `_avoid_dfm_failed_headline` | Verified: bracket's injection-molding route hard-fails draft, so headline is *demoted* to MJF (DFM-clean) while IM stays as the at-volume crossover. Routing card and DFM matrix no longer contradict. |
| **G2 fix (no superalloy-on-polymer, turning only when rotational)** | `_routing_sane`, `select_material` | Verified: material selection is class-compatible + cheapest, not positional `materials[0]`. |
| **Every issue carries provenance/citation + fix suggestion** | Every `Issue` has `code`, `severity`, `measured_value`, `required_value`, `fix_suggestion`, and a standards `cite` | Good enterprise-audit hygiene. Standards strings (Sandvik, Protolabs, DIN 6935, EOS PA12, ISO/ASTM 52910) are attached per analyzer. |
| **STEP → mesh path** | `step_mesher.py` via gmsh/OCC | Real tessellation path; single solids recover watertightness via vertex merge. |

**Earlier bug status — RESOLVED:**
- *Turning-for-brackets:* routing now requires inertia axisymmetry AND roundness AND 0.25≤L/D≤8 AND cross-dia≥5mm. A flat bracket no longer routes to turning. ✔
- *Sheet-metal-for-everything:* `check_bends` threshold was inverted (flagged every flat coplanar pair as a "sharp bend"); now correctly flags only knife-edge folds (>150° normal divergence). Verified a flat gauge no longer hard-fails sheet metal. ✔
- *Inconel-for-plastic:* `select_material` is class-gated. ✔

---

## STUBBED / FRAGILE — looks done, isn't

### 1. THE HEADLINE: "76 flags · 21 critical" is systematic over-flagging that destroys trust
This is the finding for my lens. The frontend flag count (`LivingInstrument.tsx::dfmSummary` → `IssueList.tsx::flattenIssues`) is the **union of DFM issues across all 21 processes**, deduped only by `code|message`. Measured on real parts:

| Part | bbox (mm) | Flattened total | "critical" (ERROR) | Recommended process | Flags *on the recommended process* |
|---|---|---|---|---|---|
| miata-ms3 top-bracket | 120×80×38 | **58** | **11** | mjf | **0 errors, 0 warnings (CLEAN)** |
| battery_holddown | 90×66×38 | 44 | 9 | mjf | 0 / 0 |
| obd_cover_v2 | 43×19×12 | 40 | 9 | injection_molding | 1 / 3 |
| ThrottleBodyAdapter | 40×34×22 | 52 | 13 | (rotational) | — |
| Manifold_5ch | 70×19×9 | **76** | **21** | — | — |

The bracket's 11 "critical" flags are **entirely** `INSUFFICIENT_DRAFT` / `THIN_WALL_MOLDING` / `UNDERCUT` / `NOT_ROTATIONALLY_SYMMETRIC` from **die_casting, investment_casting, sand_casting, forging, injection_molding, cnc_3axis, wire_edm** — **none** of which is the recommended process. The recommended process (MJF) has **zero** flags. A process engineer reads "11 critical" and concludes the tool is noise; the truth is "0 critical for how you'd actually make this."

**Root cause:** the DFM panel never filters to the recommended/eligible process(es). Each process contributes its own violations, so 8 casting/molding/forging analyzers guarantee ~5–6 draft/wall "critical" errors on *every* 3D-printed part regardless of the part. `score_process` turns any single ERROR into `verdict="fail"`, so those processes are also "failed" — correct internally, but the aggregate count shown to the user is meaningless.
**Fix:** show flags for the recommended process (+ the costed shortlist), or group by process with the recommended one expanded and the rest collapsed. Do not headline a summed "critical" count across processes the part will never use.

### 2. CNC 3-axis marks nearly every real part "NOT DFM-ready" via UNDERCUT = ERROR
`check_undercuts_from_z` flags any downward-facing face above the bottom margin as an undercut, severity **ERROR** → `verdict="fail"`. On the bracket: "400 faces (23.8%) are undercuts." In reality this part is machined in **two setups (flip)** — routine, not a failure. Because CNC is the most common real process, marking it FAIL/"not DFM-ready" on typical prismatic parts is both wrong and self-defeating. 5-axis correctly downgrades the same check to WARNING; 3-axis should express this as "N setups required," not a hard fail. **[Partly NEEDS REAL-EXPERT VALIDATION on the setup-count heuristic.]**

### 3. Draft / overhang / undercut are computed against the STL's arbitrary Z — no orientation reasoning
`check_draft_angles`, `check_overhangs`, `check_undercuts_*` all assume pull/build/machining axis = +Z of the file. There is **no parting-line selection and no build-orientation search.** Rotating the bracket 90° about X changed the flag counts for injection_molding, sheet_metal, and SLA (verified). A DFM tool that reports "insufficient draft" or "overhang, supports required" without choosing (or asking for) the parting/build orientation is not trustworthy to a process engineer — draft/support/undercut are *orientation-defined* quantities. This is the difference between a toy and a tool.

### 4. Injection-molding "rib check" is a canned message, not a check
`injection_molding.py::_check_rib_rules` loops over features, does nothing (`pass`), then emits a generic `RIB_RULES_CHECK` INFO **on any part with >200 faces** — regardless of whether ribs exist. It is boilerplate dressed as analysis. `THIN_BOSS` is real (keyed off detected bosses), but ribs, gate/weld-line, sink, and knit-line analysis are absent. Molding is called "the money maker" in the code comment, yet its analyzer is the thinnest of the formative set.

### 5. Tolerance / GD&T achievability — fully built, fully disconnected (dead code)
There is a complete-looking subsystem: `tolerance_models.py` (14 ISO 1101 types), `capabilities/loader.py` + `process_tolerances.yaml`, `gdt_extractor.py`, `step_ap242_parser.py`, `services/tolerance_service.py`. **None of it reaches the user:**
- `is_ap242_supported()` returns **False** in this environment (OCP XDE not installed) — verified.
- `analyze_tolerances` is **not called from any route** (grep of `src/api` is empty) — verified.
- The DFM path for STEP uses gmsh, which **explicitly drops PMI/GD&T** (documented in `step_mesher.py`).
- All corpus parts are STL, which has no tolerance data at all.

So the platform's DFM never answers the question that actually decides manufacturability: *can this process hold your ±0.05 position / Ra 0.8 / flatness 0.02?* For an "enterprise DFM" claim this is the biggest single gap — tolerances are the substance of DFM, and they are absent from the live product.

### 6. Feature detection is holes/flats only — the "Phase 2" detectors never shipped
`detect_all` runs `detect_flats` + `detect_cylinders`. The `THREAD` FeatureKind exists in `models.py` but **there is no thread detector**. No chamfer, fillet, pocket, slot, counterbore, or countersink recognition (docstring in `detector.py` promises these as "Phase 2"). The high feature counts (148, 713) are mostly coplanar facet groups, not machinable features. So there is no "this is a tapped M6 hole" / "this is a keyway" reasoning — the engine can't cost or DFM-check threads, and hole callouts are geometric radius/depth only.

### 7. Legacy analyzers are dead code
`additive_analyzer.py`, `cnc_analyzer.py`, `casting_analyzer.py`, `molding_analyzer.py`, `sheet_metal_analyzer.py` (top-level `analysis/`) are **imported nowhere** (verified). Superseded by `processes/`. Harmless but confusing — two parallel "analyzer" implementations invite a future edit to the wrong one.

### 8. Flat round parts fall through to a wrong route
A flat washer/ring (ThrottleBodyRingInner, 25.7×23.2×5.2, clearly round) routed to `bulk_solid → mjf` because L/D 0.21 < the 0.25 turning floor and it isn't `sheet_like`. A thin round plate should be face-turned, laser/water-cut, or stamped — not powder-bed printed. There's a gap between "sheet panel," "rotational," and "flat disk."

### 9. Purely geometric routing has no material/functional awareness
A 1.4mm flat rubber **gasket/seal** (Ancel_Seal) routes to `sheet_metal` (a metal stamping process). Geometrically defensible, manufacturing-wise wrong. And `material_class` **defaults to "polymer" for every part** — so metal parts silently route to MJF/SLS unless the user overrides `--material-class`. The engine can't tell a structural aluminum bracket from a printed plastic one; it guesses polymer.

---

## MISSING — to be a credible enterprise DFM platform

1. **Tolerance/GD&T-driven DFM (highest priority).** Wire `tolerance_service` into the pipeline, get a working B-rep/PMI reader (cadquery/OCP), and let the *user enter tolerances* even for STL (a form: "position ±X on these holes, Ra Y here"). Then answer "process P can/can't hold it." This is the DFM question; today it's unanswerable in-product.
2. **Build/parting-orientation optimization.** For AM: search orientations to minimize supports/overhangs and report the chosen one. For molding: pick/ask parting line. For CNC: report setup count and the flip axes. Every orientation-dependent flag is currently an artifact of file orientation.
3. **Real machinable-feature recognition:** threads/tapped holes, counterbores/countersinks, slots, pockets, keyways, chamfers, fillets, bosses-with-ribs. Needed for both DFM (tap depth, thread mill access) and cost (per-feature machining time).
4. **DFM presentation scoped to the recommended process.** Stop unioning 21 processes into one "critical" count. Show the part's *intended/recommended* route's flags primarily.
5. **Setup/fixturing reasoning for CNC** beyond a flat-area %: number of setups, workholding access, tool-reach/length for deep pockets, 5-axis vs 3-axis decision with justification.
6. **Material-aware routing:** infer or require material class; don't default everything to polymer. A seal/gasket material class, elastomer processes, etc.
7. **Process-specific DFM depth** where it's thin: molding (sink/weld-line/gate/rib), casting (parting-line/gating/riser/porosity zones), sheet metal (bend-relief, hole-to-edge, K-factor/flat-pattern, minimum flange), turning (undercut/relief, thread relief, parting-off).
8. **Validation of thresholds against real shop capability** (see below) and per-material thresholds (min wall for ABS ≠ PC ≠ PA12; the checks largely use one number per process).
9. **Confidence/uncertainty on the DFM verdict itself**, especially when wall thickness came from the sampled/KDTree path on large meshes, or when the mesh is coarse.

---

## Where a process engineer would NOT trust it (today)

- The **critical-flag count** (they'll dismiss the tool in the demo — see finding #1).
- Any **draft/overhang/undercut** verdict, because the **orientation is arbitrary** and unshown (#3).
- **CNC "not DFM-ready"** on obviously machinable prismatic parts (#2 in FRAGILE).
- **Absence of tolerances** — they'll ask "what tolerance did you assume?" and there's no answer (#5).
- **No thread/feature callouts** — they'll ask "did you see the tapped holes?" and the answer is no (#6).
- **Molding rib "check"** that fires on face count, not geometry (#4 in FRAGILE).

They *would* trust: the wall-thickness map, hole/cylinder detection, rotational-symmetry gate, sheet-gauge/bend logic, and the routing headline on clear archetypes.

---

## [NEEDS REAL-EXPERT VALIDATION] — what to show, what to ask

These require a real manufacturing engineer and/or real quotes; the engine cannot self-certify them:

1. **Threshold correctness.** Show the per-process threshold table (min wall 0.8mm CNC / 0.7mm SLS / 0.5mm IM; draft 1°; hole depth 10:1; L/D 10:1; sheet gauge 0.5–6mm; sharp-corner 0.5mm). *Ask:* "For your shop and these materials, are these the right limits, and which are material-specific?"
2. **CNC undercut → setup count.** Show a part flagged "400 faces undercut, NOT DFM-ready." *Ask:* "Is this a hard fail, or a routine 2-setup job? What geometry actually forces a 5-axis/EDM escalation?"
3. **Draft on printed parts.** Show that every printed part fails molding draft. *Ask:* "If a customer intends to injection-mold this, is the 1°/2° internal call right, and would you gate on it?"
4. **Routing archetype boundaries.** Show ring→turning, washer→MJF, gasket→sheet_metal, cover→IM. *Ask:* "Where would you route these differently, and what signal (material, function, tolerance) is missing?"
5. **Molding depth.** *Ask:* "What DFM checks do you actually run for injection molding (sink, weld line, gate location, rib ratios) that a buyer expects to see?"
6. **Whether over-flagging alone would lose the deal.** Show the "58 flags · 11 critical vs 0 on the recommended route" screen. *Ask:* "Does this help you or make you distrust the tool?" (I predict the latter — validate it.)

---

## Prioritized fix list (my lens)

1. **P0 — Scope the DFM flag display to the recommended/costed process(es).** Pure presentation + a filter; kills the #1 trust problem immediately. (finding FRAGILE-1)
2. **P0 — Downgrade CNC 3-axis UNDERCUT from ERROR to "N setups" advisory.** One severity/heuristic change; stops falsely failing the most common process. (FRAGILE-2) **[validate heuristic]**
3. **P1 — Surface and choose orientation.** At minimum, show the assumed pull/build/machining axis; ideally optimize it for AM and pick parting for molding. (FRAGILE-3)
4. **P1 — Let users enter tolerances (even for STL) and wire `tolerance_service` in.** Turns a shape checker into a DFM checker. (FRAGILE-5, MISSING-1)
5. **P1 — Replace the fake rib check; add sink/weld-line/gate for molding.** (FRAGILE-4)
6. **P2 — Thread + counterbore/countersink/slot recognition.** (FRAGILE-6, MISSING-3)
7. **P2 — Material-aware routing + flat-disk route; delete dead legacy analyzers.** (FRAGILE-7,8,9)

---

### Reproduction
```
cd backend
PYTHONPATH=. .venv/bin/python -W ignore /tmp/dfm_probe.py <part.stl>      # per-process issue counts + flattened total
PYTHONPATH=. .venv/bin/python -W ignore /tmp/route_probe.py <part.stl>    # drivers + routing archetype
PYTHONPATH=. .venv/bin/python -W ignore /tmp/orient_probe.py <part.stl>   # orientation sensitivity
.venv/bin/python -W ignore -m src.costing.cli <part.stl> --qty 100,10000  # full decision card
```
Parts used: `printables_205285_miata-nb-ms3-top-bracket.stl`, `r3_36253_battery_holddown_backend.stl`, `printables_241157_obd_cover_v2.stl`, `printables_122552_ThrottleBodyRing{Inner,Outer}.stl`, `printables_122552_ThrottleBodyAdapter.stl`, `thangs_870098_..._Manifold_5ch.stl`, `thangs_921023_..._Ancel_Seal.stl` (from the scratchpad `parts/` set).
</content>
</invoke>
