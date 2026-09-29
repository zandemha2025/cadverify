# ProofShape verification-depth + corpus-v3 adversarial audit

Seat: GLM (max effort), 2026-09-14. Scope: the deployed verification engine and its corpus truth.

**Provenance.** Repo `zandemha2025/cadverify` main @ `d3164d456b9b16f56faae5303f90fce6087c9659`.
Live API `cadverify-api.onrender.com/health` reports `build_id` = the same SHA, so local and
production behavior below are the same code. Live receipts were produced against the public
`/api/v1/validate/demo` endpoint on 2026-09-14 ~18:50 UTC (files in `live-receipts/`).
Method: all 21 registered process analyzers were run over all 29 trap-corpus v1.2 fixtures and
33 corpus-v3 fixtures (`probe-v1.2-all-processes.json`, `probe-v3-all-processes.json`); six
fixtures were additionally run through the live API. Corpus v1.2 gate re-run green on main
(2 KNOWN-GAP rows carried: unit_flag, 2mm drain).

Note: the v1.2 gate is environment-sensitive. Without `rtree` installed, the same gate fails
10 rows red (wall/containment paths degrade silently). CI installs `requirements-prod.lock`
(trimesh 5.1.0, rtree 1.4.1) and is green; anyone running it outside the locked env gets a
false red. The v3 gate verifies fixture SHA-256 hashes before analysis for the same reason:
corpus truth must be reproducible truth.

## What the engine actually is today

- 21 registered process analyzers (11 additive, 4 subtractive, 6 formative), all executed on
  every upload (`routes.py` `_analyze` path), plus universal geometry checks.
- 27 shared check functions in `processes/checks.py`, 5 universal geometry checks, and
  process-private checks (cupping, rib/boss rules, conductivity hint, sintering note,
  machining allowance, rib-aspect).
- Scoring: any ERROR -> process score 0, verdict fail; each WARNING costs 0.1 (floor 0.3);
  INFO is free (`matcher/profile_matcher.py:23-41`).
- Corpus truth before v3: 29 fixtures asserting FDM+SLA behavior on 6 gates only
  (wall, overhang, small features, build volume, aspect, trapped volume). 19 processes and
  ~24 check codes had zero corpus expectations.
- Corpus v3 (this delivery): 33 fixtures, 32 rows, 14 processes under expectation,
  19 hard rows green today, 13 KNOWN-GAP rows holding the proven divergences below open.
  Gate: `backend/scripts/corpus_v3_gate.py` (exit 0 = green; run receipt in
  `corpus-v3-gate-run.txt`). Still uncovered after v3: binder_jetting, ded, ebm, forging,
  mjf, sls, waam (v3.1 candidates).

## Confirmed findings (each held open by a KNOWN-GAP row)

**F1 - SLA CUPPING_RISK fires on any flat-bottomed solid; it never tests concavity.**
`sla.py:_check_cupping` flags >10% downward-facing area. Docstring claims "concave
downward-facing pockets"; a solid 10mm cube's exterior base trips it. Live: cube ->
`sla CUPPING_RISK warning`. It also fires on a cup with a compliant 4mm drain hole (the
drain that the cited Formlabs guidance says relieves it). Fires on 20/29 v1.2 fixtures.
Fix direction: test for enclosed/concave downward regions and respect drain holes.
Rows: `control-cube-10mm`, `control-hollow-cup-drain-4mm`.

**F2 - RESIDUAL_STRESS_RISK has no absolute-size floor.** A single flat facet group >15% of
surface area trips it, so a 10mm metal cube gets a curl-risk warning (score 0.9 for dmls/slm
live). Curl risk scales with absolute section size, not area fraction. Fires on 15/29 v1.2
fixtures. Fix direction: absolute area/dimension floor. Row: `control-cube-10mm`.

**F3 - SLA overhang gate contradicts its own citation.** `sla.py` cites Formlabs "19 deg from
horizontal without support"; Formlabs' design guide (archive-media.formlabs.com/upload/
formlabs-design-guide.pdf: "MINIMUM UNSUPPORTED OVERHANG ANGLE Recommended: 19 deg from
level") agrees with the citation. But `check_overhangs` implements `angle_from_up > 90 + 19`,
i.e. 19 deg from VERTICAL: it trips any underside shallower than 71 deg from horizontal
instead of 19. Live: a 30-deg-from-horizontal underside (self-supporting per Formlabs)
returns `sla OVERHANG warning`. The contrast row pins DLP on the same geometry tripping
correctly per its own 30-deg-from-vertical cite. Rows: `control-overhang-44deg`,
`trap-sla-overhang-30deg-from-horizontal`; hard anchors `trap-sla-overhang-10deg` (trips
under both readings) and `control-sla-overhang-80deg` (clean under both).

