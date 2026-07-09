"""Assembly P3 — context-fed per-part analysis on a real extracted assembly.

The single-part engine analyzes ONE part in isolation. P1 gave us the assembly as
structured geometry (``AssemblyModel``: per-part world-coord meshes + baked
positions + the product tree). THIS module makes that assembly an INPUT to real
analysis, TRUE BLUE — every number comes from the SAME engine ``/validate`` and
``/validate/cost`` run, never a stub:

  1. **Per-part makeability + should-cost.** For EACH part we run the EXISTING
     single-part DFM + should-cost engine on ``part.mesh`` — the SAME path the
     single-part routes use (``routes._run_cost_engine`` -> ``analyze_geometry`` /
     feature detection / process scoring, then ``costing.estimate_decision`` ->
     ``report_to_dict``). Costing is NOT reimplemented here; we call it. A part that
     fails to analyze (a degenerate fastener mesh, an engine error) yields an HONEST
     per-part ``error`` — it never breaks the whole assembly and never fakes a
     number.

  2. **Real per-part quantity from the product tree.** Instances of each unique
     design are counted from the extracted tree (``AssemblyModel.unique_designs``)
     -> the REAL quantity that design appears in THIS assembly (AS1: 8 nuts, 6
     bolts, 2 l-brackets, 1 rod, 1 plate). That per-assembly count is a FACT and is
     fed to the cost engine as the real volume signal. Annual volume still needs an
     assemblies-per-year figure, which stays USER-declared (``assemblies_per_year``)
     — the FACT/assumption boundary is surfaced, never blurred.

  3. **Real clearance / interference (pure geometry).** For part pairs whose
     bounding boxes overlap we run a REAL mesh-level check on the world-positioned
     ``.mesh`` objects: vertex containment (``trimesh.Trimesh.contains``, embree ray
     casting) for interpenetration + a ``scipy.cKDTree`` nearest-vertex gap for
     surface contact. This flags GEOMETRIC overlap/contact — for fasteners (a bolt
     through a hole, a nut on a thread) overlap is EXPECTED, not a defect. It is
     labelled "geometric contact/interference" and is NEVER asserted to be a fault;
     it is a real signal an engineer reads, not a verdict.

Bounds (never unbounded, always honest when a bound bites):
  * per-part analysis is dispatched to a bounded thread pool AND capped at
    ``MAX_ASSEMBLY_ANALYZE_PARTS`` with a wall-clock DEADLINE derived from
    ``ANALYSIS_TIMEOUT_SEC``; parts past the cap/deadline are reported "not
    analyzed (N of M)", never silently dropped and never faked.
  * interference is bbox-prefiltered and capped at ``MAX_INTERFERENCE_PAIRS``; the
    ``closest_point`` surface query is deliberately NOT used (it is ~6 s/pair —
    it would blow the budget); the fast containment + KD-tree signals are.

Honesty boundaries (surfaced verbatim in the response ``boundaries`` block):
  * material_class is a DEFAULT ASSUMPTION — AP203/AP214 geometry carries no
    material; a per-part material is a future labelled tier, not derived here.
  * derived service-world-from-role is NOT built here (a future labelled
    SUGGESTION tier).
  * interface-DFM (which faces mate) + GD&T tolerance stack-up need AP242 + a
    B-rep kernel (OCP) — a GATED tier, clearly labelled, NOT faked.
"""
from __future__ import annotations

import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutTimeout
from typing import Optional

import numpy as np

logger = logging.getLogger("cadverify.assembly_analysis")


# ── Bounds (env-overridable, always finite) ─────────────────────────────────
def _max_analyze_parts() -> int:
    try:
        return max(1, int(os.getenv("MAX_ASSEMBLY_ANALYZE_PARTS", "200")))
    except ValueError:
        return 200


def _max_interference_pairs() -> int:
    try:
        return max(1, int(os.getenv("MAX_INTERFERENCE_PAIRS", "4000")))
    except ValueError:
        return 4000


