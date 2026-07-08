# Verify — Item 3: Cap engine memory (arch audit P0 — 19 GB OOM)

**Verdict: CLOSED + PRODUCTION-WORTHY → MERGED to prod** (after one route-back for an honesty gap).
Branch `feat/engine-memory` (builder 0dee207 + honesty fix 26205c3). RAYCAST_SAMPLE_THRESHOLD 50000→5000, batched memory-bounded ray casting, ingest decimation >250k faces, MAX_TRIANGLES=2M hard-refuse retained.

## The finding (closed)
`GeometryContext.build` allocated ~19 GB on an ordinary 37k-face part (per-face pure-Python ray casting; the sample-threshold guard was backwards). OOM-killed the web machine on the first real upload.

## Evidence
- **Memory bound — PROVEN directly by the orchestrator:** 20,480-face sphere **12,181 MB (OLD) → 300 MB (NEW)** — a 40× reduction on the exact mesh class that OOM'd; 81,920 faces → **496 MB**. Real finite wall thickness computed for **every** face (not a garbage stub).
- **Correctness verifier (high conf):** batched ray-casting is **byte-identical** to the unbatched reference across batch sizes (no off-by-one in scatter-min index mapping); vertex-cluster decimation fallback (the real path — quadric libs absent) reduces faces, stays watertight, preserves volume, zero degenerate faces; `detect_features(mesh)→detect_features(ctx.mesh)` is a **true no-op for normal parts** (identity confirmed) and correct when decimated; all 16 costing gates pass, no severity flips.
- **Full-suite gate:** 560 passed / 0 failed (initial) → **563 passed / 0 failed / 7 skipped** (after honesty fix; +3 decimation tests).

## Route-back (honesty gap — the #1 rule) — RESOLVED
Initial verify found a lying-stub violation: decimation was recorded in `ctx.metadata` but **never surfaced to the user**, and code comments falsely claimed "labelled accordingly / no silent lying." Routed back; builder fixed it:
- A user-visible universal `Issue` `DECIMATED_MESH` (severity warning) now flows into `universal_issues` in all 4 GeometryContext-building paths (authed `/validate`, demo, cost `_run_cost_engine`, CLI). **Reproduced independently:** 327,680-face mesh → metadata `{original_faces:327680, analysis_faces:230186, strategy:vertex_cluster}` → warning "Analyzed on a decimated mesh: 327,680→230,186 faces (vertex_cluster). Wall-thickness, draft-angle and other DFM values are approximate…". Normal part (<250k) → no warning (no false positive). Builder also proved it via TestClient → HTTP 200 with the warning in `universal_issues`.
- The false comments (context.py:149, 406-410) reworded to describe the now-implemented labeling.
- Cosmetic numpy RuntimeWarning suppressed on the routes/service path.

## Flagged for the Zoox gate (not self-certified)
Lowering `RAYCAST_SAMPLE_THRESHOLD` 50000→5000 expands the KDTree-propagated sampled wall-thickness path to most real CAD (5k–50k faces). Verifier measured **tail error up to ~567% relative at wall-thickness discontinuities** (a thin rib adjacent to a thick boss can inherit the wrong value → possible missed/false thin-wall flag). The sampled algorithm itself is correct; its domain expanded 10×. Correctness within DFM tolerance is a Zoox-gated question — documented, not self-certified.

Merged: feat/engine-memory → dev → prod.
