# CadVerify Cycle 4 — Validation-Auditor Report

**Role:** Cycle 4 Validation-Auditor (adversarial, run-it-myself). **Date:** 2026-06-28.
**Verdict:** **COMPLETE** — all 5 checks PASS. The ground-truth labeling system is REAL and HONEST.

Scope audited: corpus manifest + 667 mesh files, `outputs/c4-corpus-report.md`,
`outputs/c4-labeler-notes.md`, `outputs/c4-eval-report.md`, `data/labels.seed.jsonl`,
and the code in `backend/src/corpus`, `backend/src/eval`, `backend/src/api/corpus_router.py`,
`backend/main.py`, `frontend/src/app/label/*`, `frontend/src/lib/ontology.ts`.

I ran every claim myself (trimesh spot-loads, sha256 recompute, FastAPI TestClient smoke,
eval `--smoke` and real run, frontend `tsc`/`next build`, the 48-test costing suite +
representative API suite + the 15 eval tests). Where I touched state I used an isolated
temp data dir so the real ground-truth store was never polluted, and I restored the
`c4-accuracy.*` smoke outputs after exercising the real-mode run.

---

## CHECK 1 — CORPUS IS REAL + LICENSED — **PASS**

**What I tested.** Manifest-vs-disk count parity; sha256 integrity (`part_id` == sha256 of
stored bytes); trimesh spot-loads of random parts; geometry-field consistency vs the actual
mesh; presence of `source_url` + `license` on every record; source reachability; dedup;
honesty about blocked sources.

**Evidence.**
- `manifest.jsonl` = **667 records**, `data/corpus/meshes/` = **667 STL files**, **667 unique
  part_ids, 0 duplicates, 0 orphan files, 0 missing files**. (`667 == 667 == 667`.)
- sha256 recompute on a random sample: **10/10 `part_id` == sha256(file)**, 0 mismatches.
- trimesh spot-load (random 4): all load with real faces/verts, e.g. Thingi10K `919993.stl`
  (9416 faces, watertight) via `huggingface.co/.../raw_meshes/919993.stl`, and
  `github:AngelLM/Thor` Art3Body (34354 faces).
- Geometry-field consistency (random 8): recomputed `n_faces` + `watertight` **match the
  manifest exactly, 0 mismatches** — records describe the real bytes, not fabricated metadata.
- **source_url + license present on all 667** (0 empty). Reachability HEAD checks: Thingi10K
  HF mesh URL → **HTTP 200**, `github.com/AngelLM/Thor` → 200, `github.com/prusa3d/Original-Prusa-i3` → 200.
- Sources: Thingi10K 455 · existing repo parts 104 (Printables/Thangs/GitHub/GitLab/forum/Drive)
  · github AngelLM/Thor 40 · prusa3d/Original-Prusa-i3 38 · BCN3D/BCN3D-Moveo 30.
- Licenses: **563/667 (84%) carry an explicit open license** (CC-BY-SA 239, CC-BY 196,
  CC-BY-SA-4.0 40, GPL-2.0 38, MIT 30, GPL 13, CC0 5, BSD 1, Public-Domain 1). The **104
  UNKNOWN** are the pre-existing consumer-site repo parts, each honestly recorded as
  `UNKNOWN (... — see source_url)` with a real checkable URL — not guessed.
- Honesty trail (corpus report §5, corroborated): ABC dataset probed and **HTTP 401 gated**;
  STEP skipped (no local tessellation, cadquery absent); GrabCAD not used (login/ToS). Logged,
  never faked.

**No fabricated/synthetic parts found.** Every spot-checked record corresponds to a real,
hash-matching, trimesh-loadable mesh from a reachable openly-licensed source.

**Fix:** none required.

---

## CHECK 2 — NO AUTO-LABELS / NON-CIRCULAR — **PASS**

**What I tested.** Whether any engine-derived or auto-generated value is stored as a
ground-truth label; whether the smoke seed is clearly marked and excluded from real metrics;
whether `process_family_guess` is tagged as a heuristic, not a label.

**Evidence.**
- `data/labels.jsonl` (the human ground-truth store) is **absent → 0 human labels**. Honest:
  matches the eval report's headline ("0 human labels; accuracy NOT YET MEASURED").
- `data/labels.seed.jsonl` = **6 records, all `labeler:"SMOKE_SEED"`, `confidence:"smoke"`,
  `notes:"SMOKE — synthetic seed label, NOT human ground truth"`** — one per ontology key, all
  resolving to real corpus part_ids.
- `src/eval/seed.py::select_smoke_parts` **does not call the routing engine** — it picks parts
  by the `process_family_guess` heuristic (3 families) + arbitrary unused parts (rest). The
  labels are fabricated-and-clearly-marked, not engine-derived. Non-circular.
- `src/eval/labels.py::human_labels()` **drops `SMOKE_SEED` unconditionally** (verified in code
  and at runtime: the real `--` run reports `parts=0`). The seed is only reachable via the
  separate `smoke_labels()` used under `--smoke`.
- `process_family_guess` is stamped `"UNVERIFIED HEURISTIC — not a label, not for metrics"` in
  every manifest record; the API surfaces it only as a string and the `/label` UI renders it as
  *"Unverified heuristic guess … NOT a label, shown for context only."* It is never written as a
  label and never enters metrics.

**Fix:** none required.

---

## CHECK 3 — TOOL ACTUALLY RUNS — **PASS**

**What I tested.** Frontend `/label` builds/typechecks; backend serves a real STL by part_id and
persists a posted label to `labels.jsonl`; a human can label end-to-end.

