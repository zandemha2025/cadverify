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

from sqlalchemy import select, tuple_, union, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.costing.makeability import GATE_PRIORITY
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
# Phase D — makeability projection (the machine-inventory §0 verdict + the D4
# capability-investment gap keys), derived from the Phase-C verification block on
# the cost decision. PURE — the single source of truth for the makeability
# columns, mirroring how ``derive_summary_fields`` projects the legacy columns.
# ---------------------------------------------------------------------------


_EMPTY_MAKEABILITY: dict = {
    "makeability_verdict": None,
    "in_house_makeable": None,
    "makeability_bucket": "unknown",
    "unlock_process": None,
    "unlock_gate": None,
    "unlock_single": None,
    "unlock_need_num": None,
    "unlock_need_label": None,
    "makeability_gap": None,
}

# Verdicts that are a concrete "makeable" (in-house) vs a concrete "not in-house".
_IN_HOUSE_VERDICTS = ("makeable_in_house", "makeable_with_secondary_op")
_NOT_IN_HOUSE_VERDICTS = (
    "makeable_not_on_owned", "makeable_outsource_only",
    "environment_excluded", "not_makeable",
)


def _binding_failure(fails: list) -> Optional[dict]:
    """The single BINDING FitFailure among a route's hard failures — the gate that
    most defines the machine class you'd have to acquire (envelope/axes lead, per
    the engine's own ``GATE_PRIORITY``). Deterministic; ``None`` for no failures."""
    if not fails:
        return None

    def _rank(f: dict) -> int:
        g = f.get("gate")
        return GATE_PRIORITY.index(g) if g in GATE_PRIORITY else len(GATE_PRIORITY)

    return min(fails, key=_rank)


def _need_of(f: dict):
    """Split a FitFailure ``need`` into (numeric, label): a number → the numeric
    requirement (envelope mm / mass kg / IT grade / axes / ...); a string (e.g. a
    material name) → the categorical label; else (None, None)."""
    need = f.get("need")
    if isinstance(need, bool):
        return None, str(need)
    if isinstance(need, (int, float)):
        return float(need), None
    if need is None:
        return None, None
    return None, str(need)


def _derive_unlock(verification: dict, recommended_process: Optional[str] = None) -> dict:
    """The single primary acquisition that would unlock a currently-blocked part,
    derived from the §0 verification's ``per_route`` detail (D4).

    * ``makeable_outsource_only`` → ACQUIRE a machine of an eligible-but-unowned
      process (gate None, single True — owning any capable machine makes the route).
      Prefer the engine's RECOMMENDED make-now route (the process the part would
      actually be made by), so the ranking groups parts by their intended process;
      fall back to the first outsource route otherwise.
    * ``makeable_not_on_owned`` → UPGRADE an owned process: pick the CLOSEST route
      (fewest distinct binding gates, tie-break by process id), and its binding
      gate defines the acquisition. ``single`` is True only when ONE gate blocks
      that route — a part blocked by multiple constraints is NOT unlocked by one
      acquisition, and is excluded from the ranking tally (honest).
    """
    verdict = verification.get("verdict")
    per_route = verification.get("per_route") or {}

    if verdict == "makeable_outsource_only":
        procs = sorted(
            p for p, info in per_route.items()
            if isinstance(info, dict)
            and info.get("verdict") == "makeable_outsource_only"
        )
        if not procs:
            return {}
        # Prefer the recommended make-now route when it is itself an outsource route
        # (coherent grouping by intended process); else the first deterministically.
        proc = recommended_process if recommended_process in procs else procs[0]
        return {
            "unlock_process": proc, "unlock_gate": None, "unlock_single": True,
            "unlock_need_num": None, "unlock_need_label": None,
            "makeability_gap": {"kind": "acquire", "process": proc,
                                "gate": None, "single": True, "gap": []},
        }

    if verdict == "makeable_not_on_owned":
        cands = []
        for p, info in per_route.items():
            if not isinstance(info, dict):
                continue
            if info.get("verdict") != "makeable_not_on_owned":
                continue
            fails = [f for f in (info.get("failures") or []) if isinstance(f, dict)]
            distinct = list(dict.fromkeys(f.get("gate") for f in fails))
            cands.append((len(distinct), str(p), p, fails, distinct))
        if not cands:
            return {}
        cands.sort(key=lambda t: (t[0], t[1]))
        _, _, proc, fails, distinct_gates = cands[0]
        binding = _binding_failure(fails)
        if binding is None:
            return {}
        single = len(distinct_gates) == 1
        need_num, need_label = _need_of(binding)
        return {
            "unlock_process": proc, "unlock_gate": binding.get("gate"),
            "unlock_single": single,
            "unlock_need_num": need_num, "unlock_need_label": need_label,
            "makeability_gap": {"kind": "upgrade", "process": proc,
                                "gate": binding.get("gate"), "single": single,
                                "gap": fails},
        }

    return {}


