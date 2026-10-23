"""What a share link shows a supplier, and package links.

A record's link (``/s/cost/{id}``) and a package's link (``/s/pkg/{id}``) are
what a buyer sends a supplier. Anyone with the link can open it without signing
in, until it ends or is switched off (``src.services.share_links``).

A record's link shows what a supplier quotes from: the part (name, size,
material), its specs, the quantity, the buyer's note, and the CAD file only
when the sharer ticked it. Our should-cost (prices, price lines, crossover, the
make-vs-buy reasoning, assumptions) is in it only when the sharer turned
"Include our cost estimate" on, and then as ``outbound.cost_share`` cleans it.
A link made before these options (``share_options`` NULL) shows no cost: it
fails closed. Review state is never in it.

A package's link shows the package as its ZIP does
(``rfq_package_service.supplier_view``): the brief, every part, the CAD the
package holds and a ZIP of it all; our cost only when the package was built
with it.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.org_context import caller_org_subquery
from src.db.models import CostDecision, PartContext, RfqPackage
from src.services import outbound, share_links
from src.services import rfq_package_service as rfq

logger = logging.getLogger("cadverify.supplier_links")


def shows(row: Any) -> dict[str, Any]:
    """What a link shows; a link made before options shows no cost and no CAD."""
    opts = getattr(row, "share_options", None)
    opts = opts if isinstance(opts, dict) else {}
    return {"include_cost": opts.get("include_cost") is True, "include_cad": opts.get("include_cad") is True,
            "note": opts.get("note") if isinstance(opts.get("note"), str) else None,
            "quantity": opts.get("quantity") if isinstance(opts.get("quantity"), int) else None}


async def _part_context(session: AsyncSession, d: CostDecision) -> Optional[PartContext]:
    return (
        await session.execute(
            select(PartContext).where(PartContext.org_id == d.org_id, PartContext.mesh_hash == d.mesh_hash)
        )
    ).scalars().first()


async def _cad_info(d: CostDecision) -> Optional[dict[str, Any]]:
    from src.services import kept_part_jobs

    try:
        info = await kept_part_jobs.kept_source_info(d.org_id, d.mesh_hash)
    except Exception:  # noqa: BLE001
        return None
    if info is None or info.size > rfq._cad_max_bytes():
        return None
    return {"filename": rfq._cad_name(d.filename, info.suffix), "bytes": info.size, "suffix": info.suffix}


async def record_view(session: AsyncSession, d: CostDecision, short_id: str) -> dict[str, Any]:
    """``GET /s/cost/{id}``: the part as a supplier is asked to quote it."""
    opt = shows(d)
    ctx = await _part_context(session, d)
    specs = outbound.part_specs(getattr(ctx, "part_specs", None))
    yearly = getattr(ctx, "annual_volume", None)
    status = rfq._decision_status(d)
    requested = outbound.requested_route(status["user_disposition"], status["disposition_basis"])
    req = rfq._request(d, requested, None, {"annual_volume": yearly} if yearly else None,
                       await rfq._run_facts(session, d), opt["quantity"])
    terms = await outbound.org_names(session, d.org_id)
    geo = ((d.result_json or {}).get("geometry") or {})
    from src.costing.part_specs import spec_summary

    out: dict[str, Any] = {
        "kind": "part",
        "name": outbound.text(req["name"], outbound._Terms(terms)) or d.filename,
        "filename": d.filename,
        "file_type": d.file_type,
        "label": d.label,
        "material": req["material"],
        "quantity": req["quantity"],
        "yearly_volume": req["yearly_volume"],
        "bbox_mm": geo.get("bbox_mm") if isinstance(geo.get("bbox_mm"), list) else None,
        "specs": spec_summary(specs) if specs else [],
        "must_hold": outbound.supplier_must_hold(specs) if specs else [],
        "note": opt["note"],
        "includes_cost_estimate": opt["include_cost"],
        "cad": None,
        **share_links.public_meta(d),
    }
    if opt["include_cad"]:
        info = await _cad_info(d)
        if info:
            out["cad"] = {"filename": info["filename"], "bytes": info["bytes"], "url": f"/s/cost/{short_id}/cad"}
    if opt["include_cost"]:
        out["cost"] = outbound.cost_share(d, terms=terms)
    return out


async def record_cad(session: AsyncSession, short_id: str) -> tuple[str, bytes]:
    """The CAD file of a record's working link, when its sharer included it."""
    from src.services.source_artifact_service import read_source_artifact

    d = (await session.execute(select(CostDecision).where(CostDecision.share_short_id == short_id))
         ).scalar_one_or_none()
    d = share_links.public_or_raise(d, "Shared part not found")
    if not shows(d)["include_cad"]:
        raise HTTPException(status_code=404, detail="This link doesn't include the CAD file.")
    info = await _cad_info(d)
    if info is None:
        raise HTTPException(status_code=404, detail="The CAD file isn't available any more.")
    try:
        data, _suffix = await read_source_artifact(d.org_id, d.mesh_hash, info["suffix"])
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=404, detail="The CAD file isn't available any more.")
    return info["filename"], data


