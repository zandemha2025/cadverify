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
from typing import cast

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src import __version__ as _app_version
from src.auth.org_context import caller_org_subquery
from src.db.models import CostDecision
from src.services.pdf_service import _format_number, _process_name

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
    """Format a number as USD, tolerating None/'N/A'. Cents round half-up on the
    stored number, as the screen does (src.costing.footing): $0.175 reads $0.18 in
    both, not $0.17 here and $0.18 there."""
    if value is None or value == "N/A":
        return "N/A"
    try:
        from src.costing.footing import cents

        return f"${cents(float(value)) / 100:,.2f}"
    except (ValueError, TypeError, ArithmeticError):
        return str(value)


def _footed(estimate) -> dict:
    """An estimate's lines to the cent with the Rounding line that makes them add up (ce-01)."""
    from src.costing.footing import footed_items

    e = estimate or {}
    return footed_items(e.get("line_items") or {}, e.get("unit_cost_usd"))


def _line_keys(estimates) -> list:
    from src.costing.footing import keys_in

    return keys_in(estimates or [])


def _line_name(key) -> str:
    from src.costing.footing import line_name

    return line_name(str(key))


def _pdf_text(value) -> str:
    """Prefer stable text glyphs when the PDF engine cannot place emoji glyphs.

    WeasyPrint/Pango can position an emoji variation selector as a separate
    fallback glyph, leaving symbols such as ``⚙️`` floating outside the note.
    The persisted/exported JSON and CSV values stay untouched; only the PDF
    presentation drops U+FE0F so the same symbol renders inline as text.
    """
    return str(value or "").replace("\ufe0f", "")


_jinja_env.filters["format_number"] = _format_number
_jinja_env.filters["format_money"] = _format_money
_jinja_env.filters["footed"] = _footed
_jinja_env.filters["line_keys"] = _line_keys
_jinja_env.filters["line_name"] = _line_name
_jinja_env.filters["pdf_text"] = _pdf_text
# Engine process ids read as the same names the v4 screens use ("cnc_3axis" → "3-axis milling").
_jinja_env.filters["process_name"] = _process_name


def _units(text, unit="mm", with_mm=False):
    """Engine text in the person's length unit (mm figures → in when chosen).

    ``with_mm`` (a supplier's copy) keeps each mm figure beside its inches.
    """
    from src.services.length_units import in_text

    return in_text(text, unit, keep_mm=with_mm)


_jinja_env.filters["units"] = _units


def stale_lines(governance: dict, rates: dict | None) -> list[str]:
    """What makes a saved record out of date, in words, for the top of its PDF (ce-14):
    the rate card it was priced at against the one in effect, and any other change
    (machines, material prices, calibration) since it was checked."""
    out = []
    rates = rates or {}
    rates_stale = bool(rates.get("out_of_date"))
    if rates_stale:
        out.append(f"{rates.get('text')} Re-cost before quoting.")
    if governance.get("is_stale"):
        code = str(governance.get("stale_reason") or "").partition(":")[0]
        if not (rates_stale and code == "rate_library_published"):
            words = {
                "rate_library_published": "New rates were published",
                "material_library_published": "New material prices were published",
                "machine_inventory_changed": "Your machines changed",
            }.get(code, "What it was priced from changed")
            when = str(governance.get("stale_at") or "")[:16].replace("T", " ")
            out.append(f"{words}{f' on {when} UTC' if when else ''}: check the part again before relying on it.")
    return out


def build_cost_pdf_context(decision: CostDecision, outbound: dict | None = None,
                           length_unit: str = "mm", rates: dict | None = None) -> dict:
    """Assemble the Jinja render context from a persisted CostDecision.

    ``outbound`` makes the supplier's copy (RFQ package): ``decision.result_json``
    is then already an ``outbound.cost_record`` and ``outbound`` is its
    ``outbound.rfq_governance`` (review status, out of date, requested route), so
    the report carries no approvers, recorded outcome, notes or file hash. A
    supplier's copy in inches keeps every mm figure alongside its inches
    ("11.81 × 7.874 × 3.937 in (300 × 200 × 100 mm)"): the drawing is in mm.
    """
    from src.services import length_units as lu
    from src.services.cost_decision_service import governance_fields

    unit = length_unit if length_unit in ("mm", "in") else "mm"
    with_mm = outbound is not None and unit == "in"
    gov = {} if outbound is not None else governance_fields(decision)
    rates = None if outbound is not None else rates
    geo = (decision.result_json or {}).get("geometry") or {}
    return {
        "length_unit": unit,
        "with_mm": with_mm,
        "geo_text": {
            "volume": (lu.volume_with_cm3 if with_mm else lu.volume_cm3)(geo.get("volume_cm3"), unit),
            "area": (lu.area_with_cm2 if with_mm else lu.area_cm2)(geo.get("surface_area_cm2"), unit),
            "bbox": (lu.dims_with_mm if with_mm else lu.dims)(geo.get("bbox_mm"), unit),
        },
        "filename": decision.filename,
        "file_type": decision.file_type,
        "label": decision.label,
        "created_at": decision.created_at.isoformat() if decision.created_at else "",
        "material_class": (decision.result_json or {}).get("material_class"),
        "result": decision.result_json or {},
        "engine_version": decision.engine_version or _app_version,
        "mesh_hash": "" if outbound is not None else (decision.mesh_hash or "")[:12],
        "governance": gov,
        "outbound": outbound,
        # Which rate card priced it, and what makes it out of date (ce-10, ce-14).
        "rates": rates,
        "stale_lines": [] if outbound is not None else stale_lines(gov, rates),
        "checked_at": (decision.created_at.strftime("%Y-%m-%d %H:%M UTC") if decision.created_at else ""),
    }