def _analyze_workers() -> int:
    """Bounded thread-pool width for the per-part cost loop. The cost engine is
    numpy-heavy (releases the GIL), so a small pool genuinely overlaps the parts;
    cost is per-part CPU, so we cap independently of core count."""
    try:
        env = os.getenv("ASSEMBLY_ANALYZE_WORKERS")
        if env:
            return max(1, int(env))
    except ValueError:
        pass
    return max(1, min(4, (os.cpu_count() or 2)))


# Surfaced verbatim in every analysis response so a hardcore engineer sees the
# line between FACT, DEFAULT assumption, SUGGESTION, and GATED tier.
_BOUNDARIES = {
    "quantity": (
        "REAL FACT: the per-part quantity is the true instance count of that "
        "design in THIS assembly, counted from the extracted product tree. It is "
        "fed to the cost engine as the real per-assembly volume signal."
    ),
    "annual_volume": (
        "USER-DECLARED: annual volume = per-assembly quantity × assemblies_per_year. "
        "assemblies_per_year is not in the geometry; unset => cost is reported at the "
        "per-assembly quantity only (the honest FACT), never an invented annual figure."
    ),
    "material_class": (
        "DEFAULT ASSUMPTION: AP203/AP214 geometry carries no material. The costed "
        "material_class is a stated default (overridable), not derived from the part. "
        "A per-part material inference is a future labelled tier."
    ),
    "interference": (
        "REAL GEOMETRY, NOT A VERDICT: overlap/contact is measured on the world-"
        "positioned meshes (vertex containment + nearest-vertex gap). For fasteners "
        "(bolt through a hole, nut on a thread) this overlap is EXPECTED and is NOT "
        "asserted to be a fault — it is a signal an engineer reads."
    ),
    "service_world": (
        "NOT BUILT HERE (future SUGGESTION tier): inferring a part's service world "
        "(exterior/internal) from its role/position would be a labelled suggestion the "
        "user confirms, never a fabricated fact."
    ),
    "interface_dfm_and_gdt": (
        "GATED TIER (needs AP242 + a B-rep kernel / OCP): which faces MATE with a "
        "neighbour (interface-DFM) and tolerance STACK-UP are not reconstructable "
        "from this triangulated extraction and are NOT faked here."
    ),
}


# ── Per-part quantity from the product tree ─────────────────────────────────
def _design_key(part) -> str:
    """The design a part instance belongs to. AP203 names each unique design once
    (``bolt``, ``nut``, …); sibling occurrences share the name. Grouping by name is
    exactly how ``AssemblyModel.unique_designs`` counts instances, so per-part
    quantity here === that count (kept consistent by construction)."""
    return part.name


def _quantities_by_design(model) -> dict[str, int]:
    """design name -> real instance count in THIS assembly (the FACT). Mirrors
    ``model.unique_designs`` but recomputed from the parts so the two never drift."""
    counts: dict[str, int] = {}
    for p in model.parts:
        counts[_design_key(p)] = counts.get(_design_key(p), 0) + 1
    return counts


# ── Per-part DFM + should-cost (REUSES the single-part engine) ──────────────
def _dfm_summary(result, material_class: str, prefer: Optional[list[str]] = None) -> dict:
    """Compact DFM view built from the SAME ``AnalysisResult`` the ``/validate``
    route serializes — the verdict, the best process, and the top issues. Not a
    reimplementation: ``result`` came straight out of ``_run_cost_engine``.

    ``best_process`` is MATERIAL-AWARE here (Fix 1+2): chosen only among processes
    makeable in ``material_class`` and, on a tie at the top DFM score, biased
    toward ``prefer`` (the cost make-now + the geometric routing pick) so the DFM
    headline AGREES with — or is a sane sibling of — the dollar route. A steel/
    aluminum bolt can therefore never show a resin "best process": that was the
    material-blind bug where resin/powder won purely on having the fewest geometry
    constraints, floating a "best: DLP Resin" above a "make-now: CNC Turning".
    """
    from src.matcher.profile_matcher import best_process_for_material

    issues = list(result.universal_issues)
    best_pt = best_process_for_material(result, material_class, prefer=prefer)
    best_proc = best_pt.value if best_pt is not None else None
    # Surface the most severe issues first (error before warning before info).
    _rank = {"error": 0, "warning": 1, "info": 2}
    top = sorted(
        issues,
        key=lambda i: _rank.get(getattr(i.severity, "value", str(i.severity)), 3),
    )[:5]
    return {
        "verdict": result.overall_verdict,
        "best_process": best_proc,
        "best_process_basis": (
            f"most-manufacturable process makeable in the "
            f"'{material_class}' material class (material-aware DFM)"
        ),
        "issue_count": len(issues),
        "top_issues": [
            {
                "code": i.code,
                "severity": getattr(i.severity, "value", str(i.severity)),
                "message": i.message,
            }
            for i in top
        ],
    }


