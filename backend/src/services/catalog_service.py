"""Catalog service — the org-scoped parts×decisions grid (W1 step 4).

The read surface behind the "lakehouse" catalog: one row per PART (a distinct
``mesh_hash`` within the caller's org), unifying the two artifacts a part can
have — a DFM **analysis** (``analyses``) and a should-cost **decision**
(``cost_decisions``) — into a single grid row. It is the backend the FE-4
catalog door will consume instead of joining the raw ``/analyses`` +
``/cost-decisions`` endpoints on the client.

Two layers, deliberately split:

* **Pure derivation** (this module's top half) — no DB, no I/O. Reads the
  engine's own ``report_to_dict`` / analysis ``result_json`` VERBATIM and derives
  every grid cell (route, unit cost, findings, posture, lifecycle). It is a
  1:1 Python port of the frontend's ``lib/catalog.ts`` + ``lib/dfm-scope.ts`` so
  the two implementations never drift, and it is unit-testable with plain dicts.

* **DB query** (``build_catalog``) — org-scoped fetch + latest-per-part fold +
  hydration, then hands each part to the pure derivation. The tenant boundary is
  ``org_id`` (resolved from the caller upstream) — a caller only ever sees their
  own org's parts.

Honesty contract (identical to the live decision / FE catalog):
  * ``unit_cost`` is WITHHELD (null) on a DFM-blocked route — the grid never
    prints a make-price for a part that can't be made as-designed.
  * ``findings`` is null when the part has no analysis (a cost decision alone
    does NOT embed the DFM Issue array) — an honest absence, never faked from
    the route's blocker count (which is surfaced separately, real).
  * ``unit_cost.validated`` rides the engine's ``confidence.validated`` — which
    is ``False`` for every band today (no Zoox ground truth yet). No number is
    ever laundered into "validated" by living in the catalog.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import and_, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from src.analysis.models import ProcessType
from src.db.models import Analysis, CostDecision, PartContext, PartSummary
from src.services import part_context_service as pcsvc

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Safety cap on how many rows we scan per source table before folding to parts.
# v1's catalog is "early, mostly-empty" (plan §4 W1.4 / vision §8 Q3), so a
# generous cap is never hit in practice; it exists so a pathological org cannot
# force an unbounded scan/hydrate. When a scan hits the cap the response carries
# ``truncated: true`` — the omission is declared, never silent. The scale path
# (a denormalized per-part catalog summary refreshed on write) is a real W-track
# follow-up, not pretended-away here.
CATALOG_SCAN_CAP = 2000

_COSTED = "Costed"
_DRAFTED = "Drafted"


# ---------------------------------------------------------------------------
# Pure derivation — DFM finding scoping (port of frontend lib/dfm-scope.ts)
# ---------------------------------------------------------------------------


def issue_severity_bucket(severity: str) -> str:
    """Issue severity -> headline bucket (mirrors ``lib/dfm-scope`` exactly).

    error/critical/fail -> critical · warning/warn -> advisory · else info.
    The backend Severity enum only emits error/warning/info, but the extra
    aliases keep this byte-identical to the frontend so a future severity never
    silently drifts between the two.
    """
    if severity in ("error", "critical", "fail"):
        return "critical"
    if severity in ("warning", "warn"):
        return "advisory"
    return "info"


def scoped_findings(result_json: dict, scoped_processes: list[str]) -> dict:
    """Route-scoped DFM finding counts from an analysis ``result_json``.

    The #1 demo trust-killer (FRAGILE-1) fixed the same way the FE does it: the
    count reflects the route the part will ACTUALLY be made by — the recommended
    process's issues PLUS the part-level ``universal_issues`` (geometry validity,
    non-watertight, …) which are real regardless of process. Issues from
    processes NOT on the route do not inflate the count. Deduped by
    ``(code, message)`` (first occurrence wins the severity, universal first),
    matching ``lib/dfm-scope`` ``collect``.
    """
    in_scope = {p for p in scoped_processes if p}
    seen: dict[tuple, str] = {}

    def push(issue: dict) -> None:
        key = (issue.get("code"), issue.get("message"))
        if key not in seen:
            seen[key] = issue_severity_bucket(issue.get("severity", ""))

    for iss in result_json.get("universal_issues") or []:
        push(iss)
    for ps in result_json.get("process_scores") or []:
        if ps.get("process") in in_scope:
            for iss in ps.get("issues") or []:
                push(iss)

    counts = {"total": 0, "critical": 0, "advisory": 0, "info": 0}
    for bucket in seen.values():
        counts["total"] += 1
        counts[bucket] += 1
    return counts


# ---------------------------------------------------------------------------
# Pure derivation — cost posture / route / unit (port of lib/catalog.ts)
# ---------------------------------------------------------------------------


def posture(drivers: Optional[list[dict]]) -> dict:
    """Provenance mix across an estimate's drivers (filled vs hollow).

    grounded = MEASURED + SHOP + USER (filled markers) · guess = DEFAULT (hollow
    ring). ``grounded_pct`` is grounded/total in [0,1], 0 when there are no
    drivers. 1:1 with ``lib/catalog.ts`` ``posture``.
    """
    c = {"measured": 0, "shop": 0, "user": 0, "default": 0}
    for d in drivers or []:
        prov = d.get("provenance")
        if prov == "MEASURED":
            c["measured"] += 1
        elif prov == "SHOP":
            c["shop"] += 1
        elif prov == "USER":
            c["user"] += 1
        else:
            c["default"] += 1
    total = c["measured"] + c["shop"] + c["user"] + c["default"]
    grounded = c["measured"] + c["shop"] + c["user"]
    return {
        **c,
        "total": total,
        "grounded": grounded,
        "guess": c["default"],
        "grounded_pct": round(grounded / total, 4) if total > 0 else 0.0,
    }


def make_now_estimate(cost_result_json: dict) -> Optional[dict]:
    """The estimate behind the recommended make-now route.

    The FIRST estimate whose ``process`` equals ``decision.make_now_process`` —
    the same ``pickEstimate`` convention the saved-decision hero and the resident
    Inspector use. None when there is no decision or no matching estimate.
    """
    decision = cost_result_json.get("decision") or {}
    proc = (decision.get("make_now_process") or "").strip()
    if not proc:
        return None
    for e in cost_result_json.get("estimates") or []:
        if e.get("process") == proc:
            return e
    return None


def _process_score(analysis_result_json: dict, process: str) -> Optional[dict]:
    for ps in analysis_result_json.get("process_scores") or []:
        if ps.get("process") == process:
            return ps
    return None


# ---------------------------------------------------------------------------
# Pure derivation — the row
# ---------------------------------------------------------------------------


@dataclass
class SourceRef:
    """A hydrated source artifact (analysis or cost decision) for one part.

    DB-free by construction so ``derive_row`` unit-tests with plain values.
    """

    id: str                      # the ulid (also the /api link key)
    filename: str
    file_type: str
    created_at: datetime
    result_json: dict


def derive_row(
    *,
    part_key: str,
    analysis: Optional[SourceRef],
    cost: Optional[SourceRef],
) -> dict:
    """Derive one catalog row from a part's (optional) analysis + cost artifacts.

    Every cell binds to a real engine field; a missing field yields ``null``,
    never a fabricated figure. Requires at least one of ``analysis`` / ``cost``.
    """
    if analysis is None and cost is None:  # pragma: no cover - guarded by caller
        raise ValueError("derive_row needs at least one of analysis/cost")

    cost_json = cost.result_json if cost else {}
    an_json = analysis.result_json if analysis else {}
    decision = (cost_json.get("decision") or {}) if cost else {}

    lifecycle_state = _COSTED if cost is not None else _DRAFTED

    # --- recommended route -------------------------------------------------
    # Costed → the decision's make-now route (real). Drafted → the analysis's
    # DFM-recommended best_process (real, but not costed). Either is honestly
    # labeled by ``source`` so the UI never conflates a costed route with a raw
    # DFM suggestion.
    est = make_now_estimate(cost_json) if cost else None
    recommended_route: Optional[dict] = None
    scoped_process = ""
    if cost is not None:
        proc = (decision.get("make_now_process") or "").strip()
        if proc:
            scoped_process = proc
            recommended_route = {
                "process": proc,
                "material": (
                    (est or {}).get("material")
                    or (decision.get("make_now_material") or None)
                ),
                "source": "costed",
            }
    if recommended_route is None and analysis is not None:
        best = (an_json.get("best_process") or "").strip()
        if best:
            scoped_process = scoped_process or best
            ps = _process_score(an_json, best) or {}
            recommended_route = {
                "process": best,
                "material": ps.get("recommended_material") or None,
                "source": "dfm",
            }
    # If costed but the recommended route is unknown, still scope findings to the
    # analysis best_process where available (so the count is never mis-scoped).
    if not scoped_process and analysis is not None:
        scoped_process = (an_json.get("best_process") or "").strip()

    # --- unit cost (withheld on a blocked route) ---------------------------
    unit_cost: Optional[dict] = None
    route_blocker_count = 0
    provenance_posture: Optional[dict] = None
    if est is not None:
        blocked = not est.get("dfm_ready", True)
        blockers = est.get("dfm_blockers") or []
        route_blocker_count = len(blockers)
        ci = est.get("confidence") or {}
        provenance_posture = posture(est.get("drivers"))
        unit_cost = {
            # Withhold the price on a DFM-blocked route — never a make-price for a
            # part that can't be made as-designed.
            "usd": None if blocked else est.get("unit_cost_usd"),
            "qty": est.get("quantity"),
            "currency": "USD",
            "withheld": blocked,
            "withheld_reason": blockers[0] if (blocked and blockers) else None,
            # Honesty: False for every assumption-based band today (no ground
            # truth yet); the catalog never presents an unvalidated cost as
            # measured.
            "validated": bool(ci.get("validated", False)),
        }
    elif cost is not None:
        # Costed but no matching make-now estimate (e.g. GEOMETRY_INVALID) — the
        # cost artifact exists yet carries no price. Posture is honestly absent.
        provenance_posture = None

    # --- findings (route-scoped, from the analysis's real Issue array) -----
    findings: Optional[dict] = None
    if analysis is not None:
        counts = scoped_findings(an_json, [scoped_process] if scoped_process else [])
        findings = {**counts, "scoped_process": scoped_process}

    # --- identity / links / recency ----------------------------------------
    primary = cost or analysis  # the "decision" is the headline artifact
    updated = max(
        [r.created_at for r in (analysis, cost) if r is not None]
    )

    return {
        "part_key": part_key,
        "filename": primary.filename,
        "file_type": primary.file_type,
        "lifecycle_state": lifecycle_state,
        "recommended_route": recommended_route,
        "unit_cost": unit_cost,
        "findings": findings,
        "provenance_posture": provenance_posture,
        "route_blocker_count": route_blocker_count,
        "cost_decision": (
            {"id": cost.id, "url": f"/api/v1/cost-decisions/{cost.id}"}
            if cost is not None
            else None
        ),
        "analysis": (
            {"id": analysis.id, "url": f"/api/v1/analyses/{analysis.id}"}
            if analysis is not None
            else None
        ),
        "updated_at": updated.isoformat(),
    }


# ---------------------------------------------------------------------------
# Pure derivation — facets + filtering (real predicates over derived rows)
# ---------------------------------------------------------------------------


def row_has_findings(row: dict) -> Optional[bool]:
    """Tri-state: True (>0 route-scoped findings), False (known 0), None (no
    analysis → genuinely unknown, not zero)."""
    f = row.get("findings")
    if f is None:
        return None
    return f.get("total", 0) > 0


def matches_filters(
    row: dict,
    *,
    state: Optional[str],
    route: Optional[str],
    has_findings: Optional[bool],
) -> bool:
    """Whether a derived row passes the requested facet filters. Every predicate
    reads a real derived field; ``has_findings`` excludes unknown (null-findings)
    rows from BOTH True and False, since "no analysis" is not "zero findings"."""
    if state is not None and row.get("lifecycle_state") != state:
        return False
    if route is not None:
        rr = row.get("recommended_route") or {}
        if rr.get("process") != route:
            return False
    if has_findings is not None:
        hf = row_has_findings(row)
        if hf is None or hf != has_findings:
            return False
    return True


def compute_facets(rows: list[dict]) -> dict:
    """Available facet values with real counts over the given rows (unfiltered),
    so the UI can render filter chips that reflect what is actually in the org's
    catalog — every count derived, none invented."""
    by_state: dict[str, int] = {}
    by_route: dict[str, int] = {}
    with_findings = 0
    without_findings = 0
    findings_unknown = 0
    for r in rows:
        st = r.get("lifecycle_state")
        by_state[st] = by_state.get(st, 0) + 1
        rr = r.get("recommended_route") or {}
        proc = rr.get("process")
        if proc:
            by_route[proc] = by_route.get(proc, 0) + 1
        hf = row_has_findings(r)
        if hf is None:
            findings_unknown += 1
        elif hf:
            with_findings += 1
        else:
            without_findings += 1
    return {
        "state": by_state,
        "route": by_route,
        "findings": {
            "with_findings": with_findings,
            "without_findings": without_findings,
            "unknown": findings_unknown,
        },
    }


# ---------------------------------------------------------------------------
# DB query — org-scoped fetch + latest-per-part fold + hydrate
# ---------------------------------------------------------------------------


def _fold_latest_by_mesh(rows: list) -> dict[str, Any]:
    """Keep the latest artifact per ``mesh_hash``. ``rows`` MUST already be
    ordered ulid-desc (newest first), so the first seen per mesh is the latest.
    ULIDs are monotonic + unique, so this is a stable "latest wins"."""
    latest: dict[str, Any] = {}
    for r in rows:
        if r.mesh_hash not in latest:
            latest[r.mesh_hash] = r
    return latest


async def _fold_org_parts(
    session: AsyncSession, org_id: str
) -> tuple[list[tuple[str, Optional[SourceRef], Optional[SourceRef]]], bool]:
    """The org-scoped fetch + latest-per-part fold shared by the catalog grid and
    the portfolio roll-up. Returns ``([(mesh, analysis_ref, cost_ref), ...],
    truncated)`` — one entry per distinct part (mesh_hash) in the org, each
    hydrated into DB-free ``SourceRef``s. A single bounded, ulid-desc scan per
    source table (cap+1 so truncation is honest without a second COUNT)."""
    # One bounded, ulid-desc query per source table (newest first). Fetch cap+1
    # so we can honestly report truncation without a second COUNT round-trip.
    an_rows = (
        (
            await session.execute(
                select(Analysis)
                .where(Analysis.org_id == org_id)
                .order_by(Analysis.ulid.desc())
                .limit(CATALOG_SCAN_CAP + 1)
            )
        )
        .scalars()
        .all()
    )
    cost_rows = (
        (
            await session.execute(
                select(CostDecision)
                .where(CostDecision.org_id == org_id)
                .order_by(CostDecision.ulid.desc())
                .limit(CATALOG_SCAN_CAP + 1)
            )
        )
        .scalars()
        .all()
    )
    truncated = len(an_rows) > CATALOG_SCAN_CAP or len(cost_rows) > CATALOG_SCAN_CAP
    an_rows = an_rows[:CATALOG_SCAN_CAP]
    cost_rows = cost_rows[:CATALOG_SCAN_CAP]

    an_by_mesh = _fold_latest_by_mesh(an_rows)
    cost_by_mesh = _fold_latest_by_mesh(cost_rows)

    parts: list[tuple[str, Optional[SourceRef], Optional[SourceRef]]] = []
    for mesh in set(an_by_mesh) | set(cost_by_mesh):
        a = an_by_mesh.get(mesh)
        c = cost_by_mesh.get(mesh)
        analysis_ref = (
            SourceRef(
                id=a.ulid,
                filename=a.filename,
                file_type=a.file_type,
                created_at=a.created_at,
                result_json=a.result_json or {},
            )
            if a is not None
            else None
        )
        cost_ref = (
            SourceRef(
                id=c.ulid,
                filename=c.filename,
                file_type=c.file_type,
                created_at=c.created_at,
                result_json=c.result_json or {},
            )
            if c is not None
            else None
        )
        parts.append((mesh, analysis_ref, cost_ref))
    return parts, truncated


async def build_catalog(session: AsyncSession, org_id: Optional[str]) -> dict:
    """Build the full org-scoped catalog: one derived row per part.

    Returns ``{"rows": [...], "truncated": bool}`` — the caller applies facet
    filters + pagination on top. ``org_id`` None (a caller with no membership —
    e.g. a mocked session) yields an empty catalog, never a cross-org read.
    """
    if not org_id:
        return {"rows": [], "truncated": False}

    parts, truncated = await _fold_org_parts(session, org_id)
    rows = [
        derive_row(part_key=mesh, analysis=analysis_ref, cost=cost_ref)
        for (mesh, analysis_ref, cost_ref) in parts
    ]

    # Most-recent activity first (the grid's default order). ``updated_at`` is a
    # real timestamp on every row.
    rows.sort(key=lambda r: r["updated_at"], reverse=True)
    return {"rows": rows, "truncated": truncated}


# ---------------------------------------------------------------------------
# Portfolio roll-up (W3) — savings ranking over the org's COSTED parts
# ---------------------------------------------------------------------------


def derive_savings(cost_result_json: dict) -> Optional[dict]:
    """The single, honest savings signal for a costed part — or None.

    SAVINGS HONESTY (the crux of W3): every number here is one the engine already
    computed and PERSISTED in ``result_json``. The signal is the engine's own
    ``if_redesigned`` alternative being cheaper than the recommended make-as-is at
    a quoted quantity — a per-unit delta of two persisted engine unit costs:

        ``decision.recommendation[q].unit_cost_usd``  (tier-1 make-as-is, the
            make-now baseline — coherence invariant pins it to make_now_process)
      − ``decision.if_redesigned[q].unit_cost_usd``   (tier-2 cheaper-if-redesigned)

    Mirrors the frontend ``lib/portfolio.ts::bestRedesignSaving`` field-for-field
    (make-now / redesigned unit + qty + pct + the engine's own caveat, verbatim):
    it scans every quoted qty, keeps only qtys where the redesign is genuinely
    cheaper, and picks the DEEPEST ``save_pct`` (ties → larger qty, where a
    redesign matters most to a portfolio owner). JSONB stringifies the int qty
    keys on round-trip, so the recommendation lookup is string-key tolerant. No
    cheaper redesign at any qty → None (never a fabricated saving).
    """
    decision = cost_result_json.get("decision") or {}
    rec = decision.get("recommendation") or {}
    alt = decision.get("if_redesigned") or {}
    if not isinstance(rec, dict) or not isinstance(alt, dict):
        return None

    best: Optional[dict] = None
    for q_key, alt_at_q in alt.items():
        if not alt_at_q:
            continue
        rec_at_q = _lookup_by_qty(rec, q_key)
        if not rec_at_q:
            continue
        make_now_usd = rec_at_q.get("unit_cost_usd")
        redesigned_usd = alt_at_q.get("unit_cost_usd")
        if make_now_usd is None or redesigned_usd is None or make_now_usd <= 0:
            continue
        save_unit_usd = round(make_now_usd - redesigned_usd, 2)
        if save_unit_usd <= 0:
            continue  # redesign not cheaper — no saving to claim
        save_pct = round(save_unit_usd / make_now_usd, 4)
        try:
            qty = int(q_key)
        except (TypeError, ValueError):
            qty = q_key
        candidate = {
            # basis: the exact engine field this delta was read from, so the
            # number is always traceable to persisted engine output.
            "basis": "decision.if_redesigned",
            "qty": qty,
            "make_now_unit_usd": round(make_now_usd, 2),
            "redesigned_unit_usd": round(redesigned_usd, 2),
            "save_unit_usd": save_unit_usd,
            "save_pct": save_pct,
            "redesigned_process": alt_at_q.get("process"),
            # the engine's OWN caveat (why the cheaper option is not the make-as-
            # is pick) — rendered verbatim, never softened.
            "caveat": alt_at_q.get("caveat") or None,
        }
        if (
            best is None
            or save_pct > best["save_pct"]
            or (save_pct == best["save_pct"] and _qty_num(qty) > _qty_num(best["qty"]))
        ):
            best = candidate
    return best


def _lookup_by_qty(rec: dict, q_key) -> Optional[dict]:
    """String-key tolerant lookup (JSONB turns int qty keys into strings), so a
    saved decision re-derives identically to a live one."""
    if q_key in rec:
        return rec.get(q_key)
    s = str(q_key)
    if s in rec:
        return rec.get(s)
    for k in rec:
        if str(k) == s:
            return rec.get(k)
    return None


def _qty_num(q) -> float:
    try:
        return float(q)
    except (TypeError, ValueError):
        return float("-inf")


def _empty_posture_agg() -> dict:
    return {
        "measured": 0, "shop": 0, "user": 0, "default": 0,
        "total": 0, "grounded": 0, "grounded_pct": 0.0,
    }


# The honest reason an annualized $/year is withheld: the user never declared an
# annual_volume, and we NEVER fabricate a demand quantity to invent one.
_NO_VOLUME_REASON = (
    "no declared annual_volume; annualized $/year withheld (never fabricated)"
)


def _group_by_program(rows: list[dict]) -> list[dict]:
    """Per-program roll-up over enriched portfolio rows (pure).

    Groups the costed rows that carry a declared ``program`` and sums their
    annualized figures. A row's ``$/year`` contributes ONLY when it is a real
    number (the owner declared an annual_volume); rows without one are counted
    (``parts``) but never fabricate a total. Returns [] when no row has a
    program. Sorted by program name for a stable, deterministic response.
    """
    groups: dict[str, dict] = {}
    for r in rows:
        ctx = r.get("context") or {}
        program = ctx.get("program")
        if not program:
            continue
        g = groups.setdefault(
            program,
            {
                "program": program,
                "parts": 0,
                "annualized_cost_usd": None,
                "annualized_savings_usd": None,
            },
        )
        g["parts"] += 1
        for key in ("annualized_cost_usd", "annualized_savings_usd"):
            val = r.get(key)
            if val is not None:
                g[key] = round((g[key] or 0.0) + val, 2)
    return [groups[p] for p in sorted(groups)]


def _context_block(ctx_row: Any) -> Optional[dict]:
    """The USER-DECLARED context block for a portfolio row, or None when the part
    has no declared context. Every field is a user assertion (``provenance:
    'user'``), never inferred from the mesh."""
    if ctx_row is None:
        return None
    return {
        "program": getattr(ctx_row, "program", None),
        "parent_assembly": getattr(ctx_row, "parent_assembly", None),
        "units_per_parent": getattr(ctx_row, "units_per_parent", None),
        "annual_volume": getattr(ctx_row, "annual_volume", None),
        "provenance": "user",
    }


async def build_portfolio(session: AsyncSession, org_id: Optional[str]) -> dict:
    """The org-scoped portfolio roll-up: costed parts ranked by redesign savings.

    A SECOND derivation pass over the same org fold the catalog uses (no new
    tables, no SQL GROUP BY). Each costed part becomes a row carrying its make-now
    route, withheld-aware unit cost, quantities, validated flag, provenance
    posture, crossover, and the honest savings signal (or ``savings: null`` +
    reason). Rows rank by ``save_pct`` descending (ties → larger qty), matching
    the frontend savings queue. Parts with NO cost decision are excluded from the
    ranking and counted in ``excluded_no_cost_count`` — you can't rank a savings
    on a part that was never costed.

    ``org_id`` None → an empty roll-up, never a cross-org read. ``truncated`` is
    carried through: when true the roll-up is over a CAPPED scan (older parts
    omitted), and the response says so.
    """
    if not org_id:
        return {
            "summary": {
                "parts": 0, "costed": 0, "drafted": 0,
                "excluded_no_cost_count": 0, "truncated": False,
                "posture": _empty_posture_agg(),
            },
            "rows": [],
        }

    parts, truncated = await _fold_org_parts(session, org_id)

    # W3.5 rung-1: join each part to its optional USER-DECLARED context. This is
    # PURELY ADDITIVE — when the org has declared NO contexts, ``ctx_by_mesh`` is
    # empty, ``has_any_context`` is False, and every roll-up field below is left
    # exactly as it was before this table existed (byte-identical output). No
    # part is ever enriched with an inferred/fabricated context.
    contexts = await pcsvc.list_contexts(session, org_id)
    ctx_by_mesh = {c.mesh_hash: c for c in contexts}
    has_any_context = bool(ctx_by_mesh)

    rows: list[dict] = []
    drafted_count = 0
    agg = _empty_posture_agg()

    for mesh, analysis_ref, cost_ref in parts:
        if cost_ref is None:
            # Drafted-only (analysis, no cost) — can't derive savings; excluded.
            drafted_count += 1
            continue

        base = derive_row(part_key=mesh, analysis=analysis_ref, cost=cost_ref)
        cost_json = cost_ref.result_json or {}
        decision = cost_json.get("decision") or {}
        unit_cost = base.get("unit_cost")
        pp = base.get("provenance_posture")

        # Posture aggregate across costed parts (driver provenance mix).
        if pp:
            for k in ("measured", "shop", "user", "default"):
                agg[k] += pp.get(k, 0)

        savings = derive_savings(cost_json)
        row = {
            "part_key": mesh,
            "filename": base["filename"],
            "lifecycle_state": base["lifecycle_state"],
            "make_now_process": (base.get("recommended_route") or {}).get("process"),
            # withheld-aware unit cost dict (same rule as catalog rows).
            "unit_cost": unit_cost,
            "quantities": cost_json.get("quantities") or [],
            # copied from the engine's confidence band — NEVER computed here.
            "validated": (unit_cost or {}).get("validated") if unit_cost else None,
            "posture": pp,
            # the engine's authoritative make-vs-buy crossover (or null).
            "crossover_qty": decision.get("crossover_qty"),
            "cost_decision": base.get("cost_decision"),
            "savings": savings,
        }
        if savings is None:
            row["reason"] = (
                "no engine-computed cheaper alternative "
                "(make-as-is is cheapest at every quoted quantity)"
            )

        # Additive declared-context enrichment (only when the org has declared
        # at least one context — otherwise the row is byte-identical to today).
        if has_any_context:
            ctx_row = ctx_by_mesh.get(mesh)
            annual_volume = getattr(ctx_row, "annual_volume", None) if ctx_row else None
            unit_usd = (unit_cost or {}).get("usd") if unit_cost else None
            save_unit = (savings or {}).get("save_unit_usd") if savings else None
            row["context"] = _context_block(ctx_row)
            # $/year appears ONLY with a user-declared annual_volume; otherwise
            # null + an honest reason. Never a fabricated demand quantity.
            row["annualized_cost_usd"] = pcsvc.annualized_cost(unit_usd, annual_volume)
            row["annualized_savings_usd"] = pcsvc.annualized_cost(
                save_unit, annual_volume
            )
            if annual_volume is None:
                row["annualized_reason"] = _NO_VOLUME_REASON

        rows.append(row)

    # Rank by savings descending: parts WITH a signal first (deepest save_pct;
    # ties → larger qty), null-savings parts last (stable among themselves).
    rows.sort(
        key=lambda r: (
            1 if r["savings"] else 0,
            (r["savings"] or {}).get("save_pct", 0.0),
            _qty_num((r["savings"] or {}).get("qty", 0)),
        ),
        reverse=True,
    )

    grounded = agg["measured"] + agg["shop"] + agg["user"]
    total = grounded + agg["default"]
    agg["total"] = total
    agg["grounded"] = grounded
    agg["grounded_pct"] = round(grounded / total, 4) if total > 0 else 0.0

    summary = {
        "parts": len(rows) + drafted_count,
        "costed": len(rows),
        "drafted": drafted_count,
        # parts excluded from the ranking because they have no cost decision.
        "excluded_no_cost_count": drafted_count,
        "truncated": truncated,
        "posture": agg,
    }

    # Per-program roll-up — ADDITIVE, and only when at least one costed part
    # carries a declared ``program``. Sums are honest: a part's $/year only
    # contributes when its owner declared an annual_volume (else it is omitted,
    # never fabricated). Absent any declared program, ``summary`` is byte-identical.
    if has_any_context:
        programs = _group_by_program(rows)
        if programs:
            summary["programs"] = programs

    return {"summary": summary, "rows": rows}


# ---------------------------------------------------------------------------
# Makeability triage roll-up (W1 value-prop 1) — "can we make it, and how?" at
# portfolio scale. A THIRD pure aggregation over the SAME catalog rows: it turns
# a pile of legacy parts into an actionable summary — of N parts, how many are
# routable to each process, and how many are makeable / need review / unknown.
# No shop, no cost validation: this is the DFM-makeability lens only.
# ---------------------------------------------------------------------------


# Human labels for every real engine process id (ProcessType). Keeps the rollup
# honest: buckets key off the engine's own category, and the label is a display
# string only — an unrecognized id falls back to a titleized form, never dropped.
_PROCESS_LABELS: dict[str, str] = {
    ProcessType.FDM.value: "FDM 3D Printing",
    ProcessType.SLA.value: "SLA 3D Printing",
    ProcessType.DLP.value: "DLP 3D Printing",
    ProcessType.SLS.value: "SLS 3D Printing",
    ProcessType.MJF.value: "MJF 3D Printing",
    ProcessType.DMLS.value: "DMLS Metal 3D Printing",
    ProcessType.SLM.value: "SLM Metal 3D Printing",
    ProcessType.EBM.value: "EBM Metal 3D Printing",
    ProcessType.BINDER_JET.value: "Binder Jetting",
    ProcessType.DED.value: "Directed Energy Deposition",
    ProcessType.WAAM.value: "Wire-Arc Additive (WAAM)",
    ProcessType.CNC_3AXIS.value: "CNC Milling (3-axis)",
    ProcessType.CNC_5AXIS.value: "CNC Milling (5-axis)",
    ProcessType.CNC_TURNING.value: "CNC Turning",
    ProcessType.WIRE_EDM.value: "Wire EDM",
    ProcessType.INJECTION_MOLDING.value: "Injection Molding",
    ProcessType.DIE_CASTING.value: "Die Casting",
    ProcessType.INVESTMENT_CASTING.value: "Investment Casting",
    ProcessType.SAND_CASTING.value: "Sand Casting",
    ProcessType.SHEET_METAL.value: "Sheet Metal",
    ProcessType.FORGING.value: "Forging",
}

# The three makeability postures. Every part lands in EXACTLY one (see
# ``triage_bucket``); they are mutually exclusive and sum to ``total``.
TRIAGE_BUCKETS = ("makeable", "needs_review", "unknown")


def process_label(process_id: Optional[str]) -> str:
    """Human label for an engine process id (display only, never a category)."""
    if not process_id:
        return "Unrouted"
    return _PROCESS_LABELS.get(process_id) or process_id.replace("_", " ").title()


def triage_bucket(row: dict) -> str:
    """Classify one derived catalog row into a makeability posture.

    Mutually exclusive, evaluated in order — every row lands in exactly one, and
    every branch keys off a REAL engine-derived field on the row:

    * ``needs_review`` — the part IS routed to a process, but the engine flagged a
      blocking/critical DFM problem on that route: either a cost-side DFM blocker
      (``route_blocker_count > 0``, the same signal that withholds the price) or a
      route-scoped critical DFM finding (``findings.critical > 0``). A concrete,
      engine-computed reason it can't be made as-designed.
    * ``makeable`` — routed AND a DFM analysis actually ran on the route
      (``findings`` present) AND that analysis has zero critical findings. We only
      call a part makeable once the DFM engine has CONFIRMED the route is clean —
      never on a cost decision alone.
    * ``unknown`` — everything else: no recommended route at all, OR routed but
      never DFM-analyzed (a cost decision does not embed the DFM Issue array). We
      do not KNOW it's makeable, so we never assume it. Honest by construction.
    """
    route = (row.get("recommended_route") or {}).get("process")
    findings = row.get("findings")
    if route:
        if (row.get("route_blocker_count") or 0) > 0:
            return "needs_review"
        if findings and (findings.get("critical") or 0) > 0:
            return "needs_review"
        # Makeable only when a DFM analysis actually ran and found nothing
        # blocking — a route without an analysis is unknown, never makeable.
        if findings is not None:
            return "makeable"
    return "unknown"


def _empty_triage_summary() -> dict:
    return {
        "total": 0,
        "analyzed": 0,
        "makeable": 0,
        "needs_review": 0,
        "unknown": 0,
        "truncated": False,
    }


def triage_rollup(
    rows: list[dict],
    *,
    truncated: bool = False,
    programs: Optional[dict[str, str]] = None,
) -> dict:
    """Pure makeability roll-up over derived catalog rows (no DB, no I/O).

    Aggregates the exact rows ``build_catalog`` produced — it never re-derives or
    re-queries. Returns:

    * ``summary`` — ``total`` parts; ``analyzed`` (= makeable + needs_review, the
      parts carrying a real DFM makeability signal); the three posture counts; and
      ``truncated`` passed straight through (true ⇒ the scan was capped and older
      parts were NOT counted — stated, never implied away).
    * ``by_process`` — for each process any part is routed to, the count of parts
      on that route with the engine process id + a human label. Sorted by count
      desc then id, so it's deterministic. Only routed parts appear (an unrouted
      ``unknown`` part contributes to no process).
    * ``programs`` (optional) — the same posture counts grouped by USER-DECLARED
      ``program``, present ONLY when at least one part carries one. Additive; the
      response is byte-identical without it.

    Honesty: every count is a tally of a real engine-derived field. A part with no
    analysis is ``unknown`` (never assumed makeable); a % is only ever count/total,
    computed by the caller if at all — none is fabricated here.
    """
    summary = _empty_triage_summary()
    summary["truncated"] = bool(truncated)
    by_process: dict[str, int] = {}
    prog_groups: dict[str, dict] = {}

    for r in rows:
        summary["total"] += 1
        bucket = triage_bucket(r)
        summary[bucket] += 1

        proc = (r.get("recommended_route") or {}).get("process")
        if proc:
            by_process[proc] = by_process.get(proc, 0) + 1

        if programs:
            program = programs.get(r.get("part_key"))
            if program:
                g = prog_groups.setdefault(
                    program,
                    {"program": program, "total": 0,
                     "makeable": 0, "needs_review": 0, "unknown": 0},
                )
                g["total"] += 1
                g[bucket] += 1

    summary["analyzed"] = summary["makeable"] + summary["needs_review"]

    by_process_list = [
        {"process": p, "label": process_label(p), "count": c}
        for p, c in by_process.items()
    ]
    by_process_list.sort(key=lambda x: (-x["count"], x["process"]))

    out: dict = {"summary": summary, "by_process": by_process_list}
    if prog_groups:
        out["programs"] = [prog_groups[p] for p in sorted(prog_groups)]
    return out


async def build_triage(session: AsyncSession, org_id: Optional[str]) -> dict:
    """The org-scoped makeability triage roll-up.

    Reuses ``build_catalog``'s derived rows verbatim (no new tables, no raw
    re-query) and folds them into a portfolio-scale "can we make it, and how?"
    summary. ``org_id`` None → a zeroed summary (never a cross-org read), matching
    the empty-org contract of the catalog/portfolio surfaces.

    Program grouping is additive: when the org has declared at least one part
    ``program``, the roll-up carries a per-program posture breakdown; otherwise the
    response is byte-identical without it. Truncation is carried through honestly.
    """
    if not org_id:
        return {"summary": _empty_triage_summary(), "by_process": []}

    built = await build_catalog(session, org_id)
    rows = built["rows"]

    # Optional declared-program grouping — same source the portfolio join uses.
    contexts = await pcsvc.list_contexts(session, org_id)
    prog_by_mesh = {
        c.mesh_hash: c.program
        for c in contexts
        if getattr(c, "program", None)
    }

    return triage_rollup(
        rows,
        truncated=built["truncated"],
        programs=prog_by_mesh or None,
    )


# ===========================================================================
# SCALE PATH (Aramco GAP 2) — summary-backed reads over ``part_summaries``.
#
# These ADD alongside build_triage / build_catalog (which stay UNTOUCHED as the
# byte-identity oracle). They compute the whole-inventory triage COUNT with a SQL
# GROUP BY (O(buckets), scales to millions) and paginate the grid by keyset —
# never scanning + folding raw rows in Python, never capped. Proven byte-identical
# to the legacy output on identical data: the summary rows carry the exact
# ``derive_row`` dict + the exact ``triage_bucket`` classification.
# ===========================================================================


async def build_triage_scaled(session: AsyncSession, org_id: Optional[str]) -> dict:
    """Whole-inventory makeability triage — the SCALE version of ``build_triage``.

    SAME OUTPUT SHAPE as ``build_triage`` (``summary`` + ``by_process`` + optional
    ``programs``), but computed by SQL aggregation over ``part_summaries`` instead
    of folding the 2000 newest raw rows in Python:

    * ``summary`` — ``GROUP BY triage_bucket`` gives the three posture counts; the
      derived ``total`` and ``analyzed`` (= makeable + needs_review) follow. This
      counts the ENTIRE inventory, so ``truncated`` is ALWAYS False — there is no
      cap to exceed.
    * ``by_process`` — ``GROUP BY route_process`` (routed parts only) → the per-
      process counts, labeled + sorted by (count desc, id) exactly as the legacy
      rollup.
    * ``programs`` (optional) — a bounded JOIN to ``part_contexts`` grouped by the
      USER-DECLARED program × bucket; present ONLY when a part carries a program,
      byte-identical without it (programs are few, so the join is cheap).

    Byte-identical to ``build_triage`` for any org whose parts fit under the legacy
    cap (the byte-identity test asserts this). ``org_id`` None → the same zeroed
    ``_empty_triage_summary()`` + ``[]`` contract.
    """
    if not org_id:
        return {"summary": _empty_triage_summary(), "by_process": []}

    # --- posture counts (GROUP BY triage_bucket) ---------------------------
    bucket_rows = (
        await session.execute(
            select(PartSummary.triage_bucket, func.count())
            .where(PartSummary.org_id == org_id)
            .group_by(PartSummary.triage_bucket)
        )
    ).all()
    summary = _empty_triage_summary()
    for bucket, cnt in bucket_rows:
        summary["total"] += cnt
        if bucket in TRIAGE_BUCKETS:
            summary[bucket] += cnt
    summary["analyzed"] = summary["makeable"] + summary["needs_review"]
    # Whole inventory is counted — never truncated (no cap on a SQL COUNT).
    summary["truncated"] = False

    # --- by_process (GROUP BY route_process, routed parts only) ------------
    proc_rows = (
        await session.execute(
            select(PartSummary.route_process, func.count())
            .where(
                PartSummary.org_id == org_id,
                PartSummary.route_process.isnot(None),
            )
            .group_by(PartSummary.route_process)
        )
    ).all()
    by_process_list = [
        {"process": p, "label": process_label(p), "count": c}
        for p, c in proc_rows
    ]
    by_process_list.sort(key=lambda x: (-x["count"], x["process"]))

    # --- programs (bounded JOIN to declared contexts) ----------------------
    prog_rows = (
        await session.execute(
            select(PartContext.program, PartSummary.triage_bucket, func.count())
            .select_from(PartSummary)
            .join(
                PartContext,
                and_(
                    PartContext.org_id == PartSummary.org_id,
                    PartContext.mesh_hash == PartSummary.mesh_hash,
                ),
            )
            .where(
                PartSummary.org_id == org_id,
                PartContext.program.isnot(None),
            )
            .group_by(PartContext.program, PartSummary.triage_bucket)
        )
    ).all()
    prog_groups: dict[str, dict] = {}
    for program, bucket, cnt in prog_rows:
        g = prog_groups.setdefault(
            program,
            {"program": program, "total": 0,
             "makeable": 0, "needs_review": 0, "unknown": 0},
        )
        g["total"] += cnt
        if bucket in TRIAGE_BUCKETS:
            g[bucket] += cnt

    out: dict = {"summary": summary, "by_process": by_process_list}
    if prog_groups:
        out["programs"] = [prog_groups[p] for p in sorted(prog_groups)]
    return out


# ---------------------------------------------------------------------------
# Keyset-paginated catalog grid (scale) — one page of derived rows at a time
# ---------------------------------------------------------------------------

# Opaque cursor cap — bound a single page so a caller cannot force an unbounded
# hydrate; mirrors the spirit of CATALOG_SCAN_CAP for the scale path.
CATALOG_PAGE_MAX = 500


def _encode_page_cursor(updated_at_iso: str, mesh_hash: str) -> str:
    """Opaque forward cursor = base64("updated_at_iso|mesh_hash"). Encodes the
    LAST row of the page on the ``(updated_at DESC, mesh_hash DESC)`` sort key."""
    raw = f"{updated_at_iso}|{mesh_hash}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode_page_cursor(cursor: str) -> tuple[datetime, str]:
    """Decode a cursor into ``(updated_at datetime, mesh_hash)``. The datetime is
    parsed from the exact ISO string the row's ``row_json['updated_at']`` carried,
    so it compares equal to the stored ``updated_at`` timestamptz column."""
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    ts_str, mesh = raw.split("|", 1)
    return datetime.fromisoformat(ts_str), mesh


async def build_catalog_page(
    session: AsyncSession,
    org_id: Optional[str],
    *,
    cursor: Optional[str] = None,
    limit: int = 100,
) -> dict:
    """One keyset-paginated page of the org catalog grid (the SCALE version of
    ``build_catalog``'s row list).

    Orders by ``(updated_at DESC, mesh_hash DESC)`` — the same most-recent-first
    order the legacy grid sorts on, with ``mesh_hash`` as a deterministic
    tie-break so pages never overlap or skip. Hydrates ONLY the current page's
    ``row_json`` (each is the exact ``derive_row`` dict). Returns
    ``{"rows": [...], "next_cursor": str | None}``; ``next_cursor`` is None only on
    the final page. ``cursor`` opaquely encodes the previous page's last row;
    ``limit`` is bounded at ``CATALOG_PAGE_MAX``. ``org_id`` None → an empty page.
    """
    if not org_id:
        return {"rows": [], "next_cursor": None}

    limit = max(1, min(int(limit), CATALOG_PAGE_MAX))

    q = select(
        PartSummary.updated_at, PartSummary.mesh_hash, PartSummary.row_json
    ).where(PartSummary.org_id == org_id)
    if cursor:
        cur_ts, cur_mesh = _decode_page_cursor(cursor)
        q = q.where(
            tuple_(PartSummary.updated_at, PartSummary.mesh_hash)
            < tuple_(cur_ts, cur_mesh)
        )
    # Fetch limit+1 so we know whether a further page exists without a COUNT.
    q = q.order_by(
        PartSummary.updated_at.desc(), PartSummary.mesh_hash.desc()
    ).limit(limit + 1)

    fetched = (await session.execute(q)).all()
    has_more = len(fetched) > limit
    page = fetched[:limit]
    rows = [r.row_json for r in page]

    next_cursor: Optional[str] = None
    if has_more and page:
        last = page[-1]
        next_cursor = _encode_page_cursor(last.row_json["updated_at"], last.mesh_hash)
    return {"rows": rows, "next_cursor": next_cursor}
