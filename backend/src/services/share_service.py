"""Share service — base62 short ID generation, share toggle, and sanitization.

Provides:
  - generate_short_id()          — 12-char cryptographically random base62 string
  - create_share()               — toggle analysis to public, assign short ID
  - revoke_share()               — toggle analysis to private, null short ID
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

from src.db.models import Analysis

logger = logging.getLogger("cadverify.share_service")

BASE62_CHARS = string.digits + string.ascii_letters  # 0-9A-Za-z (62 chars)


def generate_short_id(length: int = 12) -> str:
    """Generate a cryptographically random base62 string of the given length."""
    raw = secrets.token_bytes(length)
    return "".join(BASE62_CHARS[b % 62] for b in raw)


async def create_share(
    analysis_ulid: str, user_id: int, session: AsyncSession
) -> dict:
    """Toggle an analysis to public and assign a share short ID.

    Returns the share URL and short ID. If already shared, returns the
    existing share URL without generating a new ID.
    """
    stmt = select(Analysis).where(
        Analysis.ulid == analysis_ulid,
        Analysis.user_id == user_id,
    )
    result = await session.execute(stmt)
    analysis = result.scalar_one_or_none()

    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found")

    # Already shared — return existing URL
    if analysis.share_short_id is not None:
        return {
            "share_url": f"/s/{analysis.share_short_id}",
            "share_short_id": analysis.share_short_id,
        }

    short_id = generate_short_id()
    analysis.share_short_id = short_id
    analysis.is_public = True
    await session.commit()

    logger.info(
        "Analysis %s shared as /s/%s by user %d",
        analysis_ulid,
        short_id,
        user_id,
    )

    # Audit: share.created
    import asyncio
    from src.services.audit_service import fire_and_forget_audit, _lookup_email
    _email = await _lookup_email(user_id)
    asyncio.create_task(fire_and_forget_audit(
        user_id=user_id, user_email=_email,
        action="share.created", resource_type="share",
        resource_id=short_id,
        detail={"analysis_ulid": analysis_ulid},
    ))

    return {"share_url": f"/s/{short_id}", "share_short_id": short_id}


async def revoke_share(
    analysis_ulid: str, user_id: int, session: AsyncSession
) -> None:
    """Revoke sharing — null the short ID and set is_public=false."""
    stmt = select(Analysis).where(
        Analysis.ulid == analysis_ulid,
        Analysis.user_id == user_id,
    )
    result = await session.execute(stmt)
    analysis = result.scalar_one_or_none()

    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found")

    old_short_id = analysis.share_short_id
    analysis.share_short_id = None
    analysis.is_public = False
    await session.commit()

    logger.info("Analysis %s unshared by user %d", analysis_ulid, user_id)

    # Audit: share.revoked
    import asyncio
    from src.services.audit_service import fire_and_forget_audit, _lookup_email
    _email = await _lookup_email(user_id)
    asyncio.create_task(fire_and_forget_audit(
        user_id=user_id, user_email=_email,
        action="share.revoked", resource_type="share",
        resource_id=old_short_id,
        detail={"analysis_ulid": analysis_ulid},
    ))


async def get_shared_analysis(
    short_id: str, session: AsyncSession
) -> dict | None:
    """Fetch a public analysis by its share short ID.

    Returns a sanitized dict or None if not found / not public.
    """
    stmt = select(Analysis).where(
        Analysis.share_short_id == short_id,
        Analysis.is_public.is_(True),
    )
    result = await session.execute(stmt)
    analysis = result.scalar_one_or_none()

    if analysis is None:
        return None

    return sanitize_analysis_for_share(analysis)


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
