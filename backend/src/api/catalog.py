"""Catalog API — the org-scoped parts×decisions grid (W1 step 4).

``GET /api/v1/catalog`` — the lakehouse read surface: one row per part in the
caller's org, each carrying the recommended route, unit cost (withheld on a
blocked route), route-scoped DFM findings, provenance posture, and lifecycle
state (Drafted/Costed). This is what the FE-4 catalog door consumes instead of
joining the raw ``/analyses`` + ``/cost-decisions`` endpoints on the client.

Tenancy: ORG-SCOPED via the ``resolve_org`` boundary W1 step 3 established — the
grid is built only from rows whose ``org_id`` matches the caller's org. A caller
never sees another org's parts (cross-tenant test asserts this by name). Row
derivation lives in ``catalog_service`` (pure, unit-tested); this router owns
only auth, facet parsing, and pagination.

Facets (real query params, applied to real derived fields):
  state=Drafted|Costed · route=<process id> · has_findings=true|false

Pagination: offset-based (``page`` / ``page_size``) with a real ``total`` — the
natural shape for a grid that shows a row count and jumps pages. Saved-view
persistence is intentionally out of scope (read surface first, per plan §4.4).
"""
from __future__ import annotations

import logging
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.org_context import resolve_org
from src.auth.rate_limit import limiter
from src.auth.rbac import Role, require_role
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session
from src.services import catalog_service as svc

logger = logging.getLogger("cadverify.catalog")

router = APIRouter(tags=["catalog"])

# Canonical lifecycle states (v1: Drafted/Costed only — vision §8 Q3).
_STATES = {"drafted": "Drafted", "costed": "Costed"}