# ── packages ──────────────────────────────────────────────────────────────────
async def _owned_package(session: AsyncSession, package_id: str, user_id: int) -> RfqPackage:
    pkg = (
        await session.execute(
            select(RfqPackage)
            .where(RfqPackage.ulid == package_id, RfqPackage.org_id == caller_org_subquery(user_id))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if pkg is None:
        raise HTTPException(status_code=404, detail="RFQ package not found.")
    return pkg


def package_link(pkg: RfqPackage) -> dict[str, Any]:
    return {"share_url": share_links.url_for(pkg) if share_links.status(pkg) == "active" else None,
            "share_short_id": pkg.share_short_id, **share_links.fields(pkg)}


async def _fresh_package_short_id(session: AsyncSession, tries: int = 5) -> str:
    """A short id no package holds: the generator record and check links use (12
    random base62 characters), tried again on the (unique-indexed) collision."""
    from src.services.share_service import generate_short_id

    for _ in range(tries):
        short_id = generate_short_id()
        taken = (await session.execute(
            select(RfqPackage.id).where(RfqPackage.share_short_id == short_id))).first()
        if taken is None:
            return short_id
    raise HTTPException(status_code=503, detail="The link wasn't made. Try again in a moment.")


async def create_package_link(session: AsyncSession, package_id: str, user_id: int,
                              options: share_links.ShareOptions) -> dict[str, Any]:
    """Share a package as one link. A link that is on is replaced by the new one
    (the old one stops working); the package itself decides whether our cost is in it."""
    from src.services.audit_service import emit_event

    pkg = await _owned_package(session, package_id, user_id)
    replaced = pkg.share_short_id if share_links.status(pkg) == "active" else None
    if replaced is not None:
        # Replacing switches the live link off: its maker or an org admin only.
        await share_links.require_can_switch_off(session, pkg, user_id)
    short_id = await _fresh_package_short_id(session)
    share_links.open_link(pkg, user_id, options.expires_in_days, short_id, ends_at=options.ends_at(),
                          shows={"include_cost": rfq.includes_cost(pkg), "include_cad": True, "note": None,
                                 "quantity": None})
    await emit_event(
        session, actor_id=user_id, action="share.created", resource_type="share", resource_id=short_id,
        detail={"rfq_package_ulid": package_id, "replaced": replaced,
                "expires_at": pkg.share_expires_at.isoformat() if pkg.share_expires_at else None},
        org_id=pkg.org_id,
    )
    await session.commit()
    logger.info("RFQ package %s shared as /s/pkg/%s by user %d", package_id, short_id, user_id)
    return package_link(pkg)


async def revoke_package_link(session: AsyncSession, package_id: str, user_id: int) -> None:
    from src.services.audit_service import emit_event

    pkg = await _owned_package(session, package_id, user_id)
    if share_links.status(pkg) != "active":
        return
    await share_links.require_can_switch_off(session, pkg, user_id)
    share_links.close_link(pkg)
    await emit_event(session, actor_id=user_id, action="share.revoked", resource_type="share",
                     resource_id=pkg.share_short_id, detail={"rfq_package_ulid": package_id}, org_id=pkg.org_id)
    await session.commit()


async def _public_package(session: AsyncSession, short_id: str) -> RfqPackage:
    pkg = (await session.execute(select(RfqPackage).where(RfqPackage.share_short_id == short_id))
           ).scalar_one_or_none()
    return share_links.public_or_raise(pkg, "Shared package not found")


async def package_view(session: AsyncSession, short_id: str) -> dict[str, Any]:
    """``GET /s/pkg/{id}``: the package as its supplier reads it."""
    pkg = await _public_package(session, short_id)
    unit = await rfq._supplier_unit(session, pkg)
    terms = await outbound.org_names(session, pkg.org_id)
    items = [outbound.rfq_item(item, terms=terms) for item in pkg.items_json or []]
    view = rfq.supplier_view(pkg, items, unit)
    for part in view["parts"]:
        part.pop("folder", None)
        if part.get("cad"):
            part["cad"] = {"filename": part["cad"]["filename"], "bytes": part["cad"].get("bytes"),
                           "url": f"/s/pkg/{short_id}/cad/{part['line']}"}
    return {"kind": "package", **view, "zip_url": f"/s/pkg/{short_id}/download.zip",
            **share_links.public_meta(pkg)}


async def package_zip(session: AsyncSession, short_id: str) -> tuple[str, bytes]:
    pkg = await _public_package(session, short_id)
    from src.api.rfq_packages import _safe_zip_name

    return _safe_zip_name(pkg.title, short_id), await rfq.build_zip(session, pkg)


async def package_cad(session: AsyncSession, short_id: str, line: int) -> tuple[str, bytes]:
    pkg = await _public_package(session, short_id)
    items = pkg.items_json or []
    if not 1 <= line <= len(items):
        raise HTTPException(status_code=404, detail="No such part in this package.")
    cad = await rfq.part_cad(session, pkg, outbound.rfq_item(items[line - 1]))
    if cad is None:
        raise HTTPException(status_code=404, detail="This part's CAD file isn't in the package.")
    return cad
