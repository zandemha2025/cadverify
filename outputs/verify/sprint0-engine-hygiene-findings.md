# Sprint 0 — Engine Hygiene: Report-Only Findings

Branch `feat/engine-hygiene`. This document covers item 3 (a-d) of the engine-hygiene
task: four report-only investigations, no code changes. (Items 1 and 2 — dead-analyzer
deletion and the cost-persist observability fix — are separate code changes on this
same branch; see the builder report for their status.)

All investigations were run with throwaway probe scripts in the scratchpad
(`/private/tmp/.../scratchpad/{repair_efficacy_probe,dfm_regression_probe}.py`), driving
the *real* service/route code in this worktree — not reimplemented logic. The scripts
are not part of the deliverable and are not committed.

---

## 3a. Repair-route efficacy (Cost-S12)

**Honest scope caveat, stated up front:** this repo ships **no real (downloaded /
checked-in) CAD corpus**. Every fixture in `backend/tests/conftest.py` and
`backend/tests/test_repair_service.py` / `test_repair_endpoint.py` is a procedurally
generated trimesh primitive (a box with a couple of faces deleted). `backend/src/corpus/`
builds an evaluation corpus at runtime from an external source that isn't present in
this environment, and `test_eval_harness.py` / `test_step_corruption.py` are **skipped**
in this environment for exactly that reason ("real corpus manifest not present",
"cadquery not installed"). So there is no way to honestly report a "real-mesh" success
rate — there are no real meshes to run. What follows is the closest available proxy:
a deliberately more adversarial set of **procedurally generated** non-watertight meshes
(not just the single trivial "one face removed" fixture already in the test suite),
run through the **actual** `POST /api/v1/validate/repair` endpoint (`repair_service.repair_mesh`,
tier-1 `trimesh.repair.*` + tier-2 `pymeshfix.MeshFix`, both engines really invoked —
`pymeshfix` is installed in this venv) via `TestClient`, exactly the code path production
traffic hits.

**9 cases attempted, chosen to try to make repair *fail*, not to flatter it:**

| case | defect type | orig faces | tier used | result |
|---|---|---:|---|---|
| `box_single_face_removed` | 1 flat-face hole | 10 | trimesh (tier 1) | watertight |
| `box_multi_hole` | 4 scattered holes | 8 | pymeshfix (tier 2) | watertight |
| `sphere_patch_removed` | curved-surface hole (non-planar) | 308 | pymeshfix | watertight |
| `box_non_manifold_dup_face` | duplicated face → 3-face edge | 13 | pymeshfix | watertight |
| `overlapping_boxes_unbooleaned` | two overlapping solids concatenated (not booleaned) | 24 | trimesh | watertight* |
| `annulus_compound_defect` | hole + degenerate faces + flipped winding, on a cylinder | 253 | pymeshfix | watertight |
| `sphere_30pct_random_faces_removed` | 30% of faces removed at random | 239 | pymeshfix | watertight |
| `two_disjoint_shells` | box + a disjoint smaller box, one mesh | 24 | trimesh | watertight* |
| `sphere_80pct_faces_removed` | 80% of faces removed at random (near-total destruction) | 53 | pymeshfix | watertight |

**Result: 9/9 ended `is_watertight=True` after repair, all via the real endpoint** (`repair_applied: true` in every case).

**Caveats on that 9/9 (do not read as "repair never fails"):**
- All 9 are topologically simple / near-convex primitives (box, sphere, cylinder). `pymeshfix`
  is doing essentially all of the real work for anything past a single removed face — tier 1
  (`trimesh` built-in `fill_holes`) only closed the trivial single-hole case on its own.
  Real CAD parts with thin ribs, small internal features, or multi-body assemblies were not
  represented (again: no real corpus to draw them from).
- `*` `overlapping_boxes_unbooleaned` and `two_disjoint_shells` were meant as self-intersection /
  multi-shell adversarial cases, but `trimesh.is_watertight` only checks edge-manifoldness and
  winding consistency — it does **not** detect self-intersection or that a mesh is multiple
  disjoint solids. Both were already "watertight" by that (narrow) definition before repair ran,
  so they're not real evidence of repair robustness; they're evidence of a **detection gap**
  (worth a separate ticket: `NOT_SOLID_VOLUME` universal issue seems to catch some of this — it
  fired in an earlier probe — but "watertight" alone is not sufficient to certify manufacturability).
