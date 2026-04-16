# Phase 4: Shareable URLs + PDF Export - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md -- this log preserves the alternatives considered.

**Date:** 2026-04-15
**Phase:** 04-shareable-urls-pdf-export
**Mode:** --auto (all gray areas auto-resolved with recommended defaults)
**Areas discussed:** Share URL format, Access control, PDF generation library, PDF content layout, PDF caching strategy, Frontend share page, Rate limiting

---

## Share URL Format

| Option | Description | Selected |
|--------|-------------|----------|
| `/share/{ulid}` | Uses existing ULID as share ID; longer URL but no new ID generation | |
| `/s/{short_id}` (12-char base62) | Short opaque ID; matches SHARE-01 spec; enumeration-proof | ✓ |
| Token-based (HMAC-signed) | Signed URL with expiry baked in; more complex, harder to revoke | |

**User's choice:** [auto] `/s/{short_id}` with 12-char base62 (recommended default)
**Notes:** REQUIREMENTS.md SHARE-01 locks the 12-char base62 format. Pitfall 11 confirms opaque IDs. The `share_short_id` column already exists in the schema from Phase 3.

---

## Access Control for Shared Links

| Option | Description | Selected |
|--------|-------------|----------|
| Public, no expiry, toggle on/off | Simplest model; share or unshare instantly | ✓ |
| Time-limited (30-day default) | Auto-expires stale links; adds schema column | |
| Password-protected | Gate shared page with a password; adds UX complexity | |

**User's choice:** [auto] Public toggle (recommended default)
**Notes:** Success Criterion #2 requires instant revocation. Toggle model is the simplest that satisfies requirements. Expiry and password deferred.

---

## PDF Generation Library

| Option | Description | Selected |
|--------|-------------|----------|
| WeasyPrint + Jinja2 | HTML/CSS to PDF via Cairo/Pango; locked by REQUIREMENTS.md | ✓ |
| Puppeteer / headless Chrome | High fidelity; adds ~500 MB to Docker image | |
| ReportLab | Programmatic PDF; no font stack issues; less pretty | |

**User's choice:** [auto] WeasyPrint + Jinja2 (locked by PDF-02)
**Notes:** Pitfall 12 confirms WeasyPrint is the right choice for beta. Font deps must be addressed in Phase 6 Dockerfile.

---

## PDF Content Layout

| Option | Description | Selected |
|--------|-------------|----------|
| Comprehensive (6 sections) | Header, summary, issues, process ranking, geometry, footer stamp | ✓ |
| Minimal (summary + issues only) | Faster to render; less useful for RFQs | |
| Branded (custom logo + cover page) | Professional but adds complexity; v2 feature | |

**User's choice:** [auto] Comprehensive 6-section layout (recommended default)
**Notes:** PDF-02 requires verdict, issues, process ranking, material/machine recs. PDF-03 requires engine-version footer stamp. The comprehensive layout covers all requirements.

---

## PDF Caching Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Fly volume (local filesystem) | Simplest; single-instance only; disposable cache | ✓ |
| Tigris/R2 (S3-compatible) | Multi-instance; requires credentials; more durable | |
| No cache (regenerate each time) | Simplest code; 1-3s latency on every download | |

**User's choice:** [auto] Fly volume filesystem (recommended default)
**Notes:** PDF-04 specifies blob caching. Fly volume is sufficient for single-instance beta. Analyses are immutable, so cache never needs invalidation per-request.

---

## Frontend Share Page

| Option | Description | Selected |
|--------|-------------|----------|
| Server-rendered (RSC) | Enables OG meta tags for link previews; SEO-friendly | ✓ |
| Client-side rendered (CSR) | Simpler; but blank link previews in Slack/email | |
| Static pre-rendered (SSG) | Fast; but requires build-time data fetching | |

**User's choice:** [auto] Server-rendered RSC (recommended default)
**Notes:** Link preview meta tags (Open Graph, Twitter Card) are a significant UX win for a sharing feature. CSR would show blank previews. SSG doesn't apply to dynamic content.

---

## Rate Limiting on Share/PDF Endpoints

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse existing per-key limits + per-IP on public | Minimal new config; per-IP 120/hr on unauthenticated endpoint | ✓ |
| Separate stricter limits for share/PDF | More granular control; more configuration surface | |
| No additional limits | Rely on existing infrastructure | |

**User's choice:** [auto] Reuse existing + per-IP 120/hr + PDF concurrency semaphore (recommended default)
**Notes:** Share/unshare are low-frequency. PDF generation needs concurrency control (CPU-bound). Per-IP limit on public endpoint prevents scraping.

---

## Claude's Discretion

- Base62 encoding implementation details
- Jinja2 template file organization
- WeasyPrint CSS specifics (page size, margins, fonts)
- Sanitized serializer exact field list
- Share modal styling
- PDF cache directory lifecycle
- Whether `/s/{short_id}` returns JSON or HTML

## Deferred Ideas

- Time-limited share links
- Password-protected share links
- 3D viewer on share page
- Share analytics
- Batch PDF export
- Custom branding on PDFs
- PDF via email
- Tigris/R2 blob storage migration
- Open Graph image generation
