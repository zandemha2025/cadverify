# Cycle 4 — EVAL + SIMILARITY Harness Report

**Author:** Eval builder
**Date:** 2026-06-28
**Status:** Built & runs end-to-end. **All numbers here are SMOKE-ONLY** — real
routing-accuracy metrics are **gated on human labels** (none exist yet).

> **HEADLINE HONESTY STATEMENT.** The DFM engine's real routing accuracy is
> **NOT YET MEASURED.** `data/labels.jsonl` currently holds **0 human labels**.
> Everything below was produced by running the pipeline against a TINY, clearly
> quarantined **SMOKE seed** (`data/labels.seed.jsonl`, labeler `SMOKE_SEED`) whose
> labels are *synthetic and fabricated* purely to prove the plumbing works. The
> harness **refuses to emit a headline accuracy number** until ≥ 30 human labels
> exist, and the smoke seed is **never** counted toward that gate or mixed into a
> real run. See "Regenerating real metrics" at the end.

---

## 1. What this harness does (spec §6)

Two capabilities, both consuming the local corpus (`data/corpus/manifest.jsonl`,
667 real parts) + the human label store (`data/labels.jsonl`):

1. **Routing accuracy** — for each *human-labeled* part, run the engine's canonical
   routing sequence, map `best_process` to its ontology **family**, and compare it
   to the human label. Outputs top-1 accuracy, a 5×(5+1) confusion matrix, per-family
   precision/recall, and a ranked **mis-route list** ("where the engine is wrong").
