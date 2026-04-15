# Feature Research

**Domain:** DFM / CAD analysis SaaS — product surface around an existing analysis engine
**Researched:** 2026-04-15
**Confidence:** MEDIUM-HIGH (developer-SaaS onboarding patterns HIGH; DFM competitor PDF/share specifics MEDIUM; self-host DX HIGH)

## Scope Note

Core DFM analyzers (21 processes, rule packs, material/machine DB, Three.js viewer) are **built**. This research covers the *product surface* around the engine: signup, auth, history, persistence, sharing, reports, API docs, and self-host packaging — everything the beta needs to stop feeling like a demo and start feeling like a product.

## Feature Landscape

### Table Stakes (Users Expect These)

Missing any of these = "this is a toy, not a product."

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **API-key signup with zero-friction flow** | Dev-tool SaaS 2026 convention: Google OAuth → key issued in < 60s. Stripe/Clerk/Resend all do this. Email+password is a signal of low maturity. | MEDIUM | Magic link *or* GitHub/Google OAuth → one-click key issuance. No passwords. No email verification loop for beta (post-hoc OK). Target TTFI (time-to-first-integration) < 5 min. |
| **API-key management dashboard** | Rotate, revoke, name keys. Stripe/Resend/OpenAI all do this. | LOW-MED | Show masked key (last 4), creation date, last-used timestamp, revoke button. One key per user is fine for beta; multi-key nice-to-have. |
| **Per-key usage dashboard (read-only)** | Devs want to see "am I hitting limits?" before billing surprises them. Already in PROJECT.md Active list. | MEDIUM | Request count over time, rate-limit state, recent analyses. No need for fancy charts — a table + counter beats a dashboard with nothing in it. |
| **Per-key rate limiting** | Abuse protection. Expected on any public free tier. | MEDIUM | Token bucket or sliding window. Return `429` with `Retry-After` + `X-RateLimit-*` headers (RFC 6585 + draft IETF). Document limits publicly. |
| **Persistent analysis history** | "I lost the tab" is a product-breaking UX. Every peer (Xometry, Protolabs ProDesk, CASTOR) stores analyses. | MEDIUM | Postgres-backed, keyed by mesh hash + user. List view with filename, timestamp, verdict, process. Paginated. |
| **Shareable analysis URL** | Xometry has "Forward to Purchaser"; Protolabs ProDesk has collab links. Engineers forward DFM results to colleagues constantly. | MEDIUM | Signed URL with `analysis_id` + optional expiry. Read-only. Anonymous viewer (no login required to view a shared link). Server-side render of 3D + issues. |
| **PDF export of analysis report** | Peer products all produce PDFs. Engineers attach them to RFQs, design reviews, QMS records. Critical for the "handoff" moment. | MEDIUM | Server-side render (WeasyPrint or Playwright-to-PDF). Include: geometry summary, per-process verdict, top issues with fix suggestions, rule pack used, timestamp, mesh hash. 3D snapshot images (front/iso views). |
| **OpenAPI spec + interactive docs** | Stripe benchmark. Every dev-SaaS 2026 ships OpenAPI 3.1 + playground (Scalar, Mintlify, Redoc, or Fern). FastAPI emits this natively — just expose and style it. | LOW | Already half-free with FastAPI. Host at `/docs` (Scalar/Redoc rebrand) and `/openapi.json`. Include realistic example requests with curl/Python/JS snippets. |
| **Error responses with codes + docs links** | Stripe-style structured errors. `{"error": {"code": "mesh_not_watertight", "message": "...", "doc_url": "..."}}`. | LOW | Standardize once, apply everywhere. Link to `/docs/errors/mesh_not_watertight`. |
| **Docker Compose quickstart (self-host)** | PROJECT.md constraint. Plausible/Supabase/Sentry/Cal.com all ship `docker-compose up` that works first try. | MEDIUM | `docker-compose.yml` with backend + Postgres + worker. One `.env.example`. Target: `git clone && docker compose up` → working in < 10 min. |
| **Landing page with "try it" demo** | Dev-tool convention. Let users see analysis output without signing up. | LOW-MED | Static landing + one public demo STL (no auth). Drives signup conversion more than any pitch copy. |
| **Status badges on analysis list** | Verdict-at-a-glance (pass / issues / fail). Color-coded. | LOW | Cheap, high-impact UX. |
| **Request ID in every response** | Support debugging. `X-Request-ID` header + include in error body. Dev-SaaS hygiene. | LOW | UUID per request, logged everywhere. |
| **Result caching by mesh hash** | Same file re-uploaded → instant. Reduces compute cost, improves perceived perf. | LOW-MED | Already in PROJECT.md Active. Keyed by `sha256(mesh_bytes) + process_set + rule_pack`. |
| **Mesh repair endpoint (`pymeshfix`)** | Already in PROJECT.md Active. Peer products offer auto-heal. Non-watertight meshes are ~30% of real-world uploads. | MEDIUM | `/api/v1/validate/repair` returns repaired mesh + re-analysis. Lightweight — no topology reconstruction. |
| **SDK(s) — at minimum a Python client** | Dev-SaaS 2026: Python + TypeScript SDKs are table stakes. Can be thin wrappers. | LOW-MED | Start with Python (matches backend users). Auto-generated from OpenAPI via Fern or `openapi-generator` is acceptable for beta. |