def _compact_estimates(rd: dict) -> list[dict]:
    """The should-cost numbers, compacted from ``report_to_dict``'s estimates —
    the real per-quantity unit cost + DFM readiness, kept lean for an 18-part
    response. The full glass-box engine ran; this is its headline table."""
    out: list[dict] = []
    for e in rd.get("estimates") or []:
        out.append({
            "process": e.get("process"),
            "material": e.get("material"),
            "quantity": e.get("quantity"),
            "unit_cost_usd": e.get("unit_cost_usd"),
            "fixed_cost_usd": e.get("fixed_cost_usd"),
            "variable_cost_usd": e.get("variable_cost_usd"),
            "est_error_band_pct": e.get("est_error_band_pct"),
            "dfm_verdict": e.get("dfm_verdict"),
            "lead_time": e.get("lead_time"),
        })
    return out


# ── COTS / standard-hardware detection (Fix 3) ──────────────────────────────
# Catalog BUY-price estimates for standard off-the-shelf fasteners. These are
# labelled DEFAULT/estimate catalog ranges (McMaster/Fastenal-class, common
# sizes & grades, single-unit price) — NOT a live quote and NOT derived from the
# geometry. Provenance is surfaced honestly so a buyer never mistakes them for a
# vendor quotation. (point_usd, (low_usd, high_usd)).
_COTS_CATALOG: dict[str, tuple[float, tuple[float, float]]] = {
    "bolt":     (0.75, (0.20, 3.00)),
    "screw":    (0.30, (0.05, 1.50)),
    "nut":      (0.20, (0.05, 1.00)),
    "washer":   (0.05, (0.01, 0.30)),
    "stud":     (1.00, (0.30, 5.00)),
    "rivet":    (0.10, (0.02, 0.60)),
    "dowel":    (0.30, (0.05, 2.00)),
    "pin":      (0.30, (0.05, 2.00)),
    "standoff": (0.60, (0.15, 3.00)),
    "spacer":   (0.40, (0.10, 2.00)),
    "fastener": (0.50, (0.10, 3.00)),
}

# Longest keywords first so "cap screw"/"machine screw"/"hex bolt" bind before a
# bare token; each maps to a catalog kind above.
_COTS_NAME_TOKENS: list[tuple[str, str]] = [
    ("machine screw", "screw"), ("cap screw", "screw"), ("set screw", "screw"),
    ("hex bolt", "bolt"), ("hex nut", "nut"), ("lock nut", "nut"),
    ("lock washer", "washer"), ("flat washer", "washer"),
    ("bolt", "bolt"), ("screw", "screw"), ("nut", "nut"), ("washer", "washer"),
    ("stud", "stud"), ("rivet", "rivet"), ("dowel", "dowel"),
    ("standoff", "standoff"), ("spacer", "spacer"),
    ("fastener", "fastener"),
]

# A geometry-only fastener is SMALL. Absolute cap in mm on the largest bounding-box
# extent — a real M-hardware fastener is well under this; a bracket/plate is not.
_COTS_MAX_DIM_MM = 60.0