2. **k-NN similarity** — an 18-dim, scale-aware geometry feature vector per part,
   z-score standardized and compared by Euclidean (L2) distance, returning a query
   part's nearest **labeled** neighbours plus the 2–3 `shared` descriptors that
   explain the match ("resembles these labeled parts because both are blocky with a
   dominant flat face").

At this corpus scale, labels are for **EVALUATION + SIMILARITY**, never for training
a classifier.

### Non-circularity / honesty guarantees baked into the code

- **No auto-labeling.** This package never *writes* a manufacturing label. It only
  reads `data/labels.jsonl` (human-applied via the labeling tool). Using the engine
  to fill a ground-truth label would be circular fabrication — forbidden, and not done.
- **Smoke seed quarantined.** `labels.py::human_labels()` drops every record whose
  labeler is `SMOKE_SEED`; the seed is loadable only through the separate
  `smoke_labels()` function, used only under `--smoke`.
- **Gate.** Until ≥ `MIN_HUMAN_LABELS` (default 30) human labels exist in the 5
  manufacturable classes, the run prints `INSUFFICIENT HUMAN LABELS … PIPELINE SMOKE
  ONLY` and withholds the headline accuracy (confusion matrix marked PROVISIONAL).
- **Zero network egress.** The eval package has no network imports; it reads local
  STL/JSONL only. (Verified: `grep -rn 'requests|urllib|http|socket' src/eval` → none.)

---

## 2. Architecture (`backend/src/eval/`)

| Module | Responsibility |
|---|---|
| `ontology.py` | **Single source of truth.** `LABELS` (6 keys), `MANUFACTURABLE` (5), `FAMILY_OF: dict[ProcessType,str]` (all 21 ProcessTypes → 5 families), `family_of()` (`None`→`no_route`). Fails at import if a new ProcessType is unmapped. |
| `engine.py` | Canonical routing wrapper (spec §1.1) — verbatim `validate_demo` sequence, including the load-bearing `best_process = ranked[0].process if ranked[0].score>0 else None` rule. `geometry_pass()` exposes the shared cheap half (geometry+ctx+features) so a part is analyzed once. |
| `labels.py` | Manifest loader, last-write-wins label resolution per `(part_id, labeler)`, majority across labelers, `human_labels()` (seed-excluded), `smoke_labels()`, gate counter. **Read-only — never writes a label.** |
| `routing_accuracy.py` | `evaluate({part_id:label})` → confusion matrix, precision/recall, ranked mis-routes. |
| `similarity.py` | `feature_vector()` (18 dims, never NaN), resumable/checkpointing `build_feature_matrix()`, atomic `save_features`/`load_features` (`features.npz`), `knn()` (z-scored L2, labeled-pool filter, `shared` descriptors), CLI. |
| `seed.py` | Deterministically writes the TINY smoke seed (one part per ontology key, labeler `SMOKE_SEED`). Does **not** use the routing engine (would be circular). |
| `run.py` | CLI orchestrator + report rendering; owns the gate + smoke banners. |

**Data flow (one part, analyzed once):**
`STL → trimesh.load → analyze_geometry → GeometryContext.build → detect_all`
→ (a) per-process analyzers + `score_process` + `rank_processes` → `best_process`
→ `FAMILY_OF` → compare to human label;  and (b) `feature_vector` → z-score → L2 k-NN.

### Engine ProcessType → family map (`ontology.FAMILY_OF`, spec §1.2)

`additive` ← fdm/sla/dlp/sls/mjf/dmls/slm/ebm/binder_jetting/ded/waam ·
`subtractive` ← cnc_3axis/cnc_5axis/cnc_turning/wire_edm ·
`injection_molding` ← injection_molding/die_casting ·
`sheet_metal` ← sheet_metal ·
`casting` ← investment_casting/sand_casting/forging.
`unsure_other` is a human-only label the engine never emits; an engine `None` maps to
the `no_route` confusion column.

### The 18-dim similarity feature vector (`similarity.DIMS`, spec §6.2)

Sorted bbox dims `d1≥d2≥d3`, `diag=√(d1²+d2²+d3²)`, `hullV=convex_hull.volume`,
`A=surface_area`, `mw=median(finite wall_thickness)`:

1 elongation `d2/d1` · 2 flatness `d3/d1` · 3 squareness `d3/d2` · 4 solidity
`|vol|/hullV` · 5 compactness `A/diag²` · 6 rel-wall `mw/diag` · 7 log10 faces ·
8 log10 diag · 9 watertight flag · 10 log1p bodies · 11 genus proxy
`(2−euler)/2` · 12–15 log1p counts of CYLINDER_HOLE / CYLINDER_BOSS / FLAT / CURVED ·
16 flat-area frac · 17 curved-area frac · 18 largest-flat frac. Non-finite/failed
components → `0.0` (never NaN). Persisted to `data/corpus/features.npz`
(`part_ids`, raw `X`, `mean`, `std+1e-9`, `dims`); **metric = z-score then L2**
(= diagonal-Mahalanobis). k-NN candidates are restricted to **labeled** parts.

---

## 3. SMOKE run output (`python -m src.eval.run --smoke`)

> **SMOKE — synthetic seed labels, NOT human ground truth.** The smoke seed assigns
> one fabricated label per ontology key to 6 real corpus parts solely to exercise
> load→route→compare→report. `unsure_other` is not scored (5 manufacturable rows).
> The engine routing is real; the *labels* are fake, so "correctness" here is
> meaningless — the point is only that the pipeline runs.

### Confusion matrix (rows = true SMOKE label, cols = engine family)

```
true \ engine   addtv  subtr  injmo  sheet  cast   noRte   | total
------------------------------------------------------------------
additive            1      0      0      0      0      0   | 1
subtractive         1      0      0      0      0      0   | 1
injection_molding   1      0      0      0      0      0   | 1
sheet_metal         1      0      0      0      0      0   | 1
casting             0      1      0      0      0      0   | 1
```

Observation (expected, not a metric): on these 6 arbitrarily-chosen parts the engine
routes almost everything to **additive** — consistent with the known additive bias
of the engine + the additive-heavy corpus. This is *exactly* the kind of skew the
real (human-labeled) eval is built to quantify.

Gate banner emitted by the run:
`INSUFFICIENT HUMAN LABELS (n=0 < 30) — PIPELINE SMOKE ONLY, NOT GROUND TRUTH`.
Headline accuracy is **withheld**; raw plumbing fraction = 1/5 (PROVISIONAL/SMOKE).

### k-NN similarity example

Query part (a real corpus part, **not** in the label pool):
`023e1210… (macchina_m2_M2R3_CASE_TOP_UTD.STL)`. Neighbour pool = the 6 SMOKE
seed labels. Nearest labeled parts by z-scored L2 distance:

| rank | neighbor part_id | label | distance | shared descriptors |
|---|---|---|---|---|
| 1 | `0012f6a9f15c` | additive | 2.994 | watertight, log_n_curved, log_bodies |
| 2 | `01b094f4fc70` | casting | 3.997 | watertight, curved_area_frac, log_bodies |
| 3 | `01094739dae3` | sheet_metal | 4.633 | watertight, log_n_curved, curved_area_frac |
| 4 | `0204c16ec9ac` | subtractive | 5.356 | watertight, log_n_curved, log_bodies |
| 5 | `0109832a6889` | injection_molding | 6.336 | watertight, log_n_curved, curved_area_frac |
| 6 | `01f0ad149235` | unsure_other | 7.834 | log_n_curved, curved_area_frac, squareness |

Reading: the query "resembles" the additive seed part most closely because both are
watertight, similarly curved, and single-body — the `shared` column is the
explainable evidence, exactly the "resembles these labeled parts because…" surface.

> **Feature-matrix note.** The above z-scoring used the on-the-fly bounded sample the
> harness builds when the persisted matrix is absent (it auto-falls-back so `--smoke`
> always runs). The full-corpus `data/corpus/features.npz` (all 667 parts) is built
> by the **resumable, checkpoint-every-25** job `python -m src.eval.run
> --build-features` (it persisted in 25-part increments while this report was
> written). Re-running `python -m src.eval.run --smoke` (or the similarity CLI) after
> that job completes refreshes the example with full-corpus mean/std — the code path,
> neighbours, and `shared` evidence are identical; only the standardization
> population changes. A standalone check against the (partial) persisted matrix:
> `python -m src.eval.similarity --smoke --part <id> --k 5` returns the same shape of
> result (verified).

Machine-readable copies of the above are written to
`outputs/c4-accuracy.json` and `outputs/c4-accuracy.md` on every run.

---

## 4. Tests

`backend/tests/test_eval_harness.py` — **15 tests, all passing**
(`python -m pytest tests/test_eval_harness.py -q` → `15 passed`). They run on
*procedural* meshes + a *temporary* 4-part corpus (no dependency on the gitignored
local corpus) and cover:

- ontology maps every `ProcessType`; the 6 keys + `no_route` sentinel round-trip;
- the engine wrapper sets `best_process` with the `score>0` rule; `geometry_pass`
  attaches features;
- the feature vector is shape-(18,) and finite even on a degenerate single triangle;
- `build_feature_matrix` + `save/load` round-trip; k-NN ranks by L2, excludes the
  query, and filters to the labeled pool; `shared` descriptors are valid dim names;
- label resolution is last-write-wins and **quarantines the smoke seed** out of
  `human_labels()`; the gate counter ignores `unsure_other`;
- `evaluate` builds a well-formed confusion matrix + precision/recall; mis-routes
  are ranked by engine confidence;
- the full `run.py` orchestrator: `--smoke` writes both outputs, flags the gate as
  unmet, and proves `human_labels()` stays empty while `smoke_labels()` is populated;
  a real-mode run with injected human labels passes the gate, drops the banner, and
  produces a k-NN example drawn only from the labeled pool.

The wider suite still collects cleanly (`489 tests collected`), so adding
`src/eval` broke nothing.

---

## 5. Real metrics are PENDING human labels — how to regenerate

The real, ungated routing accuracy is produced the moment humans have labeled enough
parts. There is **no code change** required — only labels.

1. Run the labeling tool and label parts (the Tool builder's `/label` page → backend
   `POST /api/v1/corpus/labels` → appends to `data/labels.jsonl`, append-only).
2. Once **≥ 30** parts carry a manufacturable human label, from `backend/`:
   ```bash
   python -m src.eval.run --build-features   # one-time; builds data/corpus/features.npz (resumable)
   python -m src.eval.run                     # REAL, ungated metrics → outputs/c4-accuracy.{json,md}
   ```
   - The non-`--smoke` run reads **only** `data/labels.jsonl` (seed excluded) and,
     once the gate is met, prints the real top-1 accuracy + confusion matrix and
     drops the SMOKE/PROVISIONAL banners.
   - `--labeler <name>` scores one labeler's labels; default is majority across
     labelers. `--min-human-labels N` adjusts the gate.
3. Inspect a part's similarity neighbours directly:
   ```bash
   python -m src.eval.similarity --part <part_id> --k 8     # nearest labeled parts
   python -m src.eval.similarity --stl /path/new.stl --k 8  # new part: hash→reuse/compute vector
   ```

`features.npz` (the heavy build) is **resumable + checkpointing**: it persists every
25 parts and a restart reuses already-computed rows, so the one-time full-corpus
build survives interruption.

---

## 6. Deliverable files

- Code: `backend/src/eval/{__init__,ontology,engine,labels,routing_accuracy,similarity,seed,run}.py`
- Tests: `backend/tests/test_eval_harness.py` (15 passing)
- Smoke seed: `data/labels.seed.jsonl` (labeler `SMOKE_SEED`, quarantined; gitignored)
- Feature matrix: `data/corpus/features.npz` (gitignored)
- Machine reports: `outputs/c4-accuracy.json`, `outputs/c4-accuracy.md`
- This report: `outputs/c4-eval-report.md`

All corpus + label artifacts live under the gitignored `data/` (CAD-as-IP, local
only). No part data egresses anywhere.
