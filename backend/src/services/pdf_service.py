"""PDF generation service — WeasyPrint + Jinja2 with file cache and semaphore.

Generates PDF reports from stored analysis results. Uses asyncio.Semaphore(2)
to limit concurrent CPU-intensive WeasyPrint renders and run_in_executor to
avoid blocking the event loop.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src import __version__ as _app_version
from src.db.models import Analysis

logger = logging.getLogger("cadverify.pdf")

PDF_CACHE_DIR = os.getenv("PDF_CACHE_DIR", "/data/pdf-cache/")
_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "pdf"

_pdf_semaphore = asyncio.Semaphore(2)

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=False,
)

# ── Custom Jinja2 filters ──────────────────────────────────────


def _format_duration(ms: float | int) -> str:
    """Format milliseconds as a human-readable duration string."""
    if ms is None:
        return "N/A"
    return f"{ms / 1000:.2f}s"


def _format_number(value) -> str:
    """Format a number with thousand separators."""
    if value is None or value == "N/A":
        return str(value) if value else "N/A"
    try:
        return f"{int(value):,}"
    except (ValueError, TypeError):
        return str(value)


_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def _sort_by_severity(issues: list[dict]) -> list[dict]:
    """Sort issues by severity: error first, then warning, then info."""
    return sorted(issues, key=lambda i: _SEVERITY_ORDER.get(i.get("severity", "info"), 99))


def _merge_key(issue: dict, key: str, value: str) -> dict:
    """Return a copy of the issue dict with an extra key merged in."""
    merged = dict(issue)
    merged[key] = value
    return merged


_jinja_env.filters["format_duration"] = _format_duration
_jinja_env.filters["format_number"] = _format_number
_jinja_env.filters["sort_by_severity"] = _sort_by_severity
_jinja_env.filters["merge_key"] = _merge_key


# ── PDF rendering ──────────────────────────────────────────────


def _render_pdf_sync(context: dict) -> bytes:
    """Render the analysis report template to PDF bytes (synchronous).

    This is CPU-bound work — always call via run_in_executor.
    """
    from weasyprint import HTML

    template = _jinja_env.get_template("analysis_report.html")
    html_str = template.render(**context)
    pdf_bytes = HTML(
        string=html_str,
        base_url=str(_TEMPLATE_DIR),
    ).write_pdf()
    return pdf_bytes


async def generate_pdf(analysis: Analysis) -> bytes:
    """Generate a PDF report for the given analysis.

    Acquires _pdf_semaphore to limit concurrency, then renders via
    run_in_executor to avoid blocking the event loop.
    """
    context = {
        "filename": analysis.filename,
        "file_type": analysis.file_type,
        "verdict": analysis.verdict,
        "face_count": analysis.face_count,
        "duration_ms": analysis.duration_ms,
        "created_at": analysis.created_at.isoformat(),
        "result": analysis.result_json,
        "engine_version": _app_version,
        "mesh_hash": (analysis.mesh_hash or "")[:12],
    }

    async with _pdf_semaphore:
        loop = asyncio.get_event_loop()
        pdf_bytes = await loop.run_in_executor(None, _render_pdf_sync, context)

    logger.info(
        "PDF generated for analysis %s (%d bytes)",
        analysis.ulid,
        len(pdf_bytes),
    )
    return pdf_bytes


# ── Cache + orchestration ──────────────────────────────────────


async def get_or_generate_pdf(
    analysis_ulid: str,
    user_id: int,
    session: AsyncSession,
) -> tuple[bytes, str]:
    """Look up analysis, serve cached PDF or generate a new one.

    Returns (pdf_bytes, original_filename).
    Raises HTTPException 404 if analysis not found or not owned by user.
    """
    stmt = select(Analysis).where(
        Analysis.ulid == analysis_ulid,
        Analysis.user_id == user_id,
    )
    result = await session.execute(stmt)
    analysis = result.scalar_one_or_none()

    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found")

    # T-04B-01: Validate ULID has no path traversal characters
    assert "/" not in analysis.ulid and ".." not in analysis.ulid, (
        f"Invalid ULID format: {analysis.ulid}"
    )

    cache_path = Path(PDF_CACHE_DIR) / f"{analysis.ulid}.pdf"

    # Serve from cache if available
    if cache_path.exists():
        logger.info("Serving cached PDF for %s", analysis.ulid)
        pdf_bytes = cache_path.read_bytes()
        return pdf_bytes, analysis.filename

    # Generate and cache
    pdf_bytes = await generate_pdf(analysis)

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(pdf_bytes)
        logger.info("Cached PDF at %s", cache_path)
    except OSError:
        logger.warning("Failed to cache PDF at %s", cache_path, exc_info=True)

    return pdf_bytes, analysis.filename


def _safe_filename(filename: str) -> str:
    """Derive a safe download filename from the original upload filename.

    Returns '{stem}-dfm-report.pdf' with unsafe characters stripped.
    """
    stem = Path(filename).stem
    # Strip anything that is not alphanumeric, dash, underscore, or dot
    safe_stem = re.sub(r"[^\w\-.]", "_", stem)
    if not safe_stem:
        safe_stem = "analysis"
    return f"{safe_stem}-dfm-report.pdf"