def classify_cots_fastener(name: str, occurrence: str, features=None,
                           max_dim_mm: Optional[float] = None) -> Optional[dict]:
    """Detect a standard off-the-shelf fastener (buy, not make).

    Two honest signals (name/occurrence match AND/OR small threaded geometry):
      * NAME/OCCURRENCE token match {bolt, nut, screw, washer, stud, …} — the
        strong, high-confidence signal (AP203 names the design, e.g. "bolt").
      * GEOMETRY: a SMALL part (largest extent < ~60mm) that ALSO carries a
        detected THREAD feature — a medium-confidence signal for hardware the
        product tree did not name. A small part with NO thread is NOT flagged
        (a small bracket is not a fastener).

    Returns a COTS block (kind, confidence, detected_by, catalog buy-price with
    provenance + honesty note) or None. Never invents a fault; a COTS part still
    gets its full should-cost as the in-house fabrication upper-bound.
    """
    hay = f"{name or ''} {occurrence or ''}".lower()
    kind = None
    detected_by = None
    confidence = None
    for token, mapped in _COTS_NAME_TOKENS:
        # Word-boundary match so 'pin' does not fire on 'spindle', 'nut' on
        # 'walnut', 'washer' on 'washerless' — only a real fastener token counts.
        if re.search(r"\b" + re.escape(token) + r"\b", hay):
            kind = mapped
            detected_by = f"product/occurrence name matches '{token}'"
            confidence = "high"
            break

    if kind is None:
        # Geometry-only path: small AND threaded => generic fastener.
        has_thread = False
        if features:
            for f in features:
                ftype = getattr(getattr(f, "kind", None), "value", None) \
                    or getattr(getattr(f, "feature_type", None), "value", None)
                if ftype == "thread":
                    has_thread = True
                    break
        if has_thread and max_dim_mm is not None and max_dim_mm <= _COTS_MAX_DIM_MM:
            kind = "fastener"
            detected_by = (
                f"geometry: small threaded solid (largest extent "
                f"{max_dim_mm:.1f}mm ≤ {_COTS_MAX_DIM_MM:.0f}mm with a detected thread)"
            )
            confidence = "medium"

    if kind is None:
        return None

    point, (low, high) = _COTS_CATALOG.get(kind, _COTS_CATALOG["fastener"])
    return {
        "is_cots": True,
        "kind": kind,
        "confidence": confidence,
        "detected_by": detected_by,
        "recommendation": "BUY — standard off-the-shelf fastener; do not machine in-house",
        "buy_price_usd": point,
        "buy_price_range_usd": [low, high],
        "buy_price_provenance": "DEFAULT",
        "note": (
            "Standard off-the-shelf fastener — BUY, not make. The buy-price is a "
            "labelled catalog estimate (McMaster/Fastenal-class, common size/grade, "
            "single-unit; provenance DEFAULT), NOT a live quote. The should-cost "
            "figures below are the fabrication UPPER-BOUND if this were machined "
            "in-house — they are not the recommended cost for a catalog part."
        ),
    }


