# CadVerify — Design Handoff (2026-07-04, current)

This bundle supersedes `design_handoff_cadverify_site/` entirely. It contains the
post-pivot, audited, canonical designs: the marketing site (12 pages) and the full
product prototype (one file, 14+ surfaces). `DESIGN-DECISIONS.md` in this folder is
binding — thesis, register split, tokens, honesty rules, file status.

## How to view
Every `.dc.html` opens directly in a browser (each folder carries its own
`support.js`; three.js loads from unpkg, so viewing needs network). These are
high-fidelity design references with working interaction logic — recreate them in
the production stack (Next.js App Router at `frontend/`), don't ship them as-is.

## Thesis (one line)
Makeability verification: "Every part arrives with a question — can this be made,
on your machines, in materials that survive its world, and what will it really
take?" Should-cost is one artifact inside The Verdict, never the destination.

## Register (blessed split)
- SITE `site/` — dark theater: `#050506`, Helvetica Neue light, mono evidence,
  WebGL part-choreography (three.js r160), scroll acts measured per-section.
- PRODUCT `product/` — light instrument: `#f6f6f7` bg, `#ffffff` panels,
  `#e2e2e6` hairlines, `#17181a` ink, 16px-radius cards, `ui-monospace` evidence.
- Provenance tokens (light/dark pairs) + status colors + hatched-vs-solid and
  filled-vs-hollow encodings: see DESIGN-DECISIONS.md. Hours are ○ MODEL, only
  geometry is ● MEASURED.

## Site map (`site/`)
Home (Direction - Cinematic) · Method · Platform · Teams · Security · Developers ·
Company (pilot form at #pilot) · five persona journeys (For *). All nav/footers
cross-link relatively; footer tagline everywhere: "verification, made of glass".
Keep: the live crossover dial (Home), Σ scroll-assembly (Method), security beam,
±40% objection section, question-hierarchy strip, the three-gates band.

## Product (`product/Product - Verify.dc.html`)
One React-style component; all state in one object (see the `state = {…}` block —
it is effectively the app's store and maps 1:1 to backend needs).

Surfaces: Sign-in · Home desk (KPIs, Needs-Your-Action queue, in-flight, activity,
drop zone) · Verify (3D stage + environment door + Verdict walk + crossover scrub +
provenance disclosure + ask dock) · Parts catalog (geometry thumbnails, facets,
search) · Part standing page (history, blockers) · Compare · Records (+ read-only
shared-record modal w/ export) · Programs + Program detail (volume → exposure) ·
Machines + Machine detail (rate history, routed parts) + Add-machine modal ·
Triage (buckets, drill-down, capability ranking) · Calibration & truth (rates,
Hallmark ceremony, governed change, members, webhooks + delivery log, usage,
audit log) · Acquisition-consideration modal · Notifications · Calibration
switcher · ⌘K command palette · shortcuts overlay (?) · toasts · pipeline overlay.

Scenarios (part chips on Verify): `shaft` = the real fixture; `impeller` = the
negative verdict (walk stops at the failed envelope gate — steps 2–5 not rendered);
`firstrun` = org day zero (unknown verdict + designed empty states everywhere).

Cinematics-in-use (recreate faithfully):
- Pipeline → live walk assembly: gates check in one-by-one (430ms cadence),
  verdict banner reads "COMPUTING — GATES CHECKING IN" until it lands last;
  the 3D stage does a slow orbit sweep during assembly.
- Stage reactions: hostile world warms the rim light; recorded decision flashes
  it green (~950ms); hovering the IM blocker row lights the failing sidewall.
- X-ray toggle, Seat-in-assembly (ghost housing converges, camera pulls back),
  bands draw in via `bandIn` (scaleX), screens enter via `screenIn`.
- Hotkeys: ⌘K palette · H/V/P/R/G/M/T/C nav · ? shortcuts · Esc closes all.
- Scripted walkthroughs live ONLY in ⌘K ("Play use case: …") — never on Home.

Backend seams (all designed, ready to wire):
POST /api/v1/validate → routing+DFM · /validate/cost → cost record (pipeline
overlay = the request lifecycle) · decisions/records/audit (decideOpts →
records/history/audit all update from one state) · calibrations (switcher pins
old records to their rate VERSION — v13) · machines CRUD (● USER until an
accounting export re-tags SHOP) · programs (volume × unit cost = exposure, only
when a verified part is assigned) · webhooks (verification.completed etc.) ·
validation upload → the Hallmark band flip.

## Honesty rules (violations are bugs — full list in DESIGN-DECISIONS.md)
Only the real fixture is presented as engine output: object.stl · $14.14 ·
drivers 6.39/3.89/3.82/0.04 · band $8.49–19.80 ±40% n=0 · crossover 1,962 ·
routing cnc_turning 0.80 · DFM "423 faces undercut" / "1 sidewall <1.0°" ·
Midwest rates $52/$95/$30, margin 0.30, util 0.80 · lead 5.6–10.4d [queue model].
Everything else is labeled [illustrative] / IN DEVELOPMENT / withheld. Validation
is always schematic until real actuals exist. The walk never fakes past a failed
gate. Exposure is computed only from user-entered volume.
