# CadVerify Cycle 4 — Ground-Truth Labeling System: Architecture Spec

**Author:** Cycle-4 Architect
**Date:** 2026-06-28
**Status:** Build-ready. Three builders (Corpus, Tool, Eval) implement this with **zero open decisions.**

---

## 0. What we are building and why (read first)

The DFM engine today **routes** a part to a process family (3D print / CNC / injection
molding / sheet-metal / casting) using **unvalidated geometric heuristics**. We have
**never measured** whether those routes are correct. Cycle 4 builds the apparatus to:

1. **Collect** a diverse, real, openly-licensed CAD/mesh corpus (the existing 107 repo
   parts are almost all hobbyist 3D-printed automotive enclosures — additive-biased and
   not enough on their own).
2. **Label** each part's *true* manufacturing method **by a human** through a local tool.
3. **Measure** the engine's routing accuracy against those labels, and surface
   *"resembles these labeled parts"* as explainable k-NN evidence.

At this scale labels are for **EVALUATION + SIMILARITY**, not training a classifier.

### Hard rules every builder must honor (the Validation-Auditor enforces these)

- **REAL DATA ONLY.** Every corpus part is a genuine file downloaded from an
  openly-licensed, reachable source. **Never fabricate/synthesize geometry** and never
  present generated geometry as collected. Record per part: source URL, dataset, license,
  mesh sha256, geometry summary.
- **NO AUTO-LABELING.** The ground-truth `label` is **human-applied via the tool only.**
  Using the engine (or any guess) to fill `label` is **circular = fabrication = forbidden.**
  A geometry-derived `process_family_guess` MAY be stored **only** if tagged as an
  unverified heuristic, **never** as a label, and **never** used to compute real metrics.
- **CAD-as-IP / local.** Corpus + tool are local. Parts are streamed to the viewer from
  `localhost` only. No part data egresses to any third party. The only network use is
  *gathering downloads into the corpus.*
- **HONESTY.** Report exactly what was gathered, from where, counts, licenses, and what
  was blocked. On any block write `BLOCKED: <reason>` to
  `/Users/nazeem/Desktop/developer/cadverify/outputs/c4-<role>-log.md` and stop — never
  fake a count or a run.

---

## 1. Verified environment facts (do not re-discover)

| Fact | Value |
|---|---|
| Repo root | `/Users/nazeem/Desktop/developer/cadverify` |
| Python | `/Users/nazeem/Desktop/developer/cadverify/backend/.venv/bin/python` (3.9.6) |
| trimesh | 4.11.5 installed |
| `huggingface_hub` | **NOT installed** — gatherer uses plain `https` (curl/requests) OR `pip install huggingface_hub` |
| cadquery | **NOT installed** — **STL only**; STEP cannot be tessellated locally (see §2.4) |
| Engine import root | `from src...` with cwd=`backend` (or `backend` on `sys.path`) |
| Backend app | `backend/main.py`; routers mounted via `app.include_router(...)`; API prefix `/api/v1` |
| Frontend | Next.js 16 + React 19 + Three.js at `frontend/`; `node_modules` present |
| Reusable STL viewer | `frontend/src/app/(dashboard)/reconstruct/components/MeshCanvas.tsx` — loads STL **from a URL** via `STLLoader`; this is what `/label` reuses |
| Frontend API base | `frontend/src/lib/api-base.ts` → `API_BASE = http://localhost:8000/api/v1` in dev |
| Existing 107 parts | `/private/tmp/claude-501/-Users-nazeem-Desktop-developer-cadverify/3182c9c6-e59b-4394-a584-d9c4cd4ce0dc/scratchpad/parts` (+ `_manifest.csv`); also `ecu_automotive_batch2.zip` |

### 1.1 The canonical engine routing sequence (verified from `backend/src/api/routes.py`)

This is the **only** sanctioned way to obtain the engine's routing pick. The eval harness
and the (optional) `process_family_guess` MUST go through it verbatim:

