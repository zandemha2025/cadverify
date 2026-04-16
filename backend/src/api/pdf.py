"""PDF download endpoint — GET /analyses/{analysis_id}/pdf.

Returns a rendered PDF of the analysis report with proper Content-Disposition
header for browser download.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.rate_limit import limiter
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session
from src.services import pdf_service
from src.services.pdf_service import _safe_filename

logger = logging.getLogger("cadverify.pdf")

router = APIRouter(tags=["pdf"])


@router.get("/{analysis_id}/pdf")
@limiter.limit("60/hour;500/day")
async def download_pdf(
    analysis_id: str,
    request: Request,
    user: AuthedUser = Depends(require_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """Download a PDF report for the specified analysis."""
    pdf_bytes, original_filename = await pdf_service.get_or_generate_pdf(
        analysis_ulid=analysis_id,
        user_id=user.user_id,
        session=session,
    )

    safe_name = _safe_filename(original_filename)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
        },
    )
