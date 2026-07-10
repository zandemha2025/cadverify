"""Cost-report PDF generation — WeasyPrint + Jinja2, file-cached, semaphore-bounded.

Mirrors ``pdf_service`` (the DFM PDF stack) but renders the NEW
``templates/pdf/cost_report.html`` for a persisted ``CostDecision``: geometry,
routing, per-process estimates with line items + provenance tags, the honest
confidence band (labeled "assumption-based, not yet validated" — never
"validated"), the make-vs-buy crossover, and the assumptions log.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
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


def _pdf_store():
    """Object store for cached cost-report PDFs.

    Uses the ops object-store seam (``src.storage``): local disk by default
    (rooted at ``PDF_CACHE_DIR``, byte-for-byte the historical file cache) and
    S3 when an operator opts in. One namespace ("cost-pdf") for every cached
    cost report — single-PDF downloads and RFQ-package items share it.
    """
    from src.storage import get_object_store

    return get_object_store("cost-pdf", default_root=PDF_CACHE_DIR)


def _cache_key(ulid: str, fingerprint: str) -> str:
    """Content-addressed cache key for a decision's rendered PDF.

    Keyed by the decision ULID *and* a fingerprint of the exact render inputs
    (the rendered HTML), so a cache entry is reused ONLY when the honest content
    is byte-for-byte what a fresh render would produce. Any change to the
    decision (result_json, label, engine version, …) changes the HTML, changes
    the fingerprint, and forces a re-render — the cache can never serve a stale
    or mismatched PDF. Guards against path traversal on both components.
    """
    assert "/" not in ulid and ".." not in ulid, f"Invalid ULID format: {ulid}"
    assert re.fullmatch(r"[0-9a-f]{8,64}", fingerprint), fingerprint
    return f"cost-{ulid}-{fingerprint}.pdf"

# autoescape on: mirrors pdf_service — user-controlled values (filename, etc.)
# are interpolated into HTML that WeasyPrint parses, so escaping is required to
# stop markup injection into the rendered PDF. No |safe expressions in the
# template, so no legitimate output changes.
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(("html", "xml")),
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


def _render_cost_pdf_sync(decision: CostDecision, html_str: str | None = None) -> bytes:
    """Render cost_report.html to PDF bytes (CPU-bound — call via executor)."""
    from weasyprint import HTML

    if html_str is None:
        html_str = render_cost_html(decision)
    return HTML(string=html_str, base_url=str(_TEMPLATE_DIR)).write_pdf()


def _fingerprint(html_str: str) -> str:
    """Stable content fingerprint of a rendered cost report (drives the cache key)."""
    return hashlib.sha256(html_str.encode("utf-8")).hexdigest()[:16]


async def generate_cost_pdf(decision: CostDecision, html_str: str | None = None) -> bytes:
    """Generate a cost-report PDF, bounded by the render semaphore."""
    async with _cost_pdf_semaphore:
        loop = asyncio.get_event_loop()
        pdf_bytes = await loop.run_in_executor(
            None, _render_cost_pdf_sync, decision, html_str
        )
    logger.info(
        "Cost PDF generated for %s (%d bytes)", decision.ulid, len(pdf_bytes)
    )
    return pdf_bytes


async def cached_cost_pdf(decision: CostDecision) -> bytes:
    """Return this decision's cost-report PDF, rendering ONCE and caching bytes.

    Content-addressed: the cache key embeds a fingerprint of the rendered HTML,
    so a hit is only ever served for byte-identical honest content and stale
    decisions self-invalidate (new fingerprint → miss → re-render). This is the
    hot path for BOTH the single-PDF download and every RFQ-package item, so a
    package download streams stored bytes with no per-request WeasyPrint render.
    """
    html_str = render_cost_html(decision)
    key = _cache_key(decision.ulid, _fingerprint(html_str))
    store = _pdf_store()
    try:
        if store.exists(key):
            logger.info("Serving cached cost PDF for %s (%s)", decision.ulid, key)
            return store.get(key)
    except Exception:  # pragma: no cover - cache read is best-effort
        logger.warning("Cost PDF cache read failed for %s", key, exc_info=True)

    pdf_bytes = await generate_cost_pdf(decision, html_str)
    try:
        store.put(key, pdf_bytes, content_type="application/pdf")
        logger.info("Cached cost PDF at %s", key)
    except Exception:  # pragma: no cover - caching is best-effort
        logger.warning("Failed to cache cost PDF at %s", key, exc_info=True)
    return pdf_bytes


async def precompute_cost_pdf(decision: CostDecision) -> bytes | None:
    """Warm the PDF cache for a decision (best-effort; never raises).

    Called when the durable evidence is assembled (RFQ-package create), so the
    heavy WeasyPrint render happens once, up front, and later downloads only
    stream stored bytes.
    """
    try:
        return await cached_cost_pdf(decision)
    except Exception:  # pragma: no cover - warming must not break the caller
        logger.warning(
            "Cost PDF precompute failed for %s", decision.ulid, exc_info=True
        )
        return None


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

    pdf_bytes = await cached_cost_pdf(decision)
    return pdf_bytes, decision.filename


def safe_cost_filename(filename: str) -> str:
    """Derive a safe '{stem}-cost-report.pdf' download filename."""
    stem = Path(filename).stem
    safe_stem = re.sub(r"[^\w\-.]", "_", stem)
    if not safe_stem:
        safe_stem = "cost"
    return f"{safe_stem}-cost-report.pdf"