- A **tenth, orthogonal case** (`box_nan_vertex`: a corrupted vertex set to NaN, an analogue of a
  bad STEP tessellation) is a genuinely concerning finding: the pipeline did not crash (good), but
  it also did not detect/report the corruption. `is_watertight` was `True` **before and after**
  repair (NaN coordinates don't affect edge-topology checks), and tier-1 `nondegenerate_faces()`
  silently dropped the faces touching the NaN vertex — the reported `volume_mm3` changed from the
  correct 1000mm³ to 833.3mm³ with no warning surfaced anywhere in the response. This is tangential
  to "repair efficacy" strictly defined but directly relevant to trusting repair *output*: a
  topologically clean result can still be a silently wrong part. Flagging, not fixing (out of
  this item's scope).

**Bottom line:** on the *procedural* non-watertight cases available, the repair path's real success
rate is 9/9 (100%) for topologically-simple-primitive damage (holes, non-manifold duplicate faces,
severe random face loss). This is **not** the same claim as "S12 is closed" — it has not been tested
against a single real, professionally-modeled or STEP-tessellated part, because none exist in this
repo/environment. Recommend sourcing even a handful of real (e.g. GrabCAD/Thingiverse, license-checked)
broken STL/STEP files into a proper eval corpus before treating this as validated.

---

## 3b. Wright-curve M3 sub-scope

Audit finding (`outputs/audit/audit-cost.md:178-179`) defines **M3 — Volume & learning economics**
as four sub-components:
1. machining cycle-time reduction
2. labor learning curve
3. **dedicated-fixture/automation regimes**
4. **yield improvement with volume**

The shipped fix (`feat/cnc-volume`, merged; `backend/src/costing/cost_model.py::_learning_multiplier`,
documented in `outputs/impl/cnc-volume-note.md`) is a single **Wright cumulative-average learning
curve** (`mult(Q) = clamp((Q/Q_ref)**b, floor, 1.0)`) applied multiplicatively to **attended
conversion cost** (machine cycle time + post-process labor) for the subtractive (CNC) and
fabrication (sheet-metal) process families. Read in full:

- **Sub-component 1 (cycle-time reduction) — covered.** The multiplier is applied directly to
  `machine_cost` (`cost_model.py:281-283`).
- **Sub-component 2 (labor learning curve) — covered.** The same multiplier is applied to
  post-process labor cost (see `machine_learned`/labor cost lines around `cost_model.py:280-320`).
- **Sub-component 3 (dedicated-fixture/automation regimes) — NOT separately modeled; remains open.**
  "Dedicated fixturing/pallets" and "automation" are cited in the `_learning_multiplier` docstring
  (`cost_model.py:44-46`) and the impl note as *narrative justification for why a continuous curve
  is a reasonable model* — but there is no discrete regime-change mechanism anywhere in
  `backend/src/costing/`: no fixture NRE cost, no volume threshold at which the model switches rate
  cards or adds/removes a capex line for automation, no distinct cost structure for
  "manual fixturing" vs. "dedicated/automated fixturing." It is folded entirely into one smooth
  per-doubling multiplier. Grep confirms: `fixture`/`automation`/`dedicated tool`/`hard tool` appear
  **only** in that one docstring/prose spot and in `decision.py`'s hard-tooling framing (formative vs.
  make-now) — nothing computational.
- **Sub-component 4 (yield improvement with volume) — NOT modeled at all; remains open.** `scrap`
  (`backend/src/costing/rates.py`, e.g. lines 82-149) is a **static, per-process constant**
  (e.g. `scrap=0.10`, `scrap=0.05`, `scrap=0.03`) multiplied into material cost
  (`cost_model.py:230-236`: `material_cost = input_mass * price_per_kg * (1.0 + scrap)`). It does not
  vary with quantity anywhere in the codebase — no code path reduces scrap/yield as cumulative volume
  grows. Neither the impl note (`outputs/impl/cnc-volume-note.md`) nor the verify note
  (`outputs/verify/cnc-volume.md`) mentions "yield" or "scrap" at all — it wasn't explicitly descoped
  in writing, it's simply absent.

**Conclusion:** the shipped learning-curve work closes 2 of M3's 4 sub-components (cycle-time +
labor learning). Dedicated-fixture/automation regimes and volume-driven yield improvement are
**genuinely open** — not silently broken, just not attempted yet. Recommend tracking as a distinct
follow-up (a step-function fixture/automation cost break at a configurable volume threshold, and a
`scrap(qty)` curve analogous to `_learning_multiplier`) rather than assuming M3 is closed.

---

## 3c. DFM-value regression: `RAYCAST_SAMPLE_THRESHOLD` 50000 → 5000

**Why this matters:** `backend/src/analysis/context.py::_raycast_sample_threshold()` (default
lowered from 50000 to 5000 by the engine-memory-bound fix) decides whether per-face wall thickness
is computed by the **exact** per-face inward ray cast (`n_faces <= threshold`) or the **sampled +
KDTree-nearest-neighbor-propagated approximation** (`n_faces > threshold`). Draft-angle checks
(`ctx.angles_from_up_deg`) are **not** gated by this threshold at all — they come straight from face
normals (`context.py:172`), so they are an unaffected control in this test.

