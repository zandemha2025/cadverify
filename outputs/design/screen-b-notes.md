# Screen Builder B — surfaces converted onto the one product

Scope: bring the remaining surfaces onto the shared app shell + `components/ui` primitives +
the single status map (`lib/status.ts`). No new nav, no inline buttons/cards/badges, no
per-file color maps, no off-system colors/radii. Data layer (`lib/api*`) untouched.

## Proof (all run from `frontend/`)

- `npx tsc --noEmit` → **exit 0 (green)**
- `npm run lint` (eslint) → **0 errors** (3 pre-existing warnings: `IssueList` unused import,
  legacy `ModelViewer` unused prop, `data-table` TanStack React-Compiler note — none in B's edits)
- `npm run build` → **Compiled successfully**, TypeScript passed, 14/14 routes generated
  (incl. `/history`, `/batch`, `/batch/[id]`, `/keys`, `/label`, `/reconstruct`,
  `/analyses/[id]`, `/s/[shortId]`)
- Dev-server smoke (`:3000`): `/history /batch /label /reconstruct /s/[id]` → **200**.
  `/keys` → 500 = pre-existing `Error: list failed` (server component requires an authed
  `dash_session`; identical un-guarded `await listKeys()` as the original — the throw is in
  data-fetch, before any JSX renders, not a B regression).

## Surfaces converted

| Surface | File(s) | Now uses |
|---|---|---|
| History | `app/(app)/history/page.tsx` (page already shell-wrapped) + `AnalysisHistoryTable.tsx`, `QuotaDisplay.tsx` | `DataTable` (TanStack) + `StatusBadge` (verdict), `Select` filter, `EmptyState`, `ErrorState`, `Button`; quota uses shared `Progress` with `usageTone`. Dropped `VERDICT_BADGE` + `usageColor` maps. |
| Analyses detail | `app/(app)/analyses/[id]/page.tsx`, `ShareButton`, `ShareModal`, `PdfDownloadButton`, `RepairButton`, `RepairComparison` | `PageHeader` + back `Button`, `Spinner`, `ErrorState`; Share/PDF/Repair actions are `Button`s; "Shared" = `StatusBadge`; share dialog = `Dialog` + `Input`; repair banners = toned `Card` + `StatusBadge`. Dropped `bg-black`/outline-blue/`bg-green-600` one-offs. |
| Batch list | `app/(app)/batch/page.tsx`, `BatchUploadForm.tsx` | `PageHeader`, `Card`, `DataTable` + `StatusBadge`, `EmptyState`, `Button`; upload form = `Tabs` (ZIP/S3) + shared `Dropzone` + `Field`/`Input` + `Button`. Dropped `STATUS_BADGES` map + inline `<table>` + 3rd dropzone + blue buttons. |
| Batch detail | `app/(app)/batch/[id]/page.tsx`, `BatchItemsTable.tsx`, `BatchProgressBar.tsx` | `PageHeader` + back `Button`, destructive cancel via `AlertDialog`; items = `DataTable` + `StatusBadge` + `Select` filter; progress = `Card` + `StatusBadge` + shared `Progress` (`batchStatusTone` fill). Dropped two duplicate batch status-color maps. |
| API keys | `app/(app)/keys/page.tsx`, `RevealOnceModal.tsx` | `PageHeader`, `Card` + shared `Table`, `StatusBadge` (Active/Revoked), `Button` (server-action forms preserved), `EmptyState`; reveal = `Dialog` + `Button`. Dropped `bg-black` + `neutral-*` grays. |
| Reconstruct | `app/(app)/reconstruct/page.tsx` + `ImageUploader`, `ReconstructionProgress`, `MeshPreview`, `ConfidenceBadge` | `PageHeader`, `Card`, `Button`, `ErrorState`; uploader = shared `Dropzone`; progress = shared `Spinner` + `Progress`; confidence = `StatusBadge`; **viewer consolidated to the one `CadViewer`** (deleted the duplicate `MeshCanvas.tsx`). Dropped 3rd dropzone, 4px spinner, blue buttons, level color map. |
| Label (Parts) | `app/(app)/label/page.tsx` | **Folded into the shell** (was an orphan full-screen `bg-gray-50` page with its own header/no nav). Now `PageHeader`, `Card`, `Button`, `Input`/`Field`/`Textarea`, `StatusBadge` (progress), `EmptyState`, `ErrorState`, `Spinner`; viewer via existing `CorpusViewer`→`CadViewer`. Keyboard shortcuts + flow intact. |
| Public share | `app/s/[shortId]/page.tsx` | Reskinned to the design language (public, no app nav by design): `Card` (tone), `StatusBadge` (verdict/severity via `verdictTone`/`severityTone`), shared `Table`, `Button`, token surfaces, a minimal CadVerify wordmark bar. Dropped `VERDICT_STYLES`/`SEVERITY_STYLES` maps + `bg-black` CTAs. |

## Cohesion guarantees

- Every data-dense list (History, Batch list, Batch items, Keys, Share process ranking) uses
  the shared `Table`/`DataTable` with right-aligned mono (`num`) numerics + `StatusBadge` from
  the single map. No inline `<table>`/`<button>` remain in B's surfaces (verified by grep:
  no `bg-black|bg-blue-|bg-gray-|bg-green-|bg-red-|bg-yellow-|text-gray-|text-blue-|border-blue-|rounded-md|rounded-lg|rounded-xl|<table|<button`).
- States standardized: `EmptyState` (with CTA), `Spinner`/`TableSkeleton` loading,
  `ErrorState` + `sonner` toasts for errors — across all listed surfaces.
- Status vocabulary is single-sourced: removed 6 per-file color/label maps
  (`AnalysisHistoryTable.VERDICT_BADGE`, `QuotaDisplay.usageColor`, `batch/page.STATUS_BADGES`,
  `BatchItemsTable.STATUS_BADGES`, `BatchProgressBar.STATUS_COLORS`, `ConfidenceBadge.LEVEL_STYLES`,
  `s/[shortId].VERDICT_STYLES/SEVERITY_STYLES`).
- Shared primitive enhanced (not re-rolled): `Progress` gained an optional `tone` so quota
  (`usageTone`) and batch (`batchStatusTone`) bars consume the one status map instead of
  re-declaring bar colors.

## One cross-agent note (honesty)

`src/components/cost/BreakevenChart.tsx` (Screen Builder A's concurrently-created cost file,
absent at B's start) had a Recharts v3 tooltip typing error blocking the **shared** `tsc`/build.
Applied a minimal, type-only, runtime-preserving fix (re-declared the two context-omitted
`payload`/`label` props on the tooltip prop type) so the shared tree compiles green. A's logic
untouched; A may overwrite the file. No other A-owned file was modified.