```python
import src.analysis.processes  # noqa: F401  — populates the @register analyzer registry
from src.analysis.base_analyzer import analyze_geometry, run_universal_checks
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all as detect_features
from src.matcher.profile_matcher import rank_processes, score_process
from src.analysis.processes.base import get_analyzer
from src.analysis.processes import base as pbase
from src.analysis.models import AnalysisResult

geometry = analyze_geometry(mesh)                      # GeometryInfo
ctx = GeometryContext.build(mesh, geometry)
ctx.features = detect_features(mesh)                   # list[Feature]
universal = run_universal_checks(mesh)
scores = [
    score_process(get_analyzer(p).analyze(ctx), geometry, p)
    for p in pbase._REGISTRY
    if get_analyzer(p)
]
result = AnalysisResult(
    filename=filename, file_type="stl", geometry=geometry,
    segments=ctx.segments, universal_issues=universal, process_scores=scores,
)
ranked = rank_processes(result)                        # sorted desc by score
# CRITICAL: rank_processes returns the sorted list but does NOT set best_process.
result.best_process = ranked[0].process if ranked and ranked[0].score > 0 else None
```

**Gotcha (load-bearing):** `rank_processes()` only sorts; it leaves
`result.best_process = None`. The caller must set `best_process = ranked[0].process` when
`ranked[0].score > 0`, else `None`. The eval harness MUST replicate this or every part
reads as "no route." (This mirrors `validate_demo` in `routes.py`.)

**Second gotcha:** `analyze_geometry` sets `volume = 0.0` when the mesh is **not
watertight** (many Thingi10K meshes are not). So `volume_cm3` in the manifest is `0.0`
for non-watertight parts — that is expected, record it as-is and rely on `watertight`.

### 1.2 ProcessType → label-family mapping (the single source of truth for eval)

`ProcessType` (21 values, from `backend/src/analysis/models.py`) collapses to the **6-button
ontology** as follows. The engine never emits `unsure_other`.

| Label key (ontology) | Button text | Engine `ProcessType` members |
|---|---|---|
| `additive` | **3D Print** | fdm, sla, dlp, sls, mjf, dmls, slm, ebm, binder_jetting, ded, waam |
| `subtractive` | **CNC Machining** | cnc_3axis, cnc_5axis, cnc_turning, wire_edm |
| `injection_molding` | **Injection Molding** | injection_molding, die_casting |
| `sheet_metal` | **Sheet Metal / Stamping** | sheet_metal |
| `casting` | **Casting** | investment_casting, sand_casting, forging |
| `unsure_other` | **Unsure / Other** | *(label only — never an engine output)* |

Builders MUST implement this as a single shared constant
`backend/src/eval/ontology.py::FAMILY_OF: dict[ProcessType, str]` and a parallel
`LABELS: list[str]` (the 6 keys). The frontend mirrors the same 6 keys (§5.3).

> Note the engine's internal 3-family taxonomy (ADDITIVE/SUBTRACTIVE/FORMATIVE) is **not**
> the eval taxonomy: FORMATIVE splits into injection_molding / sheet_metal / casting here.

---

## 2. CORPUS — layout, manifest schema, dedup

### 2.1 Storage layout (gitignored)

```
data/                              # gitignored (see §2.6)
  corpus/
    meshes/                        # all normalized STL files live here, flat
      <sha256>.stl                 # filename IS the part_id (mesh sha256) + .stl
    manifest.jsonl                 # one JSON record per line, one per part (append-only)
    features.npz                   # similarity vectors (written by eval, §6.2)
  labels.jsonl                     # human labels (append-only, §3)
  labels.seed.jsonl                # TINY smoke seed, clearly marked (§6.3) — NOT ground truth
```

Root constant: `CORPUS_ROOT = <repo>/data/corpus`, `MESH_DIR = CORPUS_ROOT/meshes`,
`MANIFEST = CORPUS_ROOT/manifest.jsonl`, `LABELS = <repo>/data/labels.jsonl`.
Define once in `backend/src/corpus/paths.py` and import everywhere (env override
`CADVERIFY_DATA_DIR` allowed, default `<repo>/data`).

### 2.2 Manifest record schema (one JSON object per line in `manifest.jsonl`)