@router.get("")
@limiter.limit("60/hour;500/day")
async def get_catalog(
    request: Request,
    response: Response,
    page: int = Query(1, ge=1, description="1-based page number"),
    page_size: int = Query(20, ge=1, le=100, description="Rows per page (max 100)"),
    state: Optional[str] = Query(
        None, description="Lifecycle facet: Drafted | Costed"
    ),
    route: Optional[str] = Query(
        None, description="Recommended-route facet: an engine process id (e.g. cnc_3axis)"
    ),
    has_findings: Optional[bool] = Query(
        None,
        description=(
            "Findings facet: true = parts with >0 route-scoped DFM findings; "
            "false = parts known to have zero. Parts with no DFM analysis are "
            "'unknown' and match neither."
        ),
    ),
    keyset: bool = Query(
        False,
        description=(
            "Opt-in SCALE mode (Aramco GAP 2): keyset-paginate the whole "
            "inventory over the materialized part-summary projection instead of "
            "the capped raw scan. Returns {rows, next_cursor}; pass the returned "
            "cursor back to walk pages. Facet filters do not apply in this mode."
        ),
    ),
    cursor: Optional[str] = Query(
        None, description="Opaque keyset cursor from a prior page's next_cursor."
    ),
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Paginated parts×decisions grid for the caller's organization.

    Every cell is read verbatim from the engine's own serialization — a missing
    field is null, never fabricated. Filters apply to real derived fields BEFORE
    pagination, so ``total`` and the page are always mutually consistent.

    ``keyset=true`` opts into the SCALE path: the grid is served one keyset page at
    a time from the materialized ``part_summaries`` projection (whole-inventory,
    never capped) as ``{rows, next_cursor}``. The default offset path below is
    otherwise byte-identical to before.
    """
    # Validate the state facet up front (400 beats silently returning empty).
    canonical_state: Optional[str] = None
    if state is not None:
        canonical_state = _STATES.get(state.strip().lower())
        if canonical_state is None:
            raise HTTPException(
                status_code=400,
                detail="Invalid state: expected 'Drafted' or 'Costed'",
            )

    # The tenant boundary: the caller's org (single-org v1). None → no membership
    # (e.g. a mocked session) → an empty catalog, never a cross-org read.
    org_id = await resolve_org(session, user.user_id)

    # SCALE mode: keyset page over the materialized projection (opt-in, so the
    # default response shape stays unchanged for existing callers).
    if keyset:
        from src.services import part_summary_service

        try:
            page = await svc.build_catalog_page(
                session, org_id, cursor=cursor, limit=page_size
            )
        except svc.InvalidCursorError:
            # The client sent an undecodable cursor — a 400, never a 500.
            raise HTTPException(status_code=400, detail="invalid cursor")
        # Cold-projection fallback (READ-ONLY, mirrors the /triage path): if the
        # first page is empty but the org actually has parts, the projection is
        # cold (data predating it / a deploy before the one-time backfill). Don't
        # silently show an empty grid for a non-empty org — fall back to the
        # legacy capped catalog for this response (honest: `truncated` flags it),
        # no write on the GET. Once the backfill runs / new writes land, the
        # uncapped keyset path takes over. Only checked on the FIRST page (no
        # cursor) so mid-walk pages are never misread as "cold".
        if (
            org_id
            and cursor is None
            and not page["rows"]
            and await part_summary_service.org_has_raw_parts(session, org_id)
        ):
            built = await svc.build_catalog(session, org_id)
            return {
                "rows": built["rows"],
                "next_cursor": None,
                "cold_projection": True,
                "truncated": built["truncated"],
            }
        return page

    built = await svc.build_catalog(session, org_id)
    all_rows = built["rows"]

    # Facet summary over the FULL org catalog (pre-filter) so the UI's filter
    # chips reflect everything available, independent of the current selection.
    facets = svc.compute_facets(all_rows)

    filtered = [
        r
        for r in all_rows
        if svc.matches_filters(
            r,
            state=canonical_state,
            route=route,
            has_findings=has_findings,
        )
    ]

    total = len(filtered)
    total_pages = max(1, math.ceil(total / page_size)) if total else 0
    start = (page - 1) * page_size
    page_rows = filtered[start : start + page_size]

    return {
        "rows": page_rows,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "has_more": start + page_size < total,
        },
        "facets": facets,
        # Honest: true when the org exceeded the scan cap and some older parts
        # were not included (never a silent omission).
        "truncated": built["truncated"],
        "filters": {
            "state": canonical_state,
            "route": route,
            "has_findings": has_findings,
        },
    }


@router.get("/portfolio")
@limiter.limit("60/hour;500/day")
async def get_portfolio(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Org-scoped portfolio roll-up: the caller's COSTED parts ranked by the
    engine's redesign savings, plus a posture aggregate (W3).

    HONEST BY CONSTRUCTION: every ``savings`` figure is a delta of two numbers the
    engine already computed and persisted (``decision.recommendation`` vs
    ``decision.if_redesigned`` at a quoted qty) — never a fabricated %/$ or a
    portfolio "total spend" (demand quantities are unknown). A costed part with no
    engine savings signal carries ``savings: null`` + a reason. ``validated`` is
    copied from the confidence band, never set here. Parts with no cost decision
    are excluded from the ranking (``excluded_no_cost_count``).

    W3.5 rung-1: when a part has a USER-DECLARED context (program / assembly /
    annual volume), each row additionally carries a ``context`` block and honest
    annualized ``$/year`` figures — present ONLY when an annual_volume was
    declared (else null + a reason), never a fabricated demand quantity. When no
    context is declared anywhere in the org, the response is byte-identical to W3.
    """
    # Tenant boundary: the caller's org. None → no membership → empty roll-up.
    org_id = await resolve_org(session, user.user_id)
    built = await svc.build_portfolio(session, org_id)

    summary = built["summary"]
    resp = {
        "summary": summary,
        "rows": built["rows"],
    }
    # When the scan was capped, say so plainly: the roll-up covers only the most
    # recent parts, not the full history.
    if summary.get("truncated"):
        resp["note"] = (
            "This roll-up is over a capped scan of the most recent parts; "
            "older parts were not included."
        )
    # Additive + gated: only when at least one program is declared do we surface
    # the declared-context honesty note (byte-identical to W3 otherwise).
    if summary.get("programs"):
        resp["context_note"] = (
            "Annualized $/year figures are derived from USER-DECLARED annual "
            "volumes (provenance: user); parts without a declared volume show "
            "null, never a fabricated demand quantity."
        )
    return resp


@router.get("/triage")
@limiter.limit("60/hour;500/day")
async def get_triage(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Org-scoped makeability triage roll-up: of the caller's N parts, how many
    are routable to each process and how many are makeable / need review / unknown.

    This is the FIRST value prop (can-we-make-it-and-how) at PORTFOLIO scale — a
    pile of legacy parts summarized into an actionable catalog. It needs no shop
    and no cost validation: the buckets are a pure DFM-makeability lens.

    HONEST BY CONSTRUCTION: every count is a tally of a real engine-derived field
    on the same catalog rows the grid uses. ``makeable`` = routed AND DFM-analyzed
    with zero critical findings; ``needs_review`` = routed but the engine flagged a
    blocking DFM blocker or a critical finding; ``unknown`` = no route OR never
    DFM-analyzed. Every part lands in exactly one bucket (they sum to ``total``); a
    part with no analysis is never assumed makeable. When the org scan was capped,
    ``truncated`` is true and a ``note`` says so — full coverage is never implied.

    Empty org → a zeroed summary (not an error). Program grouping is additive:
    present only when a part carries a USER-DECLARED program.
    """
    # Tenant boundary: the caller's org. None → no membership → zeroed summary.
    org_id = await resolve_org(session, user.user_id)
    # SCALE (Aramco GAP 2): the whole-inventory triage COUNT is a SQL GROUP BY over
    # the materialized part-summary projection — O(buckets), never capped — instead
    # of folding the 2000 newest raw rows in Python. Byte-identical output shape.
    built = await svc.build_triage_scaled(session, org_id)

    # Cold-projection fallback (READ-ONLY — no write on a GET). If the scaled
    # projection is empty but the org actually has parts (data predating the
    # projection, or a deploy that shipped before the one-time backfill ran), we
    # do NOT synchronously backfill the whole org inside a read request — for a
    # million-part org that would be an unbounded, request-blocking write. Instead
    # we fall back to the LEGACY capped fold for THIS response: honest
    # (``truncated:true`` says coverage is partial), bounded (≤ the scan cap), and
    # read-only. Once the deploy backfill runs (or new writes land via the persist
    # hooks), the uncapped scaled path takes over automatically. A genuinely empty
    # org has no raw parts → the scaled zero is correct and we never touch legacy.
    if org_id and built["summary"]["total"] == 0:
        from src.services import part_summary_service

        if await part_summary_service.org_has_raw_parts(session, org_id):
            built = await svc.build_triage(session, org_id)

    summary = built["summary"]
    resp = {
        "summary": summary,
        "by_process": built["by_process"],
    }
    if built.get("programs"):
        resp["programs"] = built["programs"]
    # When the scan was capped, say so plainly: the triage covers only the most
    # recent parts, not the full history — never a silent implication of coverage.
    if summary.get("truncated"):
        resp["note"] = (
            "This makeability triage is over a capped scan of the most recent "
            "parts; older parts were not counted."
        )
    return resp


@router.get("/makeability")
@limiter.limit("60/hour;500/day")
async def get_makeability(
    request: Request,
    response: Response,
    bucket: Optional[str] = Query(
        None,
        description=(
            "Drill-down mode: return one keyset page of the parts in this "
            "makeability bucket (makeable_in_house | makeable_outside | "
            "needs_capability | not_makeable | unknown | geometry_invalid). "
            "Omit for the rollup."
        ),
    ),
    cursor: Optional[str] = Query(
        None, description="Opaque keyset cursor from a prior drill-down page."
    ),
    page_size: int = Query(100, ge=1, le=500, description="Drill-down page size."),
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Org-scoped IN-HOUSE makeability breakdown (Phase D — spec §10 D3).

    Refines the DFM triage with the machine-inventory §0 verdict: of the caller's N
    parts, how many are makeable on OWNED equipment (``makeable_in_house``), buyable
    but on no owned family (``makeable_outside``), owned-family-but-no-fit with a
    concrete gap (``needs_capability``), not makeable / environment-excluded
    (``not_makeable``), unevaluated (``unknown`` — no declared inventory or not
    costed), or geometry-invalid.

    A SQL GROUP BY over the materialized ``part_summaries`` projection — O(buckets),
    whole inventory, never capped. HONEST: verdicts are projections of the Phase-C
    verification block the cost path already computed (never re-invented); a verdict
    computed against inventory that has since changed is carried as STALE (a visible
    count + flag), never served as fresh. Empty org → a zeroed rollup.

    ``bucket`` opts into a keyset drill-down (``{rows, next_cursor}``) — each row is
    the catalog row plus a ``makeability`` block ({verdict, stale, gap}) showing WHY.
    """
    org_id = await resolve_org(session, user.user_id)

    # ── drill-down mode: one keyset page of a single bucket ──────────────────
    if bucket is not None:
        b = bucket.strip()
        if b not in svc.MAKEABILITY_BUCKETS:
            raise HTTPException(
                status_code=400,
                detail=(
                    "invalid bucket: expected one of "
                    + ", ".join(svc.MAKEABILITY_BUCKETS)
                ),
            )
        try:
            return await svc.build_makeability_bucket_page(
                session, org_id, b, cursor=cursor, limit=page_size
            )
        except svc.InvalidCursorError:
            raise HTTPException(status_code=400, detail="invalid cursor")

    # ── rollup mode ──────────────────────────────────────────────────────────
    built = await svc.build_makeability_rollup(session, org_id)
    summary = built["summary"]
    resp = {"summary": summary, "buckets": list(svc.MAKEABILITY_BUCKETS)}

    # Cold-projection honesty (READ-ONLY — no write on a GET), mirroring /triage: if
    # the projection is empty but the org actually has parts (data predating the
    # projection, or a deploy before the one-time backfill), say so plainly rather
    # than imply a genuinely-empty org. There is no legacy makeability fold to fall
    # back to (this lens is projection-only), so we flag it and point at the fix.
    if org_id and summary["total"] == 0:
        from src.services import part_summary_service

        if await part_summary_service.org_has_raw_parts(session, org_id):
            resp["cold_projection"] = True
            resp["note"] = (
                "The makeability projection is cold for this org (parts predate it, "
                "or the one-time backfill has not run). Run the part-summary "
                "backfill or re-cost parts to populate the in-house breakdown."
            )

    # Staleness is surfaced, never hidden: the counts above INCLUDE stale rows and
    # ``stale_count`` says how many; this note tells the reader how to refresh.
    if summary.get("stale"):
        resp["stale_note"] = (
            f"{summary['stale_count']} verdict(s) predate a recent machine-inventory "
            "change and are marked stale (counted above, never hidden); re-cost the "
            "affected parts to refresh their in-house verdict."
        )

    # If nothing has been evaluated against a declared inventory, say so — an
    # all-'unknown' breakdown is honest, not a bug.
    evaluated = (
        summary["makeable_in_house"] + summary["makeable_outside"]
        + summary["needs_capability"] + summary["not_makeable"]
    )
    if summary["total"] > 0 and evaluated == 0 and not resp.get("cold_projection"):
        resp["evaluation_note"] = (
            "No parts have been evaluated against a declared machine inventory — "
            "in-house makeability is 'unknown'. Declare machines and (re-)cost parts "
            "to populate the breakdown."
        )
    return resp


@router.get("/capability-investment")
@limiter.limit("60/hour;500/day")
async def get_capability_investment(
    request: Request,
    response: Response,
    process: Optional[str] = Query(
        None,
        description=(
            "Drill-down mode: return one keyset page of the parts unlocked by the "
            "acquisition of this process. Omit for the ranking."
        ),
    ),
    gate: Optional[str] = Query(
        None,
        description=(
            "Drill-down: the binding gate of the acquisition (envelope | material | "
            "tolerance | axes | ...). Omit for a pure 'acquire' (owns none of the "
            "family) acquisition."
        ),
    ),
    cursor: Optional[str] = Query(
        None, description="Opaque keyset cursor from a prior drill-down page."
    ),
    page_size: int = Query(100, ge=1, le=500, description="Drill-down page size."),
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Org-scoped CAPABILITY-INVESTMENT ranking (Phase D — spec §10 D4): which ONE
    machine acquisition unlocks the most currently-blocked parts.

    Computed ENTIRELY from stored real gap data — the §0 verdict + the binding
    FitFailure the projection denormalized per part — via one SQL GROUP BY over
    ``(unlock_process, unlock_gate)``. Each entry names the acquisition (process +
    class/envelope spec aggregated from the group's real needs), the parts unlocked
    (count + a keyset drill-down), and its basis. Parts blocked by MULTIPLE
    constraints (no single acquisition unlocks them) are reported separately in
    ``summary.blocked_by_multiple_constraints`` — never folded into an entry. NO
    acquisition dollar cost is fabricated (none is available from engine data). A
    stale entry (verdict predates a machine change) carries ``stale: true`` + a
    count.

    ``process`` opts into a keyset drill-down of the parts that acquisition unlocks.
    """
    org_id = await resolve_org(session, user.user_id)

    # ── drill-down mode: the parts a specific acquisition unlocks ────────────
    if process is not None:
        try:
            return await svc.build_capability_investment_page(
                session,
                org_id,
                process.strip(),
                gate.strip() if gate else None,
                cursor=cursor,
                limit=page_size,
            )
        except svc.InvalidCursorError:
            raise HTTPException(status_code=400, detail="invalid cursor")

    # ── ranking mode ─────────────────────────────────────────────────────────
    built = await svc.build_capability_investment(session, org_id)
    resp = {"ranking": built["ranking"], "summary": built["summary"]}
    resp["basis_note"] = (
        "Ranking counts parts whose SINGLE binding constraint one acquisition "
        "closes, computed only from stored gap data. Parts blocked by multiple "
        "constraints are reported in blocked_by_multiple_constraints and never "
        "folded in. No acquisition dollar cost is shown — none is available from "
        "engine data (never fabricated)."
    )
    if built["summary"].get("stale"):
        resp["stale_note"] = (
            "Some ranked verdicts predate a recent machine-inventory change and are "
            "marked stale (flagged per entry, never hidden); re-cost the affected "
            "parts to refresh."
        )
    if not built["ranking"] and built["summary"]["total_blocked"] == 0:
        resp["note"] = (
            "No single-acquisition unlock opportunities found — either nothing is "
            "currently blocked, or the makeability projection is cold (see "
            "GET /catalog/makeability for coverage)."
        )
    return resp