**F4 - Build-volume check is orientation-naive.** `check_build_volume` zips bbox dims against
the envelope axis-by-axis; it never tries rotations. Live: a 350x200x100 part, which fits the
300x300x350 FDM envelope rotated, returns `fdm EXCEEDS_BUILD_VOLUME error, score 0.0`; a
300mm shaft along X fails the lathe envelope (254,254,533) though 300 < 533. Sorted-dims vs
sorted-envelope is the standard fit test. Rows: `trap-buildvolume-rotated-fit-350x200x100`,
`trap-turning-volume-rotated-x300`; hard opposite: `trap-buildvolume-true-exceed-350x310x100`.

**F5 - Phantom thick walls from hole/cavity surfaces corrupt wall uniformity.** The
inward-ray wall estimator fires rays from a hole's cylindrical surface radially through the
part; they travel tens of mm and inflate t_max. Measured on a uniform 3mm-wall hollow box
with a 4mm drain: min 2.99, median 3.0, max 38.5mm, 45% of faces >6mm -> IM/die THICK_WALL +
NON_UNIFORM_WALLS on a geometrically uniform part. Live: plain 5mm plate with one 2mm hole ->
`injection_molding fail 0.05` with THICK_WALL + NON_UNIFORM_WALLS. This also explains the
NON_UNIFORM_WALLS on v1.2's `control-hollow-cup-drain-4mm`. Fix direction: cap ray distance
at first surface crossing in the inward half-space, or medial-axis wall measure; exclude
non-material-crossing rays. Rows: `control-hollow-box-uniform-3mm-wall`,
`trap-plate-5mm-through-hole-2mm`.

**F6 - The internal-corner floors disagree with each other and miss single features.**
`check_internal_radii` (CNC) stays silent under 10 sharp concave edges;
`check_fillet_requirements` (casting) stays silent under 5. One square pocket (8 edges)
fires MISSING_FILLETS for die casting but escapes the CNC radii check entirely, though a
0.5mm-radius tool cannot cut it. Row: `trap-pocket-single-sharp-corner` (die_casting sub-row
hard/green; cnc_3axis sub-row KNOWN-GAP). Positive control: `trap-pocket-grid-16-sharp-corners`.

**F7 - SMALL_FEATURES has a 5%-of-edges significance floor; a single unprintable feature is
invisible.** Ten 5mm ribs + one 0.3mm rib on a plate: the 0.3mm rib is 1.4% of edges, so the
gate stays silent (THIN_WALL still catches it at WARNING). Row:
`trap-single-0p3mm-rib-among-many` (THIN_WALL sub-row hard/green).

**F8 - SHARP_INTERNAL_CORNERS fires on every modeled blind hole.** A drilled blind hole has a
118 deg conical bottom; a modeled flat-bottomed hole's tessellation edges count as >=10 sharp
concave edges. Live-adjacent proof: `control-hole-8mmx16mm` (ratio 2, perfectly machinable)
trips it. Row: `control-hole-8mmx16mm` (DEEP_HOLE-absent sub-row hard/green).

**F9 - check_sheet_gauge reads thickness as the smallest bounding-box dimension.** A U-channel
formed from 2mm sheet (bbox min 28mm) is flagged TOO_THICK_SHEET. Live-confirmed. Any formed
(non-flat) sheet part trips this. Fix direction: use `ctx.wall_thickness` distribution, not
bbox. Row: `trap-uchannel-2mm-formed`. Hard controls: `control-plate-2mm-flat` (clean),
`trap-plate-0p2mm-foil` (TOO_THIN_SHEET error).

**F10 - Undocumented threshold divergence: sand_casting shrinkage modulus 12.0 vs
investment_casting 15.0.** Same check, same units, no citation on either side explaining the
difference. Pinned by boundary pair `control-cube-60mm` (modulus 10, clean both) /
`trap-cube-100mm-bulky` (modulus 16.7, trips both).