def analyze_one_part(
    part,
    *,
    quantity: int,
    cost_quantity: int,
    material_class: str,
    region: str,
) -> dict:
    """Run the EXISTING single-part DFM + should-cost engine on ONE part's mesh.

    Reuses ``routes._run_cost_engine`` (DFM/geometry/features) and
    ``costing.estimate_decision`` -> ``report_to_dict`` (the make-vs-buy should-
    cost) — the identical path ``/validate`` + ``/validate/cost`` take. Costing is
    NOT reimplemented. Any failure (degenerate mesh, engine error) is caught and
    returned as an HONEST per-part ``error`` so one bad fastener never breaks the
    assembly and never fabricates a number.
    """
    base = {
        "id": part.id,
        "name": part.name,
        "tree_path": part.tree_path,
        "quantity": quantity,
        "world_volume_mm3": round(float(part.world.volume), 2),
        "bbox_size_mm": [round(float(d), 2) for d in part.world.bbox_size],
    }
    mesh = getattr(part, "mesh", None)
    if mesh is None or len(getattr(mesh, "faces", [])) == 0:
        base["error"] = {
            "code": "NO_MESH",
            "message": (
                "No per-part mesh available (metadata-only or empty tessellation); "
                "DFM + should-cost require geometry."
            ),
        }
        return base
    try:
        # Lazy import: the engine helper lives in the route module. Imported here
        # (not at module load) so this service never creates an import cycle.
        from src.api.routes import _run_cost_engine
        from src.costing import EstimateOptions, estimate_decision, report_to_dict

        result, m, features = _run_cost_engine(mesh, f"{part.name}.step")
        options = EstimateOptions(
            quantities=[int(cost_quantity)],
            material_class=material_class,
            material_class_is_user=(material_class != "polymer"),
            region=region,
            region_is_user=(region != "US"),
        )
        report = estimate_decision(result, m, features, options)
        rd = report_to_dict(report)

        # COTS / standard-hardware detection (Fix 3). Small-threaded geometry uses
        # the part's largest world extent + the engine's detected features.
        max_dim = max((float(d) for d in part.world.bbox_size), default=0.0)
        cots = classify_cots_fastener(
            part.name, getattr(part, "occurrence", "") or "",
            features=features, max_dim_mm=max_dim,
        )

        # Prefer the cost make-now + the geometric routing pick when breaking a
        # DFM-score tie for best_process, so the DFM headline agrees with the
        # dollar route (Fix 2). Order matters: make-now first.
        dec = rd.get("decision") or {}
        routing = rd.get("routing") or {}
        prefer = [p for p in (dec.get("make_now_process"),
                              routing.get("recommended_process")) if p]
        base["dfm_summary"] = _dfm_summary(result, material_class, prefer=prefer)

        if rd.get("status") == "GEOMETRY_INVALID":
            # A real, honest engine refusal (volume<=0 / non-watertight): surfaced,
            # never faked into a cost.
            base["should_cost"] = {
                "status": "GEOMETRY_INVALID",
                "reason": rd.get("reason"),
            }
        else:
            should_cost = {
                "status": rd.get("status"),
                "cost_quantity": int(cost_quantity),
                "make_now_process": dec.get("make_now_process"),
                "make_now_material": dec.get("make_now_material"),
                "crossover_qty": dec.get("crossover_qty"),
                "recommendation": dec.get("recommendation"),
                "estimates": _compact_estimates(rd),
            }
            if cots:
                # Re-frame the machined figure honestly for a catalog part: it is
                # the in-house fabrication upper-bound, NOT the recommended cost.
                should_cost["cost_basis"] = "fabrication_upper_bound_if_made_in_house"
                should_cost["cost_basis_note"] = (
                    "This part is a standard COTS fastener (see 'cots'): the "
                    "should-cost figures are what it would cost to MAKE it in-house "
                    "(a fabrication upper-bound), not the recommended buy cost."
                )
            base["should_cost"] = should_cost

        if cots:
            base["cots"] = cots
        return base
    except Exception as exc:  # honest per-part error, never breaks the assembly
        logger.info("per-part analysis failed for %s: %s", part.tree_path, exc)
        base["error"] = {
            "code": "ANALYSIS_ERROR",
            "message": f"{type(exc).__name__}: {exc}",
        }
        return base


# ── Real clearance / interference (pure geometry, bounded) ──────────────────
def _bbox_overlap(a_min, a_max, b_min, b_max, tol: float) -> bool:
    a_min = np.asarray(a_min, dtype=float)
    a_max = np.asarray(a_max, dtype=float)
    b_min = np.asarray(b_min, dtype=float)
    b_max = np.asarray(b_max, dtype=float)
    return bool(np.all(a_max + tol >= b_min) and np.all(b_max + tol >= a_min))


def _nearest_vertex_gap(mesh_a, mesh_b) -> Optional[float]:
    """Nearest vertex-to-vertex distance between two meshes via a KD-tree — a fast
    (ms), REAL proximity signal for surface contact. It is a vertex-set
    approximation of surface distance (honest: not the exact point-to-triangle
    closest distance, which at ~6 s/pair would blow the budget); at assembly-scale
    tessellation density it reliably separates 'touching' from 'clears'."""
    try:
        from scipy.spatial import cKDTree

        tree = cKDTree(np.asarray(mesh_b.vertices, dtype=float))
        d, _ = tree.query(np.asarray(mesh_a.vertices, dtype=float), k=1)
        return float(np.min(d))
    except Exception:
        return None