### Differentiators (Competitive Advantage)

Features where CadVerify can meaningfully stand out vs. Xometry/Protolabs/CASTOR/Netfabb.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **DFM-as-API (not quote-gated)** | Xometry/Protolabs DFM is bundled with their quoting/ordering flow — you can't get just the analysis without going through their manufacturing pipeline. CASTOR is closer but enterprise-priced. A clean public API for DFM alone is a real gap. | — (it's the whole product) | Emphasize this positioning in landing page: "DFM without the sales call." |
| **21 process analyzers in one API call** | Peer tools usually pick *one* process (Xometry quotes CNC or injection or 3DP; ProtoFlow is molding-specific). Returning all viable processes ranked is differentiated. | — (built) | Surface the multi-process ranking prominently in the UI and report. |
| **Industry rule packs as a selector** | Aerospace/automotive/medical/oil-gas overlays are normally consulting-services, not self-serve. Exposing them as a query param is distinctive. | — (built) | Highlight in docs with "medical-device-class" example. |
| **Self-hostable open-ish core** | Developers prefer tools they can `docker compose up` on prem. Sentry/Plausible/Cal.com model. Rare in DFM space — Xometry/Protolabs are closed SaaS, Netfabb is shrink-wrapped desktop. | MEDIUM | Even if not fully OSS for beta, publishing a working docker-compose is rare differentiation. Decide license posture later. |
| **Reproducible analysis (mesh hash + engine version in report)** | Engineers need to defend analysis results months later in audits. "Same mesh + same version = byte-identical report" is a trust feature Xometry doesn't offer. | LOW | Record `engine_version`, `rule_pack_version`, `mesh_sha256` in every stored analysis + PDF. |
| **Webhooks for async results** | When SAM-3D lands as async, devs want push not poll. Stripe/GitHub pattern. | MEDIUM | Nice-to-have for beta; required once async endpoints exist. Defer if time-tight — polling works for beta. |
| **CLI tool (`cadverify analyze file.stl`)** | Dev-tool signal. Matches self-host ethos. Integrates with CI for design-review gates. | LOW-MED | Thin wrapper over API. Publish on PyPI + Homebrew. Devs who see a CLI in docs assume the product is serious. |
| **GitHub Action / CI integration example** | "DFM checks in your PR" is a concrete, tweetable use case. Lands with the dev audience. | LOW | Just a documented example Action using the CLI + API key. No need to publish a marketplace action for beta. |