def render_cost_html(decision: CostDecision, outbound: dict | None = None,
                     length_unit: str = "mm", rates: dict | None = None) -> str:
    """Render the cost report template to HTML (no WeasyPrint dependency).

    Exposed so tests can assert on rendered content without the system PDF
    libraries, and reused by the sync PDF renderer below.
    """
    template = _jinja_env.get_template("cost_report.html")
    return template.render(**build_cost_pdf_context(decision, outbound, length_unit, rates))


def _render_cost_pdf_sync(decision: CostDecision, html_str: str | None = None) -> bytes:
    """Render cost_report.html to PDF bytes (CPU-bound — call via executor)."""
    from weasyprint import HTML

    if html_str is None:
        html_str = render_cost_html(decision)
    # write_pdf() with no target returns the PDF's bytes (WeasyPrint is untyped).
    return cast(bytes, HTML(string=html_str, base_url=str(_TEMPLATE_DIR)).write_pdf())


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


async def cached_cost_pdf(decision: CostDecision, outbound: dict | None = None,
                          length_unit: str = "mm", rates: dict | None = None) -> bytes:
    """Return this decision's cost-report PDF, rendering ONCE and caching bytes.

    Content-addressed: the cache key embeds a fingerprint of the rendered HTML,
    so a hit is only ever served for byte-identical honest content and stale
    decisions self-invalidate (new fingerprint → miss → re-render). This is the
    hot path for BOTH the single-PDF download and every RFQ-package item, so a
    package download streams stored bytes with no per-request WeasyPrint render.
    """
    html_str = render_cost_html(decision, outbound, length_unit, rates)
    key = _cache_key(decision.ulid, _fingerprint(html_str))
    store = _pdf_store()
    try:
        if await asyncio.to_thread(store.exists, key):
            logger.info("Serving cached cost PDF for %s (%s)", decision.ulid, key)
            return await asyncio.to_thread(store.get, key)
    except Exception:  # pragma: no cover - cache read is best-effort
        logger.warning("Cost PDF cache read failed for %s", key, exc_info=True)

    pdf_bytes = await generate_cost_pdf(decision, html_str)
    try:
        await asyncio.to_thread(
            store.put,
            key,
            pdf_bytes,
            content_type="application/pdf",
        )
        logger.info("Cached cost PDF at %s", key)
    except Exception:  # pragma: no cover - caching is best-effort
        logger.warning("Failed to cache cost PDF at %s", key, exc_info=True)
    return pdf_bytes


async def precompute_cost_pdf(
    decision: CostDecision, outbound: dict | None = None, length_unit: str = "mm"
) -> bytes | None:
    """Warm the PDF cache for a decision (best-effort; never raises).

    Called when the durable evidence is assembled (RFQ-package create), so the
    heavy WeasyPrint render happens once, up front, and later downloads only
    stream stored bytes.
    """
    try:
        return await cached_cost_pdf(decision, outbound, length_unit)
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

    # Lengths in the person's unit (mm or in), the same as their screens.
    from src.services.length_units import length_unit_for

    # Which rate card priced it and which is in effect: an out-of-date record's PDF says so (ce-14).
    from src.services.rate_card_basis import basis_for

    rates = (await basis_for(session, decision.org_id, [decision])).get(decision.ulid)
    pdf_bytes = await cached_cost_pdf(decision, length_unit=await length_unit_for(session, user_id), rates=rates)
    return pdf_bytes, decision.filename


def safe_cost_filename(filename: str, record_id: str | None = None, kind: str = "cost-report.pdf") -> str:
    """A safe download filename, unique per record: '{stem}-{last 6 of the record id}-cost-report.pdf'
    (ce-14: every pocket-block record exported as the same pocket-block-cost.csv)."""
    stem = Path(filename).stem
    safe_stem = re.sub(r"[^\w\-.]", "_", stem)
    if not safe_stem:
        safe_stem = "cost"
    rid = re.sub(r"[^0-9A-Za-z]", "", record_id or "")[-6:].upper()
    return f"{safe_stem}{f'-{rid}' if rid else ''}-{kind}"
