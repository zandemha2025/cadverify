# DESIGN MISSION — read this first, then design

> **THESIS UPDATE 2026-07-04 — read `PLATFORM-DNA.md` (repo root) FIRST and design to IT.** The platform's center of gravity moved from should-cost to **makeability VERIFICATION** (can this be made — on your machines, in materials that survive its environment, at physical resource cost; price is secondary). Where this file and PLATFORM-DNA.md disagree, **the DNA wins** — in particular, the #1 signature moment is now **The Verdict**, and the DNA adds three new moments (Your Machines, The Environment Door, Triage at Scale). The register, hard NOs, anatomy, honesty rules, and working rules below all still apply unchanged.

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

## Screen & artifact inventory (what to actually design)

### App anatomy
Every screen lives in one anatomy: **rail** (nav) / **workspace** (center) / **inspector** (right, progressive disclosure) — plus the **conversation surface**, the CUI entry point, always reachable (as the workspace's spine or a summonable thread). Design how conversation and direct manipulation coexist; that relationship is the product's signature.

### Screens
1. **Sign-in / first-run** (real email+password auth exists; design an honest, craft-level first-run).
2. **Home — the three doors** (Decide / Catalog / Portfolio), role-aware landing.
3. **Decision workspace** (THE core screen): drop zone → part hero stage → conversation with the engine → decision artifacts. This is the founder's first-contact surface — it carries The Crossover moment.
4. **Part detail** (a catalog entry): hero stage, the context moment, DFM findings, its cost-decision history, lineage.
5. **Catalog explorer**: grid with isometric hero thumbnails, facets, saved views, the specimen-admission beat.
6. **Portfolio cost-down board**: savings ranking clustered by program, posture bar, drill-to-rows.
7. **Batch run monitor**: a ZIP of parts costing progressively — honest per-item states including failures (a failed part shows why, never disappears).
8. **Cost decision detail + compare** (two decisions side-by-side; differences that don't exist show "—", never fake zeros).
9. **Public shared artifact page** (`/s/cost/…`) — marketing-grade: this page is how the product spreads; it must carry the honesty labels intact.
10. **Ground-truth ingest / the Hallmark moment**: real quotes come back → the assumption band flips solid. Design the flip.
11. **Governed libraries** (rate cards, materials, shops — versioned, effective-dated): one concept frame now, full design later.
12. **Org settings**: members/roles, API keys, webhooks — functional register, same system.
13. **Empty states for every list** — empty catalog, empty portfolio, no-context part. Empty states are designed moments here, not gray placeholders.

### Cards / artifacts (the atoms — these ARE the product)
Should-cost **decision card** (make-vs-buy + crossover qty) · **crossover chart** (a designed chart, not a library default) · **glass-box driver table** with provenance chips (MEASURED / SHOP / USER / DEFAULT) · **confidence band** (dashed assumption vs solid measured; the `validated` flag) · **DFM findings card** scoped to the recommended route, with the honest expander to the full 21-process matrix · **part hero thumbnail** (isometric, used in every list) · **context lineage strip** · **portfolio savings row** (with `basis` — which engine field the saving comes from) · **posture bar** (provenance aggregate) · **batch progress card** · honesty primitives: the **withheld number**, the **DEFAULT-assumption chip** with `[assumption, not shop-validated]`, the **"assumption-based, not yet validated"** label, the **decimated-mesh notice**.

### Interactions (design as moments, with motion)
- **The drop** — file lands, engine works, the part materializes onto the hero stage (the opening ceremony).
- **Ask the engine** — conversational what-ifs, ONLY the ones the engine actually answers: quantity, region, material class, shop profile, rate overrides. The UI must never offer a question the engine can't compute.
- **The crossover scrub** — drag quantity, watch the make-vs-buy decision flip at the computed crossover.
- **Provenance disclosure** — tap any chip → the driver's source, verbatim.
- **The zoom-out** — the context moment (three states, per the brief).
- **Compare** — two decisions, differences composed, absences honest.
- **Share** — decision → public artifact page.
- **The batch drop** — a ZIP arrives, the portfolio fills progressively.
- **The Hallmark** — ground truth ingested, the band flips solid: the single most emotionally important interaction in the product.
- **The withheld tap** — tap a withheld number → why it's withheld and what would unlock it.

## Working rules
- Create a `design/<your-name>` branch and commit ONLY there — **never to `dev` or `prod`** (an autonomous build loop merges to those).
- Do not touch `backend/`.
- The frontend is a **nonstandard Next.js** app — read `frontend/AGENTS.md` and the bundled Next docs in `frontend/node_modules/next/dist/docs/` before writing any app code.
- New surfaces go behind `NEXT_PUBLIC_*` feature flags, default off.