### Anti-Features (Deliberately NOT Build for Beta)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Billing / Stripe integration** | "Looks serious," investors ask | Zero revenue signal until usage validates demand; adds tax/PCI/dunning surface. PROJECT.md already out-of-scope. | Free beta; add billing only after 50+ active keys. |
| **Email+password signup with verification loop** | "Standard" | 2026 dev SaaS has moved to OAuth + magic link. Password resets, MFA, breach handling = weeks of work for zero differentiation. | GitHub/Google OAuth + magic-link fallback via Resend. |
| **Multi-user orgs / teams / RBAC** | Enterprise asks | Multi-tenancy schema decisions compound for years. 10× the permission bugs. | One user = one key. Revisit after 10 customers ask. |
| **Real-time collaboration on analyses (cursors, comments)** | "Figma-like" is seductive | Collab infra (CRDTs, WS, presence) is a multi-month project that doesn't improve DFM output. | Shareable read-only link + PDF. Comments via forwarded PDF + email. |
| **Synchronous SAM-3D segmentation** | Users want "one button, full analysis" | 30–60s blocking HTTP calls break load balancers, mobile networks, user patience. PROJECT.md already out-of-scope. | Async job + poll endpoint (or webhook later). |
| **Native desktop apps / CAD plugins (Fusion, SolidWorks, Onshape)** | "Engineers live in CAD" | Each plugin is a separate SDK + review + signing pipeline. Xometry has a Fusion plugin — that's one full-time job. | CLI + API; plugins after beta demand proven. |
| **Custom rule-pack authoring UI** | "Let users add their own rules" | Rule DSL + UI + validation + security is a product unto itself. | Accept PRs to rule packs; or YAML config file for self-hosters. |
| **GPU / CUDA default path** | "AI-powered!" | Raises deploy cost 5–10×; Fly/Railway GPU is expensive and capacity-constrained. | CPU-only default. GPU is opt-in for SAM-3D worker only. |
| **CAD file conversion / export (STEP→STL, mesh simplification, remeshing)** | Natural adjacent ask | Each format/operation is a support surface. Not DFM. | Document external tools (FreeCAD, Blender, meshlab). |
| **Analytics / A/B infrastructure for users' own apps** | "Like Mixpanel for CAD uploads" | Feature-creep into observability. | Return enough in API response for users to build own analytics. |
| **Webhook retries, DLQs, signing, replay UI** | "Like Stripe webhooks" | Stripe-grade webhooks are weeks of work. If shipping webhooks at all, start minimal (HTTP POST, HMAC signature, no retries). | Defer webhooks entirely; polling is fine for async endpoints in beta. |
| **Audit log / SOC2 trails** | "Enterprise-ready" | Irrelevant pre-revenue. PROJECT.md out-of-scope. | Postgres row timestamps are enough for beta. |
| **In-browser CAD editing / fix-and-resubmit** | "Close the loop" | CAD kernel in browser = multi-year project (see Onshape, Shapr3D). | Mesh repair endpoint + "download fixed file" link is enough. |
| **Custom domains for shared links** | "White-label" | Cert provisioning, DNS validation, per-tenant routing. | `cadverify.com/a/{id}` is fine for beta. |
| **Multiple API versions (v1/v2) day one** | "Good API hygiene" | Only one version exists. Don't invent migration problems before they happen. | Commit to `/api/v1` and hold it stable. Document deprecation policy for later. |

## Feature Dependencies

```
API-key signup
    ├──requires──> API-key management dashboard
    ├──requires──> Per-key rate limiting
    └──enables───> Per-key usage dashboard

Persistent analysis history
    ├──requires──> Postgres + schema
    ├──requires──> API-key signup (analyses tied to user_id)
    └──enables───> Shareable URLs
                    └──enables──> PDF export (share + PDF draw from same stored record)

PDF export
    ├──requires──> Persistent analysis history (render from stored data, not re-run)
    └──requires──> Server-side rendering path (WeasyPrint or headless browser)

Mesh repair endpoint
    └──requires──> pymeshfix in Docker image

Result caching by mesh hash
    ├──requires──> Persistent storage (can be Redis or Postgres)
    └──enhances──> All endpoints (transparent speedup)

Docker Compose quickstart
    ├──requires──> Production Dockerfile (cadquery baked in)
    ├──requires──> Postgres in compose
    └──requires──> .env.example with all knobs documented

OpenAPI docs
    ├──already provided by──> FastAPI
    └──enables───> SDK generation (Python, TS via Fern or openapi-generator)

CLI tool ──requires──> Python SDK (or direct HTTP — either works)

GitHub Action example ──requires──> CLI tool
```