```jsonc
{
  "part_id":      "9e12d4...e0d9c",      // REQUIRED. sha256 hex of the RAW stored STL bytes. Primary key.
  "filename":     "100027.stl",           // original source filename (provenance, display)
  "rel_path":     "meshes/9e12d4...e0d9c.stl",  // path relative to CORPUS_ROOT
  "source_url":   "https://huggingface.co/datasets/Thingi10K/Thingi10K/resolve/main/raw_meshes/100027.stl",
  "dataset":      "Thingi10K",            // dataset/source name (see §2.5 source table)
  "license":      "CC-BY-4.0",            // per-part license string; "UNKNOWN" only if truly unrecoverable
  "original_format": "stl",               // stl|obj|ply|off|glb  (what we downloaded before normalizing)
  "downloaded_at": "2026-06-28T20:11:03Z",
  "n_faces":      270,                     // len(mesh.faces)
  "volume_cm3":   0.0,                     // round(GeometryInfo.volume/1000, 3); 0.0 when not watertight
  "bbox_mm":      [51.0, 55.0, 142.8],     // GeometryInfo.bounding_box.dimensions, rounded 1dp
  "watertight":   false,                   // bool(mesh.is_watertight)
  "process_family_guess": {                // OPTIONAL, may be omitted. NEVER a label.
      "family": "additive",                //   one of the 5 manufacturable label keys
      "source": "heuristic_v1",            //   tag proving it is NOT human, NOT engine-routing
      "note":   "UNVERIFIED HEURISTIC — not a label, not for metrics"
  }
}
```

**Field rules**
- `part_id` = `hashlib.sha256(stored_stl_bytes).hexdigest()`. Compute on the **final
  normalized STL bytes** that land in `meshes/` (so re-running is reproducible).
- `volume_cm3`, `bbox_mm`, `watertight`, `n_faces` come from the canonical
  `analyze_geometry(mesh)` (§1.1) — do **not** invent a second geometry path.
- `process_family_guess` is **optional and clearly tagged.** See §2.7 for the exact
  heuristic. It exists for coverage dashboards only.

### 2.3 Dedup

- **Primary:** by `part_id` (sha256 of normalized bytes). Before writing a part, scan the
  in-memory set of known `part_id`s; **skip exact duplicates.** The gatherer keeps a
  `seen: set[str]` and never appends a duplicate manifest line.
- **Optional near-dup guard** (recommended, not required): also key on
  `(round(volume_cm3, 1), n_faces)`; if collision, log and skip. This catches the same
  model re-exported. Mark skips in the gatherer log.

### 2.4 Normalize-to-STL rules

| Source format | Action |
|---|---|
| `.stl` | Keep bytes as-is → hash → store. |
| `.obj`, `.ply`, `.off`, `.glb`/`.gltf` | `trimesh.load(...)`, force a single `Trimesh` (`mesh = trimesh.util.concatenate(mesh.dump())` if it loads as a `Scene`), `mesh.export(buf, file_type="stl")` (binary), then hash the exported bytes → store. Record `original_format`. |
| `.step`/`.stp` | **SKIP.** cadquery is not installed; there is no local tessellation path. Log `BLOCKED: STEP source <url> requires cadquery (not installed) — skipped` and move on. **Do not** fabricate a mesh. |

- **Units:** assume mm. Record `detect_units(mesh)` (`backend/src/analysis/base_analyzer.py`)
  in the gatherer log if it != "mm", but **do not rescale** — rescaling guesses corrupt
  provenance. The bbox is stored in source units.
- **Sanity gate:** drop (and log) any mesh with `len(mesh.faces) == 0` or that trimesh
  fails to load. Optionally cap absurd sizes (e.g. faces > 2_000_000) to keep the viewer
  responsive — log every drop.

### 2.5 Gatherer plan — ranked, openly-licensed, reachability-verified sources

All reachability HEAD/GET-probed on 2026-06-28 (HTTP code shown). Be polite: timeouts
(15–25 s), modest counts per source, no login, no ToS-forbidden scraping.