No real CAD corpus exists in this repo (see 3a) — meshes below are procedurally generated the same
way `backend/tests/test_engine_memory_bound.py` builds its face-count-targeted fixtures (box/cone
subdivision). No boolean backend (`manifold3d`/blender) is installed here, so a genuine thin-wall
hollow shell via CSG difference could not be constructed (`test_features.py` is skipped in this
environment for the same reason) — a solid tapered cone (thickness varies continuously along its
axis, unlike a box) was used as the best available proxy for a part with non-uniform wall thickness.

Ran `GeometryContext.build()` (the same context every process analyzer consumes) twice per mesh —
once with `RAYCAST_SAMPLE_THRESHOLD=50000`, once with `=5000` — on meshes sized into the affected
zone (>5000 faces, so old=exact / new=sampled):

| mesh | n_faces | wall_thickness_min OLD | wall_thickness_min NEW | Δ min | per-face max abs diff |
|---|---:|---:|---:|---:|---:|
| solid box (uniform thickness) | 12,288 | 39.99307180 | 39.99307180 | 0.0 | 0.0mm |
| solid box (uniform thickness) | 49,152 | 39.99307180 | 39.99307180 | 0.0 | 0.0mm |
| tapered cone (non-uniform, tip 1.24mm) | 32,768 | 1.24175378875 | 1.24175378876 | ~2e-9mm (fp noise) | **3.75mm (50.2% rel.)** |
| tapered cone, thinner tip (0.50mm, trips FDM's 0.8mm `THIN_WALL`) | 32,768 | 0.50070433223 | 0.50070433223 | **0.0 (bit-identical)** | not measured |
| control: box, 3,072 faces (below both thresholds either way) | 3,072 | 39.99307180 | 39.99307180 | 0.0 | 0.0mm |

Also re-ran the thin-tip cone through the real `FDM` process analyzer (`get_analyzer(ProcessType.FDM)`)
and compared the actual `THIN_WALL` issue emitted: **`measured_value` was bit-identical
(0.5007043322263518) under both thresholds.** Draft-angle deltas were `0.0` in every case, as expected
(unaffected control).

**Honest conclusion:**
- The **global minimum** wall thickness — the number that actually drives the `THIN_WALL`/`MIN_WALL_THICKNESS`
  pass/fail verdict and the value shown in the issue the customer sees — was **unchanged** (identical
  to ~9 decimal places, i.e. no practical difference) across every case tested, including a case
  engineered specifically to have non-uniform thickness. A verdict that flips because of this change
  was not observed.
- The **mean** wall thickness shifted by a negligible amount on the non-uniform mesh (21.380mm →
  21.407mm, ~0.13%) — not surfaced to users anywhere in the current API response.
- **Per-face values can diverge substantially** on non-uniform geometry (up to 50% relative, 3.75mm
  absolute, on the tapered cone) — because the sampled path imputes un-sampled faces from their
  nearest *sampled* neighbor via KDTree rather than measuring them directly. This only matters if/when
  a future feature consumes per-face thickness directly (a thickness heatmap, "show me exactly which
  faces are thin" region highlighting) — today's `Issue.affected_faces` / `measured_value` reporting
  is min-based and was not observed to change.
- This is 3 non-uniform-thickness samples (only one true non-uniform shape, tested at two tip
  thicknesses) plus 2 uniform controls — a small sample. It supports "no observed regression in the
  headline number" but is not exhaustive proof for all real geometry (e.g., a part with many separate
  local thin regions where the *specific* thin region identified, not just its magnitude, could matter).

---

## 3d. PDF smoke test in Docker

**SKIPPED.** No Docker (or Podman/Colima) is installed in this environment: `docker`, `podman`, and
`colima` are all "command not found," and there is no `/Applications/Docker.app`. Cannot build/run
the image to exercise WeasyPrint's system libs, which is exactly the gap `outputs/RESUME-HERE.md`
already flags as a non-blocking cleanup ("PDF binary needs Docker WeasyPrint libs"). The existing PDF
tests (`test_cost_persist_api.py::test_pdf_endpoint_contract`, `test_cost_pdf_template_is_honest`)
mock the WeasyPrint renderer and assert on the pre-render HTML instead — that coverage is real but is
explicitly not a substitute for an actual rendered-PDF smoke test. Recommend running this check in CI
(which does have Docker) or on a machine with Docker installed; it was not fabricated or approximated
here.
