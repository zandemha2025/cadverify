# Phase 4: Shareable URLs + PDF Export - Pattern Map

**Mapped:** 2026-04-15
**Phase:** 04-shareable-urls-pdf-export

## Files to Create/Modify

### Backend — New Files

| File | Role | Closest Analog | Pattern Source |
|------|------|----------------|----------------|
| `backend/src/api/share.py` | API router for share/unshare + public view | `backend/src/api/history.py` | APIRouter + Depends pattern |
| `backend/src/api/pdf.py` | API router for PDF download | `backend/src/api/history.py` | APIRouter + Depends pattern |
| `backend/src/services/share_service.py` | Share business logic (generate ID, toggle) | `backend/src/services/analysis_service.py` | Service module pattern |
| `backend/src/services/pdf_service.py` | PDF generation + caching | `backend/src/services/analysis_service.py` | Service module with caching |
| `backend/src/templates/pdf/analysis_report.html` | Jinja2 PDF template | None (new artifact type) | WeasyPrint HTML template |
| `backend/src/templates/pdf/style.css` | PDF CSS styles | None (new artifact type) | Print CSS with @page rules |

### Backend — Modified Files

| File | Change | Pattern Source |
|------|--------|----------------|
| `backend/src/api/routes.py` (or app init) | Mount share + pdf routers | Existing `router.include_router(history.router)` pattern |
| `backend/requirements.txt` | Add `weasyprint>=62.0`, `jinja2>=3.1.0` | Existing dependency lines |

### Frontend — New Files

| File | Role | Closest Analog | Pattern Source |
|------|------|----------------|----------------|
| `frontend/src/app/s/[shortId]/page.tsx` | SSR public share page | `frontend/src/app/(dashboard)/analyses/[id]/page.tsx` | Server component with `generateMetadata` |
| `frontend/src/components/ShareModal.tsx` | Share URL modal with copy-to-clipboard | `frontend/src/components/RevealOnceModal.tsx` | Modal with action button |
| `frontend/src/components/ShareButton.tsx` | Share/Unshare toggle button | None (new component) | Button with state toggle |
| `frontend/src/components/PdfDownloadButton.tsx` | PDF download trigger | None (new component) | Blob fetch + download pattern |

### Frontend — Modified Files

| File | Change | Pattern Source |
|------|--------|----------------|
| `frontend/src/lib/api.ts` | Add `shareAnalysis()`, `unshareAnalysis()`, `downloadPdf()`, `fetchSharedAnalysis()` | Existing `fetchAnalysis()` pattern |
| `frontend/src/app/(dashboard)/analyses/[id]/page.tsx` | Add ShareButton + PdfDownloadButton | Existing metadata header section |

## Code Excerpts — Analog Patterns

### Router Pattern (from `history.py`)

```python
# backend/src/api/history.py — lines 20-22
router = APIRouter(tags=["history"])

# Route with auth + rate limit + session
@router.get("/{analysis_id}")
@limiter.limit("60/hour;500/day")
async def get_analysis(
    analysis_id: str,
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_api_key),
    session: AsyncSession = Depends(get_db_session),
):
```

**Apply to:** `share.py` (share/unshare endpoints use this exact pattern), `pdf.py` (PDF endpoint uses this pattern).

**Variation for public endpoint:** `GET /s/{short_id}` omits `Depends(require_api_key)` and uses IP-based rate limit `@limiter.limit("120/hour")`.

### Query Pattern (from `history.py`)

```python
# Single-row lookup by ULID + user ownership check
stmt = select(Analysis).where(
    Analysis.ulid == analysis_id,
    Analysis.user_id == user.user_id,
)
result = await session.execute(stmt)
analysis = result.scalar_one_or_none()
if analysis is None:
    raise HTTPException(status_code=404, detail="Analysis not found")
```

**Apply to:** Share/unshare endpoints (lookup by ULID + user_id), PDF endpoint (lookup by ULID + user_id).

**Variation for public share:** Lookup by `share_short_id` + `is_public=True`, no user_id filter.

### API Client Pattern (from `api.ts`)

```typescript
// frontend/src/lib/api.ts — authenticated fetch pattern
export async function fetchAnalysis(id: string): Promise<AnalysisDetail> {
  const res = await fetch(`${API_BASE}/analyses/${id}`, {
    headers: authHeaders(),
  });
  if (!res.ok) {
    throw new Error(res.status === 404 ? "Analysis not found" : "Failed to fetch analysis");
  }
  return res.json();
}
```

**Apply to:** `shareAnalysis()`, `unshareAnalysis()` (POST/DELETE with auth headers), `downloadPdf()` (GET with auth, blob response), `fetchSharedAnalysis()` (GET without auth, different base URL).

### Analysis Detail Page Pattern (from `analyses/[id]/page.tsx`)

```tsx
// Metadata header block — extend with Share + PDF buttons
<div className="rounded-md border p-3">
  <h1 className="text-lg font-semibold">{analysis.filename}</h1>
  <p className="text-sm text-gray-500">
    {analysis.file_type.toUpperCase()} &middot;{" "}
    {new Date(analysis.created_at).toLocaleString()}
  </p>
  {/* ADD: <ShareButton /> and <PdfDownloadButton /> here */}
</div>
```

### Modal Pattern (from `RevealOnceModal.tsx`)

The existing `RevealOnceModal` component (used for API key reveal in Phase 2) establishes the modal UX pattern. `ShareModal` follows the same structure: overlay + centered card + action button + dismiss.

### Response Headers Pattern (from `rate_limit.py`)

The `rate_limit_handler` already sets `X-RateLimit-*` headers. For share pages, additional headers:

```python
response.headers["X-Robots-Tag"] = "noindex"
response.headers["Cache-Control"] = "private, no-store"
```

## Data Flow

```
Share flow:
  User -> POST /analyses/{id}/share (authed)
       -> share_service.create_share(analysis_ulid, user_id, session)
       -> UPDATE analyses SET share_short_id, is_public=true
       <- { share_url: "/s/{short_id}" }

Public view flow:
  Visitor -> GET /s/{short_id} (no auth, IP rate limited)
          -> SELECT * FROM analyses WHERE share_short_id = :id AND is_public = true
          -> sanitize_analysis_for_share(analysis)
          <- sanitized JSON

PDF flow:
  User -> GET /analyses/{id}/pdf (authed)
       -> pdf_service.get_or_generate(analysis_ulid, user_id, session)
       -> check cache -> hit: return bytes | miss: render + cache
       <- PDF bytes (Content-Type: application/pdf)
```

## PATTERN MAPPING COMPLETE
