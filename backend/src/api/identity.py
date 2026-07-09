"""Confirmed-identity API (identity Slice 1 — the human-in-the-loop seam).

The retrieval-grounding engine only ever SUGGESTS an identity (a provenance-tagged,
confidence-scored neighbour). This route is where a human turns a suggestion into an
ASSERTION: ``POST /identity/confirm`` stamps the declared part number / name /
program onto the org's corpus row for a part's ``mesh_hash`` and flips its source to
``user_confirmed`` — so a future retrieval of a similar part carries the human-
confirmed identity, not just a guess.

Tenancy: ORG-SCOPED. The caller's org is resolved (``resolve_org``) and every write
is filtered by ``org_id`` (``part_signature_service.confirm_identity``), so a caller
can NEVER touch another org's row — a cross-tenant confirm finds no row and 404s.
Requires the ``analyst`` role (the same role that authors decisions / declares
context).

Honesty: a confirmed identity is a USER assertion (``provenance: "USER"``), never
inferred from the mesh. The route confirms an EXISTING corpus row (a part the org has
already analyzed / seen); it never fabricates a signature it cannot measure — a mesh
not yet in the corpus is a 404, not a silent create.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.org_context import resolve_org
from src.auth.rate_limit import limiter
from src.auth.rbac import Role, require_role
from src.auth.require_api_key import AuthedUser
from src.db.engine import get_db_session
from src.services import part_signature_service as sigsvc

logger = logging.getLogger("cadverify.identity")

router = APIRouter(tags=["identity"])


class ConfirmIdentityBody(BaseModel):
    mesh_hash: str
    declared_part_id: Optional[str] = None
    declared_name: Optional[str] = None
    program: Optional[str] = None


@router.post("/confirm")
@limiter.limit("120/hour;600/day")
async def confirm_identity(
    request: Request,
    response: Response,
    body: ConfirmIdentityBody,
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Confirm (or correct) a part's identity in the caller's org corpus.

    Upserts the declared identity onto the ``(org, mesh_hash)`` corpus row and
    stamps ``source='user_confirmed'`` (provenance USER). A ``mesh_hash`` with no
    corpus row in this org — including another org's part — is a 404, never a write.
    """
    org_id = await resolve_org(session, user.user_id)
    if not org_id:
        raise HTTPException(status_code=400, detail="no organization for caller")

    mesh_hash = (body.mesh_hash or "").strip()
    if not mesh_hash:
        raise HTTPException(status_code=400, detail="mesh_hash is required")

    # At least one declared field must be supplied — a confirm asserts SOMETHING.
    if not any((body.declared_part_id, body.declared_name, body.program)):
        raise HTTPException(
            status_code=400,
            detail="supply at least one of declared_part_id, declared_name, program",
        )

    row = await sigsvc.confirm_identity(
        session,
        org_id,
        mesh_hash,
        declared_part_id=body.declared_part_id,
        declared_name=body.declared_name,
        program=body.program,
    )
    if row is None:
        # No corpus row for this (org, mesh) — you can only confirm a part your org
        # has already seen. Never a cross-tenant write, never a fabricated signature.
        raise HTTPException(
            status_code=404,
            detail="no part in your library for that mesh_hash (analyze it first)",
        )
    await session.commit()

    # Honest audit fire (best-effort, background) — a human asserted an identity.
    # emit_event resolves the actor email + writes one audit_log row off-request;
    # a scheduling failure is swallowed, never breaking the confirm that committed.
    try:
        from src.services import audit_service

        audit_service.emit_event(
            actor_id=user.user_id,
            action="identity.confirm",
            resource_type="part_signature",
            resource_id=mesh_hash,
            detail={
                "declared_part_id": body.declared_part_id,
                "declared_name": body.declared_name,
                "program": body.program,
            },
        )
    except Exception:  # pragma: no cover - audit is best-effort, never fatal
        logger.warning("identity.confirm audit fire failed", exc_info=True)

    return sigsvc.serialize_signature(row)
