# CadVerify — Product / Platform Strategy Audit
**Lens:** Product/Platform Strategist — completeness vs the DFM + should-cost category
**Date:** 2026-07-01
**Method:** Direct inspection of the running app (frontend `:3000`, backend `:8000`), the FastAPI router graph (`backend/main.py`), the Postgres data model (`backend/src/db/models.py`), every mounted product surface, and 2026 competitive research on aPriori, Paperless Parts, 3D Spark, Xometry, DFMPro. I read the code and exercised the live services; I did **not** take the marketing site at face value.

---

## BOTTOM LINE (up front)

CadVerify is a **single-seat analyst instrument**, not yet an enterprise **platform**. The engineering *depth* on the core loop (geometry → routing → per-process DFM → glass-box should-cost) is real and, on the "explainability" axis, genuinely ahead of the category. But almost everything that turns a good analysis tool into a *bought* platform is either missing or a thin stub:

1. **The flagship deliverable produces no artifact.** The should-cost / make-vs-buy decision — the thing the whole marketing site is built around — is computed **in-memory and thrown away**. It cannot be saved, exported to PDF, shared, versioned, or compared. There is literally no cost record in the database. `backend/src/api/routes.py:759` states it plainly: *"nothing is persisted (no DB session, no mesh blob)."* A procurement or cost-engineering buyer's entire job is to *produce and defend a number over time* — CadVerify hands them a number they can't keep.
2. **There is no multi-user / org / team concept anywhere.** The data model (`backend/src/db/models.py`) has `users` and per-user rows — no `organizations`, `teams`, `tenants`, `projects`, `folders`, or `tags`. Every enterprise buyer purchases *seats for a team*; CadVerify has no team.
3. **There is no AI/copilot layer** in a category that went AI-native in 2025–26 (Paperless "Wingman", aPriori "aP Generate/AI Insights", Xometry AI quoting). CadVerify's only ML is image→mesh reconstruction (TripoSR), not a copilot.
4. **Batch / portfolio is DFM-only.** The one surface that could deliver enterprise value at scale (screen a portfolio for make-vs-buy) runs `analysis_service.run_analysis` per item (`backend/src/jobs/batch_tasks.py:232`) — DFM, **not** cost. The exact 3D Spark / aPriori enterprise use case is absent.

Net: the *proof-of-concept of the hard part* is real. The *product around it* is ~15–20% built against what the category calls table stakes in 2026. The gaps below are ordered by how directly they block adoption and revenue.

---

## REAL — verified to exist and work

| Surface | Evidence | Verdict |
|---|---|---|
| **Core "Living Instrument" (analyze + cost)** | `/analyze` and `/cost` both render `LivingInstrument` (`frontend/src/app/(app)/analyze/page.tsx`, `.../cost/page.tsx`); 35KB component with real 3D part, quantity scrubber, glass-box drawer. Backend `POST /api/v1/validate/cost` returns full provenance-tagged decision JSON. | Real, and the differentiated surface. Works end-to-end locally. |
| **DFM analysis + persistence** | `analyses` table with `result_json`, `verdict`, dedup constraint, mesh-hash cache (`models.py:100`). `GET /api/v1/analyses` history, `GET /{id}` detail. | Real. This is the *only* part of the loop that produces a durable record. |
| **DFM PDF report** | `GET /api/v1/analyses/{id}/pdf` via WeasyPrint + Jinja (`backend/src/api/pdf.py`, `services/pdf_service.py`, template `templates/pdf/analysis_report.html`). File-cached, semaphore-bounded. | Real — but **DFM-only** (see Stubbed). |
| **Public share link (read-only)** | `POST/DELETE /api/v1/analyses/{id}/share`, public `GET /s/{short_id}` with `noindex` + sanitized payload (`backend/src/api/share.py`, `share_service`). | Real, but single-artifact, no collaboration (see Missing). |
| **Batch (DFM) with webhooks** | `POST /api/v1/batch` (ZIP or S3 input), `batches`/`batch_items`/`webhook_deliveries` tables, CSV results export `GET /batch/{id}/results/csv`, HMAC webhook with retry/backoff (`batch_router.py`, `jobs/batch_tasks.py`, `services/webhook_service.py`). | Real code path; **DFM-only** and **needs a running arq worker** (see Fragile). |
| **Auth breadth** | Password + Google OAuth + magic-link + SAML, `AUTH_MODE`-gated (`backend/main.py:152-162`, `backend/src/auth/*`). RBAC roles viewer/analyst/admin (`auth/rbac.py`). API keys with rotate/rename/revoke + reveal-once (`auth/keys_api.py`, `/settings/developer`). | Real and unusually complete for the stage. SAML/OAuth are wired, not just stubs. |
| **API + docs** | OpenAPI, `/docs`, `/redoc`, and Scalar (`/scalar`) interactive docs. Developer settings page issues keys. | Real. A credible developer surface. |
| **Admin API** | `GET /api/v1/admin/users`, user detail, `PATCH /users/{id}/role`, `GET /audit-log` CSV export (`admin_routes.py`); `audit_log` table with IP/UA/file-hash. | API is real — but **no admin UI** (see Missing). |
| **Command palette + minimal shell** | ⌘K palette (`components/ui/command-palette.tsx`), slim contextual top strip. Pro-tool feel. | Real, polished. |