### Dependency Notes

- **History is the keystone.** Shareable URLs and PDF export both render from the same stored analysis row. Build history first, then both can be layered on in one phase each.
- **Auth gates everything.** Rate limiting, per-user history, and usage dashboards all require the API-key system. Auth must come before persistence in phase ordering.
- **Docker Compose is not just deploy** — it's the local-dev story too. Building it early de-risks every later phase (all contributors get identical envs).
- **Mesh repair is independent.** Can ship any time after the core `/validate` is stable. Good "parallel track" work.
- **Async SAM-3D has no dependencies on the product-surface work** — it's its own infra track (worker, queue, polling endpoint).

## MVP Definition

### Launch With (Beta v1)

Everything required to not feel like a demo. Ruthless minimum:

- [ ] **API-key signup** (Google OAuth, magic-link fallback) — no auth = no product
- [ ] **Per-key rate limiting** — abuse prevention from day one
- [ ] **Persistent analysis history** (Postgres, keyed by user + mesh hash) — "lost tab" is a showstopper
- [ ] **Shareable analysis URL** (signed, read-only, anonymous viewer) — the forward-to-colleague moment
- [ ] **PDF export** — the RFQ/design-review handoff moment
- [ ] **Mesh repair endpoint** (`pymeshfix`) — already PROJECT.md Active; ~30% of uploads need it
- [ ] **OpenAPI + Scalar/Redoc docs at `/docs`** — FastAPI gives this ~free
- [ ] **Structured errors with codes + doc links** — Stripe-style hygiene, cheap to add
- [ ] **Result caching by mesh hash** — perf + cost
- [ ] **Docker Compose quickstart** — PROJECT.md constraint; also enables clean CI + local dev
- [ ] **Landing page with public demo** — conversion driver
- [ ] **Production Dockerfile with cadquery baked in** — unblocks deploy and self-host simultaneously
- [ ] **Per-key usage dashboard (read-only table)** — rate-limit visibility

### Add After Validation (Beta v1.x, post-first-users)

- [ ] **Python SDK** (auto-generated from OpenAPI) — once 3+ users write their own HTTP clients
- [ ] **Async SAM-3D job + poll endpoint** — once segmentation accuracy is validated offline
- [ ] **CLI tool** — once Python SDK stable
- [ ] **GitHub Action example** — riff on CLI, piece of content marketing
- [ ] **Webhooks (minimal: POST + HMAC, no retries)** — only if users ask; polling is fine initially
- [ ] **Multi-key support per user** — once someone asks

### Future Consideration (Post-beta / v2+)

- [ ] Billing (Stripe) — after 50+ active keys + usage signal
- [ ] Multi-user orgs / RBAC — after 3+ teams ask
- [ ] Custom rule-pack authoring — after 5+ users edit rule packs manually
- [ ] TypeScript SDK — if frontend-heavy users emerge
- [ ] CAD plugins (Fusion, SolidWorks) — after product-market fit
- [ ] SOC2 / audit logging — when enterprise deals appear
- [ ] Full OSS license decision — when self-host adoption justifies licensing work

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| API-key signup (OAuth + magic-link) | HIGH | MEDIUM | **P1** |
| Per-key rate limiting | HIGH | MEDIUM | **P1** |
| Persistent analysis history | HIGH | MEDIUM | **P1** |
| Shareable analysis URL | HIGH | MEDIUM | **P1** |
| PDF export | HIGH | MEDIUM | **P1** |
| Docker Compose quickstart | HIGH | MEDIUM | **P1** |
| Production Dockerfile (cadquery baked) | HIGH | MEDIUM | **P1** |
| Mesh repair endpoint | HIGH | MEDIUM | **P1** |
| OpenAPI + Scalar docs | HIGH | LOW | **P1** |
| Structured errors | MEDIUM | LOW | **P1** |
| Result caching by mesh hash | MEDIUM | LOW | **P1** |
| Usage dashboard (read-only) | MEDIUM | LOW | **P1** |
| Landing page + public demo | HIGH | LOW | **P1** |
| API-key management (rotate/revoke) | MEDIUM | LOW | **P1** |
| Request ID header | MEDIUM | LOW | **P1** |
| Python SDK | MEDIUM | LOW (auto-gen) | **P2** |
| Async SAM-3D job + poll | MEDIUM | HIGH | **P2** |
| CLI tool | MEDIUM | LOW | **P2** |
| GitHub Action example | LOW | LOW | **P2** |
| Webhooks | LOW | MEDIUM | **P3** |
| Multi-key per user | LOW | LOW | **P3** |
| Billing | — | HIGH | **Out of scope** |
| Orgs / RBAC | — | HIGH | **Out of scope** |