| # | Source | Why / what it adds | How to fetch | Reachable | Bounded target |
|---|---|---|---|---|---|
| 1 | **Thingi10K** (HF dataset `Thingi10K/Thingi10K`) | 10k real meshes, broad geometry diversity, **per-object licenses** (CC0/CC-BY/CC-BY-SA + some NC). PRIMARY. | List tree `GET https://huggingface.co/api/datasets/Thingi10K/Thingi10K/tree/main/raw_meshes` (paginate via `?cursor=`); download each `…/resolve/main/raw_meshes/<id>.stl`. Licenses from the `metadata/` dir (per-file license field). | `200`; sample STL `100026.stl` verified = real 270-face mesh | ~600–900, stratified across size buckets (see balancing §2.6) |
| 2 | **Existing repo 107 parts** | Already downloaded; Printables + `ME7.5Duino` GitHub; automotive ECU enclosures. Provenance in `_manifest.csv`. | Copy STLs from the parts dir; map `_manifest.csv` columns `source`→`dataset`, fill `license` from source (Printables = per-model; GitHub = repo LICENSE). | local | ~100 (note: **additive-biased**, flag it) |
| 3 | **Permissive GitHub STL repos** (open-hardware: brackets, fixtures, cast housings, turned parts) | Targets under-represented families: **sheet_metal, casting, subtractive**. | Hand-pick repos with a clear MIT/Apache/CC `LICENSE`; `GET` raw `.stl` blobs via `raw.githubusercontent.com`. Record repo URL + license. Modest counts/repo. | repo probes `200` (e.g. prusa3d, grbl org repos) | ~150–300, spread across families |
| 4 | **ABC CAD dataset subset** (mechanical CAD) | Mechanical/engineered parts (CNC/molding-shaped) to counter the hobbyist bias. | Public ABC chunk archives over `https` if a permissive, login-free mirror is reachable. HF mirrors probed were **gated (`401`)** → if no open mirror resolves, **log `BLOCKED:` and skip.** STEP entries are skipped per §2.4 unless an OBJ/mesh variant exists. | HF mirrors `401` (gated) | stretch; 0 acceptable if unreachable |
| 5 | **Objaverse** (`allenai/objaverse`, CC-BY) | Huge; mostly artistic/consumer — low signal for manufacturing. OPTIONAL last resort only if a mechanical filter is applied. | HF resolve URLs. | `200` | optional, ≤100, mechanical only |

**Target & floor.** Build a **balanced few-hundred → ~1500** parts maximizing geometry
diversity across the ontology. **Hard floor: ~300** real parts or the corpus is too small
to be useful — if you cannot reach 300 from reachable sources, write `BLOCKED:` with the
count you *did* reach and stop (do not pad with fabricated parts).

### 2.6 Balancing (avoid re-creating the additive bias) — without circularity

Balance by **source/geometry diversity**, NOT by the engine's own routing. Concretely:
- Stratify Thingi10K downloads across **bbox-diagonal size buckets** and **face-count
  buckets** (small/medium/large) so we don't pull 800 tiny trinkets.
