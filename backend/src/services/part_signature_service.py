"""Part-signature store — the org-scoped geometry retrieval CORPUS (identity Slice 1).

Persists ``part_signatures``: ONE row per ``(org_id, mesh_hash)`` carrying the
18-dim MEASURED shape signature (``src.eval.similarity.feature_vector``) plus
whatever DECLARED identity the customer gave (their own part number / name /
program). It is the flywheel storage behind the identity-retrieval engine — as an
org analyzes parts, each one enters ITS corpus, and a new part is grounded by
retrieving the org's own closest prior signatures.

Two responsibilities, both thin and org-scoped (mirrors ``groundtruth_service`` /
``part_context_service``):

  * **write-back** — ``upsert_signature`` (idempotent, last-write-wins on
    ``(org_id, mesh_hash)``): a part the org analyzes enters its corpus, carrying
    the latest declared identity. Wired into the analysis persist funnel
    best-effort / non-fatal, so a signature failure can NEVER break a live
    analysis.
  * **read** — ``list_signatures`` (``WHERE org_id = caller-org``): the whole
    org matrix the retrieval engine loads. A caller only ever sees their own org's
    signatures — cross-tenant isolation by construction.

HONESTY: the signature is MEASURED geometry; the declared_* fields are
USER/file-declared identity, never inferred from the mesh. This module only
persists + filters — it never asserts an identity as fact. Zero network.
"""
from __future__ import annotations

import logging
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from src.db.models import PartSignature

logger = logging.getLogger("cadverify.part_signature_service")


def _to_float_list(vector: Sequence[float]) -> list[float]:
    """Coerce a signature vector (numpy array or sequence) to a plain float list
    for JSONB storage. Non-finite entries are scrubbed to 0.0 (the same NaN-safe
    discipline ``similarity.feature_vector`` already applies), so a degenerate mesh
    can never poison the corpus with a value that breaks the JSONB insert."""
    import math

    out: list[float] = []
    for v in list(vector):
        try:
            f = float(v)
        except (TypeError, ValueError):
            f = 0.0
        out.append(f if math.isfinite(f) else 0.0)
    return out


async def upsert_signature(
    session: AsyncSession,
    org_id: str,
    mesh_hash: str,
    vector: Sequence[float],
    *,
    declared_part_id: Optional[str] = None,
    declared_name: Optional[str] = None,
    program: Optional[str] = None,
    source: str = "upload",
) -> Optional[PartSignature]:
    """Insert or update THE single ``(org_id, mesh_hash)`` signature row.

    Idempotent (last write wins): re-analyzing the same part in the same org
    updates the ONE row in place — its signature is refreshed and its declared
    identity is overwritten with the latest values, never a second row. Org-scoped:
    only ever touches the caller-org's row for this mesh. Does NOT commit — it
    participates in the caller's transaction. Returns ``None`` when ``org_id`` /
    ``mesh_hash`` is falsy (nothing to key on).

    The declared_* fields are USER/file-declared identity (nullable — the customer
    may not have given one yet); ``vector`` is the MEASURED 18-dim shape signature.
    """
    if not org_id or not mesh_hash:
        return None

    sig = _to_float_list(vector)
    stmt = pg_insert(PartSignature).values(
        org_id=org_id,
        mesh_hash=mesh_hash,
        signature=sig,
        declared_part_id=declared_part_id,
        declared_name=declared_name,
        program=program,
        source=source,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["org_id", "mesh_hash"],
        set_={
            "signature": stmt.excluded.signature,
            "declared_part_id": stmt.excluded.declared_part_id,
            "declared_name": stmt.excluded.declared_name,
            "program": stmt.excluded.program,
            "source": stmt.excluded.source,
            "updated_at": func.now(),
        },
    )
    await session.execute(stmt)
    return None


async def upsert_signature_safe(
    session: AsyncSession,
    org_id: Optional[str],
    mesh_hash: Optional[str],
    vector: Optional[Sequence[float]],
    *,
    declared_part_id: Optional[str] = None,
    declared_name: Optional[str] = None,
    program: Optional[str] = None,
    source: str = "upload",
) -> None:
    """Graceful-degrade wrapper for the analysis write hook — NEVER raises.

    Runs ``upsert_signature`` inside a SAVEPOINT so a corpus-write failure rolls
    back ONLY the signature write (the real analysis persist in the outer
    transaction survives), then logs + swallows. Building the org's identity
    corpus must never break a live analysis. Skips silently on a falsy
    org/mesh/vector or a non-DB (mocked) session.
    """
    if not org_id or not mesh_hash or vector is None:
        return
    if not isinstance(session, AsyncSession):
        return
    try:
        async with session.begin_nested():
            await upsert_signature(
                session, org_id, mesh_hash, vector,
                declared_part_id=declared_part_id,
                declared_name=declared_name,
                program=program,
                source=source,
            )
    except Exception:
        logger.warning(
            "part-signature write-back failed for org=%s mesh=%.12s… — swallowed "
            "(live analysis preserved)",
            org_id,
            mesh_hash or "?",
            exc_info=True,
        )


async def list_signatures(session: AsyncSession, org_id: str) -> list[PartSignature]:
    """Every signature in the caller's org — the matrix the retrieval engine loads.

    ``WHERE org_id = caller-org`` (mirrors ``groundtruth_service.list_records``):
    a caller only ever sees their own org's corpus, so retrieval can never return
    another org's parts. ``org_id`` falsy → empty list (never a cross-org read).
    Ordered newest-first for a deterministic, stable matrix.
    """
    if not org_id:
        return []
    stmt = (
        select(PartSignature)
        .where(PartSignature.org_id == org_id)
        .order_by(PartSignature.id.desc())
    )
    return list((await session.execute(stmt)).scalars().all())
