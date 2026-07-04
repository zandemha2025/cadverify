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
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.auth.org_context import caller_org_subquery
from src.auth.require_api_key import AuthedUser
from src.db.models import CostDecision, UsageEvent
from src.services.share_service import generate_short_id

logger = logging.getLogger("cadverify.cost_decision_service")


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
) -> str:
    """SHA-256 of the canonical cost parameters.

    Two cost runs on the same file with the same parameters produce the same
    decision, so this is the second half of the (user, mesh, params) dedup key.
    """
    canonical = json.dumps(
        {
            "quantities": sorted(quantities),
            "region": region or "US",
            "cavities": int(cavities),
            "complexity": complexity,
            "material_class": material_class,
            "shop": shop or "",
            "overrides": overrides or {},
        },
        sort_keys=True,
        separators=(",", ":"),
    )
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
    session: AsyncSession, user_id: int, mesh_hash: str, params_hash: str
) -> Optional[CostDecision]:
    stmt = select(CostDecision).where(
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
) -> CostDecision:
    """Insert (or return the deduped) CostDecision row and flush to get its ulid.

    Dedup key is (user_id, mesh_hash, params_hash): a repeat cost of the same
    file with the same params returns the existing row instead of duplicating.
    Race-safe via IntegrityError re-query (mirrors analysis_service).
    """
    existing = await _lookup_dedup(session, user.user_id, mesh_hash, params_hash)
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

    decision = CostDecision(
        ulid=str(ULID()),
        user_id=user.user_id,
        org_id=await resolve_org(session, user.user_id),
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
            session, user.user_id, mesh_hash, params_hash
        )
        if existing is not None:
            await _refresh_summary_for(session, existing)
            return existing
        raise

    await _refresh_summary_for(session, decision)
    return decision


async def _refresh_summary_for(session: AsyncSession, decision: CostDecision) -> None:
    """Maintain the materialized per-part catalog projection for a persisted (or
    deduped) cost decision — Aramco GAP 2. Graceful-degrade + same-transaction:
    delegated to ``part_summary_service.refresh_part_summary_safe`` which isolates
    any failure in a SAVEPOINT and swallows it, so a broken projection never
    breaks the live cost persist."""
    from src.services import part_summary_service

    await part_summary_service.refresh_part_summary_safe(
        session, decision.org_id, decision.mesh_hash
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
        "filename": d.filename,
        "file_type": d.file_type,
        "label": d.label,
        "make_now_process": d.make_now_process,
        "crossover_qty": d.crossover_qty,
        "quantities": d.quantities or [],
        "created_at": d.created_at.isoformat(),
        "is_public": d.is_public,
        "share_url": f"/s/cost/{d.share_short_id}" if d.share_short_id else None,
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


# ---------------------------------------------------------------------------
# CSV export — estimates / line-items table
# ---------------------------------------------------------------------------


def build_estimates_csv(result_json: dict) -> str:
    """Flatten per-(process, qty) estimates into an auditable CSV table.

    Includes the honest confidence band columns (band label + validated flag)
    so the exported artifact never presents an unvalidated number as measured.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
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
            "line_items",
        ]
    )
    for e in result_json.get("estimates", []) or []:
        ci = e.get("confidence") or {}
        line_items = e.get("line_items") or {}
        li_str = "; ".join(f"{k}={v}" for k, v in line_items.items())
        writer.writerow(
            [
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
                li_str,
            ]
        )
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Share (mirror share_service, cost-decision flavored)
# ---------------------------------------------------------------------------


async def create_share(
    ulid: str, user_id: int, session: AsyncSession
) -> dict:
    """Toggle a cost decision public and assign a share short id (idempotent).

    W1 step 3: org-scoped lookup — only a decision in the caller's org can be
    shared; another org's decision is invisible (404).
    """
    stmt = select(CostDecision).where(
        CostDecision.ulid == ulid,
        CostDecision.org_id == caller_org_subquery(user_id),
    )
    d = (await session.execute(stmt)).scalar_one_or_none()
    if d is None:
        raise HTTPException(status_code=404, detail="Cost decision not found")

    if d.share_short_id is not None:
        return {
            "share_url": f"/s/cost/{d.share_short_id}",
            "share_short_id": d.share_short_id,
        }

    short_id = generate_short_id()
    d.share_short_id = short_id
    d.is_public = True
    await session.commit()
    logger.info("Cost decision %s shared as /s/cost/%s by user %d", ulid, short_id, user_id)
    return {"share_url": f"/s/cost/{short_id}", "share_short_id": short_id}


async def revoke_share(
    ulid: str, user_id: int, session: AsyncSession
) -> None:
    """Revoke sharing — the public link 404s immediately.

    W1 step 3: org-scoped lookup (see ``create_share``).
    """
    stmt = select(CostDecision).where(
        CostDecision.ulid == ulid,
        CostDecision.org_id == caller_org_subquery(user_id),
    )
    d = (await session.execute(stmt)).scalar_one_or_none()
    if d is None:
        raise HTTPException(status_code=404, detail="Cost decision not found")

    d.share_short_id = None
    d.is_public = False
    await session.commit()
    logger.info("Cost decision %s unshared by user %d", ulid, user_id)


async def get_shared(short_id: str, session: AsyncSession) -> Optional[dict]:
    """Fetch a public cost decision by share short id -> sanitized dict / None."""
    stmt = select(CostDecision).where(
        CostDecision.share_short_id == short_id,
        CostDecision.is_public.is_(True),
    )
    d = (await session.execute(stmt)).scalar_one_or_none()
    if d is None:
        return None
    return sanitize_for_share(d)


def sanitize_for_share(d: CostDecision) -> dict:
    """Allow-listed public payload — ZERO owner/user PII.

    EXCLUDED: user_id, api_key_id, mesh_hash, params_hash, share_short_id,
    is_public, id, ulid. The decision content (geometry, estimates with
    provenance, honest confidence band, crossover, assumptions) is preserved
    verbatim so the public view stays as honest as the private one.
    """
    result_json = d.result_json or {}
    return {
        "filename": d.filename,
        "file_type": d.file_type,
        "label": d.label,
        "created_at": d.created_at.isoformat(),
        "make_now_process": d.make_now_process,
        "crossover_qty": d.crossover_qty,
        "quantities": d.quantities or [],
        # Glass-box decision content, preserved (provenance + honest CI intact).
        "geometry": result_json.get("geometry", {}),
        "material_class": result_json.get("material_class"),
        "routing": result_json.get("routing"),
        "estimates": result_json.get("estimates", []),
        "decision": result_json.get("decision"),
        "assumptions": result_json.get("assumptions", []),
        "engine_feasibility": result_json.get("engine_feasibility", []),
        "notes": result_json.get("notes", []),
        "status": result_json.get("status"),
    }


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