---

## STUBBED / FRAGILE — looks done, isn't

1. **The should-cost decision is ephemeral — the single biggest product hole.**
   `POST /api/v1/validate/cost` and `/validate/cost/demo` explicitly persist nothing (`routes.py:720-820`; docstring: *"IP-local … nothing is persisted"*). Consequences that a buyer hits in the first session:
   - No cost **history** (History lists DFM `analyses` only — `history.py`; cost never enters the DB).
   - No cost **PDF/export** (the PDF template `analysis_report.html` has **no** cost/should-cost/make-vs-buy section — only verdict, DFM issues, process ranking, tolerances, geometry).
   - No cost **share link** (`share_service` only shares persisted `analyses`).
   - No **re-run / audit trail** of a number you quoted last month.
   The instrument (`LivingInstrument.tsx`, cost components in `components/cost/`, `components/glass-box/`) has **zero** save/export/download/share affordance — grep confirms the only "share/pdf/download" buttons in the app (`PdfDownloadButton`, `ShareButton`, `ShareModal`) are wired **only** into `/analyses/[id]` (the DFM detail), never the cost surface. The flagship is demoware in the literal sense: great live, gone on refresh.

2. **PDF/reporting is DFM-only and un-branded.** No cost breakdown, no driver/provenance table, no confidence interval, no make-vs-buy crossover, no assumptions log, no company logo/cover, no "share with supplier" framing. This is an engineer's check sheet, not a should-cost report a buyer forwards to a supplier or a finance stakeholder. (`templates/pdf/analysis_report.html`)

3. **Batch is DFM-only and inert without a worker.** `batch_tasks.py:232` runs `analysis_service.run_analysis` (DFM) per item — there is **no batched cost / portfolio make-vs-buy**. And in the live environment there is **no arq worker running** (`pgrep arq` → none) and no local `redis-cli` on PATH, so a submitted batch would sit `pending` indefinitely. The pipeline exists in code; it is not a demonstrable, always-on capability.

4. **"Admin" is an API, not a product.** No admin frontend exists (`find frontend -iname '*admin*'` → nothing; the command palette has no admin entry). A customer admin cannot invite users, see team usage, manage roles, or view the audit log without curling the API. For an enterprise sale, "admin" == a UI.

5. **Sharing ≠ collaboration.** The one share primitive is a public, read-only, unauthenticated link to a single DFM analysis. No expiry controls beyond revoke, no access list, no comments, no "share to a named teammate," no notification. It's a "send a link" feature, not a workspace.

6. **History depth is shallow.** `GET /api/v1/analyses` filters by **verdict only** (pass/issues/fail) with cursor pagination (`history.py`). No full-text/filename search, no date range, no filter by process/material/rule-pack, no sort options, no tags/folders, no cost. At even a few hundred parts this becomes unusable — and enterprise portfolios are thousands.

7. **Internal tools masquerade as product surface.** `/reconstruct` (image→mesh) and `/label` (corpus annotator) are dev-gated (`devOnly` in the palette; `LABELING_ENABLED` mount in `main.py:170`). Legitimate to have, but they are R&D/labeling scaffolding, not customer capabilities — don't count them toward product completeness.

---

## MISSING — A-Z platform gaps vs the 2026 category

Prioritized by adoption/revenue impact. **P0** = blocks the core buying use case; **P1** = blocks team/enterprise adoption; **P2** = expected polish/parity.

### P0 — blocks the money use case