**Priority key:**
- P1: Must ship in beta — missing = product feels unfinished
- P2: Should ship soon after beta — not blocking launch
- P3: Nice to have — ship only if costs near-zero

## Competitor Feature Analysis

| Feature | Xometry IQE | Protolabs ProDesk | CASTOR | Netfabb (Autodesk) | **CadVerify Approach** |
|---------|-------------|-------------------|--------|--------------------|-----------------------|
| DFM output | Yes, tied to quote | Yes, AI-driven (new 2025) | Yes, DFAM-focused | Yes, desktop + cloud | **API-first, no quote gate** |
| Shareable analysis | "Forward to Purchaser" link | Collab links | Enterprise portal | None (desktop) | Signed public URL, anonymous viewer |
| PDF report | Yes (quote + DFM) | Yes (ProDesk) | Yes | Export to PDF | Yes, with engine version + mesh hash for reproducibility |
| API access | Limited partner API | None public | Enterprise API | None | **Public API is the product** |
| Self-host | No | No | No | Desktop install only | **docker-compose** |
| Multi-process ranking | No (pick one) | Per-service | Primarily additive | Primarily additive | **All 21 in one call** |
| Industry rule packs | Implicit in services | Some | Some | Via templates | **Explicit query param** |
| Free tier | Quote-only | Quote-only | None (enterprise) | None | **Free beta, full API** |
| Developer docs | Partner-only | None | Enterprise | Plugin SDK | **Stripe-grade public OpenAPI** |

**Competitive gap CadVerify fills:** Public, dev-friendly, self-hostable, multi-process DFM API — a position no incumbent holds because their business models require funneling to manufacturing revenue.

## Sources

- [Stripe API onboarding](https://docs.stripe.com/connect/api-onboarding)
- [SaaS Onboarding Best Practices 2026](https://designrevision.com/blog/saas-onboarding-best-practices)
- [SaaSUI — Onboarding flows that convert 2026](https://www.saasui.design/blog/saas-onboarding-flows-that-actually-convert-2026)
- [Clerk llms.txt](https://clerk.com/llms.txt)
- [Stripe API Reference](https://docs.stripe.com/api)
- [Stripe OpenAPI repo](https://github.com/stripe/openapi)
- [Fern — SDKs and docs for APIs](https://buildwithfern.com/)
- [Mintlify playground](https://www.mintlify.com/docs/api-playground/overview)
- [Xometry — How it works](https://www.xometry.com/how-xometry-works/)
- [Xometry Instant Quoting Engine](https://www.xometry.com/quoting/home)
- [Protolabs Automated Design Analysis](https://www.protolabs.com/en-gb/automated-design-analysis/)
- [Protolabs ProDesk launch](https://www.engineering.com/protolabs-launches-prodesk-digital-manufacturing-hub/)
- [Leo — Best DFM Services 2026 review](https://www.getleo.ai/blog/5-best-dfm-services-that-provide-instant-feedback---2026-review)
- [Supabase Self-Hosting Docker](https://supabase.com/docs/guides/self-hosting/docker)
- [Sentry Self-Hosted](https://develop.sentry.dev/self-hosted/)
- [Dokploy (Supabase/Cal.com templates)](https://dokploy.com/)
- [Feature Creep Anti-Pattern](https://www.minware.com/guide/anti-patterns/feature-creep)
- [Apidog — Why Stripe's docs are the benchmark](https://apidog.com/blog/stripe-docs/)

---
*Feature research for: DFM/CAD analysis SaaS product surface*
*Researched: 2026-04-15*
