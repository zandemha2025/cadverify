"""Part-summary projection service (Aramco GAP 2 — scale to millions).

Maintains ``part_summaries``: ONE materialized row per ``(org_id, mesh_hash)``
carrying the full ``catalog_service.derive_row`` dict plus the scalar columns the
whole-inventory triage COUNT and the keyset-paginated grid aggregate in SQL. It
turns the catalog/triage/portfolio read path from a "scan the 2000 newest raw
rows and fold in Python" (capped, ``truncated:true`` past the cap) into an
O(buckets) ``GROUP BY`` that scales to millions of parts.

DE-RISKING — additive, legacy path UNTOUCHED. This module never modifies the
legacy fold (``catalog_service._fold_org_parts`` / ``derive_row`` /
``triage_bucket``); it CALLS them so the projection is byte-identical to the
legacy output by construction:

  * ``row_json`` is the exact ``derive_row`` dict → the scaled grid hydrates a
    page byte-identically to the legacy grid.
  * the ``triage_bucket`` column is exactly ``catalog_service.triage_bucket(row)``
    → the scaled rollup counts identically to the legacy rollup.

Maintenance runs at the TWO persist funnels (analysis + cost decision) in the
SAME transaction as the write (no separate commit) and NEVER raises into the
caller — a projection failure must never break a live analysis/cost persist. The
failure is isolated in a SAVEPOINT so it rolls back ONLY the projection, leaving
the real write intact, and is logged + swallowed (the graceful-degrade discipline
of ``cost_decision_service.record_persist_failure``).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select, tuple_, union
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Analysis, CostDecision, PartSummary
from src.services import catalog_service

logger = logging.getLogger("cadverify.part_summary_service")


# ---------------------------------------------------------------------------
# Pure mapper — the single source of truth for what the columns hold
# ---------------------------------------------------------------------------


def derive_summary_fields(row: dict) -> dict:
    """Project a ``catalog_service.derive_row`` output dict into the summary
    columns. PURE (no DB): the ONE place that says what each column carries.

    ``triage_bucket`` is ``catalog_service.triage_bucket(row)`` VERBATIM (never
    re-implemented) and ``row_json`` is the row itself, so the summary reproduces
    the legacy classification + grid cell exactly. ``updated_at`` is parsed back
    from ``row["updated_at"]`` (the same ISO string the grid sorts on) so the
    timestamptz column and the JSON string can never drift.
    """
    route = (row.get("recommended_route") or {}).get("process")
    return {
        "triage_bucket": catalog_service.triage_bucket(row),
        "route_process": route,
        "has_analysis": row.get("analysis") is not None,
        "has_cost": row.get("cost_decision") is not None,
        "updated_at": datetime.fromisoformat(row["updated_at"]),
        "row_json": row,
    }


# ---------------------------------------------------------------------------
# Fold one part (latest analysis + latest cost) — mirrors _fold_org_parts
# ---------------------------------------------------------------------------


def _source_ref(artifact) -> catalog_service.SourceRef:
    """Hydrate a DB row into a DB-free ``SourceRef`` — byte-for-byte the same
    construction ``_fold_org_parts`` uses, so ``derive_row`` sees identical input.
    """
    return catalog_service.SourceRef(
        id=artifact.ulid,
        filename=artifact.filename,
        file_type=artifact.file_type,
        created_at=artifact.created_at,
        result_json=artifact.result_json or {},
    )


async def _latest_analysis(
    session: AsyncSession, org_id: str, mesh_hash: str
) -> Optional[Analysis]:
    return (
        (
            await session.execute(
                select(Analysis)
                .where(Analysis.org_id == org_id, Analysis.mesh_hash == mesh_hash)
                .order_by(Analysis.ulid.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )


async def _latest_cost(
    session: AsyncSession, org_id: str, mesh_hash: str
) -> Optional[CostDecision]:
    return (
        (
            await session.execute(
                select(CostDecision)
                .where(
                    CostDecision.org_id == org_id,
                    CostDecision.mesh_hash == mesh_hash,
                )
                .order_by(CostDecision.ulid.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )


async def refresh_part_summary(
    session: AsyncSession, org_id: str, mesh_hash: str
) -> bool:
    """Recompute + UPSERT the ``(org_id, mesh_hash)`` summary from the LATEST
    analysis + LATEST cost decision for that part.

    Fetches the newest artifact of each kind (ulid-desc, limit 1 — the same
    "latest wins" the legacy fold uses), builds ``SourceRef``s exactly as
    ``_fold_org_parts`` does, calls ``derive_row`` then ``derive_summary_fields``,
    and upserts on the ``(org_id, mesh_hash)`` unique constraint. Idempotent:
    calling twice on unchanged data yields the identical row. No-ops (returns
    False) when neither artifact exists or ``org_id`` is falsy. Does NOT commit —
    it participates in the caller's transaction.
    """
    if not org_id:
        return False

    analysis = await _latest_analysis(session, org_id, mesh_hash)
    cost = await _latest_cost(session, org_id, mesh_hash)
    if analysis is None and cost is None:
        return False

    row = catalog_service.derive_row(
        part_key=mesh_hash,
        analysis=_source_ref(analysis) if analysis is not None else None,
        cost=_source_ref(cost) if cost is not None else None,
    )
    fields = derive_summary_fields(row)

    stmt = pg_insert(PartSummary).values(
        org_id=org_id, mesh_hash=mesh_hash, **fields
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["org_id", "mesh_hash"],
        set_={
            "triage_bucket": stmt.excluded.triage_bucket,
            "route_process": stmt.excluded.route_process,
            "has_analysis": stmt.excluded.has_analysis,
            "has_cost": stmt.excluded.has_cost,
            "updated_at": stmt.excluded.updated_at,
            "row_json": stmt.excluded.row_json,
        },
    )
    await session.execute(stmt)
    return True


async def refresh_part_summary_safe(
    session: AsyncSession, org_id: Optional[str], mesh_hash: Optional[str]
) -> None:
    """Graceful-degrade wrapper for the write hooks — NEVER raises.

    Runs ``refresh_part_summary`` inside a SAVEPOINT so a projection failure rolls
    back ONLY the projection (the real analysis/cost write in the outer
    transaction survives), then logs + swallows. A broken projection must never
    break a live persist. Skips silently when ``org_id``/``mesh_hash`` is falsy.
    """
    if not org_id or not mesh_hash:
        return
    # Only maintain the projection on a real DB session — unit tests that drive the
    # persist funnels with a mocked AsyncMock session have no transaction to nest a
    # SAVEPOINT in (and nothing to project into); skip cleanly rather than churn.
    if not isinstance(session, AsyncSession):
        return
    try:
        async with session.begin_nested():
            await refresh_part_summary(session, org_id, mesh_hash)
    except Exception:
        logger.warning(
            "part-summary projection failed for org=%s mesh=%.12s… — swallowed "
            "(live write preserved)",
            org_id,
            mesh_hash or "?",
            exc_info=True,
        )


async def org_has_raw_parts(session: AsyncSession, org_id: str) -> bool:
    """Cheap read-only EXISTS: does the org have ANY analysis or cost decision?

    Used to tell a genuinely-empty org (correct zero) apart from a COLD projection
    (org has raw parts written before the projection existed / before the deploy
    backfill ran). Two indexed ``LIMIT 1`` probes — never a scan, never a write.
    """
    if not org_id:
        return False
    a = (
        await session.execute(
            select(Analysis.id).where(Analysis.org_id == org_id).limit(1)
        )
    ).first()
    if a is not None:
        return True
    c = (
        await session.execute(
            select(CostDecision.id).where(CostDecision.org_id == org_id).limit(1)
        )
    ).first()
    return c is not None


# ---------------------------------------------------------------------------
# Backfill (deploy / byte-identity test population) — unbounded, paged
# ---------------------------------------------------------------------------


async def backfill_part_summaries(
    session: AsyncSession,
    org_id: Optional[str] = None,
    batch_size: int = 500,
) -> int:
    """Reconstruct summaries for existing parts — the once-per-deploy backfill.

    Pages through every distinct ``(org_id, mesh_hash)`` present in ``analyses``
    ∪ ``cost_decisions`` (optionally scoped to one ``org_id``) via keyset on
    ``(org_id, mesh_hash)`` — bounded per batch (only ``batch_size`` pairs in
    memory at a time, never an unbounded list) — and upserts each part's summary.
    Idempotent: re-running changes nothing. Returns the number of parts upserted.
    Does NOT commit (the caller owns the transaction boundary).
    """
    a_sel = select(Analysis.org_id, Analysis.mesh_hash)
    c_sel = select(CostDecision.org_id, CostDecision.mesh_hash)
    if org_id:
        a_sel = a_sel.where(Analysis.org_id == org_id)
        c_sel = c_sel.where(CostDecision.org_id == org_id)
    # UNION dedups the pairs across both source tables.
    pairs = union(a_sel, c_sel).subquery("pairs")
    org_col = pairs.c.org_id
    mesh_col = pairs.c.mesh_hash

    count = 0
    last: Optional[tuple[str, str]] = None
    while True:
        q = select(org_col, mesh_col).order_by(org_col, mesh_col).limit(batch_size)
        if last is not None:
            q = q.where(tuple_(org_col, mesh_col) > tuple_(last[0], last[1]))
        rows = (await session.execute(q)).all()
        if not rows:
            break
        for o, m in rows:
            if await refresh_part_summary(session, o, m):
                count += 1
        last = (rows[-1][0], rows[-1][1])
        if len(rows) < batch_size:
            break
    return count
