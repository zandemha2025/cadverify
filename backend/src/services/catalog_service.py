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

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Analysis, CostDecision

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


async def build_catalog(session: AsyncSession, org_id: Optional[str]) -> dict:
    """Build the full org-scoped catalog: one derived row per part.

    Returns ``{"rows": [...], "truncated": bool}`` — the caller applies facet
    filters + pagination on top. ``org_id`` None (a caller with no membership —
    e.g. a mocked session) yields an empty catalog, never a cross-org read.
    """
    if not org_id:
        return {"rows": [], "truncated": False}

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

    rows: list[dict] = []
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
        rows.append(
            derive_row(part_key=mesh, analysis=analysis_ref, cost=cost_ref)
        )

    # Most-recent activity first (the grid's default order). ``updated_at`` is a
    # real timestamp on every row.
    rows.sort(key=lambda r: r["updated_at"], reverse=True)
    return {"rows": rows, "truncated": truncated}
