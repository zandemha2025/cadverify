"""Cost-report PDF generation — WeasyPrint + Jinja2, file-cached, semaphore-bounded.

Mirrors ``pdf_service`` (the DFM PDF stack) but renders the NEW
``templates/pdf/cost_report.html`` for a persisted ``CostDecision``: geometry,
routing, per-process estimates with line items + provenance tags, the honest
confidence band (labeled "assumption-based, not yet validated" — never
"validated"), the make-vs-buy crossover, and the assumptions log.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src import __version__ as _app_version
from src.auth.org_context import caller_org_subquery
from src.db.models import CostDecision
from src.services.pdf_service import _format_number

logger = logging.getLogger("cadverify.cost_pdf")

PDF_CACHE_DIR = os.getenv("PDF_CACHE_DIR", "/data/pdf-cache/")
_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "pdf"

_cost_pdf_semaphore = asyncio.Semaphore(2)

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=False,
)


def _format_money(value) -> str:
    """Format a number as USD, tolerating None/'N/A'."""
    if value is None or value == "N/A":
        return "N/A"
    try:
        return f"${float(value):,.2f}"
    except (ValueError, TypeError):
        return str(value)


_jinja_env.filters["format_number"] = _format_number
_jinja_env.filters["format_money"] = _format_money


def build_cost_pdf_context(decision: CostDecision) -> dict:
    """Assemble the Jinja render context from a persisted CostDecision."""
    return {
        "filename": decision.filename,
        "file_type": decision.file_type,
        "label": decision.label,
        "created_at": decision.created_at.isoformat(),
        "material_class": (decision.result_json or {}).get("material_class"),
        "result": decision.result_json or {},
        "engine_version": decision.engine_version or _app_version,
        "mesh_hash": (decision.mesh_hash or "")[:12],
    }


def render_cost_html(decision: CostDecision) -> str:
    """Render the cost report template to HTML (no WeasyPrint dependency).

    Exposed so tests can assert on rendered content without the system PDF
    libraries, and reused by the sync PDF renderer below.
    """
    template = _jinja_env.get_template("cost_report.html")
    return template.render(**build_cost_pdf_context(decision))


def _render_cost_pdf_sync(decision: CostDecision) -> bytes:
    """Render cost_report.html to PDF bytes (CPU-bound — call via executor)."""
    from weasyprint import HTML

    html_str = render_cost_html(decision)
    return HTML(string=html_str, base_url=str(_TEMPLATE_DIR)).write_pdf()


async def generate_cost_pdf(decision: CostDecision) -> bytes:
    """Generate a cost-report PDF, bounded by the render semaphore."""
    async with _cost_pdf_semaphore:
        loop = asyncio.get_event_loop()
        pdf_bytes = await loop.run_in_executor(
            None, _render_cost_pdf_sync, decision
        )
    logger.info(
        "Cost PDF generated for %s (%d bytes)", decision.ulid, len(pdf_bytes)
    )
    return pdf_bytes


async def get_or_generate_cost_pdf(
    ulid: str, user_id: int, session: AsyncSession
) -> tuple[bytes, str]:
    """Look up a cost decision in the caller's org, serve/generate its PDF.

    Returns (pdf_bytes, original_filename). Raises HTTPException 404 if the
    decision does not exist or belongs to another org (W1 step 3: org-scoped).
    """
    from fastapi import HTTPException

    stmt = select(CostDecision).where(
        CostDecision.ulid == ulid,
        CostDecision.org_id == caller_org_subquery(user_id),
    )
    decision = (await session.execute(stmt)).scalar_one_or_none()
    if decision is None:
        raise HTTPException(status_code=404, detail="Cost decision not found")

    # Guard against path traversal in the cache filename.
    assert "/" not in decision.ulid and ".." not in decision.ulid, (
        f"Invalid ULID format: {decision.ulid}"
    )

    cache_path = Path(PDF_CACHE_DIR) / f"cost-{decision.ulid}.pdf"
    if cache_path.exists():
        logger.info("Serving cached cost PDF for %s", decision.ulid)
        return cache_path.read_bytes(), decision.filename

    pdf_bytes = await generate_cost_pdf(decision)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(pdf_bytes)
        logger.info("Cached cost PDF at %s", cache_path)
    except OSError:
        logger.warning("Failed to cache cost PDF at %s", cache_path, exc_info=True)

    return pdf_bytes, decision.filename


def safe_cost_filename(filename: str) -> str:
    """Derive a safe '{stem}-cost-report.pdf' download filename."""
    stem = Path(filename).stem
    safe_stem = re.sub(r"[^\w\-.]", "_", stem)
    if not safe_stem:
        safe_stem = "cost"
    return f"{safe_stem}-cost-report.pdf"