**F11 - TOO_THIN_SHEET trips at 0.3mm but the message says "below 0.5mm min gauge".** A 0.4mm
sheet passes the code and violates the stated message. Threshold/message mismatch; pick one.
(Hard row pins the code behavior: `trap-plate-0p2mm-foil`.)

**F12 - check_prismatic counts faces, not area.** A prismatic 60x60x5 plate with r4 edge
fillets (a normal wire-EDM part) trips NOT_PRISMATIC because 256 small fillet triangles
outvote the plate. The verdict changes with tessellation, not geometry. Row:
`trap-filleted-plate-prismatic`; hard opposite: `trap-pyramid-top-nonprismatic`.

**F13 - SMALL_FEATURES reads tessellation chords as features.** At standard 64-section STL
export, any hole/curve under ~8mm diameter has chord edges below the 0.4mm FDM threshold:
the 2mm-hole plate's chords (0.098mm) are 31.4% of all edges; an 8mm hole's chords (0.3925mm)
still trip FDM. Live: SMALL_FEATURES warning on the 5mm plate across fdm/sls/mjf/ebm/
binder_jetting/dmls/slm. The gate meant to catch sub-resolution features fires on ordinary
holes. Fix direction: ignore edges that bound coplanar-within-tolerance facets (chords), or
measure feature size from detected features, not raw edges. Rows:
`trap-plate-5mm-through-hole-2mm`, `control-hole-8mmx16mm`.

**F14 - Aspect-ratio message truth.** The gate is orientation-blind by design (v1.2 pins a
7.9:1 plate as pass, 8.1:1 as trip), but the issue text says "Tall/thin parts risk failure"
on flat plates too (live: 50x50x5 plate -> `fdm EXTREME_ASPECT_RATIO`). Physics (large thin
sections warp) partially justifies the trip; the message should say what it measures.
No corpus row: message copy, not gate behavior.

## Scoring interaction (why these matter to the verdict, not just the issue list)

One ERROR zeroes a process. Today every part with vertical walls gets INSUFFICIENT_DRAFT
(error) from all five molding/casting/forging analyzers - on the clean 10mm cube live,
die_casting/investment_casting/sand_casting/forging all score 0.0 and injection_molding 0.05.
That is defensible per the cited 1 deg rule, but it means the molding family can never rank
above fail for prismatic parts, and any additional false-positive ERROR (F4 rotated volume,
F12 tessellation prismatic) silently removes a viable process from the ranked table the user
sees. Every WARNING costs 0.1 regardless of materiality, so F1/F2/F13 warnings depress
scores on clean parts product-wide. The three always-on INFO notes (SINTERING_SHRINKAGE,
MACHINING_ALLOWANCE, CONDUCTIVITY_REQUIRED) fire on 100% of uploads - no score impact, but
they train users to ignore the issue list.

## Depth assessment by check family

- Threshold-solid (code matches cite, boundary-pinned by v3): wall thickness (FDM/SLA pair
  from v1.2), draft (new 0.5/1.5 pair), build volume true-exceed, turning L/D (9/11 pair),
  shrinkage modulus (60/100 pair), deep hole (11:1), sheet thin/thick, trapped volume +
  fragile core (new sealed-channel fixture), undercut (T-shape/stepped-shaft pair),
  prismatic true-nonprismatic.
- Heuristic with proven failure modes: cupping (F1), residual stress (F2), SLA overhang
  semantics (F3), build-volume rotation (F4), wall uniformity near holes (F5), corner/fillet
  floors (F6/F8), small features (F7/F13), sheet gauge (F9), prismatic (F12).
- Dead-until-proven: no v1.2/v3 fixture has yet produced RIB/boss positives, HIGH_RIB_RATIO
  controls, FRAGILE_CORE negative control, or ANALYSIS_PARTIAL rows; forging/mjf/sls/ebm/ded/
  waam/binder_jetting have no behavioral expectations at all. That is the v3.1 surface.

## Corpus v3 contract

`backend/tests/corpus-v3/manifest_v3.json` + 33 hashed fixtures + `gen_v3_fixtures*.py`
provenance scripts + `verification_measurements.json`. Gate:
`python backend/scripts/corpus_v3_gate.py` from repo root; exit 0 with 19 hard rows green and
13 KNOWN-GAP rows reported (receipt: `corpus-v3-gate-run.txt`). When a fix lands, its
KNOWN-GAP row flips green and the gate prints a promotion notice; the row must then be
reclassed out of KNOWN-GAP so the behavior locks.