- **[P0] Persist + export + version the cost decision.** A saved should-cost record with a stable URL, a branded PDF (drivers, provenance, CI, crossover, assumptions), CSV/JSON export, and re-run history. Without this there is *no deliverable to buy*. Every competitor ends in a saveable artifact: Paperless "digital quotes," aPriori cost reports into PLM, 3D Spark "C-level reporting," Xometry an orderable quote.
- **[P0] Quote / RFQ object (even if internal-only).** There is no `quote`/`rfq`/`order` concept anywhere (grep confirms "quote" appears only as prose). CadVerify positions against Paperless Parts (whose entire product *is* the quote/RFQ workflow) and Xometry (instant orderable quote). A cost number that can't become a quote line, be sent, tracked, revised, and won/lost has no place in the buyer's actual workflow. This is the wedge competitors will attack.
- **[P0] Portfolio / batch **cost** at scale.** The enterprise value of 3D Spark and aPriori is "point us at 2,000 parts and rank the make-vs-buy / cost-down opportunities." CadVerify's batch is DFM-only and single-user. A batched cost run with a sortable savings/should-cost table and rollup KPIs is the single highest-leverage enterprise feature it lacks.
- **[P0] AI / copilot layer — the category's 2026 center of gravity.** Zero LLM in the stack (no `openai`/`anthropic`/`langchain` in `requirements.txt`; the only ML is TripoSR image→mesh). Meanwhile: Paperless "Wingman" auto-extracts GD&T/tolerance/material/BOM from drawings and RFQs; aPriori "aP Generate" auto-costs at PLM check-in and surfaces AI cost-down insights; Xometry quotes via ML on millions of parts. The glass-box provenance data is *ideal* grounding for a "why is this number what it is / how do I get it down" copilot — its absence is now a competitive liability, not just a missing nicety.

### P1 — blocks team/enterprise adoption

- **[P1] Multi-user org / team model.** No `organizations`/`teams`/`tenant` in `models.py`. Need: org entity, membership, invites, seat management, team-scoped visibility of analyses/batches. You cannot sell seats to a team that doesn't exist in the schema. This is a **data-model change**, so it's expensive later — flag it now.
- **[P1] Admin UI.** Surface the existing admin API as a real console: members & roles, usage/quota by user, audit-log viewer/export, org settings. Enterprise security review will ask to *see* this.
- **[P1] Collaboration primitives.** Comments/annotations on a part or a driver, assign-to-teammate, "needs review"/approval status, activity feed, @mentions. None exist (grep confirms). This is how a cost estimate moves engineer → buyer → approver.
- **[P1] Projects / folders / tags + real search.** Organize the portfolio; search by filename, material, process, verdict, date, cost band. Table stakes past ~50 parts.
- **[P1] CAD / PLM / ERP integrations.** None exist beyond outbound batch webhooks and optional S3 batch input. The category is defined by *living inside the buyer's stack*: DFMPro embeds in SolidWorks/Creo/NX; aPriori integrates PLM/CAD/ERP and auto-analyzes at check-in; Paperless pushes/pulls ERP/CRM/BI. At minimum: a CAD-plugin or Onshape/Fusion connector, PLM check-in hook, and ERP/CSV round-trip. This is the deepest moat competitors have and CadVerify's biggest whitespace-to-close.
- **[P1] Notifications.** No in-app or email notifications except the magic-link email and batch webhooks (grep: only `magic_link.py` sends mail). Need: "batch done," "part shared with you," "quote updated," "comment added," digest emails. Required for any async team workflow.
- **[P1] Onboarding.** No guided first-run, sample part, empty-state tour, or "paste this STL to see it work" (grep: no onboarding/tour/welcome). Enterprise trials die in the first 10 minutes without this; the depth here needs hand-holding.

### P2 — expected polish / parity

- **[P2] Billing / plans / usage metering as product.** No Stripe/subscription/seat/plan (grep). "Quota" today is only rate limits (`QuotaDisplay`). A self-serve or contract billing surface + usage dashboard is expected even for design-partner deals.
- **[P2] Assemblies / BOM.** Single-part only. Paperless shipped an AI BOM Builder; aPriori costs whole BOMs. Real parts arrive as assemblies.
- **[P2] Comparison / scenario surface at the portfolio level.** There's per-part process comparison, but no "compare part A vs B" or "scenario: qty/material/region sweep saved side by side" as a durable, shareable view.
- **[P2] Supplier / shop directory as product.** `GET /shops` and per-shop calibration exist in the engine, but there's no managed supplier list, capability matrix, or "route this to shop X" handoff — the connective tissue between a should-cost and a purchase.
- **[P2] Sustainability / carbon.** aPriori and 3D Spark both lead with CO₂. Not present; increasingly a buyer checkbox.
- **[P2] Region/material data libraries as a browsable, governed asset.** The engine has regions/materials, but there's no admin-governed, versioned rate-library surface (aPriori's "digital factories" are a headline asset). Buyers ask "whose numbers are these and can I edit them for my plant?"

---

## Competitive benchmark — capability matrix (2026)

