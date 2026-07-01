# Cycle 4 — Frontend Labeler: run guide, endpoint contract, evidence

**Role:** Tool builder (spec §4 + §5). Builds the `/label` tool and its backend
corpus/label endpoints. Date: 2026-06-28.

The labeling tool lets a human apply a *ground-truth manufacturing method* to each
corpus part through a local 3D viewer. **CAD stays on localhost** — STL bytes are
streamed from the local backend to the local viewer; nothing egresses. **No
auto-labeling**: the engine is never used to fill a label.

---

## 1. Files delivered

### Backend
| File | Purpose |
|---|---|
| `backend/src/corpus/paths.py` | Canonical local-corpus paths (`CORPUS_ROOT`, `MESH_DIR`, `MANIFEST`, `LABELS_PATH`, `LABELS_SEED`). Env override `CADVERIFY_DATA_DIR` (default `<repo>/data`). |
| `backend/src/corpus/demo_seed.py` | **Demo fallback only.** If the corpus manifest is empty at build time, seeds a local corpus from the already-downloaded 107 repo parts (real Printables/GitHub meshes — corpus source #2) so the tool is demonstrable. Idempotent; superseded by the real gathered corpus. |
| `backend/src/api/corpus_router.py` | The 5 endpoints (§4): list, stream-STL, get-record, post-label, progress. |
| `backend/main.py` (edited) | Mounts the corpus router **only** under `LABELING_ENABLED=1` (prod-safe); broadens CORS to localhost in that mode so the viewer can fetch STLs cross-origin (`:3000` → `:8000`). |

### Frontend
| File | Purpose |
|---|---|
| `frontend/src/lib/ontology.ts` | Shared 6-key ontology + hotkeys (mirrors backend §1.2). |
| `frontend/src/app/label/CorpusViewer.tsx` | Thin `dynamic(..., {ssr:false})` wrapper that **reuses the existing** `reconstruct/components/MeshCanvas.tsx` STL-from-URL viewer (no new viewer written). |
| `frontend/src/app/label/page.tsx` | The `/label` page: 70% viewer + 30% panel, 6 ontology buttons with keys 1–6, confidence (low/med/high), notes, prev/next/skip, progress counter, labeler input. |

`data/` is already gitignored (CAD-as-IP; corpus + labels never committed).

---

## 2. How to run it

Two processes. Backend on `:8000`, frontend on `:3000`.

**Backend** (from `backend/`):
```bash
cd /Users/nazeem/Desktop/developer/cadverify/backend
# uvicorn is not installed in .venv; use any ASGI runner you have, e.g.:
LABELING_ENABLED=1 python -m uvicorn main:app --host 127.0.0.1 --port 8000
# (or hypercorn / gunicorn -k uvicorn.workers.UvicornWorker)
```
- `LABELING_ENABLED=1` is **required** — without it the corpus routes are not mounted.
- Optional: `LABELER=you@example.com` sets the default labeler; `CADVERIFY_DATA_DIR`
  relocates the corpus/labels.
- On first request, if `data/corpus/manifest.jsonl` is empty, the backend
  auto-seeds the demo fallback from the repo parts (one-time).

**Frontend** (from `frontend/`):
```bash
cd /Users/nazeem/Desktop/developer/cadverify/frontend
npm run dev          # Next.js 16 dev server on http://localhost:3000
```
Then open **http://localhost:3000/label**.

Use: a part renders in 3D on the left; click a method button (or press `1`–`6`) to
save a label and advance. `←`/`→` navigate, `s` skips without labeling. Labels are
written to `data/labels.jsonl`. Progress shows `labeled / total`.

> NOTE: the frontend `API_BASE` in dev points at `http://localhost:8000/api/v1`
> (`frontend/src/lib/api-base.ts`). Run the backend on port **8000** for the
> default to work, or set `NEXT_PUBLIC_API_BASE`.

---

## 3. Endpoint contract (all under `/api/v1/corpus`, dev-gated)

| Method / path | Purpose | Key response fields |
|---|---|---|
| `GET /parts?offset&limit&unlabeled_only&labeler` | Paginated corpus list, label overlay for `labeler` (else majority). `limit` ≤ 200. | `{total, offset, limit, labeled, unlabeled, parts:[{part_id, filename, dataset, license, n_faces, volume_cm3, bbox_mm, watertight, process_family_guess, label, mesh_url}]}` |
| `GET /parts/{part_id}/mesh.stl` | Stream one STL. Path-safe (resolves inside `CORPUS_ROOT`, rejects traversal). | `FileResponse`, `media_type=model/stl`, `ETag=<part_id>`, `Cache-Control: public, max-age=3600`. 404 if unknown/missing. |
| `GET /parts/{part_id}` | One manifest record + all resolved labels. | `{...manifest_fields, process_family_guess, labels:[{labeler,label,ts,confidence,notes}]}`. 404 if unknown. |
| `POST /labels` | Record a human label. Body `{part_id, label, labeler?, confidence?, notes?}`. | 404 if `part_id` unknown; **422** if `label` not one of the 6 keys; `labeler` = body / `X-Labeler` header / `LABELER` env / `"local"`; server sets `ts`; **appends** one line to `labels.jsonl`. Returns `{ok, part_id, label, labeler, ts}`. |
| `GET /progress?labeler` | Labeling progress + coverage. | `{total_parts, labeled, unlabeled, per_label_counts{6 keys}, per_guess_counts, labelers}`. |

The 6 ontology keys: `additive, subtractive, injection_molding, sheet_metal,
casting, unsure_other`. `process_family_guess` is surfaced as a string (the
heuristic family) or `null` and is shown in the UI **explicitly tagged
"unverified heuristic guess — NOT a label."** Labels are **append-only**;
last-write-wins per `(part_id, labeler)` resolved at read time.

---

## 4. Evidence it works (real smoke run)

**Frontend typecheck + lint + production build — all green:**
```
npx tsc --noEmit                  -> exit 0 (no type errors)
npx eslint src/app/label/* src/lib/ontology.ts  -> exit 0
npx next build                    -> Compiled successfully; route list includes  ○ /label
```

**Backend endpoints — end-to-end against the real corpus** (driven via the actual
ASGI app with `LABELING_ENABLED=1`; uvicorn is not installed in the venv, so the
smoke uses FastAPI `TestClient`, which exercises the same routes/middleware):

```
GET  /corpus/progress      -> 200  total_parts=253 labeled=0 per_guess_counts={additive:162, subtractive:53, sheet_metal:38}
GET  /corpus/parts?unlabeled_only=true -> 200  total=253; first part 0daa3505… "…EK_0BD1_ECU_Firewall_mount.stl" faces=1586 bbox=[160,62,32.6]
GET  /corpus/parts/0daa3505…/mesh.stl  -> 200  content-type=model/stl  ETag=0daa3505…  Cache-Control=public, max-age=3600  bytes=79384 (real binary STL)
GET  /corpus/parts/..%2f..%2fetc%2fpasswd/mesh.stl -> 404 (traversal rejected)
GET  /corpus/parts/deadbeef/mesh.stl   -> 404 (unknown id)
POST /corpus/labels {subtractive,high,notes} -> 200 {ok:true, ts set}
POST /corpus/labels {label:"not_a_label"}     -> 422 (invalid label)
POST /corpus/labels {part_id:"nope"}          -> 404 (unknown part)
GET  /corpus/parts/0daa3505…  -> 200  labels:[{labeler, subtractive, ts, confidence:high, notes}]
GET  /corpus/progress         -> 200  labeled 0 -> 1, per_label_counts.subtractive=1
labels.jsonl                  -> the POSTed label landed as one appended line
last-write-wins               -> re-label same part additive; resolved label = "additive" ✓
```

A reviewer can therefore open `/label`, see a part in 3D, click a method, and see
it persisted to `data/labels.jsonl` (then reflected in `/progress`).

> The smoke is reproducible: `cd backend && LABELING_ENABLED=1 python -c "..."`
> using `fastapi.testclient.TestClient(main.app)`.

---

## 5. Honesty notes

- **Smoke-test labels were cleaned.** The smoke wrote test labels to
  `data/labels.jsonl`; these were **removed** so the human ground-truth store
  starts empty. No fabricated label is presented as human ground truth. (The
  pipeline-smoke seed is a *separate* file `data/labels.seed.jsonl` owned by the
  Eval builder, labeler `SMOKE_SEED`.)
- **Demo fallback used real parts only.** When the manifest was empty at the start
  of this build, `demo_seed.py` seeded 88 parts copied from the already-downloaded
  repo parts (Printables + ME7.5Duino GitHub, provenance in their `_manifest.csv`),
  with `license:"UNKNOWN"` and a `demo_fallback:true` flag — **no synthetic
  geometry**. The Corpus builder then populated the audited corpus (now ~253+ real
  parts across repo-parts datasets + Thingi10K), which supersedes the fallback
  (manifest has **0 duplicate part_ids**). The tool reads whatever manifest exists.
- **No auto-labeling / no circularity.** The tool never calls the routing engine to
  set a label. `process_family_guess` (if present in the manifest) is rendered only
  as an explicitly-tagged unverified heuristic and is never written as a label.
- **Dev-gated + local.** Corpus routes mount only under `LABELING_ENABLED=1` and
  carry no API-key/role auth (local single-operator tool); CAD is served from
  localhost only.

No blocks encountered. (`uvicorn` is absent from the venv, so the live-server smoke
used `TestClient` instead — this is a tooling detail, not a block: the same ASGI app
and routes are exercised, and any installed ASGI runner serves them in dev.)
