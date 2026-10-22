"""Cost-decision service — persist, dedup, list, detail, share, compare, export.

Closes Phase 2 gap #3: the should-cost / make-vs-buy decision (computed by the
costing layer and serialized via ``report_to_dict``) is turned into a durable,
exportable, shareable, comparable artifact. Mirrors ``analysis_service`` (hash +
dedup + persist), ``share_service`` (short-id share/sanitize), and
``history.py`` (cursor pagination).

The persisted/exported artifact carries the SAME honesty as the live decision:
provenance tags stay intact and the confidence band is never presented as
"validated" — persistence must not launder an unvalidated number into something
that looks certified.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.auth.org_context import caller_org_subquery
from src.auth.require_api_key import AuthedUser
from src.costing.footing import footed_items
from src.db.models import CostDecision, UsageEvent
from src.services import share_links
from src.services.share_service import generate_short_id

logger = logging.getLogger("cadverify.cost_decision_service")

APPROVAL_UNREVIEWED = "unreviewed"
APPROVAL_APPROVED = "approved"
DISPOSITION_LABELS = {
    "inhouse": "Make in-house",
    "outside": "Make outside",
    "acquire": "Acquire capability",
    "redesign": "Redesign",
    # Bought, as today: from the supplier the org buys it from, at its current price (0064).
    "supplier": "Keep buying from our supplier",
}
# Outcomes that buy the part rather than make it on a machine of yours.
BUY_OUTCOMES = ("outside", "supplier")


def cost_persist_enabled() -> bool:
    """Feature flag COST_PERSIST_ENABLED — default ON for the authed route."""
    return os.getenv("COST_PERSIST_ENABLED", "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


# ---------------------------------------------------------------------------
# Hashing / dedup
# ---------------------------------------------------------------------------


def compute_params_hash(
    *,
    quantities: list,
    region: Optional[str],
    cavities: int,
    complexity: str,
    material_class: str,
    shop: Optional[str],
    overrides: Optional[dict],
    source_units: str = "mm",
    orientation: Optional[str] = None,
    material: Optional[str] = None,
) -> str:
    """SHA-256 of the canonical cost parameters.

    Persistence also binds the computed evidence: inventory, governed rates and
    calibration may change even when these form parameters stay the same.
    """
    from src import __version__

    params = {
        "engine_version": __version__,
        "source_units": source_units,
        "quantities": sorted(quantities),
        "region": region or "US",
        "cavities": int(cavities),
        "complexity": complexity,
        "material_class": material_class,
        "shop": shop or "",
        "overrides": overrides or {},
    }
    if orientation is not None:
        # Only a turned part adds the key, so the file's own hash is unchanged.
        params["orientation"] = orientation
    if material:
        # Only a named material (a parts list's) adds the key; the class alone is unchanged.
        params["material"] = material
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _denormalize(result_json: dict) -> tuple[Optional[str], Optional[float], list]:
    """Pull the listing/filtering columns out of the glass-box artifact."""
    decision = result_json.get("decision") or {}
    make_now = decision.get("make_now_process")
    crossover = decision.get("crossover_qty")
    quantities = result_json.get("quantities") or []
    return make_now, crossover, quantities


# ---------------------------------------------------------------------------
# Persist
# ---------------------------------------------------------------------------


async def _lookup_dedup(
    session: AsyncSession,
    user_id: int,
    mesh_hash: str,
    params_hash: str,
    *,
    org_id: str | None = None,
) -> Optional[CostDecision]:
    org_scope = org_id if org_id is not None else caller_org_subquery(user_id)
    stmt = select(CostDecision).where(
        CostDecision.org_id == org_scope,
        CostDecision.user_id == user_id,
        CostDecision.mesh_hash == mesh_hash,
        CostDecision.params_hash == params_hash,
    )
    return (await session.execute(stmt)).scalars().first()


async def persist_cost_decision(
    session: AsyncSession,
    user: AuthedUser,
    *,
    mesh_hash: str,
    params_hash: str,
    engine_version: str,
    filename: str,
    file_type: str,
    result_json: dict,
    label: Optional[str] = None,
    org_id: str | None = None,
) -> CostDecision:
    """Insert (or return the deduped) CostDecision row and flush to get its ulid.

    Dedup binds the form parameters AND the complete computed evidence. A new
    inventory, rate or calibration result must not link to an older snapshot.
    Identical evidence reuses its row inside one tenant; historical rows remain
    immutable. Legacy parameter-only rows are retained, never rewritten.
    Delayed workers pass their parent row's immutable ``org_id`` explicitly.
    Race-safe via IntegrityError re-query (mirrors analysis_service).
    """
    # Normalize quantity keys exactly as JSONB does before canonical sorting.
    snapshot = json.loads(json.dumps(result_json))
    params_hash = hashlib.sha256(json.dumps(
        [params_hash, engine_version, snapshot], sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    existing = await _lookup_dedup(
        session,
        user.user_id,
        mesh_hash,
        params_hash,
        org_id=org_id,
    )
    if existing is not None:
        logger.info(
            "Cost-decision dedup hit for user=%s mesh=%.12s…", user.user_id, mesh_hash
        )
        # A dedup hit must still RECONCILE the part-summary projection (the newest
        # analysis for this mesh may have landed after the decision) — idempotent,
        # graceful-degrade, same-transaction.
        await _refresh_summary_for(session, existing)
        return existing

    make_now, crossover, quantities = _denormalize(result_json)

    from src.auth.org_context import resolve_org

    persisted_org_id = (
        org_id if org_id is not None else await resolve_org(session, user.user_id)
    )
    decision = CostDecision(
        ulid=str(ULID()),
        user_id=user.user_id,
        org_id=persisted_org_id,
        api_key_id=user.api_key_id or None,
        mesh_hash=mesh_hash,
        params_hash=params_hash,
        engine_version=engine_version,
        filename=filename,
        file_type=file_type,
        result_json=result_json,
        make_now_process=make_now,
        crossover_qty=crossover,
        quantities=quantities,
        label=label,
    )
    session.add(decision)
    try:
        await session.flush()  # assign id; surface dedup races as IntegrityError
    except IntegrityError:
        await session.rollback()
        logger.info(
            "IntegrityError on cost-decision dedup insert (race), re-querying user=%s",
            user.user_id,
        )
        existing = await _lookup_dedup(
            session,
            user.user_id,
            mesh_hash,
            params_hash,
            org_id=org_id,
        )
        if existing is not None:
            await _refresh_summary_for(session, existing)
            return existing
        raise

    await _refresh_summary_for(session, decision)

    # A part checked inside a batch or catalog run doesn't notify one by one: the
    # run says once when it has finished (batch_tasks._notify_run_finished).
    in_a_run = getattr(user, "key_prefix", None) == "batch"
    try:
        from src.services import notification_service

        if not in_a_run:
            await notification_service.emit_notification(
                session,
                org_id=decision.org_id,
                actor_user_id=user.user_id,
                kind="decision.created",
                severity="pass",
                title=f"Verification recorded - {filename}",
                body=(
                    f"make-now {make_now}" if make_now else "cost decision recorded"
                ),
                dest="records",
                source_type="cost_decision",
                source_id=decision.ulid,
                metadata={"filename": filename, "crossover_qty": crossover},
            )
    except Exception:
        logger.warning(
            "Failed to emit decision.created notification for %s",
            decision.ulid,
            exc_info=True,
        )

    # Audit: decision.created. Added to the same transaction as the decision so
    # the decision and its evidence cannot diverge.
    from src.services.audit_service import emit_event

    await emit_event(
        session,
        actor_id=user.user_id,
        action="decision.created",
        resource_type="cost_decision",
        resource_id=decision.ulid,
        detail={
            "org_id": decision.org_id,
            "filename": decision.filename,
            "make_now_process": make_now,
            "crossover_qty": crossover,
        },
        org_id=decision.org_id,
    )
    return decision


async def _refresh_summary_for(session: AsyncSession, decision: CostDecision) -> None:
    """Maintain the materialized per-part catalog projection for a persisted (or
    deduped) cost decision — Aramco GAP 2. Graceful-degrade + same-transaction:
    delegated to ``part_summary_service.refresh_part_summary_safe`` which isolates
    any failure in a SAVEPOINT and swallows it, so a broken projection never
    breaks the live cost persist."""
    from src.services import part_summary_service

    # mark_makeability_fresh=True: the cost decision's Phase-C verification block was
    # just computed against the org's CURRENT inventory, so this part's makeability
    # is fresh — clear any stale flag a prior machine change set on it.
    await part_summary_service.refresh_part_summary_safe(
        session, decision.org_id, decision.mesh_hash,
        mark_makeability_fresh=True,
    )


async def record_persist_failure(
    session: AsyncSession,
    user: AuthedUser,
    *,
    mesh_hash: Optional[str],
    error: BaseException,
) -> None:
    """Best-effort observability for a failed cost-decision persist.

    Called from the graceful-degrade ``except`` in routes.py: persistence
    must never break the live decision the buyer sees, so this function is
    not allowed to raise either. It (1) logs the exception at WARNING so
    it's no longer silent, and (2) appends a ``usage_events`` row so the
    failure rate is queryable, not just grep-able.

    Rolls back first: the triggering exception may have left the session's
    transaction in a state that rejects further flush/commit (e.g. any
    non-``IntegrityError`` DB failure inside ``persist_cost_decision``), and
    an unrecoverable session would otherwise surface as a 500 at the
    request-scoped commit in ``get_db_session`` — turning the "graceful"
    degrade into a crash. Rolling back is safe here because persisting a
    cost decision touches no other rows in this request's transaction.
    """
    logger.warning(
        "Cost-decision persistence failed for user=%s mesh=%.12s…: %s",
        user.user_id,
        mesh_hash or "?",
        error,
        exc_info=error,
    )
    try:
        await session.rollback()
        from src.auth.org_context import resolve_org

        session.add(
            UsageEvent(
                user_id=user.user_id,
                org_id=await resolve_org(session, user.user_id),
                api_key_id=user.api_key_id or None,
                event_type="cost_persist_failed",
                mesh_hash=mesh_hash,
            )
        )
        await session.flush()
    except Exception:
        # The telemetry write itself must degrade gracefully too — a DB
        # that's too unhealthy to take a usage-event insert is already
        # loudly logged above; don't let this raise into the response.
        logger.warning(
            "Failed to record cost_persist_failed usage event for user=%s",
            user.user_id,
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# List / detail (owner-scoped)
# ---------------------------------------------------------------------------


def _list_item(d: CostDecision) -> dict:
    return {
        "id": d.ulid,
        "mesh_hash": d.mesh_hash,
        "filename": d.filename,
        "file_type": d.file_type,
        "label": d.label,
        "make_now_process": d.make_now_process,
        "crossover_qty": d.crossover_qty,
        "quantities": d.quantities or [],
        "created_at": d.created_at.isoformat(),
        **share_links.fields(d),
        **governance_fields(d),
    }


# ── latest saved record per part, in one read (Rates / Real costs screens) ────
LATEST_PARTS_MAX = 500
LATEST_DETAILS_MAX = 50


def headline_qty(quantities: Any) -> Optional[int]:
    """The quantity the shop screens headline: 10 when the check priced 10, else
    its first quantity (the same rule as the screens' ``headlineQty``)."""
    if not isinstance(quantities, list) or not quantities:
        return None
    return 10 if 10 in quantities else quantities[0]


def slim_result(result_json: Any, quantities: Any) -> dict:
    """The parts of a saved decision the Rates and Real costs screens read:
    assumptions, the material class, the decision's pick per quantity, and the
    estimates at the headline quantity (the screens' headline estimate is one
    of them). The full record stays at GET /cost-decisions/{id}."""
    r = result_json if isinstance(result_json, dict) else {}
    qty = headline_qty(quantities)
    decision = r.get("decision") if isinstance(r.get("decision"), dict) else None
    return {
        "assumptions": r.get("assumptions") or [],
        "material_class": r.get("material_class"),
        "decision": (
            {k: decision.get(k) for k in ("make_now_process", "make_now_material", "recommendation")}
            if decision is not None else None
        ),
        "estimates": [
            e for e in (r.get("estimates") or [])
            if isinstance(e, dict) and qty is not None and e.get("quantity") == qty
        ],
    }


async def latest_per_part(
    session: AsyncSession,
    user_id: int,
    *,
    limit: int = LATEST_PARTS_MAX,
    detail_limit: int = 12,
) -> dict:
    """The newest saved decision for each part (by mesh hash) in the caller's
    org, newest first, plus the screens' fields for the newest ``detail_limit``
    parts. Org-scoped exactly like the list and detail reads.

    Two queries whatever the number of parts: the summaries (no result JSON),
    then the slim results for the parts shown with details.
    """
    from sqlalchemy import func
    from sqlalchemy.orm import defer

    limit = max(1, min(int(limit), LATEST_PARTS_MAX))
    detail_limit = max(0, min(int(detail_limit), LATEST_DETAILS_MAX))
    ranked = (
        select(
            CostDecision.id.label("id"),
            func.row_number().over(
                partition_by=CostDecision.mesh_hash,
                order_by=CostDecision.ulid.desc(),
            ).label("rn"),
        )
        .where(CostDecision.org_id == caller_org_subquery(user_id))
        .subquery()
    )
    newest = select(ranked.c.id).where(ranked.c.rn == 1)
    total = (await session.execute(select(func.count()).select_from(newest.subquery()))).scalar_one()
    rows = (await session.execute(
        select(CostDecision)
        .options(defer(CostDecision.result_json))
        .where(CostDecision.id.in_(newest))
        .order_by(CostDecision.ulid.desc())
        .limit(limit)
    )).scalars().all()
    shown = rows[:detail_limit]
    from src.services.rate_card_basis import basis_for

    rates = await basis_for(session, rows[0].org_id, rows) if rows else {}
    results: dict = {}
    if shown:
        found = (await session.execute(
            select(CostDecision.id, CostDecision.result_json)
            .where(CostDecision.id.in_([d.id for d in shown]))
        )).all()
        results = {row_id: rj for row_id, rj in found}
    return {
        "parts": [{**_list_item(d), "rates": rates.get(d.ulid)} for d in rows],
        "total_parts": int(total or 0),
        "has_more": int(total or 0) > len(rows),
        "details": [
            {
                **_list_item(d),
                "rates": rates.get(d.ulid),
                "headline_qty": headline_qty(d.quantities),
                "result": slim_result(results.get(d.id), d.quantities),
            }
            for d in shown
        ],
    }


def _iso(dt) -> str | None:
    return dt.isoformat() if isinstance(dt, datetime) else None


def _is_stale(d: CostDecision, now: datetime | None = None) -> bool:
    stale_at = getattr(d, "stale_at", None)
    if not isinstance(stale_at, datetime):
        return False
    now = now or datetime.now(timezone.utc)
    if stale_at.tzinfo is None:
        stale_at = stale_at.replace(tzinfo=timezone.utc)
    return stale_at <= now


def governance_fields(d: CostDecision) -> dict:
    """Serializable signoff/staleness metadata for list/detail/public-safe reads.

    ``is_stale`` is time-aware: a library publish scheduled in the future records
    ``stale_at`` now, but does not claim the saved decision is stale until that
    effective instant arrives.
    """
    raw_disposition = getattr(d, "user_disposition", None)
    disposition = raw_disposition if isinstance(raw_disposition, str) else None
    return {
        "approval_status": getattr(d, "approval_status", None) or APPROVAL_UNREVIEWED,
        "approved_by_user_id": getattr(d, "approved_by_user_id", None),
        "approved_at": _iso(getattr(d, "approved_at", None)),
        "approval_note": getattr(d, "approval_note", None),
        "is_stale": _is_stale(d),
        "stale_at": _iso(getattr(d, "stale_at", None)),
        "stale_reason": getattr(d, "stale_reason", None),
        "user_disposition": disposition,
        "user_disposition_label": (
            DISPOSITION_LABELS.get(disposition)
            if disposition is not None
            else None
        ),
        "disposition_note": getattr(d, "disposition_note", None),
        "disposition_basis": getattr(d, "disposition_basis", None),
        "disposition_updated_at": _iso(
            getattr(d, "disposition_updated_at", None)
        ),
        "disposition_updated_by_user_id": getattr(
            d, "disposition_updated_by_user_id", None
        ),
    }


async def get_owned(
    session: AsyncSession, ulid: str, user_id: int
) -> CostDecision:
    """Fetch a cost decision by ulid, scoped to the caller's org, or 404.

    W1 step 3: the isolation predicate is ``org_id`` (the tenant boundary),
    resolved from ``user_id`` via a correlated subquery. A decision in another
    org is invisible → 404 (never 403, so existence never leaks across tenants).
    """
    stmt = select(CostDecision).where(
        CostDecision.ulid == ulid,
        CostDecision.org_id == caller_org_subquery(user_id),
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Cost decision not found")
    return row


def _clean_note(note: Optional[str]) -> Optional[str]:
    if note is None:
        return None
    note = note.strip()
    if not note:
        return None
    return note[:1000]


async def approve_owned(
    session: AsyncSession,
    ulid: str,
    user_id: int,
    *,
    note: Optional[str] = None,
) -> CostDecision:
    """Approve/sign off a saved decision in the caller's org."""
    d = await get_owned(session, ulid, user_id)
    d.approval_status = APPROVAL_APPROVED
    d.approved_by_user_id = user_id
    d.approved_at = datetime.now(timezone.utc)
    d.approval_note = _clean_note(note)
    await session.commit()
    logger.info("Cost decision %s approved by user %d", ulid, user_id)
    return d


async def reopen_owned(
    session: AsyncSession,
    ulid: str,
    user_id: int,
) -> CostDecision:
    """Remove approval from a saved decision without deleting the artifact."""
    d = await get_owned(session, ulid, user_id)
    d.approval_status = APPROVAL_UNREVIEWED
    d.approved_by_user_id = None
    d.approved_at = None
    d.approval_note = None
    await session.commit()
    logger.info("Cost decision %s approval reopened by user %d", ulid, user_id)
    return d


def _disposition_estimate(
    result_json: object,
    quantity: int | None,
    process: str | None = None,
    material: str | None = None,
) -> dict | None:
    """Resolve an exact engine estimate; never accept a client-priced route.

    Without ``process`` this is the engine's own recommendation at the quantity
    (the cheapest eligible route). With ``process`` (and optionally ``material``)
    it is the user's chosen route, which must be one of this decision's own
    estimates at exactly that quantity. An ambiguous choice (one process costed
    in several materials, no material named) resolves to nothing.
    """
    if not isinstance(result_json, dict):
        return None
    estimates = [e for e in result_json.get("estimates", []) if isinstance(e, dict)]
    quantities = [e["quantity"] for e in estimates if type(e.get("quantity")) is int and e["quantity"] > 0]
    if quantity is None:
        quantity = min(quantities, default=None)
    if process is not None:
        chosen = [e for e in estimates if e.get("quantity") == quantity
                  and e.get("process") == process
                  and (material is None or e.get("material") == material)]
        return chosen[0] if len(chosen) == 1 else None
    decision = result_json.get("decision") or {}
    recommendations = decision.get("recommendation") or {}
    pick = recommendations.get(str(quantity), recommendations.get(quantity)) if recommendations else {
        "process": decision.get("make_now_process"), "material": decision.get("make_now_material")
    }
    if not pick or not pick.get("process"):
        return None
    matches = [e for e in estimates if e.get("quantity") == quantity
               and e.get("process") == pick["process"]
               and (not pick.get("material") or e.get("material") == pick["material"])]
    return matches[0] if len(matches) == 1 else None


def _inhouse_disposition_error(result_json: dict, estimate: dict | None) -> str | None:
    if not estimate:
        return "Select a computed quantity before recording Make in-house."
    if (result_json.get("status") == "GEOMETRY_INVALID" or estimate.get("dfm_ready") is not True
            or estimate.get("dfm_verdict") == "fail" or estimate.get("environment_excluded")
            or estimate.get("dfm_blockers")):
        return "Make in-house is unavailable while the selected route is blocked by DFM. Record Redesign, Make outside, or Acquire capability, or verify revised CAD that passes route DFM."
    if estimate.get("spec_excluded"):
        return ("This route can't meet the part's declared specs. "
                + (estimate.get("spec_exclusion_reason") or "")).strip()
    fit = ((result_json.get("verification") or {}).get("per_route") or {}).get(estimate["process"]) or {}
    if fit.get("verdict") not in ("makeable_in_house", "makeable_with_secondary_op"):
        return "Owned-machine fit is not verified for this route. Declare a fitting machine and re-verify before recording Make in-house."
    return None


def _chosen_route_error(disposition: str, estimate: dict) -> str | None:
    """Rules for a route the user picked instead of the engine's cheapest.

    A route the declared service environment rules out can't carry any outcome,
    and Make outside means making the part as drawn, so its route must pass DFM.
    Redesign and Acquire capability may name a DFM-blocked route: that is the
    route the redesign or the investment is for.
    """
    if estimate.get("environment_excluded"):
        return "The declared service conditions rule out this route. Choose a route that survives them."
    if estimate.get("spec_excluded") and disposition in ("inhouse", "outside"):
        return ("This route can't meet the part's declared specs: "
                + (estimate.get("spec_exclusion_reason") or "see its findings")
                + " Choose a route that meets them, or record Redesign.")
    if disposition == "outside" and (
        estimate.get("dfm_ready") is not True
        or estimate.get("dfm_verdict") == "fail"
        or estimate.get("dfm_blockers")
    ):
        return "This route can't make the part as drawn. Record Redesign for it, or choose a route that passes DFM."
    return None


async def _supplier_basis(session: AsyncSession, d: CostDecision, quantity: int | None,
                          prior: Any) -> dict:
    """What "Keep buying from our supplier" records: the quantity and today's price.

    ``{"supplier": True, "quantity", "usd_each", "price_source"}``. The price is
    the part's current price (typed on its Decision view, or from a catalog
    run's parts list), or None when none is known: the outcome stands without
    one, it just has no figure. The quantity is the one decided at, else the
    one recorded before, else the part's yearly quantity.
    """
    from src.services import part_context_service as pcs

    ctx = await pcs.get_context(session, d.org_id, d.mesh_hash) if d.mesh_hash else None
    price = getattr(ctx, "buy_price", None) if ctx is not None else None
    usd = price.get("usd_each") if isinstance(price, dict) else None
    if quantity is None and isinstance(prior, dict):
        quantity = prior.get("quantity")
    if quantity is None and ctx is not None:
        quantity = getattr(ctx, "annual_volume", None)
    return {"supplier": True, "quantity": int(quantity) if quantity else None,
            "usd_each": float(usd) if isinstance(usd, (int, float)) and usd > 0 else None,
            "price_source": price.get("source") if isinstance(price, dict) and usd else None}


async def set_disposition_owned(
    session: AsyncSession,
    ulid: str,
    user_id: int,
    *,
    disposition: Optional[str],
    note: Optional[str] = None,
    quantity: int | None = None,
    process: str | None = None,
    material: str | None = None,
) -> CostDecision:
    """Persist or withdraw the human outcome on an owned cost decision.

    ``result_json`` remains immutable engine evidence. The disposition records
    the accountable user's follow-through. Any real change reopens an existing
    approval, because a prior signoff must never silently govern a new outcome.
    Repeating an identical PUT is idempotent and does not rewrite timestamps or
    append duplicate audit entries.

    ``process``/``material`` record the route the user chose. Without them the
    basis is the engine's recommendation at the quantity (the original
    behaviour). With them the route must be one of this decision's own
    estimates at that quantity. A note-only edit keeps the recorded route.
    """
    if disposition is not None and disposition not in DISPOSITION_LABELS:
        raise HTTPException(status_code=400, detail="Invalid decision disposition")
    if quantity is not None and (type(quantity) is not int or quantity <= 0):
        raise HTTPException(status_code=400, detail="Quantity must be a positive whole number")
    if material is not None and process is None:
        raise HTTPException(status_code=400, detail="Name the process along with its material")
    if note is not None and len(note) > 1000:
        raise HTTPException(
            status_code=400,
            detail="Disposition note must be 1000 characters or fewer",
        )

    d = await get_owned(session, ulid, user_id)
    clean_note = _clean_note(note) if disposition is not None else None
    previous = getattr(d, "user_disposition", None)
    previous_note = getattr(d, "disposition_note", None)
    previous_basis = getattr(d, "disposition_basis", None)
    basis = previous_basis if disposition is not None else None
    estimate = None
    if disposition == "supplier":
        if process is not None:
            raise HTTPException(status_code=400, detail="Keep buying from our supplier names no process of ScaleCAD's")
        basis = await _supplier_basis(session, d, quantity, previous_basis if previous == "supplier" else None)
    elif disposition is not None:
        if quantity is not None or process is not None or previous is None or previous_basis:
            prior = previous_basis if isinstance(previous_basis, dict) else {}
            selected_quantity = quantity if quantity is not None else prior.get("quantity")
            chosen = process is not None
            if chosen:
                estimate = _disposition_estimate(d.result_json, selected_quantity, process, material)
                if not estimate:
                    raise HTTPException(status_code=409, detail="This decision has no single computed estimate for that route at this quantity. Pick a route and quantity from the record.")
                error = _chosen_route_error(disposition, estimate)
                if error:
                    raise HTTPException(status_code=409, detail=error)
            elif quantity is None and prior.get("process"):
                # A note-only edit keeps the route already on the record,
                # including one the user chose over the cheapest.
                estimate = _disposition_estimate(
                    d.result_json, selected_quantity, prior.get("process"), prior.get("material")
                )
            else:
                estimate = _disposition_estimate(d.result_json, selected_quantity)
            if not estimate:
                raise HTTPException(status_code=409, detail="No exact computed recommendation exists at this quantity. Re-verify before recording an outcome.")
            basis = {key: estimate[key] for key in ("process", "material", "quantity")}
        # Note-only edits preserve historical outcomes, including unscoped legacy records.
        if disposition == "inhouse" and (quantity is not None or process is not None or previous != disposition):
            error = _inhouse_disposition_error(d.result_json, estimate)
            if error:
                raise HTTPException(status_code=409, detail=error)

    if previous == disposition and previous_note == clean_note and previous_basis == basis:
        return d

    approval_reopened = (
        getattr(d, "approval_status", APPROVAL_UNREVIEWED) == APPROVAL_APPROVED
    )
    d.user_disposition = disposition
    d.disposition_note = clean_note
    d.disposition_basis = basis
    d.disposition_updated_at = datetime.now(timezone.utc)
    d.disposition_updated_by_user_id = user_id

    if approval_reopened:
        d.approval_status = APPROVAL_UNREVIEWED
        d.approved_by_user_id = None
        d.approved_at = None
        d.approval_note = None

    from src.services.audit_service import emit_event

    await emit_event(
        session,
        actor_id=user_id,
        action=(
            "decision.disposition_withdrawn"
            if disposition is None
            else "decision.disposition_recorded"
        ),
        resource_type="cost_decision",
        resource_id=d.ulid,
        detail={
            "org_id": d.org_id,
            "previous_disposition": previous,
            "disposition": disposition,
            "previous_basis": previous_basis,
            "disposition_basis": basis,
            "approval_reopened": approval_reopened,
        },
        org_id=d.org_id,
    )
    await session.commit()
    logger.info(
        "Cost decision %s disposition changed from %s to %s by user %d",
        ulid,
        previous,
        disposition,
        user_id,
    )
    return d


# stale_reason for a decision that predates a change to the org's declared
# machines or shop secondary ops: its §0 verdict and its owned-machine costing
# were computed against the old inventory.
MACHINE_INVENTORY_STALE_REASON = "machine_inventory_changed"


async def mark_org_decisions_stale(
    session: AsyncSession,
    org_id: str,
    *,
    reason: str,
    stale_at: Optional[datetime] = None,
) -> int:
    """Mark existing org decisions stale after governed assumptions change.

    This is deliberately additive: the saved glass-box artifact is never edited.
    It gains a stale marker saying the record predates a governed library update
    (or a machine-inventory change, ``MACHINE_INVENTORY_STALE_REASON``) and
    should be re-costed before being used as a current decision.
    """
    when = stale_at or datetime.now(timezone.utc)
    result = await session.execute(
        update(CostDecision)
        .where(
            CostDecision.org_id == org_id,
            CostDecision.created_at < when,
            CostDecision.stale_at.is_(None),
        )
        .values(stale_at=when, stale_reason=reason)
    )
    return int(getattr(result, "rowcount", 0) or 0)


# stale_reasons for a decision whose part's declared inputs changed after it was
# computed (the part context PUT), or whose organization applied or undid a
# calibration of its estimates (the actuals calibration routes).
PART_SPECS_STALE_REASON = "part_specs_changed"
CONDITIONS_STALE_REASON = "conditions_changed"
CALIBRATION_STALE_REASON = "calibration_changed"


async def mark_part_decisions_stale(
    session: AsyncSession,
    org_id: str,
    mesh_hash: str,
    *,
    reason: str,
    stale_at: Optional[datetime] = None,
) -> int:
    """Mark the org's saved decisions for ONE part stale (its declared inputs changed).

    Additive like ``mark_org_decisions_stale``: the saved artifact is never
    edited, and a decision already marked keeps its first reason. A signed-off
    decision keeps its sign-off; the stale marker says plainly that what it was
    signed off on has since changed.
    """
    when = stale_at or datetime.now(timezone.utc)
    result = await session.execute(
        update(CostDecision)
        .where(
            CostDecision.org_id == org_id,
            CostDecision.mesh_hash == mesh_hash,
            CostDecision.created_at < when,
            CostDecision.stale_at.is_(None),
        )
        .values(stale_at=when, stale_reason=reason)
    )
    return int(getattr(result, "rowcount", 0) or 0)


# ---------------------------------------------------------------------------
# CSV export — estimates / line-items table
# ---------------------------------------------------------------------------


def spreadsheet_safe_cell(value):
    """Neutralize formula-capable text while preserving JSON/source records.

    Spreadsheet programs may execute cells beginning with =, +, -, or @ (also
    after leading whitespace/control characters). Prefixing an apostrophe is the
    conventional CSV display escape: users see the original text, while the
    imported cell is data rather than a formula. Numeric values stay numeric.
    """
    if not isinstance(value, str) or not value:
        return value
    candidate = value.lstrip(" \t\r\n")
    if value[0] in "\t\r\n" or candidate.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


_GOVERNANCE_COLUMNS = (
    "approval_status",
    "approved_by_user_id",
    "approved_at",
    "approval_note",
    "user_disposition",
    "user_disposition_label",
    "disposition_note",
    "disposition_basis",
    "disposition_updated_at",
    "disposition_updated_by_user_id",
)
# A supplier's copy (RFQ package) states the review status only; approvers,
# the recorded outcome and its notes stay inside the organization.
# A supplier's copy carries no review state (src.services.rfq_package_service).
_OUTBOUND_GOVERNANCE_COLUMNS: tuple = ()


def build_estimates_csv(
    result_json: dict,
    *,
    governance: Optional[dict] = None,
    outbound: bool = False,
) -> str:
    """Flatten per-(process, qty) estimates into an auditable CSV table.

    Includes the honest confidence band columns (band label + validated flag)
    and the persisted approval fields, so the exported artifact never presents
    an unvalidated or unsigned number as governed evidence. ``outbound`` is the
    supplier's copy: ``result_json`` is already an ``outbound.cost_record`` and
    none of the governance travels (no review status).
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    gov_columns = _OUTBOUND_GOVERNANCE_COLUMNS if outbound else _GOVERNANCE_COLUMNS
    writer.writerow(
        [
            "process",
            "material",
            "quantity",
            "unit_cost_usd",
            "fixed_cost_usd",
            "variable_cost_usd",
            "est_error_band_pct",
            "confidence_low_usd",
            "confidence_high_usd",
            "confidence_label",
            "confidence_validated",
            "dfm_ready",
            *gov_columns,
            "line_items",
        ]
    )
    governance = governance or {}

    def gov(key: str):
        if key == "disposition_basis":
            basis = governance.get(key)
            return json.dumps(basis, sort_keys=True) if basis else ""
        return governance.get(key, "")

    for e in result_json.get("estimates", []) or []:
        ci = e.get("confidence") or {}
        # ce-01: to the cent, with the rounding line that makes them add up to
        # unit_cost_usd (src.costing.footing, the screen's and the PDF's rule).
        li_str = "; ".join(f"{k}={v:.2f}" for k, v in footed_items(
            e.get("line_items") or {}, e.get("unit_cost_usd")).items())
        writer.writerow(
            [
                spreadsheet_safe_cell(value)
                for value in [
                    e.get("process", ""),
                    e.get("material", ""),
                    e.get("quantity", ""),
                    e.get("unit_cost_usd", ""),
                    e.get("fixed_cost_usd", ""),
                    e.get("variable_cost_usd", ""),
                    e.get("est_error_band_pct", ""),
                    ci.get("low_usd", ""),
                    ci.get("high_usd", ""),
                    ci.get("label", ""),
                    # Honesty: this is False for assumption-based bands.
                    ci.get("validated", False),
                    e.get("dfm_ready", ""),
                    *(gov(key) for key in gov_columns),
                    li_str,
                ]
            ]
        )
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Share (mirror share_service, cost-decision flavored)
# ---------------------------------------------------------------------------


async def _owned_for_share(ulid: str, user_id: int, session: AsyncSession) -> CostDecision:
    """The caller-org decision, locked for the share update, or the plain 404.

    W1 step 3: org-scoped lookup — another org's decision is invisible (404).
    """
    stmt = (
        select(CostDecision)
        .where(
            CostDecision.ulid == ulid,
            CostDecision.org_id == caller_org_subquery(user_id),
        )
        .with_for_update()
    )
    d = (await session.execute(stmt)).scalar_one_or_none()
    if d is None:
        raise HTTPException(status_code=404, detail="Cost decision not found")
    return d


def _share_link(d: CostDecision) -> dict:
    return {
        "share_url": f"/s/cost/{d.share_short_id}",
        "share_short_id": d.share_short_id,
        **share_links.fields(d),
    }


async def create_share(
    ulid: str,
    user_id: int,
    session: AsyncSession,
    expires_in_days: Optional[int] = share_links.DEFAULT_DAYS,
    options: Optional["share_links.ShareOptions"] = None,
) -> dict:
    """Make a public link to a cost decision: what a supplier sees (``options``,
    ``src.services.supplier_links``) until it ends.

    Without ``options`` (callers made before the Share dialog) a link that is on
    is returned unchanged, and a new one lasts ``expires_in_days`` (``None``:
    no end date) and shows no cost and no CAD. With ``options`` the sharer chose
    what the link shows and how long it lasts, so a new link is made and one
    that was on stops working.
    """
    from src.services.audit_service import emit_event

    d = await _owned_for_share(ulid, user_id, session)
    active = share_links.status(d) == "active"
    if active and options is None:
        return _share_link(d)

    opts = options or share_links.ShareOptions(expires_in_days=expires_in_days)
    short_id = generate_short_id()
    replaced = d.share_short_id if active else None
    share_links.open_link(d, user_id, opts.expires_in_days, short_id, ends_at=opts.ends_at(), shows=opts.shown())
    await emit_event(
        session,
        actor_id=user_id,
        action="share.created",
        resource_type="share",
        resource_id=short_id,
        detail={
            "cost_decision_ulid": ulid,
            "expires_at": d.share_expires_at.isoformat() if d.share_expires_at else None,
            "shows": d.share_options,
            "replaced": replaced,
        },
        org_id=d.org_id,
    )
    await session.commit()
    logger.info("Cost decision %s shared as /s/cost/%s by user %d", ulid, short_id, user_id)
    return _share_link(d)


async def revoke_share(
    ulid: str, user_id: int, session: AsyncSession
) -> None:
    """Switch the link off now. Only its maker or an org admin may.

    The short id stays so the public page says "switched off". Idempotent.
    """
    from src.services.audit_service import emit_event

    d = await _owned_for_share(ulid, user_id, session)
    if share_links.status(d) != "active":
        return
    await share_links.require_can_switch_off(session, d, user_id)
    share_links.close_link(d)
    await emit_event(
        session,
        actor_id=user_id,
        action="share.revoked",
        resource_type="share",
        resource_id=d.share_short_id,
        detail={"cost_decision_ulid": ulid},
        org_id=d.org_id,
    )
    await session.commit()
    logger.info("Cost decision %s unshared by user %d", ulid, user_id)


async def get_shared(short_id: str, session: AsyncSession) -> Optional[dict]:
    """Public cost decision by short id -> sanitized dict; None when unknown.

    A link that ended or was switched off raises 410 with no record data.
    """
    stmt = select(CostDecision).where(CostDecision.share_short_id == short_id)
    d = (await session.execute(stmt)).scalar_one_or_none()
    if d is None:
        return None
    share_links.public_or_raise(d, "Shared cost decision not found")
    # What a supplier sees: the part, specs, note, quantity, the CAD if chosen,
    # and our cost estimate only when the sharer turned it on.
    from src.services import supplier_links

    return await supplier_links.record_view(session, d, short_id)


def sanitize_for_share(d: CostDecision, *, terms=()) -> dict:
    """The public payload of ``GET /s/cost/{id}`` — ``outbound.cost_share``.

    No owner, ids or hashes (user_id, api_key_id, mesh_hash, params_hash,
    share_short_id, id/ulid), and nothing of the sharer's shop: its machines,
    rates and terms, routes it prices on its own machines, its in-house choices,
    calibration and actuals stay inside (see ``src.services.outbound``). The
    geometry, findings, outside should-cost and stated band are kept.
    """
    from src.services import outbound

    return outbound.cost_share(d, terms=terms)


# ---------------------------------------------------------------------------
# Compare (owner-scoped structured diff)
# ---------------------------------------------------------------------------


def _unit_costs_by_qty(result_json: dict) -> dict:
    """process -> {qty(str): unit_cost_usd} from the recommendation + estimates."""
    out: dict[str, dict] = {}
    for e in result_json.get("estimates", []) or []:
        proc = e.get("process")
        if proc is None:
            continue
        out.setdefault(proc, {})[str(e.get("quantity"))] = e.get("unit_cost_usd")
    return out


def _recommended_unit_by_qty(result_json: dict) -> dict:
    """qty(str) -> recommended {process, unit_cost_usd} from the decision."""
    decision = result_json.get("decision") or {}
    rec = decision.get("recommendation") or {}
    out = {}
    for q, r in rec.items():
        if r:
            out[str(q)] = {
                "process": r.get("process"),
                "unit_cost_usd": r.get("unit_cost_usd"),
            }
    return out


def build_comparison(a: CostDecision, b: CostDecision) -> dict:
    """Structured diff of two owned cost decisions.

    Compares recommended unit cost by quantity, the make/tooling process, the
    make-vs-buy crossover quantity, and per-qty unit-cost deltas.
    """
    ja, jb = a.result_json or {}, b.result_json or {}
    da, db = ja.get("decision") or {}, jb.get("decision") or {}

    rec_a = _recommended_unit_by_qty(ja)
    rec_b = _recommended_unit_by_qty(jb)
    all_qtys = sorted(
        {int(q) for q in rec_a} | {int(q) for q in rec_b}
    )

    unit_cost_by_qty = []
    for q in all_qtys:
        qk = str(q)
        ua = (rec_a.get(qk) or {}).get("unit_cost_usd")
        ub = (rec_b.get(qk) or {}).get("unit_cost_usd")
        delta = None
        pct = None
        if ua is not None and ub is not None:
            delta = round(ub - ua, 2)
            if ua:
                pct = round(100.0 * (ub - ua) / ua, 1)
        unit_cost_by_qty.append(
            {
                "quantity": q,
                "a": rec_a.get(qk),
                "b": rec_b.get(qk),
                "delta_usd": delta,
                "delta_pct": pct,
            }
        )

    def _summary(d: CostDecision, j: dict, dec: dict) -> dict:
        return {
            "id": d.ulid,
            "filename": d.filename,
            "label": d.label,
            "make_now_process": dec.get("make_now_process"),
            "make_now_material": dec.get("make_now_material"),
            "tooling_process": dec.get("tooling_process"),
            "crossover_qty": dec.get("crossover_qty"),
            "material_class": j.get("material_class"),
            "created_at": d.created_at.isoformat(),
        }

    return {
        "a": _summary(a, ja, da),
        "b": _summary(b, jb, db),
        "unit_cost_by_qty": unit_cost_by_qty,
        "diff": {
            "make_now_process": [
                da.get("make_now_process"),
                db.get("make_now_process"),
            ],
            "tooling_process": [
                da.get("tooling_process"),
                db.get("tooling_process"),
            ],
            "crossover_qty": [
                da.get("crossover_qty"),
                db.get("crossover_qty"),
            ],
        },
        "unit_costs_by_process": {
            "a": _unit_costs_by_qty(ja),
            "b": _unit_costs_by_qty(jb),
        },
    }