def _contains_count(container, points) -> Optional[int]:
    """How many of ``points`` fall INSIDE ``container`` (real interpenetration
    signal via ``trimesh.contains`` — embree ray casting). None if the query is
    unavailable for this mesh (degenerate/non-watertight)."""
    try:
        inside = container.contains(np.asarray(points, dtype=float))
        return int(np.count_nonzero(inside))
    except Exception:
        return None


def detect_interference(model, *, deadline: Optional[float] = None) -> dict:
    """REAL pairwise geometric overlap/contact on the world-positioned meshes.

    bbox-overlap prefilter (cheap) -> for each surviving pair: vertex containment
    (interpenetration) + nearest-vertex gap (contact). Bounded by
    ``MAX_INTERFERENCE_PAIRS`` and the shared wall-clock ``deadline``; a bound that
    bites is reported honestly (``pairs_capped`` / ``deadline_reached``), never a
    silent truncation. Reports interpenetrating OR contacting pairs; a bbox-overlap
    whose geometry actually clears is NOT reported (so parts that don't touch are
    not flagged).
    """
    parts = [p for p in model.parts if getattr(p, "mesh", None) is not None
             and len(getattr(p.mesh, "faces", [])) > 0]
    diag = float(getattr(model, "assembly_diag", 0.0) or 0.0)
    # Contact tolerance: scale-relative with an absolute floor. AS1 diag ~264mm ->
    # ~0.53mm; a genuinely clearing gap (bolt-to-neighbour ~8mm) stays well outside.
    contact_tol = max(0.25, diag * 0.002)

    n = len(parts)
    # bbox-overlap prefilter (a small margin so a flush contact is not missed).
    prefilter: list[tuple[int, int]] = []
    for i in range(n):
        for j in range(i + 1, n):
            if _bbox_overlap(
                parts[i].world.bbox_min, parts[i].world.bbox_max,
                parts[j].world.bbox_min, parts[j].world.bbox_max,
                tol=contact_tol,
            ):
                prefilter.append((i, j))

    pair_cap = _max_interference_pairs()
    pairs_capped = len(prefilter) > pair_cap
    to_check = prefilter[:pair_cap]

    hits: list[dict] = []
    deadline_reached = False
    checked = 0
    for (i, j) in to_check:
        if deadline is not None and time.monotonic() > deadline:
            deadline_reached = True
            break
        checked += 1
        A, B = parts[i], parts[j]
        a_in_b = _contains_count(B.mesh, A.mesh.vertices)
        b_in_a = _contains_count(A.mesh, B.mesh.vertices)
        pen = (a_in_b or 0) + (b_in_a or 0)
        gap = _nearest_vertex_gap(A.mesh, B.mesh)
        if pen > 0:
            kind = "interpenetration"
        elif gap is not None and gap <= contact_tol:
            kind = "contact"
        else:
            continue  # bbox overlapped but the geometry clears — not flagged
        hits.append({
            "part_a": {"id": A.id, "name": A.name, "tree_path": A.tree_path},
            "part_b": {"id": B.id, "name": B.name, "tree_path": B.tree_path},
            "type": kind,
            "penetration_vertices": int(pen),
            "min_gap_mm": round(gap, 4) if gap is not None else None,
            "note": (
                "Geometric contact/interference detected on the positioned meshes. "
                "For fasteners (bolt through a hole, nut on a thread) this overlap is "
                "EXPECTED, not a defect — this is a signal, not a fault verdict."
            ),
        })
    return {
        "method": (
            "bbox-overlap prefilter -> vertex containment (trimesh.contains, embree) "
            "+ nearest-vertex KD-tree gap on world-positioned meshes"
        ),
        "contact_tolerance_mm": round(contact_tol, 4),
        "meshed_parts": n,
        "candidate_pairs": len(prefilter),
        "pairs_checked": checked,
        "pairs_capped": pairs_capped,
        "pairs_cap": pair_cap,
        "deadline_reached": deadline_reached,
        "pairs": hits,
    }


