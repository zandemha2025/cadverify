# Design brief for a fresh attempt (Claude on the web)

**Purpose:** you are being asked to produce an amazing product design + marketing website for CadVerify. This file exists so you don't re-produce what the founder has already rejected. Read it before designing anything.

## What the product is
CadVerify — "Databricks for manufacturability & cost." A governed decision layer for manufacturing: deterministic DFM analysis + glass-box should-cost with full provenance. Users are manufacturing/sourcing engineers making make-vs-buy and cost-down decisions on real CAD parts. The engine is deterministic and honest: every number carries provenance (MEASURED / SHOP / USER / DEFAULT), and nothing is marked `validated` until real shop quotes confirm it.

## Founder taste — three rejections, in order (do not repeat them)

1. **Dark graphite + one-cobalt accent → rejected as "re-skin / AI slop."** It's the LLM-median look. The founder wants a **LIGHT & EDITORIAL** register: cinematic, dense-power, tactile craft — "an art piece, Disneyland magic."
2. **Beautiful typographic tables → rejected as "an Excel sheet."** However well-set, type-and-rules alone doesn't clear the bar. Lead with **the part as hero object**: a 3D stage, isometric part thumbnails in every list, real app anatomy (rail / workspace / inspector), *designed* charts, progressive disclosure. Density done beautifully is not enough; **geometry + composition** are what clear the bar.
3. **Material-metaphor worlds (assay office, paper, hallmarks) → rejected as "word salad."** "The beautifulness went into making it look like paper rather than an actual platform." The correct paradigm is **CUI — conversational-first**: you *talk to the deterministic engine*, and every answer is an engine-computed artifact with provenance — a copilot that *structurally cannot hallucinate numbers*. Beauty = modern platform (geometry, motion, light), **not** material metaphors.

## Hard product invariants the design must express (not decorate over)
- Provenance is first-class: MEASURED / SHOP / USER / DEFAULT tags on cost drivers.
- Honesty states are real UI states: `validated: false`, "assumption-based, not yet validated" labels, and **withheld** numbers (the product shows nothing rather than a fake number). Design these states beautifully; never design them away.
- The decision artifact (should-cost decision card, crossover chart, DFM findings) is the keepable output — treat it as the object of value.

## Practical constraints
- Frontend is a **nonstandard Next.js** app (`frontend/` — read `frontend/AGENTS.md` and the bundled Next docs before touching routing/data-fetching). Existing WIP surfaces live behind flags (`NEXT_PUBLIC_STAGE_UI` etc.): three doors (Decide / Catalog / Portfolio), part-hero components.
- **Work on a `design/…` branch. Do not commit to `dev` or `prod`** — an autonomous build loop merges to those locally and force-of-habit collisions are expensive. Do not touch `backend/`.
- Known merge gotcha: every frontend branch conflicts on `frontend/package.json`'s `"test"` script line; resolution is the union of `--test` file lists.

## The context moment — "the part in its world" (added 2026-07-03)
Beyond verify/cost/DFM, the product must show where a part LIVES: its program, parent assembly, and position (screw → bracket → door module → vehicle). Three data rungs, each with its own honest visual state — design all three:
1. **Real structure exists** (STEP assembly ingested; later PLM connector): the signature cinematic moment — the hero stage zooms out and the parent assembly materializes around the part, part lit in situ; exploded views; sibling parts as isometric thumbnails; any node tappable into the hero position. Deterministic product structure only — every node in the reveal is engine-known.
2. **Declared context only** (user typed program / parent / units-per-parent / annual volume): NO parent geometry exists, so none is shown. Visual = a designed lineage strip (program → assembly → part) with USER-provenance chips on the volumes, feeding honest $/year portfolio math. Diagrammatic, never fake 3D.
3. **No context**: an honest, inviting empty state — "this part has no home yet — where does it live?" Never a stock product silhouette implying knowledge the engine doesn't have.
In the CUI paradigm, "where does this live?" is a first-class conversational question whose answer is this artifact. At portfolio level, program becomes a grouping dimension (the cost-down board clustered by product, rows carrying in-situ thumbnails). Hard rule: the zoom-out is earned by data, never decorated.

## Where the deeper context lives (in this repo)
- `outputs/long-horizon-plan.md` — Track D (design) + gates G0/G0b history.
- `outputs/design/platform-ia-vision.md` — information architecture vision.
- `outputs/design/visual-landscape.md` — visual research; the 4 rendered worlds (context for what was rejected).
- `outputs/audit/platform-gap-map.md` — the product backlog the design serves.
