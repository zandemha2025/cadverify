"""A part's next revision: the fixed file a person uploads from a problem.

When someone fixes a part in their CAD tool and uploads the fixed file from
the problem card ("Upload the fixed file"), the new file is checked like any
upload and saved as its own part. This links the two, so the new part reads
as the next revision of the old one and both pages can say so and open a
before/after comparison.

Stored as two small JSON records in the object store, next to each part's
source artifacts (no schema change), like a fixed copy's ``derived-from``
record:

* ``revision-of.json`` on the new part: ``{mesh_hash, filename, problem, at, by}``
* ``next-revision.json`` on the old part: the same shape, pointing forward.

Both parts must be saved parts of the caller's organization. A record whose
other part was deleted since is not reported. Deleting a part removes its own
records with its artifacts.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Analysis, CostDecision
from src.services.cad_fix_service import _get_json, _put_json, _record_key

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROBLEM = re.compile(r"^[a-z0-9:_-]{1,64}$")
REVISION_OF = "revision-of.json"
NEXT_REVISION = "next-revision.json"


class RevisionLinkError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


async def _part(session: AsyncSession, org_id: str, mesh_hash: str) -> dict | None:
    """The part's name and latest record, or None when it isn't a saved part of this org."""
    decision = (await session.execute(
        select(CostDecision.ulid, CostDecision.filename, CostDecision.label, CostDecision.created_at)
        .where(CostDecision.org_id == org_id, CostDecision.mesh_hash == mesh_hash)
        .order_by(desc(CostDecision.created_at)).limit(1)
    )).first()
    analysis = (await session.execute(
        select(Analysis.filename, Analysis.created_at)
        .where(Analysis.org_id == org_id, Analysis.mesh_hash == mesh_hash)
        .order_by(desc(Analysis.created_at)).limit(1)
    )).first()
    if decision is not None:
        filename = decision.label or decision.filename
    elif analysis is not None:
        filename = analysis.filename
    else:
        return None
    return {
        "mesh_hash": mesh_hash,
        "filename": filename,
        "record_id": decision.ulid if decision is not None else None,
    }


def _digest(value: str) -> str:
    digest = str(value or "").strip().lower()
    if not _SHA256.fullmatch(digest):
        raise RevisionLinkError(404, "No such part in your organization.")
    return digest


async def link_revision(session: AsyncSession, org_id: str, user_id: int, new_hash: str,
                        from_hash: str, problem: str | None = None) -> dict:
    """Record ``new_hash`` as the next revision of ``from_hash``. Idempotent."""
    new_hash, from_hash = _digest(new_hash), _digest(from_hash)
    if new_hash == from_hash:
        raise RevisionLinkError(409, "A part can't be its own revision: the file is unchanged.")
    new_part = await _part(session, org_id, new_hash)
    old_part = await _part(session, org_id, from_hash)
    if new_part is None or old_part is None:
        raise RevisionLinkError(404, "No such part in your organization.")
    clean_problem = problem if problem and _PROBLEM.fullmatch(problem) else None
    at = datetime.now(timezone.utc).isoformat()
    back = {"mesh_hash": from_hash, "filename": old_part["filename"], "problem": clean_problem, "at": at, "by": user_id}
    forward = {"mesh_hash": new_hash, "filename": new_part["filename"], "problem": clean_problem, "at": at, "by": user_id}
    await _put_json(_record_key(org_id, new_hash, REVISION_OF), back)
    await _put_json(_record_key(org_id, from_hash, NEXT_REVISION), forward)
    return await revisions(session, org_id, new_hash)


async def revisions(session: AsyncSession, org_id: str, mesh_hash: str) -> dict:
    """``{revision_of, next}``: the linked parts, each with its latest record id, or None."""
    digest = _digest(mesh_hash)
    out: dict = {"mesh_hash": digest, "revision_of": None, "next": None}
    for field, name in (("revision_of", REVISION_OF), ("next", NEXT_REVISION)):
        record = await _get_json(_record_key(org_id, digest, name))
        other = str((record or {}).get("mesh_hash") or "")
        if record is None or not _SHA256.fullmatch(other):
            continue
        part = await _part(session, org_id, other)
        if part is None:
            continue  # the other part was deleted since
        out[field] = {**part, "problem": record.get("problem"), "at": record.get("at")}
    return out
