"""Vendor quote-back on public share links — the flywheel's front door.

A supplier opening ``/s/cost/{short_id}`` can answer with their actual price
(and optional lead time) in 30 seconds. The answer lands as a ground-truth
record on the SHARER's org (``source_type='quote'`` — a real quote, real
data), plus a notification so the owner sees it. This is how a share link
stops being a one-way view and becomes the should-cost loop's ground-truth
collector: every shared part starts measuring the estimate against reality.

Honesty rails, matching the ground-truth service's own:
* the record is QUOTE-typed and labelled vendor-entered; it never flips any
  ``validated`` flag by itself (calibration apply is still the owner's
  explicit, pilot-gated action);
* a vendor cannot see anything the share didn't already show them — the form
  accepts only price/lead/shop/contact/note;
* rate-limited at the route (10/hour/link), so a link can't be spammed into
  the org's ground-truth table.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import CostDecision
from src.services import share_links

logger = logging.getLogger("cadverify.quote_back")

_MAX_NOTE = 500
_MAX_TEXT = 120


def _clean_text(value: Any, limit: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:limit] or None


async def submit_quote_back(
    session: AsyncSession, short_id: str, payload: dict[str, Any],
) -> dict[str, Any]:
    """Record one vendor quote against the decision behind ``short_id``.

    Validates, ingests a ground-truth record for the sharer's org, emits the
    owner notification, commits. Raises ValueError with plain words on bad
    input (the route maps it to 422) and lets share_links' 404/410 for dead
    links propagate untouched.
    """
    d = (
        await session.execute(select(CostDecision).where(CostDecision.share_short_id == short_id))
    ).scalar_one_or_none()
    d = share_links.public_or_raise(d, "Shared cost decision not found")

    raw_cost = payload.get("unit_cost_usd")
    try:
        unit_cost = float(raw_cost)
    except (TypeError, ValueError):
        raise ValueError("unit_cost_usd must be a number (dollars per part)") from None
    if not 0.0001 <= unit_cost <= 10_000_000.0:
        raise ValueError("unit_cost_usd must be between $0.0001 and $10,000,000")

    quantity = payload.get("quantity")
    if quantity is None:
        opt = share_links.shows(d) if hasattr(share_links, "shows") else None
        from src.services import supplier_links

        quantity = supplier_links.shows(d)["quantity"] or 100
    if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= 2_147_483_647:
        raise ValueError("quantity must be a whole number of parts")

    lead_days = payload.get("lead_days")
    if lead_days is not None:
        if not isinstance(lead_days, int) or isinstance(lead_days, bool) or not 1 <= lead_days <= 3650:
            raise ValueError("lead_days must be 1-3650 days")

    result = d.result_json or {}
    decision = result.get("decision") or {}
    process = d.make_now_process or decision.get("make_now_process") or ""
    if not process:
        estimates = result.get("estimates") or []
        process = (estimates[0] or {}).get("process") if estimates else ""
    if not process:
        raise ValueError("This record carries no routed process to quote against")

    shop = _clean_text(payload.get("shop_name"), _MAX_TEXT)
    contact = _clean_text(payload.get("contact"), _MAX_TEXT)
    note = _clean_text(payload.get("note"), _MAX_NOTE)
    notes = "; ".join(
        part for part in (
            f"vendor lead {lead_days} days" if lead_days else "",
            f"contact {contact}" if contact else "",
            note or "",
        ) if part)

    from src.services import groundtruth_service, notification_service

    record = await groundtruth_service.ingest_record(
        session, org_id=d.org_id, user_id=None,
        payload={
            "part_id": d.mesh_hash,
            "process": process,
            "quantity": quantity,
            "actual_unit_cost_usd": unit_cost,
            "material_class": result.get("material_class") or "polymer",
            "shop": shop,
            "source": "share-link quote-back",
            "source_type": "quote",
            "match_basis": "chosen",
            "vendor_quote_id": short_id,
            "notes": notes or "vendor quote via share link",
        },
    )
    await notification_service.emit_notification(
        session,
        org_id=d.org_id,
        kind="quote.received",
        title=f"Quote received: {shop or 'a vendor'} — ${unit_cost:,.2f} each at {quantity:,}",
        body=(f"{d.filename or 'a shared part'}: a vendor answered the share link with "
              f"${unit_cost:,.2f} per part at quantity {quantity:,}"
              + (f", lead {lead_days} days" if lead_days else "")
              + ". It landed in Ground truth (source: quote); calibration stays your explicit call."),
        dest="app",
        source_type="cost_decision",
        source_id=str(d.ulid),
        metadata={"unit_cost_usd": unit_cost, "quantity": quantity,
                  "lead_days": lead_days, "vendor_quote_id": short_id},
    )
    await session.commit()
    logger.info(
        "quote_back recorded short_id=%s org=%s process=%s qty=%s unit_cost=%.4f",
        short_id, d.org_id, process, quantity, unit_cost,
    )
    return {
        "ok": True,
        "quantity": quantity,
        "process": process,
        "message": "Thank you — the buyer received your quote.",
    }