def derive_makeability_fields(cost_result_json: Optional[dict]) -> dict:
    """Project a cost decision's ``result_json`` into the makeability columns.

    PURE (no DB). Reads the engine's own ``status`` + Phase-C ``verification`` block
    VERBATIM: ``makeability_bucket`` is ``catalog_service.makeability_bucket`` of the
    verdict, ``in_house_makeable`` is True only for a concrete in-house verdict, and
    the ``unlock_*``/``makeability_gap`` keys carry the single primary acquisition
    for a blocked part — all from REAL stored gap data. A part with no cost /no
    verification block reads ``unknown`` (never a fabricated verdict); an invalid
    geometry reads ``geometry_invalid`` off the engine ``status`` and is not
    in-house makeable.
    """
    if not cost_result_json:
        return dict(_EMPTY_MAKEABILITY)

    status = cost_result_json.get("status")
    verification = cost_result_json.get("verification")
    verdict = verification.get("verdict") if isinstance(verification, dict) else None
    bucket = catalog_service.makeability_bucket(verdict, status)

    fields = dict(_EMPTY_MAKEABILITY)
    fields["makeability_verdict"] = verdict
    fields["makeability_bucket"] = bucket

    if bucket == "geometry_invalid":
        fields["in_house_makeable"] = False
    elif verdict in _IN_HOUSE_VERDICTS:
        fields["in_house_makeable"] = True
    elif verdict in _NOT_IN_HOUSE_VERDICTS:
        fields["in_house_makeable"] = False
    # verdict unknown/None → in_house_makeable stays None (honest: not evaluated).

    if bucket != "geometry_invalid" and isinstance(verification, dict):
        decision = cost_result_json.get("decision") or {}
        recommended = (decision.get("make_now_process") or "").strip() or None
        fields.update(_derive_unlock(verification, recommended_process=recommended))
    return fields


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
    session: AsyncSession,
    org_id: str,
    mesh_hash: str,
    *,
    mark_makeability_fresh: bool = False,
) -> bool:
    """Recompute + UPSERT the ``(org_id, mesh_hash)`` summary from the LATEST
    analysis + LATEST cost decision for that part.

    Fetches the newest artifact of each kind (ulid-desc, limit 1 — the same
    "latest wins" the legacy fold uses), builds ``SourceRef``s exactly as
    ``_fold_org_parts`` does, calls ``derive_row`` then ``derive_summary_fields``,
    AND ``derive_makeability_fields`` (Phase D — the machine-inventory verdict from
    the cost decision's Phase-C verification block), and upserts on the
    ``(org_id, mesh_hash)`` unique constraint. Idempotent: calling twice on
    unchanged data yields the identical row. No-ops (returns False) when neither
    artifact exists or ``org_id`` is falsy. Does NOT commit — it participates in the
    caller's transaction.

    ``mark_makeability_fresh`` — set True by the COST persist hook, where the
    verification block was just computed against the org's CURRENT inventory, so the
    part's makeability is fresh and its stale flag is cleared. Left False elsewhere
    (analysis persist / backfill) so a stale flag set by a machine change is
    PRESERVED until the part is genuinely re-costed — staleness is never silently
    cleared.
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
    makeability = derive_makeability_fields(
        cost.result_json if cost is not None else None
    )

    stmt = pg_insert(PartSummary).values(
        org_id=org_id,
        mesh_hash=mesh_hash,
        makeability_stale=False,  # a freshly-computed row is not stale on INSERT
        **fields,
        **makeability,
    )
    set_ = {
        "triage_bucket": stmt.excluded.triage_bucket,
        "route_process": stmt.excluded.route_process,
        "has_analysis": stmt.excluded.has_analysis,
        "has_cost": stmt.excluded.has_cost,
        "updated_at": stmt.excluded.updated_at,
        "row_json": stmt.excluded.row_json,
        # Phase D makeability columns — recomputed every refresh (idempotent).
        "makeability_verdict": stmt.excluded.makeability_verdict,
        "in_house_makeable": stmt.excluded.in_house_makeable,
        "makeability_bucket": stmt.excluded.makeability_bucket,
        "unlock_process": stmt.excluded.unlock_process,
        "unlock_gate": stmt.excluded.unlock_gate,
        "unlock_single": stmt.excluded.unlock_single,
        "unlock_need_num": stmt.excluded.unlock_need_num,
        "unlock_need_label": stmt.excluded.unlock_need_label,
        "makeability_gap": stmt.excluded.makeability_gap,
    }
    # Only a fresh cost-time recompute clears the stale flag; an analysis-persist /
    # backfill refresh leaves the EXISTING stale flag untouched (omitted from set_).
    if mark_makeability_fresh:
        set_["makeability_stale"] = stmt.excluded.makeability_stale  # = False
    stmt = stmt.on_conflict_do_update(
        index_elements=["org_id", "mesh_hash"],
        set_=set_,
    )
    await session.execute(stmt)
    return True


async def refresh_part_summary_safe(
    session: AsyncSession,
    org_id: Optional[str],
    mesh_hash: Optional[str],
    *,
    mark_makeability_fresh: bool = False,
) -> None:
    """Graceful-degrade wrapper for the write hooks — NEVER raises.

    Runs ``refresh_part_summary`` inside a SAVEPOINT so a projection failure rolls
    back ONLY the projection (the real analysis/cost write in the outer
    transaction survives), then logs + swallows. A broken projection must never
    break a live persist. Skips silently when ``org_id``/``mesh_hash`` is falsy.
    ``mark_makeability_fresh`` is threaded through (the cost hook passes True).
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
            await refresh_part_summary(
                session, org_id, mesh_hash,
                mark_makeability_fresh=mark_makeability_fresh,
            )
    except Exception:
        logger.warning(
            "part-summary projection failed for org=%s mesh=%.12s… — swallowed "
            "(live write preserved)",
            org_id,
            mesh_hash or "?",
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Phase D — machine-inventory change → honest STALE-marking (spec §10 D2)
#
# A machine added/updated/deleted changes the §0 verdict for MANY parts at once.
# A full org re-verify per machine edit is unaffordable (millions of parts ×
# re-running the engine), so we do NOT recompute inline. Instead ONE cheap,
# org-scoped, indexed UPDATE marks every part that CARRIES a verdict as stale, so
# a verdict computed against the OLD inventory is never served as fresh. The stale
# flag is surfaced (count + flag) in the rollup and the ranking, and is cleared
# per-part when the part is genuinely re-costed against the new inventory (the cost
# hook's ``mark_makeability_fresh=True``). Never silently wrong.
# ---------------------------------------------------------------------------


async def mark_org_makeability_stale(session: AsyncSession, org_id: str) -> int:
    """Mark every verdict-carrying part_summary in the org stale (ONE indexed
    UPDATE). Only rows with a concrete ``makeability_verdict`` are touched — a part
    with no verdict is genuinely ``unknown`` regardless of inventory, not "stale".
    Returns the number of rows newly marked. Does NOT commit (caller owns the txn).
    """
    if not org_id:
        return 0
    result = await session.execute(
        update(PartSummary)
        .where(
            PartSummary.org_id == org_id,
            PartSummary.makeability_verdict.isnot(None),
            PartSummary.makeability_stale.is_(False),
        )
        .values(makeability_stale=True)
    )
    return result.rowcount or 0


async def mark_org_makeability_stale_safe(
    session: AsyncSession, org_id: Optional[str]
) -> int:
    """Graceful-degrade wrapper for the machine-inventory write paths — NEVER
    raises. Isolates the bulk stale-mark in a SAVEPOINT so a projection failure
    never breaks a live machine create/update/delete/import; skips cleanly on a
    falsy org or a non-DB (mocked) session. Returns rows marked (0 on skip/error).
    """
    if not org_id or not isinstance(session, AsyncSession):
        return 0
    try:
        async with session.begin_nested():
            return await mark_org_makeability_stale(session, org_id)
    except Exception:
        logger.warning(
            "makeability stale-mark failed for org=%s — swallowed "
            "(machine write preserved)",
            org_id,
            exc_info=True,
        )
        return 0


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