# ── Orchestration (bounded + concurrent) ────────────────────────────────────
def analyze_assembly_sync(
    model,
    *,
    material_class: str = "aluminum",
    region: str = "US",
    assemblies_per_year: Optional[int] = None,
    max_parts: Optional[int] = None,
    time_budget_sec: float = 55.0,
) -> dict:
    """Full P3 analysis of an extracted ``AssemblyModel`` — pure/sync so the route
    runs it in ONE off-loop executor call under a hard ``wait_for``.

    Per-part DFM + should-cost run concurrently on a bounded thread pool (each part
    isolated: one failure => an honest per-part error), capped at ``max_parts`` and
    a shared wall-clock deadline; then real interference. Every bound that bites is
    surfaced. Nothing here reimplements costing — it calls the single-part engine.
    """
    t_start = time.monotonic()
    deadline = t_start + max(1.0, float(time_budget_sec))

    quantities = _quantities_by_design(model)
    cap = max_parts if max_parts is not None else _max_analyze_parts()
    all_parts = list(model.parts)
    selected = all_parts[:cap]
    parts_capped = len(all_parts) > cap

    apy = None
    if assemblies_per_year is not None and assemblies_per_year > 0:
        apy = int(assemblies_per_year)

    def _job(part):
        qty = quantities.get(_design_key(part), 1)
        cost_qty = qty * apy if apy else qty
        return analyze_one_part(
            part,
            quantity=qty,
            cost_quantity=max(1, int(cost_qty)),
            material_class=material_class,
            region=region,
        )

    results: list[dict] = []
    not_analyzed: list[dict] = []
    workers = min(_analyze_workers(), max(1, len(selected)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_job, p): p for p in selected}
        for fut, part in futures.items():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                not_analyzed.append({
                    "id": part.id, "name": part.name, "tree_path": part.tree_path,
                    "reason": "assembly time budget reached before this part ran",
                })
                fut.cancel()
                continue
            try:
                results.append(fut.result(timeout=max(0.1, remaining)))
            except _FutTimeout:
                not_analyzed.append({
                    "id": part.id, "name": part.name, "tree_path": part.tree_path,
                    "reason": "per-part analysis exceeded the assembly time budget",
                })
            except Exception as exc:  # defensive: _job already catches, but never leak
                results.append({
                    "id": part.id, "name": part.name, "tree_path": part.tree_path,
                    "error": {"code": "ANALYSIS_ERROR",
                              "message": f"{type(exc).__name__}: {exc}"},
                })

    for part in all_parts[cap:]:
        not_analyzed.append({
            "id": part.id, "name": part.name, "tree_path": part.tree_path,
            "reason": f"beyond MAX_ASSEMBLY_ANALYZE_PARTS={cap}",
        })

    interference = detect_interference(model, deadline=deadline)

    ok = sum(1 for r in results if "error" not in r)
    return {
        "per_part": results,
        "not_analyzed": not_analyzed,
        "quantities_by_design": quantities,
        "interference": interference,
        "cost_context": {
            "material_class": material_class,
            "region": region,
            "assemblies_per_year": apy,
            "quantity_basis": (
                "annual = per-assembly-count × assemblies_per_year"
                if apy else "per-assembly instance count (FACT)"
            ),
        },
        "analysis_summary": {
            "parts_total": len(all_parts),
            "parts_analyzed": len(results),
            "parts_ok": ok,
            "parts_errored": len(results) - ok,
            "parts_not_analyzed": len(not_analyzed),
            "parts_capped": parts_capped,
            "analyze_cap": cap,
            "interference_pairs": len(interference["pairs"]),
            "elapsed_sec": round(time.monotonic() - t_start, 2),
        },
        "boundaries": _BOUNDARIES,
    }
