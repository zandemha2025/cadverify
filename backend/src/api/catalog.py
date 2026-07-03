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
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Paginated parts×decisions grid for the caller's organization.

    Every cell is read verbatim from the engine's own serialization — a missing
    field is null, never fabricated. Filters apply to real derived fields BEFORE
    pagination, so ``total`` and the page are always mutually consistent.
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
