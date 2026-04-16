# Phase 4: Shareable URLs + PDF Export - Context

**Gathered:** 2026-04-15
**Status:** Ready for planning
**Mode:** `--auto` (Claude selected recommended defaults for every gray area -- see each D-## "Rationale" line for the decision basis; user to review and override before `/gsd-plan-phase 4` if desired)

<domain>
## Phase Boundary

This phase lets users share an analysis with a colleague via a public link and download it as a PDF for RFQs or design reviews. Everything renders from the stored `analyses` row (Phase 3) -- no re-analysis required.

Deliverables:
1. `POST /api/v1/analyses/{id}/share` -- issues a 12-char base62 `share_short_id`, sets `is_public=true`.
2. `DELETE /api/v1/analyses/{id}/share` -- revokes share (nulls `share_short_id`, sets `is_public=false`). Instant 404 on revoked link.
3. Public `GET /s/{short_id}` -- serves a sanitized analysis view (no email, no API-key prefix, no user PII).
4. `GET /api/v1/analyses/{id}/pdf` -- returns a rendered PDF of the analysis (verdict, issues, process ranking, material/machine recs, engine-version footer stamp).
5. PDF blob caching by analysis ID (Fly volume or Tigris/R2 for prod).
6. Frontend Share/Unshare controls, copy-to-clipboard, and "Download PDF" button.
7. `X-Robots-Tag: noindex` and `Cache-Control: private, no-store` on share pages.

**Explicitly out of scope for this phase:**
- Mesh repair (Phase 5)
- 3D viewer on shared pages (Phase 8 polish; shared page shows textual/tabular analysis only)
- Time-limited or password-protected share links (KISS -- toggle on/off is sufficient for beta)
- Public gallery / search of shared analyses (not a social product)
- Batch PDF export (single analysis per PDF only)

</domain>

<decisions>
## Implementation Decisions

### Share URL Format (gray area #1)

- **D-01:** Share URL path: `/s/{short_id}` where `short_id` is a 12-character base62 string. Not `/share/{ulid}`, not a token-based URL.
  - **Rationale:** REQUIREMENTS.md SHARE-01 locks "12-char base62 `share_short_id`". The `/s/` prefix is shorter than `/share/` for copy-paste friendliness. 12 chars of base62 gives 62^12 ~= 3.2 x 10^21 possible IDs -- brute-force enumeration is infeasible. Pitfall 11 confirms opaque IDs are required. The `share_short_id` column already exists in the `analyses` table schema (Phase 3 D-15) with a partial unique index.
  - **Recommended default chosen in auto mode:** `/s/{short_id}` with 12-char base62.

- **D-02:** Short ID generation: `secrets.token_bytes(9)` base62-encoded to 12 chars, generated server-side. Not HMAC-signed (simpler; revocation is via DB flag, not token invalidation).
  - **Rationale:** `secrets.token_bytes` is cryptographically random. 9 bytes = 72 bits of entropy, base62-encoded to exactly 12 chars. HMAC signing (Pitfall 11 alternative) adds complexity for marginal benefit -- revocation already works by nulling the `share_short_id` column. No signed-URL expiry needed for beta (D-03 below).

### Access Control for Shared Links (gray area #2)

- **D-03:** Shared links are **public, no expiry, no password**. Access is toggle-only: share on / share off. Revocation is instant (nulls `share_short_id`, next request 404s).
  - **Rationale:** REQUIREMENTS.md SHARE-02 specifies "revokes (nulls share_short_id, sets is_public=false)." Success Criterion #2 says "the link 404s immediately (revocation is instant, not TTL-based)." Time-limited or password-protected links add UX complexity for a feature whose primary use case is emailing a link to a colleague. Toggle on/off is the simplest model that satisfies requirements. Expiration can be added later as an enhancement.

- **D-04:** Public share endpoint (`GET /s/{short_id}`) requires **no authentication**. It returns a sanitized JSON response stripped of all PII (no email, no API-key prefix, no user ID, no IP).
  - **Rationale:** SHARE-03 mandates sanitized view. Pitfall 11 explicitly says "Scrub PII from shared response: never include owner email, API key prefix, IP, or user-agent." The sanitized serializer returns only: filename, file_type, verdict, face_count, duration_ms, created_at, process_scores, issues, geometry_info, best_process, and the engine-version stamp.

- **D-05:** Share endpoint headers: `X-Robots-Tag: noindex` and `Cache-Control: private, no-store` on every `/s/{short_id}` response.
  - **Rationale:** SHARE-04 + Pitfall 11. Prevents Google indexing of shared analyses. `private, no-store` prevents CDN or browser caching of potentially sensitive manufacturing data.

### PDF Generation Library (gray area #3)

- **D-06:** **WeasyPrint + Jinja2** for PDF rendering. Not reportlab, not headless Chrome/Puppeteer.
  - **Rationale:** REQUIREMENTS.md PDF-02 locks "WeasyPrint + Jinja2." ROADMAP.md explicitly chose WeasyPrint to avoid Chromium image bloat (Pitfall 12). WeasyPrint renders HTML/CSS to PDF via Cairo/Pango -- produces good-looking documents from Jinja2 templates with full CSS support. Pitfall 12 mitigation: explicit font deps in Dockerfile (Phase 6).

- **D-07:** PDF rendered **synchronously** in the request handler (not queued as an async job). Cached after first render.
  - **Rationale:** A typical DFM analysis PDF (text + tables, no embedded 3D) renders in 1-3 seconds with WeasyPrint. This is acceptable for a synchronous endpoint. First request renders and caches; subsequent requests serve from cache in < 500ms (Success Criterion #5). If rendering time becomes an issue at scale, it can be moved to the arq worker (Phase 7 infrastructure) -- but that's premature for beta.

### PDF Content Layout (gray area #4)

- **D-08:** PDF sections in order:
  1. **Header:** CadVerify logo + "DFM Analysis Report" + filename + date
  2. **Summary:** Verdict badge (PASS/ISSUES/FAIL), face count, file type, analysis duration
  3. **Issues table:** All issues sorted by severity (error > warning > info), with code, message, measured vs required values, and fix suggestion
  4. **Process ranking:** Table of process scores sorted by score descending, with recommended material and machine per process
  5. **Geometry overview:** Key metrics from geometry_info (volume, surface area, bounding box, watertight/manifold status)
  6. **Footer:** Engine version + mesh SHA-256 (first 12 chars) + analysis timestamp + "Generated by CadVerify"
  - **Rationale:** PDF-02 requires "verdict, issues, process ranking, material/machine recs." PDF-03 requires "engine version + mesh SHA + analysis timestamp" in footer. This layout follows the natural reading order an engineer would use when evaluating a part for manufacturing: "Is it good? What's wrong? Which process? What are the numbers?"

- **D-09:** PDF styling: clean, professional, black-and-white-friendly. Verdict badge uses color (green/amber/red) but all content is legible when printed in grayscale. No Three.js renders or 3D previews in the PDF.
  - **Rationale:** RFQ and design review documents are frequently printed. Color is a bonus, not a requirement. Excluding 3D renders keeps PDF generation fast and avoids the headless Chrome dependency entirely.

### PDF Caching Strategy (gray area #5)

- **D-10:** PDF bytes cached on **local filesystem** (Fly volume `/data/pdf-cache/`) for beta. Keyed by `{analysis_ulid}.pdf`. Future migration to Tigris/R2 is a Phase 6 or post-beta task.
  - **Rationale:** PDF-04 specifies "Tigris/R2/Fly volume." For a single-instance beta on Fly, a volume mount is the simplest and fastest option -- no S3-compatible client library needed, no credentials to manage. The cache is disposable (PDFs can be regenerated from `result_json`), so volume loss is not data loss. If Fly scales to multiple instances, promote to Tigris/R2 at that point.

- **D-11:** Cache invalidation: PDF is generated once per analysis and never regenerated. The `analyses` table is append-only (Phase 3 specifics), so `result_json` never changes for a given analysis ID. If the PDF template changes (design update), a one-time script clears the cache directory.
  - **Rationale:** Analyses are immutable. The only reason to regenerate is a template change, which is a deployment event, not a per-request event. Simple and correct.

### Frontend Share Page (gray area #6)

- **D-12:** The public share page (`/s/{short_id}`) is a **Next.js server-rendered page** (RSC / server component). Not a client-side SPA that fetches from the API.
  - **Rationale:** Server-side rendering enables proper `<meta>` tags for link previews (Open Graph: title, description, verdict, filename). When someone pastes a CadVerify share link in Slack or email, the preview should show "DFM Analysis: bracket.stl -- PASS (3 processes viable)". CSR would show a blank preview since bots don't execute JS. The server component fetches from `GET /s/{short_id}` at render time.

- **D-13:** Share page meta tags (Open Graph + Twitter Card):
  - `og:title`: "{filename} -- DFM Analysis"
  - `og:description`: "Verdict: {verdict} | {process_count} processes evaluated | {face_count} faces"
  - `og:type`: "article"
  - `og:site_name`: "CadVerify"
  - `twitter:card`: "summary"
  - **Rationale:** Engineers share these links in Slack, Teams, and email. Good link previews increase click-through and make the product feel polished. Minimal implementation cost with server rendering already in place.

- **D-14:** Share page content: read-only, non-interactive version of the analysis result. Shows verdict, issues list, process ranking table, geometry metrics. No 3D viewer, no "Attempt repair" button, no edit controls. Includes a "View on CadVerify" link that goes to the authenticated analysis detail page.
  - **Rationale:** The share page is for viewing, not interacting. Keeping it read-only avoids the complexity of unauthenticated actions. The "View on CadVerify" link drives signup/login for users who want the full experience.

### Frontend Share Controls

- **D-15:** On the authenticated analysis detail page (`/dashboard/analyses/{id}`), add a "Share" button. Clicking it calls `POST /api/v1/analyses/{id}/share`, receives the short URL, and shows a modal with the URL + copy-to-clipboard button. If already shared, the button shows "Shared" with the URL visible and a "Revoke" action.
  - **Rationale:** SHARE-05 requires "Share and Unshare controls with copy-to-clipboard." Modal pattern matches the Stripe-style "reveal once" UX established in Phase 2 (D-17 in 02-CONTEXT.md). The share URL is not secret (it's intentionally public), but the modal focuses attention on the copy action.

- **D-16:** On the authenticated analysis detail page, add a "Download PDF" button. Clicking it fetches `GET /api/v1/analyses/{id}/pdf` as a blob and triggers a browser download with filename `{original_filename}-analysis.pdf`.
  - **Rationale:** PDF-05 requires this. Direct download via blob fetch avoids opening a new tab. The filename includes the original mesh filename for easy identification in the user's Downloads folder.

### Rate Limiting on Share/PDF Endpoints (gray area #7)

- **D-17:** `POST /api/v1/analyses/{id}/share` and `DELETE /api/v1/analyses/{id}/share` use the existing per-API-key rate limits (60/hr, 500/day) -- no separate limits.
  - **Rationale:** Share/unshare operations are low-frequency (a user shares maybe 5-10 analyses per day). Existing rate limits are more than sufficient. No new rate-limit configuration needed.

- **D-18:** `GET /s/{short_id}` (public share page API) has a **per-IP rate limit** of 120/hour (since it's unauthenticated, per-key limits don't apply).
  - **Rationale:** Public endpoints need IP-based rate limiting to prevent scraping. 120/hour is generous for legitimate use (a colleague clicking a few links) but blocks automated enumeration. Uses the same slowapi + Redis infrastructure from Phase 2.

- **D-19:** `GET /api/v1/analyses/{id}/pdf` uses the existing per-API-key rate limits. Additionally, because PDF generation is CPU-intensive (1-3s), a **per-user concurrency limit of 2 simultaneous PDF renders** is enforced via an asyncio Semaphore.
  - **Rationale:** Prevents a single user from saturating the server with PDF render requests. The semaphore is per-process (adequate for single-instance beta). At multi-instance scale, promote to a Redis-based distributed semaphore.

### Claude's Discretion

The following are left to the researcher / planner to resolve with standard patterns and no further user input:

- Exact base62 encoding implementation (use `string.ascii_letters + string.digits` or a library).
- Jinja2 template file location and structure (`backend/src/templates/pdf/` or similar).
- WeasyPrint CSS specifics (page size, margins, font selection within the Noto/DejaVu family).
- Exact sanitized serializer field list (derive from D-04 constraints + existing `result_json` shape).
- Share modal component styling and animation.
- PDF cache directory creation on startup vs lazy-create.
- Whether `GET /s/{short_id}` returns JSON (for the Next.js server component to render) or pre-rendered HTML (JSON is preferred -- keeps the backend as a pure API).
- Open Graph image (`og:image`) -- skip for beta; no screenshot generation. Can add later.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase-level requirements and roadmap
- `.planning/ROADMAP.md` S"Phase 4: Shareable URLs + PDF Export" -- goal, success criteria, key deliverables, suggested parallel plans (4.A, 4.B), pitfall references.
- `.planning/REQUIREMENTS.md` S"Shareable URLs" (SHARE-01..05) -- share endpoint spec, revocation, sanitized view, robots/cache headers, frontend controls.
- `.planning/REQUIREMENTS.md` S"PDF Export" (PDF-01..05) -- PDF endpoint, WeasyPrint+Jinja2, footer stamp, blob caching, frontend button.
- `.planning/PROJECT.md` S"Key Decisions" -- "Full history + shareable URLs + PDF export" as table-stakes for a product.

### Pitfalls research (from Phase 0 research)
- `.planning/research/PITFALLS.md` S"Pitfall 11: Shareable URL enumeration / leakage" -- opaque IDs, PII scrubbing, signed URLs (opted for simpler revocable short ID), X-Robots-Tag, unshare button.
- `.planning/research/PITFALLS.md` S"Pitfall 12: WeasyPrint / headless Chrome PDF rendering footguns" -- font deps, Dockerfile system packages, CI smoke test, avoid headless Chrome.

### Brownfield codebase map
- `.planning/codebase/ARCHITECTURE.md` -- current pipeline data flow; integration point for share/PDF endpoints alongside history endpoints.
- `.planning/codebase/STRUCTURE.md` -- `backend/src/api/` route module layout; where share and PDF route modules slot in.
- `.planning/codebase/CONVENTIONS.md` -- error-response shape, logger naming, env-var config pattern.

### Prior phase context
- `.planning/phases/02-auth-rate-limiting-abuse-controls/02-CONTEXT.md` -- rate-limit infrastructure (slowapi + Redis), AuthedUser model, CORS config, log scrubbing. Phase 4 share endpoints reuse these.
- `.planning/phases/03-persistence-analysis-service-history-caching/03-CONTEXT.md` -- analyses table schema with `is_public` and `share_short_id` columns (D-15), ULID-based IDs, `result_json` JSONB, history API shape, AnalysisDashboard component reuse.

### Existing Phase 3 code to integrate with
- `backend/src/db/models.py` -- `Analysis` model with `is_public` (Boolean, default false) and `share_short_id` (Text, nullable, partial unique index). These columns are ready for Phase 4.
- `backend/src/api/history.py` -- existing `GET /analyses/{id}` handler pattern. Share and PDF endpoints follow the same route structure.
- `backend/src/services/analysis_service.py` -- pipeline service. Phase 4 does NOT modify this; it reads from stored `analyses` rows only.
- `frontend/src/app/(dashboard)/analyses/[id]/page.tsx` -- existing analysis detail page. Share/Unshare buttons and PDF download button integrate here.
- `frontend/src/components/AnalysisDashboard.tsx` -- reusable analysis display component. The public share page can use a read-only variant of this.
- `frontend/src/lib/api.ts` -- existing API client with type definitions. Add `shareAnalysis()`, `unshareAnalysis()`, `downloadPdf()`, and `fetchSharedAnalysis()` functions.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`Analysis` ORM model** (`db/models.py:88-139`) -- `is_public` and `share_short_id` columns already exist with proper indexing. Phase 4 just writes to them.
- **`AnalysisDashboard` component** (`frontend/src/components/AnalysisDashboard.tsx`) -- renders full analysis results. The share page can use a read-only variant (strip interactive controls, add "View on CadVerify" CTA).
- **`fetchAnalysis()` API function** (`frontend/src/lib/api.ts`) -- existing fetch pattern. New `fetchSharedAnalysis()` follows the same structure but hits `/s/{short_id}`.
- **`AuthedUser` + `require_api_key` dependency** (`auth/require_api_key.py`) -- share/unshare endpoints use this. Public `/s/{short_id}` endpoint does NOT use it.
- **slowapi + Redis rate limiter** (`auth/rate_limit.py`) -- existing `@limiter.limit()` decorator. Apply to new endpoints.
- **History router pattern** (`api/history.py`) -- `APIRouter(tags=["history"])` structure. New `api/share.py` and `api/pdf.py` routers follow the same pattern.

### Established Patterns
- **Env-var config via `os.getenv()`** -- Phase 4 adds `PDF_CACHE_DIR` (default `/data/pdf-cache/`).
- **`Depends()` injection** -- share/unshare use `Depends(require_api_key)` + `Depends(get_db_session)`. PDF endpoint uses the same.
- **ULID-based public IDs** -- `analyses.ulid` is the public-facing ID used in API paths. Share and PDF endpoints use this as the `{id}` parameter (not the internal bigint PK).
- **Cursor-paginated list + detail pattern** -- history endpoints established this. No new patterns needed.

### Integration Points
- New module: `backend/src/api/share.py` -- `POST /analyses/{id}/share`, `DELETE /analyses/{id}/share`, `GET /s/{short_id}`.
- New module: `backend/src/api/pdf.py` -- `GET /analyses/{id}/pdf`.
- New module: `backend/src/templates/pdf/analysis_report.html` -- Jinja2 template for WeasyPrint.
- New Next.js route: `frontend/src/app/s/[shortId]/page.tsx` -- server-rendered public share page.
- Modified: `frontend/src/app/(dashboard)/analyses/[id]/page.tsx` -- add Share/Unshare + PDF download buttons.
- Modified: `frontend/src/lib/api.ts` -- add share/unshare/pdf/shared-fetch API functions.
- Modified: `backend/src/api/routes.py` (or app init) -- mount new routers.
- New dependency: `weasyprint` in `backend/requirements.txt` (+ system-level font/pango deps in Dockerfile, Phase 6).

</code_context>

<specifics>
## Specific Ideas

- **Share URL should be short enough to paste in a Slack message** without wrapping: `https://cadverify.com/s/Ab3xK9mN2pQr` (51 chars total).
- **PDF should be attachable to an RFQ email** -- file size under 500 KB for a typical analysis (text + tables, no images). Keep it lean.
- **Share page should feel like a "receipt"** -- clean, professional, read-only. Not a degraded version of the app. Think GitHub Gist public view.
- **"Copy link" confirmation** -- brief toast notification ("Link copied!") rather than replacing button text. Consistent with modern clipboard UX.
- **PDF download filename** follows the pattern `{original_filename}-dfm-report.pdf` (e.g., `bracket-dfm-report.pdf`). Recognizable in a Downloads folder.
- **Footer stamp in PDF** enables reproducibility: "CadVerify v0.3.0 | mesh: ab3f7c2e1d9a | 2026-04-15T12:00:00Z" -- enough for an engineer to verify which version analyzed which file.

</specifics>

<deferred>
## Deferred Ideas

All surfaced during auto-mode analysis; parked for future phases or post-beta iteration:

- **Time-limited share links** -- adding TTL-based expiry (e.g., 7 days, 30 days) to shared URLs. Not needed for beta; toggle on/off is sufficient. Revisit if users request ephemeral sharing.
- **Password-protected share links** -- adding a password gate on shared analyses. Adds UX complexity for marginal security benefit. If the link is shared intentionally, a password is redundant.
- **3D viewer on share page** -- rendering the mesh in Three.js on the public share page. Requires storing the mesh file (not in scope until Phase 5 or later) and loading Three.js for unauthenticated users (bundle size concern). Deferred to Phase 8 polish.
- **Share analytics** -- tracking how many times a shared link is viewed, by whom. Nice for engagement metrics but v2+ scope.
- **Batch PDF export** -- downloading multiple analyses as a zip of PDFs. v2+ scope.
- **Custom branding on PDFs** -- allowing users to add their company logo to PDF reports. v2/paid-tier feature.
- **PDF via email** -- sending the PDF as an email attachment instead of downloading. Requires email sending infrastructure (Resend is available from Phase 2, but this is a new capability, not a clarification).
- **Tigris/R2 blob storage for PDFs** -- migrating from Fly volume to S3-compatible storage. Deferred until multi-instance deployment (Phase 6 or post-beta). Fly volume is sufficient for single-instance beta.
- **Open Graph image generation** -- generating a preview image (screenshot of the analysis) for link previews. Requires headless browser or image generation library. Text-based OG tags are sufficient for beta.

</deferred>

---

## Gray Areas Resolved in Auto Mode -- Summary Table

| # | Gray area | Auto-selected default | Decision ID(s) |
|---|-----------|----------------------|----------------|
| 1 | Share URL format: /share/{id} vs /s/{short_id} vs token-based | `/s/{short_id}` with 12-char base62 (cryptographic random) | D-01, D-02 |
| 2 | Access control: public, time-limited, or password-protected | Public toggle (on/off), no expiry, no password, instant revocation | D-03, D-04, D-05 |
| 3 | PDF library: WeasyPrint vs Puppeteer vs reportlab | WeasyPrint + Jinja2 (locked by REQUIREMENTS.md) | D-06 |
| 4 | PDF content layout: sections, branding, detail level | Header, summary, issues table, process ranking, geometry, stamped footer | D-08, D-09 |
| 5 | PDF caching: blob storage vs filesystem vs no cache | Fly volume filesystem cache, keyed by analysis ULID | D-10, D-11 |
| 6 | Frontend share page: SSR vs CSR, meta tags | Next.js server-rendered (RSC) with Open Graph + Twitter Card meta tags | D-12, D-13, D-14 |
| 7 | Rate limiting on share/PDF endpoints | Existing per-key limits + per-IP 120/hr on public endpoint + PDF concurrency semaphore | D-17, D-18, D-19 |

## Decisions the User Should Revisit Before `/gsd-plan-phase 4`

These auto-selections are the most consequential to downstream planning. Worth a glance before committing:

1. **D-03 (No expiry on share links).** Shared analyses live forever unless manually unshared. If confidential CAD data leakage is a concern for your beta users, adding a default 30-day expiry (with "public forever" opt-in) would mitigate stale links. Easy to add later, but changes the DB schema slightly (adds `share_expires_at` column).

2. **D-10 (Fly volume for PDF cache, not Tigris/R2).** Ties PDF caching to a single Fly instance. If you scale to 2+ backend instances, cached PDFs won't be shared between them. Regeneration is cheap (1-3s), so this is a minor issue, but worth knowing. Tigris/R2 migration is straightforward when needed.

3. **D-07 (Synchronous PDF generation).** For analyses with many issues (50+ issues, complex process rankings), WeasyPrint may take 3-5 seconds. This blocks the HTTP response. If beta users report slow PDF downloads, the fallback is to queue generation via arq (Phase 7 infra) and return a polling URL. For now, sync is simpler and likely adequate.

4. **D-12 (Server-rendered share page).** Requires the Next.js frontend to be able to reach the backend API at build/render time. This is already the case for the dashboard (CSR fetches from API_BASE), but SSR adds a server-to-server call path that Phase 6 deployment must account for (internal network or public API URL).

5. **D-18 (120/hr per-IP on public share endpoint).** This is generous. If abuse becomes an issue (scraping shared analyses), tightening to 30/hr or adding Turnstile on the share page are options. Starting generous avoids false positives on legitimate corporate networks (many users behind one IP).

---

*Phase: 04-shareable-urls-pdf-export*
*Context gathered: 2026-04-15*
*Mode: --auto (all gray areas resolved with recommended defaults; see each D-## "Rationale" line)*