- Use the lightweight `process_family_guess` (§2.7) only as a **coverage dashboard** to see
  which families look thin, then deliberately add GitHub repos (#3) for those families.
- Cap any single guessed family at **≤ 40%** of the corpus so additive can't dominate.
- **Do NOT** select/drop parts using the engine's `best_process` — that would bias the very
  sample the eval measures (selection bias toward "engine is right"). Balancing is by
  source and raw geometry buckets only.

### 2.7 `process_family_guess` heuristic (optional field) — explicit, independent of the engine

To avoid circularity with the eval, the guess uses a **simple, documented, independent**
heuristic (NOT the routing engine). Tag `source: "heuristic_v1"`. Builder implements
exactly this in `backend/src/corpus/guess.py`:

```
sheet-ish  : bbox has one dim << other two (min_dim / median_dim < 0.12) AND watertight-thin
             -> "sheet_metal"
turned/round: cross-section near-circular (a Thingi/feature cue: many CYLINDER_* features,
             1 dominant axis) -> lean "subtractive"
blocky/solid: high volume/convex-hull-volume (solidity > 0.6) AND few thin walls -> "subtractive"
shelled/thin: many faces, low solidity, thin median wall -> "additive"
default     : "additive"
```

This is **best-effort and admittedly weak** — that's the point; it is for coverage only and
is stamped `"UNVERIFIED HEURISTIC — not a label, not for metrics"`. If a builder prefers to
omit the field entirely, that is allowed.

### 2.8 gitignore

Append to `<repo>/.gitignore` (this spec already applies it):

```
# Cycle 4 — local corpus + human labels (CAD-as-IP, never committed)
data/
```

---

## 3. LABEL STORE — `data/labels.jsonl` (append-only)

One JSON object per line, **append-only**. Last-write-wins per `(part_id, labeler)`,
resolved at read time (scan file, keep the last record for each pair).

```jsonc
{
  "part_id":   "9e12d4...e0d9c",   // REQUIRED, must exist in manifest
  "label":     "subtractive",       // REQUIRED, one of the 6 ontology keys (§1.2)
  "labeler":   "nazeem",            // REQUIRED, who labeled (free string / email)
  "ts":        "2026-06-28T21:04:55Z",  // REQUIRED, ISO-8601 UTC, server-set on POST
  "confidence":"high",              // OPTIONAL: "low"|"medium"|"high" (or 0..1 float)
  "notes":     "clear draft + parting line"  // OPTIONAL free text
}
```

- **Append-only:** never rewrite earlier lines. A correction is a new appended line.
- **Resolution:** `effective_labels = {}` then for each line in order
  `effective_labels[(part_id, labeler)] = line`. Aggregate a part's label across labelers
  by majority (eval uses a configurable `--labeler` filter or majority; default majority).
- The smoke seed lives in a **separate** file `data/labels.seed.jsonl` with
  `labeler == "SMOKE_SEED"` so it can never contaminate real metrics (§6.3).

---

## 4. BACKEND endpoints (local/dev only — keeps CAD local)

New router file: **`backend/src/api/corpus_router.py`**
`router = APIRouter(prefix="/api/v1/corpus", tags=["corpus-labeling"])`.

**Mounting (dev-gated, prod-safe).** In `backend/main.py`, mount **only** when the dev flag
is set, so the labeling surface never ships to production and no CAD egresses:

```python
if os.getenv("LABELING_ENABLED") == "1":
    from src.api.corpus_router import router as corpus_router
    app.include_router(corpus_router)
```

**Auth:** this is a **local single-operator tool**, so these routes **do not** use
`require_api_key`/`require_role` (unlike `routes.py`). They are protected by (a) the
`LABELING_ENABLED` env gate and (b) running on `localhost`. The labeler identity is taken
from the request (`labeler` field / `X-Labeler` header), defaulting to
`os.getenv("LABELER", "local")`. Match the existing FastAPI style otherwise (APIRouter,
Pydantic models, `HTTPException`). Rate limiting is **not** applied (local tool).

### 4.1 `GET /api/v1/corpus/parts` — paginated corpus list

Query: `offset:int=0`, `limit:int=50` (max 200), `unlabeled_only:bool=false`,
`labeler:str|None` (whose labels to overlay / filter by).

Reads `manifest.jsonl` (cache in memory, reload if file mtime changed). Overlays the
resolved label for `labeler` (or majority if `labeler` omitted). Returns:

```jsonc
{
  "total": 742, "offset": 0, "limit": 50,
  "labeled": 30, "unlabeled": 712,
  "parts": [
    {
      "part_id": "...", "filename": "100027.stl",
      "dataset": "Thingi10K", "license": "CC-BY-4.0",
      "n_faces": 270, "volume_cm3": 0.0, "bbox_mm": [51,55,142.8],
      "watertight": false,
      "process_family_guess": "additive",      // or null
      "label": "subtractive",                    // resolved for `labeler`, or null
      "mesh_url": "/api/v1/corpus/parts/<part_id>/mesh.stl"
    }
  ]
}
```

When `unlabeled_only=true`, return only parts with no label for `labeler`.

### 4.2 `GET /api/v1/corpus/parts/{part_id}/mesh.stl` — stream one STL

- Look up `part_id` in manifest → `rel_path`. **Path-safety:** resolve
  `(CORPUS_ROOT / rel_path).resolve()` and assert it is inside `CORPUS_ROOT.resolve()`
  (reject traversal); 404 if not in manifest or file missing.
- Return `FileResponse(path, media_type="model/stl", filename=f"{part_id}.stl")` with
  `headers={"ETag": part_id, "Cache-Control": "public, max-age=3600"}`. (`part_id` is a
  content hash, so it is a perfect immutable ETag — the viewer can cache aggressively.)
- This is the URL `MeshCanvas` loads (§5).

### 4.3 `GET /api/v1/corpus/parts/{part_id}` — one record + its labels

Returns the manifest record plus all resolved labels for the part:
`{ ...manifest_fields, "labels": [{labeler, label, ts, confidence, notes}, ...] }`.
404 if unknown.

### 4.4 `POST /api/v1/corpus/labels` — record a human label

Body (Pydantic `LabelIn`): `{ part_id, label, labeler?, confidence?, notes? }`.
- Validate `part_id` exists in manifest → else 404.
- Validate `label in LABELS` (the 6 keys) → else 422.
- `labeler = body.labeler or request.headers.get("X-Labeler") or env LABELER or "local"`.
- Server sets `ts = datetime.now(timezone.utc).isoformat()`.
- **Append** one line to `data/labels.jsonl` (open `"a"`, write `json.dumps(rec)+"\n"`,
  flush). Never mutate prior lines.
- Return `{ "ok": true, "part_id": ..., "label": ..., "labeler": ..., "ts": ... }`.

### 4.5 `GET /api/v1/corpus/progress` — labeling progress

Query: `labeler:str|None`. Returns:

```jsonc
{
  "total_parts": 742,
  "labeled": 30, "unlabeled": 712,
  "per_label_counts": { "additive": 12, "subtractive": 6, "injection_molding": 4,
                        "sheet_metal": 3, "casting": 3, "unsure_other": 2 },
  "per_guess_counts": { "additive": 410, "subtractive": 220, ... },  // coverage view
  "labelers": ["nazeem"]
}
```

`labeled/unlabeled` and `per_label_counts` are filtered to `labeler` when given, else
computed over the majority-resolved labels. The smoke-seed file is **excluded** here.

---

## 5. FRONTEND `/label` route

### 5.1 Files

| Path | Purpose |
|---|---|
| `frontend/src/app/label/page.tsx` | The labeling page (client component). NEW. |
| `frontend/src/app/label/CorpusViewer.tsx` | Thin `dynamic(() => import(...MeshCanvas), {ssr:false})` wrapper. NEW (≈8 lines). |
| **reuse** `frontend/src/app/(dashboard)/reconstruct/components/MeshCanvas.tsx` | **The existing STL-from-URL Three.js viewer — do NOT write a new one.** |
| **reuse** `frontend/src/lib/api-base.ts` → `API_BASE` | Backend base URL. |

> Reuse is literal: `CorpusViewer` imports the existing `MeshCanvas` and passes
> `url={`${API_BASE}/corpus/parts/${partId}/mesh.stl`}`. `MeshCanvas` already does
> `useLoader(STLLoader, url)`, auto-fit camera, OrbitControls, wireframe overlay — no
> changes needed. Wrap in `dynamic(..., {ssr:false})` exactly like `MeshPreview.tsx` does.

### 5.2 Page behavior

State: `parts[]` (fetched from `GET /corpus/parts?unlabeled_only=true&limit=200`),
`index`, `progress`. On mount, fetch the unlabeled queue and `GET /corpus/progress`.

Layout (reuse Tailwind classes already in the repo):
- **Left ~70%:** `<CorpusViewer partId={current.part_id} />` (the STL viewer).
- **Right ~30%:** part metadata (filename, dataset, license, n_faces, bbox, watertight,
  `process_family_guess` shown **explicitly labeled "engine guess — not a label"**), the 6
  ontology buttons, a confidence selector (low/med/high), a notes `<textarea>`,
  prev/next/skip buttons, and a progress counter `labeled / total`.

The 6 buttons (in this fixed order, with keyboard shortcuts):

| Key | Label key | Button text |
|---|---|---|
| `1` | `additive` | 3D Print |
| `2` | `subtractive` | CNC Machining |
| `3` | `injection_molding` | Injection Molding |
| `4` | `sheet_metal` | Sheet Metal / Stamping |
| `5` | `casting` | Casting |
| `6` | `unsure_other` | Unsure / Other |

Interactions:
- Pressing a button or its number key → `POST /corpus/labels`
  `{part_id, label, labeler, confidence, notes}` → on success advance to next part,
  reset confidence/notes, bump progress.
- `←` / `→` or Prev/Next buttons navigate without labeling. `s` or **Skip** advances
  without writing a label.
- Keyboard handler on `window` (`keydown`): digits `1–6` label, arrows navigate, `s` skip.
  Ignore keystrokes while the notes textarea is focused.
- `labeler` comes from a small input at top (default `nazeem@anodeadvisory.com` or env),
  sent as the `labeler` field.

Networking: use `fetch` against `API_BASE` (the same pattern as
`frontend/src/app/page.tsx`). No auth header needed (local dev tool). The viewer streams
STL bytes straight from `localhost:8000` — **CAD never leaves the machine.**

### 5.3 Shared ontology constant (frontend)

`frontend/src/lib/ontology.ts`: `export const ONTOLOGY = [{key:"additive",text:"3D Print",hot:"1"}, ...]`
mirroring §1.2 exactly so the buttons and the backend agree on the 6 keys.

---

## 6. EVAL + SIMILARITY harness

New package: **`backend/src/eval/`** with `ontology.py` (§1.2), `engine.py` (canonical
sequence wrapper §1.1), `routing_accuracy.py`, `similarity.py`, and a CLI
`python -m src.eval.run` (run from `backend/`). Writes reports to
`/Users/nazeem/Desktop/developer/cadverify/outputs/`.

### 6.1 Routing-accuracy harness

Input: corpus `manifest.jsonl` + resolved human labels (`labels.jsonl`, excluding
`SMOKE_SEED`). For each part **that has a human label in {additive, subtractive,
injection_molding, sheet_metal, casting}** (skip `unsure_other` and unlabeled):

1. Load STL from `meshes/<part_id>.stl` with trimesh.
2. Run the **canonical sequence (§1.1)** → `best_process` (with the `score>0` rule).
3. `engine_family = FAMILY_OF[best_process]` (or `"no_route"` if `best_process is None`).
4. Compare `engine_family` vs human `label`.

Outputs (JSON `outputs/c4-accuracy.json` + human `outputs/c4-accuracy.md`):
- **top-1 accuracy** = correct / labeled-manufacturable.
- **per-family confusion matrix** — rows = true human label (5), cols = engine family
  (5 + `no_route`); counts.
- **per-family precision/recall** derived from the matrix.
- **mis-route list**: `[{part_id, filename, true_label, engine_best_process,
  engine_family, engine_score, top3:[{process,score}], dataset, license}]` — the actionable
  "where the engine is wrong" artifact.
- **coverage line**: N labeled, per-label counts, how many `no_route`.

### 6.2 k-NN similarity ("resembles these labeled parts")

**Feature vector** — fully specified, scale-aware, ~18 dims, computed in the **same engine
pass** as routing (reuse `geometry`, `ctx`, `ctx.features`). Define in
`backend/src/eval/similarity.py::feature_vector(mesh, geometry, ctx) -> np.ndarray`.

Let sorted bbox dims `d1>=d2>=d3` (mm), `diag = sqrt(d1²+d2²+d3²)`,
`hullV = mesh.convex_hull.volume` (robust even when not watertight),
`A = geometry.surface_area`, `wt = ctx.wall_thickness[isfinite]` (median `mw`),
features split by `FeatureKind`:

| # | Component | Formula | Scale-free? |
|---|---|---|---|
| 1 | elongation | `d2/d1` | yes |
| 2 | flatness | `d3/d1` | yes |
| 3 | squareness | `d3/d2` | yes |
| 4 | solidity | `clip(abs(mesh.volume)/hullV, 0, 1)` (use hull ratio; 0 if hullV≈0) | yes |
| 5 | compactness | `A / diag²` | yes |
| 6 | rel wall | `clip(mw/diag, 0, 1)` (median wall over diagonal) | yes |
| 7 | log faces | `log10(max(n_faces,1))` | size proxy |
| 8 | log diag | `log10(max(diag,1e-3))` | size proxy |
| 9 | watertight | `1.0` if watertight else `0.0` | flag |
| 10 | log bodies | `log1p(body_count)` | yes |
| 11 | genus proxy | `clip((2 - euler_number)/2, -5, 5)` | yes |
| 12 | log n_holes | `log1p(count CYLINDER_HOLE)` | yes |
| 13 | log n_bosses | `log1p(count CYLINDER_BOSS)` | yes |
| 14 | log n_flats | `log1p(count FLAT)` | yes |
| 15 | log n_curved | `log1p(count CURVED)` | yes |
| 16 | flat area frac | `sum(area of FLAT feats)/A` | yes |
| 17 | curved area frac | `sum(area of CURVED feats)/A` | yes |
| 18 | largest flat frac | `max(area of FLAT feats)/A` (0 if none) | yes |

Non-finite/failed components → `0.0` (never NaN). Persist the matrix to
`data/corpus/features.npz`: `part_ids:(N,)`, `X:(N,18)` raw, `mean:(18,)`, `std:(18,)`
(std with `+1e-9`), `dims:list[str]`. Build over **all** corpus parts (labeled + unlabeled).

**Metric:** **z-score standardize** each dim with the persisted `mean/std`, then **Euclidean
(L2)** distance (equivalently diagonal-Mahalanobis). `python -m src.eval.similarity
--part <part_id> --k 8` (or `--stl <path>` for a new part: hash → if in corpus reuse vector,
else compute vector, z-score with stored `mean/std`) returns the `k` nearest **labeled**
parts:

```jsonc
{ "query": "<part_id or path>",
  "neighbors": [
    {"part_id":"...","label":"subtractive","distance":0.81,"dataset":"Thingi10K",
     "shared":["solidity","largest_flat_frac"]}, ...
  ] }
```

`shared` = the 2–3 dims where query and neighbor are closest (smallest |z-diff|) — this is
the **explainable** "resembles because both are blocky with a dominant flat face" evidence.

### 6.3 Gating + smoke seed (honesty)

- **Real metrics are gated on human labels.** The harness counts human labels (labeler !=
  `SMOKE_SEED`) in the 5 manufacturable classes. If `< 30`, it still runs end-to-end but
  prints a banner `INSUFFICIENT HUMAN LABELS (n=<n> < 30) — PIPELINE SMOKE ONLY, NOT GROUND
  TRUTH` and refuses to emit a headline accuracy number (writes the confusion matrix marked
  PROVISIONAL). Threshold `MIN_HUMAN_LABELS=30` is a CLI flag.
- **Smoke seed** lives in `data/labels.seed.jsonl`, every line `labeler:"SMOKE_SEED"`,
  e.g. 6 parts (one per ontology key) chosen from the corpus. It exists **only** to exercise
  the pipeline (prove load→route→compare→report works). The harness loads it **only** under
  `--smoke` and tags every output `SMOKE — synthetic seed labels, NOT human ground truth`.
  Seed labels are **never** mixed into real-metric runs and never counted toward the gate.

---

## 7. Build order & ownership (so three builders never collide)

| Builder | Owns | Produces | Depends on |
|---|---|---|---|
| **Corpus** | §2 | `backend/src/corpus/` (paths, gather, normalize, guess), `data/corpus/meshes/*.stl`, `manifest.jsonl`, gatherer log | §1.1, §1.2 constants |
| **Tool** | §4 + §5 | `backend/src/api/corpus_router.py`, `main.py` mount, `frontend/src/app/label/*`, `frontend/src/lib/ontology.ts` | manifest schema (§2.2), label schema (§3) |
| **Eval** | §6 | `backend/src/eval/` (ontology, engine, routing_accuracy, similarity, run), `outputs/c4-accuracy.{json,md}`, `features.npz`, `data/labels.seed.jsonl` | manifest (§2.2), labels (§3), engine seq (§1.1) |

Shared contracts that all three import (define **once**, in Eval's `backend/src/eval/ontology.py`,
re-exported as needed): `LABELS` (6 keys), `FAMILY_OF` (ProcessType→family), and the canonical
engine wrapper. Frontend mirror in `frontend/src/lib/ontology.ts`.

---

## 8. Acceptance checklist

- [ ] Corpus dir `data/corpus/meshes/` holds **≥300** real STLs; `manifest.jsonl` has one
      record per part with every required field; dedup by sha256; `data/` is gitignored.
- [ ] Every manifest record has a real `source_url`, `dataset`, `license`, `part_id`
      (=sha256), and geometry summary from `analyze_geometry`. No fabricated parts.
- [ ] `process_family_guess`, if present, is tagged `heuristic_v1` and never used as a label
      or in metrics.
- [ ] `labels.jsonl` append-only; last-write-wins per `(part_id, labeler)`; smoke seed in a
      separate file with `labeler="SMOKE_SEED"`.
- [ ] Backend: `GET /corpus/parts` (paginated), `GET /corpus/parts/{id}/mesh.stl` (streamed,
      path-safe), `GET /corpus/parts/{id}`, `POST /corpus/labels`, `GET /corpus/progress`;
      mounted only under `LABELING_ENABLED=1`; CAD served from localhost only.
- [ ] Frontend `/label` reuses `MeshCanvas`; 6 buttons + keys 1–6; confidence + notes;
      prev/next/skip; progress counter; calls the endpoints above.
- [ ] Eval: routing top-1 + 5×(5+1) confusion matrix + mis-route list; k-NN over the
      18-dim z-scored L2 feature vector returning nearest **labeled** parts with `shared`
      descriptors; real metrics gated on ≥30 human labels; smoke seed clearly marked.
- [ ] All blocks (STEP sources, gated ABC mirrors, sub-300 corpus) logged as
      `BLOCKED: <reason>` — never faked.
```
