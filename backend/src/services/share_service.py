"""Share service — base62 short ID generation, share toggle, and sanitization.

Provides:
  - generate_short_id()          — 12-char cryptographically random base62 string
  - create_share()               — make a public link that ends (share_links)
  - revoke_share()               — switch the link off (maker or org admin)
  - get_shared_analysis()        — fetch public analysis by short ID
  - sanitize_analysis_for_share() — strip PII, return allow-listed fields only
"""
from __future__ import annotations

import logging
import secrets
import string

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.org_context import caller_org_subquery
from src.db.models import Analysis
from src.services import share_links

logger = logging.getLogger("cadverify.share_service")

BASE62_CHARS = string.digits + string.ascii_letters  # 0-9A-Za-z (62 chars)


def generate_short_id(length: int = 12) -> str:
    """Generate a cryptographically random base62 string of the given length."""
    raw = secrets.token_bytes(length)
    return "".join(BASE62_CHARS[b % 62] for b in raw)


async def _owned(analysis_ulid: str, user_id: int, session: AsyncSession) -> Analysis:
    """The caller-org analysis, locked for the share update, or the plain 404.

    W1 step 3: org-scoped — another org's analysis is invisible (404), never 403.
    """
    stmt = (
        select(Analysis)
        .where(
            Analysis.ulid == analysis_ulid,
            Analysis.org_id == caller_org_subquery(user_id),
        )
        .with_for_update()
    )
    analysis = (await session.execute(stmt)).scalar_one_or_none()
    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return analysis


def _link(analysis: Analysis) -> dict:
    return {
        "share_url": f"/s/{analysis.share_short_id}",
        "share_short_id": analysis.share_short_id,
        **share_links.fields(analysis),
    }


async def create_share(
    analysis_ulid: str,
    user_id: int,
    session: AsyncSession,
    expires_in_days: int | None = share_links.DEFAULT_DAYS,
) -> dict:
    """Make a public link to an analysis that ends after ``expires_in_days``.

    ``None`` is the sharer's explicit "no end date". A link that is already on
    is returned unchanged (idempotent). A link that ended or was switched off
    is replaced by a new short id; the old one stops resolving.
    """
    analysis = await _owned(analysis_ulid, user_id, session)
    if share_links.status(analysis) == "active":
        return _link(analysis)

    short_id = generate_short_id()
    share_links.open_link(analysis, user_id, expires_in_days, short_id)
    from src.services.audit_service import emit_event

    await emit_event(
        session,
        actor_id=user_id,
        action="share.created",
        resource_type="share",
        resource_id=short_id,
        detail={
            "analysis_ulid": analysis_ulid,
            "expires_at": analysis.share_expires_at.isoformat() if analysis.share_expires_at else None,
        },
        org_id=analysis.org_id,
    )
    await session.commit()

    logger.info(
        "Analysis %s shared as /s/%s by user %d",
        analysis_ulid,
        short_id,
        user_id,
    )
    return _link(analysis)


async def revoke_share(
    analysis_ulid: str, user_id: int, session: AsyncSession
) -> None:
    """Switch the link off now. Only its maker or an org admin may.

    The short id stays on the row so the public page says "switched off".
    Idempotent: switching off a link that is already off (or never existed)
    changes nothing.
    """
    analysis = await _owned(analysis_ulid, user_id, session)
    if share_links.status(analysis) != "active":
        return
    await share_links.require_can_switch_off(session, analysis, user_id)

    share_links.close_link(analysis)
    from src.services.audit_service import emit_event

    await emit_event(
        session,
        actor_id=user_id,
        action="share.revoked",
        resource_type="share",
        resource_id=analysis.share_short_id,
        detail={"analysis_ulid": analysis_ulid},
        org_id=analysis.org_id,
    )
    await session.commit()

    logger.info("Analysis %s unshared by user %d", analysis_ulid, user_id)


async def get_shared_analysis(
    short_id: str, session: AsyncSession
) -> dict | None:
    """Fetch a public analysis by its share short ID.

    Returns a sanitized dict, or None for an unknown id. A link that ended or
    was switched off raises 410 with no record data (``share_links``).
    """
    stmt = select(Analysis).where(Analysis.share_short_id == short_id)
    analysis = (await session.execute(stmt)).scalar_one_or_none()
    if analysis is None:
        return None
    share_links.public_or_raise(analysis, "Shared analysis not found")
    return {**sanitize_analysis_for_share(analysis), **share_links.public_meta(analysis)}


def sanitize_analysis_for_share(analysis: Analysis) -> dict:
    """Return an allow-listed dict with zero PII fields.

    EXCLUDED: user_id, api_key_id, email, mesh_hash, share_short_id,
    is_public, ulid, key_prefix, process_set_hash, analysis_version,
    file_size_bytes, id.
    """
    result_json = analysis.result_json or {}

    return {
        "filename": analysis.filename,
        "file_type": analysis.file_type,
        "verdict": analysis.verdict,
        "face_count": analysis.face_count,
        "duration_ms": analysis.duration_ms,
        "created_at": analysis.created_at.isoformat(),
        "process_scores": result_json.get("process_scores", []),
        "universal_issues": result_json.get("universal_issues", []),
        "geometry": result_json.get("geometry", {}),
        "best_process": result_json.get("best_process"),
        "priority_fixes": result_json.get("priority_fixes", []),
    }
