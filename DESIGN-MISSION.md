# DESIGN MISSION — read this first, then design

You are doing the full **product design** and **marketing website** for CadVerify. This file is your complete mission. Follow it exactly.

Before designing anything, also read `outputs/design/claude-web-design-brief.md` — it encodes three rounds of founder rejections and is **binding**. Deeper context if you want it: `outputs/design/platform-ia-vision.md`, `outputs/long-horizon-plan.md` (Track D and §W3.5), `outputs/audit/platform-gap-map.md`.

## What this product is
CadVerify is "Databricks for manufacturability & cost" — a governed decision layer for manufacturing engineers. Drop in a CAD part; a deterministic engine produces DFM findings and a glass-box should-cost decision where every number carries provenance (MEASURED / SHOP / USER / DEFAULT) and nothing is called "validated" until real shop quotes confirm it.

## The register
Light & editorial, cinematic, dense-power, tactile craft — beauty from **geometry, motion, and light**, like a modern platform, not from material metaphors. The paradigm is **CUI, conversational-first**: you TALK to the deterministic engine, and every answer is an engine-computed artifact with provenance — **a copilot that structurally cannot hallucinate numbers**. That sentence is the soul of both the product and the website.

## Hard NOs (each was already tried and rejected by the founder)
- Dark graphite + one accent color ("AI slop, LLM-median").
- Typography-and-tables as the design ("a beautiful Excel sheet").
- Paper / assay-office / hallmark material metaphors ("word salad").
- Stock imagery, fake numbers, fake states, or implied knowledge the engine doesn't have.

## Design these six signature moments (product)
1. **The conversational decision workspace** — ask the engine, get a decision artifact: should-cost card, crossover chart, DFM findings, provenance chips on every driver.
2. **The part hero stage** — the part as hero object: 3D stage, isometric thumbnails in every list, real app anatomy (rail / workspace / inspector).
3. **The context moment** — "where does this part live?" — three states, all specified in the brief: real assembly structure → cinematic zoom-out with the part lit in situ; declared-only context → a designed lineage strip (program → assembly → part) with USER-provenance chips; no context → an honest, inviting "this part has no home yet" empty state. The zoom-out is earned by data, never decorated.
4. **The catalog explorer** — parts admitted like specimens, hero-object thumbnails, never a bare BI facet grid.
5. **The portfolio cost-down board** — org-wide savings ranking clustered by program, rows with in-situ thumbnails (the backend for this is being built right now: ranked engine-computed savings, validated flags, withheld numbers).
6. **Honest states as DESIGNED states** — `validated: false`, "assumption-based, not yet validated", withheld-rather-than-fake numbers, DEFAULT-provenance warnings. Make honesty feel like craftsmanship, not apology.

## The website
Sells the thesis — the governed decision layer, the copilot that cannot hallucinate numbers, the ground-truth flywheel ("send back real costs → the band flips solid"). The product's real artifacts ARE the hero imagery: the decision card, the crossover chart, the context zoom-out. Same register as the product. No abstract SaaS blobs, no fake dashboards.

## Sequence
1. First produce **static concept frames** — self-contained HTML/CSS art-direction renders of the six moments plus the website hero — for founder review.
2. Only after the founder picks a direction, derive tokens and components.
3. Then build app surfaces and website pages.

## Working rules
- Create a `design/<your-name>` branch and commit ONLY there — **never to `dev` or `prod`** (an autonomous build loop merges to those).
- Do not touch `backend/`.
- The frontend is a **nonstandard Next.js** app — read `frontend/AGENTS.md` and the bundled Next docs in `frontend/node_modules/next/dist/docs/` before writing any app code.
- New surfaces go behind `NEXT_PUBLIC_*` feature flags, default off.