**Evidence.**
- Frontend `npx tsc --noEmit` → **exit 0**. `npx next build` → **Compiled successfully**, route
  list includes **`○ /label`** (static). `CorpusViewer.tsx` **reuses the existing**
  `reconstruct/components/MeshCanvas.tsx` (`{ url: string }` STL-from-URL viewer) — no new viewer
  invented. `ontology.ts` exposes the **6 keys** matching the backend exactly.
- Backend smoke via FastAPI `TestClient` with `LABELING_ENABLED=1` (isolated temp data dir so the
  real store stayed empty):
  - `GET /api/v1/corpus/progress` → 200, `total_parts=667`, `labeled=0`.
  - `GET /api/v1/corpus/parts` → 200, returns parts with `mesh_url`, `label=null`,
    `process_family_guess` as a string.
  - `GET /api/v1/corpus/parts/{id}/mesh.stl` → **200, `content-type: model/stl`, `ETag`,
    `Cache-Control: public, max-age=3600`, 79384 real binary bytes.**
  - Path traversal `..%2f..%2fetc%2fpasswd` → **404**; unknown id → **404**.
  - `POST /api/v1/corpus/labels {subtractive}` → **200, appended one line to `labels.jsonl`**;
    invalid label → **422**; unknown part → **404**.
  - `/progress` then shows `labeled 0→1`, `per_label.subtractive=1`; re-labeling resolves
    **last-write-wins** (subtractive→additive).
- A human can therefore open `/label`, see a part in 3D, click a method (or press 1–6), and have
  it persisted to `data/labels.jsonl` and reflected in `/progress`.

**Fix:** none required.

---

## CHECK 4 — EVAL IS HONEST — **PASS**

**What I tested.** Eval runs on the smoke seed and produces a confusion matrix + similarity
example; real metrics are gated on human labels; the eval is non-circular.

**Evidence.**
- `python -m src.eval.run --smoke` ran end-to-end and emitted a **5×6 confusion matrix**
  (rows = SMOKE label, cols = engine family incl. `noRte`) plus a **k-NN similarity example**
  with explainable `shared` descriptors (e.g. `watertight, log_n_curved, log_bodies`). Outputs
  written to `outputs/c4-accuracy.{json,md}`.
- Gate banner printed: **`human-label gate: 0/30 (NOT MET — provisional only)`**; the headline
  accuracy is **withheld** and the matrix marked SMOKE/PROVISIONAL.
- Real-mode `python -m src.eval.run` (no `--smoke`) reads **only `data/labels.jsonl`** (seed
  excluded) → `parts=0` → empty matrix and **empty similarity pool** — it refuses to invent a
  metric. Honest.
- `src/eval` has **no network imports** (`grep` → none) and the engine routing is real while the
  labels are human-only → not circular. `src/eval/ontology.py` maps **all 21 ProcessTypes → 5
  families** with an import-time guard against enum drift; `family_of(None)` → `no_route`.
- `tests/test_eval_harness.py` → **15 passed** (covers quarantine of the seed, gate counter,
  confusion matrix, k-NN labeled-pool filter, last-write-wins).

**Fix:** none required.

---

## CHECK 5 — CAD-as-IP + NO REGRESSION — **PASS**

**What I tested.** Corpus/tool keep CAD local (no third-party egress at serve/label time); the
existing 48-test costing/API suite still passes; no prior functionality broken.

**Evidence.**
- **CAD-as-IP:** `data/` is gitignored — `git check-ignore` confirms `manifest.jsonl`,
  `meshes/`, `labels.jsonl`, `labels.seed.jsonl` all ignored; **`git ls-files data/` = 0
  tracked**. The corpus router streams `FileResponse` from local disk only; `src/eval` has no
  network code; corpus routes mount **only under `LABELING_ENABLED=1`** + localhost. No part
  data egresses to any third party at serve or label time.
- **No regression — full 48-test costing suite passes:**
  - `test_costing_model` → **14 passed**
  - `test_costing_accuracy` → **10 passed** (237s; analyzes real meshes)
  - `test_costing_gates` → **16 passed** (249s)
  - `test_cost_api` → **8 passed**
  - **Total = 48 passed.**
- Representative API suite: `test_api` + `test_require_api_key` + `test_frontend_api_config` →
  **17 passed**. New eval package: **15 passed**. The `main.py` change is gated behind
  `LABELING_ENABLED` (off by default), so default production behavior is unchanged.

**Fix:** none required.

---

## Auditor actions on shared state (disclosure)

- The backend label-POST smoke ran against an **isolated temp `CADVERIFY_DATA_DIR`** (manifest +
  2 meshes copied), so `data/labels.jsonl` was never created in the real tree — the ground-truth
  store remains **absent (0 human labels)**, which is the correct honest state.
- Exercising the **real-mode** eval run transiently overwrote `outputs/c4-accuracy.{json,md}` with
  the empty 0-human-label output; I re-ran `--smoke` to **restore** the smoke version that
  `c4-eval-report.md §3` describes.
- Temp audit data dir removed after the smoke.

## Decision

**COMPLETE.** No fabricated parts; no auto/engine label stored as ground truth; the tool runs
end-to-end (STL served, label persisted, last-write-wins); the eval is honest and gated, not
circular; and there is no regression (48 costing + 17 API + 15 eval tests green). The corpus's
honestly-disclosed additive skew and 104 UNKNOWN-license repo parts are limitations, not
violations — every part is real, hash-verified, and openly sourced or transparently flagged.