| Capability | CadVerify | aPriori | Paperless Parts | 3D Spark | Xometry | DFMPro |
|---|---|---|---|---|---|---|
| Glass-box cost provenance/CI | **Yes (lead)** | Partial | Partial | Partial | No (black box) | n/a |
| Should-cost saved artifact/report | **No** | Yes | Yes | Yes | Yes (quote) | n/a |
| Quote / RFQ workflow | **No** | via sourcing | **Yes (core)** | target-price | **Yes (core)** | No |
| Portfolio/batch **cost** at scale | **No (DFM only)** | **Yes** | Yes | **Yes (core)** | Per-order | No |
| DFM checks | Yes (21 proc) | Yes | Yes | Yes | Yes | **Yes (300+ rules)** |
| CAD/PLM/ERP integration | **No** | **Yes** | **Yes** | Yes | Upload | **Yes (embedded)** |
| AI / copilot | **No** | **Yes** | **Yes (Wingman)** | Partial | **Yes** | Partial |
| Teams / org / roles UI | **No (API only)** | Yes | Yes | Yes | Yes | Enterprise |
| Collaboration/comments | **No** | Yes | Yes | Yes | Yes | Review flows |
| Assemblies/BOM | **No** | Yes | **Yes** | Yes | Yes | Yes |
| Sustainability/CO₂ | No | **Yes** | Partial | **Yes** | Partial | No |
| Onboarding/self-serve | No | Enterprise | Yes | Yes | **Yes (best)** | Enterprise |

**Where CadVerify legitimately wins:** the glass-box, per-driver provenance (MEASURED/USER/DEFAULT/SHOP) with an honest ±40% "not yet validated" CI, and the make-vs-buy *crossover* as the hero output. That is a real, defensible differentiator on the *trust/explainability* axis — but only if it produces an artifact a buyer can keep and share, which today it does not.

---

## What blocks adoption/revenue — the prioritized path

1. **Make the cost decision a durable, exportable, shareable artifact** (P0). Persist cost runs; cost PDF with drivers/provenance/CI/crossover; CSV/JSON; stable URL + share. *Nothing else matters until the flagship leaves a trace.*
2. **Batched should-cost over a portfolio + a sortable savings table** (P0). Turns the tool into an enterprise value story ("we found $X of cost-down across your catalog").
3. **A minimal quote/RFQ object** the cost decision flows into (P0) — even internal-only — so it lives in the buyer's actual job.
4. **Org/team model + admin UI + invites/seats** (P1) — unblocks selling to more than one person; do the schema change early.
5. **A grounded copilot** on the provenance data (P1) — "why this number, how to reduce it" — to be credible in a category that is now AI-native.
6. **One real integration** (CAD plugin or PLM check-in) (P1) — proves "lives in the stack," the incumbents' moat.
7. **Search/folders/tags, notifications, onboarding** (P1/P2) — retention and trial-conversion hygiene.

---

## NEEDS REAL-EXPERT VALIDATION (I cannot self-certify these)

These are *product-strategy* calls that require the founder + a real design-partner buyer, not something I can verify from code:

1. **Persona/wedge decision — buyer vs design engineer.** The product straddles procurement/cost-engineering (aPriori/3D Spark/Paperless persona) and design-for-manufacturing (DFMPro/Xometry persona). *Ask a real cost engineer and a real mechanical design lead:* "which of these two would you pay for, and what artifact must it produce?" The right P0 feature (quote vs CAD-plugin) depends on which persona wins. **Show:** the live cost instrument + the (missing) exported report mockup. **Ask:** "would you buy the number if you couldn't save/share it? what would you forward, to whom?"
2. **Whether the ±40%-CI number is buyable at all without ground truth.** Product completeness cannot fix a number a buyer won't trust. This is the correctness question the other audit lenses own — but from a *product* standpoint, validate with a real manufacturing engineer / real quotes *before* building the quote/RFQ workflow on top of it, or the workflow ships on sand.
3. **Which single integration to build first.** *Ask 3–5 target buyers:* "what system does a part *arrive from* and a decision *go into* today?" (Onshape? SolidWorks PDM? Windchill? Excel? an ERP?) Build to the observed answer, not to a competitor's brochure.
4. **Batch/portfolio value framing.** *Show* a design partner a mocked "portfolio should-cost, ranked by savings" and *ask* whether that is the report that gets them budget — before investing in batched cost infra.

---

*Evidence anchors: `backend/db/models.py` (no org/team/quote tables), `backend/src/api/routes.py:720-820` (cost not persisted), `backend/src/api/history.py` (verdict-only filter), `backend/src/templates/pdf/analysis_report.html` (DFM-only PDF), `backend/src/jobs/batch_tasks.py:232` (batch = DFM), `backend/main.py:141-173` (mounted routers), `frontend/src/components/ui/command-palette.tsx` (nav surface), `frontend/src/components/instrument/LivingInstrument.tsx` (no export/share on cost). Live: frontend 200, backend `/health` ok; no arq worker running.*
