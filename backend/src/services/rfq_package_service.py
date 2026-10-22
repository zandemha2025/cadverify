"""RFQ packages: what a buyer sends a supplier to quote.

A package is built from saved records and downloaded as a ZIP (or opened from a
package link). ScaleCAD doesn't send it and doesn't track replies.

What a supplier receives, by default, is what a supplier quotes from and
nothing else:

* per part: its name, part number, material, the quantity asked for (and the
  yearly volume when the part has one), its specs (finish, inspection,
  certifications the supplier must hold, tolerances), the buyer's note and the
  CAD file the organization kept;
* for the package: who asks (name, company, email), the reply-by date and a
  plain list of what is in it.

Our own numbers stay with the organization: the should-cost, the price lines,
the crossover, the make-vs-buy reasoning, and the record's review state
(approved, out of date, confidence). The buyer can deliberately add the cost
estimate to one package ("Include our cost estimate"); then each part also
carries its should-cost report, its price lines and the record as data, as
``outbound.cost_record`` cleans them. Approval state never goes.

Every record in a package is saved as ``outbound.rfq_item`` (the shop's
machines, rates, in-house routes and choices, calibration, approvers and notes
never go in), and a package saved before that is cleaned on every read.

Lengths in a supplier's copy lead with the unit of the person who builds the
package, with millimetres alongside when that unit is inches. The unit is saved
on the package (``metadata.length_unit``); a package saved before that uses the
requester's current choice. JSON stays in mm.

The CAD file is the organization's kept source of the part
(``source_artifact_service``: every check and cost run keeps it), so a record
re-checked with new specs, a single upload and a catalog run all carry it. A
part from before files were kept falls back to its catalog run's ZIP.
"""
from __future__ import annotations

import asyncio
import csv
import html
import io
import json
import os
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.auth.org_context import caller_org_subquery, resolve_org
from src.auth.require_api_key import AuthedUser
from src.db.models import Batch, BatchItem, CostDecision, ManifestPart, PartContext, RfqPackage
from src.services import cost_decision_service, outbound
from src.services import length_units as lu
from src.services.cost_pdf_service import cached_cost_pdf, precompute_cost_pdf

MAX_ITEMS = 25
DEFAULT_CAD_MAX_MB = 200.0

# Strong refs to in-flight cache-warm tasks so they are not GC'd mid-render.
_WARM_TASKS: set = set()
_RFQ_PDF_SEMAPHORE = asyncio.Semaphore(2)

# The quantities ScaleCAD prices when nobody names one (the single check and the
# catalog run, catalog_run_service.QTY_LADDER); a record's other point is the
# quantity that was asked for.
_LADDER = frozenset({1, 10, 100, 1000, 2000, 5000, 10000})
_MATERIAL_WORDS = {
    "polymer": "Plastic", "aluminum": "Aluminum", "steel": "Steel", "stainless": "Stainless steel",
    "titanium": "Titanium", "nickel": "Nickel alloy", "cobalt": "Cobalt-chrome", "copper": "Copper",
    "zinc": "Zinc",
}
QUANTITY_SOURCES = {
    "package": "set in this package",
    "outside_route": "the route marked to buy outside",
    "yearly_volume": "the part's yearly volume",
    "run": "the run it was checked in",
    "record": "the record's quantity",
}


@dataclass(frozen=True)
class RfqPackageOptions:
    title: str | None = None
    supplier_name: str | None = None
    note: str | None = None
    include_raw_cad: bool = False
    # Our should-cost goes to the supplier only when the buyer turns this on.
    include_cost_estimate: bool = False
    reply_by: date | None = None
    # {"name", "company", "email"}; None uses the requester's account.
    requested_by: dict | None = None
    # decision id → the quantity to ask for, as the buyer set it in the builder.
    quantities: dict[str, int] = field(default_factory=dict)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _savepoint(session: Any):
    """A savepoint for a best-effort read, so its failure never aborts the caller's
    transaction (a plain context for test doubles)."""
    from contextlib import nullcontext

    return session.begin_nested() if isinstance(session, AsyncSession) else nullcontext()


def _clean_text(value: str | None, *, max_len: int = 200) -> str | None:
    clean = (value or "").strip() if isinstance(value, str) else ""
    return clean[:max_len] if clean else None


def _safe_name(value: str, fallback: str) -> str:
    stem = Path(value or fallback).stem or fallback
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._")
    return safe or fallback


def _cad_max_bytes() -> int:
    try:
        mb = float(os.getenv("RFQ_CAD_MAX_MB", str(DEFAULT_CAD_MAX_MB)))
    except ValueError:
        mb = DEFAULT_CAD_MAX_MB
    return int(max(0.0, mb) * 1024 * 1024)


def _day(value: Any) -> str | None:
    """``2026-11-05`` → ``5 Nov 2026``."""
    if not value:
        return None
    try:
        d = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
    return f"{d.day} {d:%b %Y}"


def _decision_status(decision: CostDecision) -> dict[str, Any]:
    gov = cost_decision_service.governance_fields(decision)
    return {
        **gov,
        "approved": gov["approval_status"] == cost_decision_service.APPROVAL_APPROVED,
        "stale": bool(gov["is_stale"]),
    }


def _snapshot_decision(item: dict[str, Any]) -> CostDecision:
    """Adapt a package record (``outbound.rfq_item``) to the PDF renderer, without
    a live row: the file and the supplier's copy of the should-cost. Approvers,
    outcomes, notes and the review status are not in it."""
    meta = item["decision"]
    fields = {key: meta.get(key) for key in ("filename", "file_type", "label")}
    fields["created_at"] = (
        datetime.fromisoformat(meta["created_at"]) if meta.get("created_at") else None
    )
    return CostDecision(
        ulid=meta.get("id") or "unknown", engine_version=meta.get("engine_version") or "unknown",
        result_json=item["cost_decision"], approval_status=None, **fields,
    )


def _supplier_governance(meta: dict[str, Any]) -> dict[str, Any]:
    """What the should-cost report says about the request, when the buyer includes
    it: the route asked for. Never the review status or whether it is out of date."""
    gov = outbound.rfq_governance(meta)
    return {"approval_status": None, "is_stale": False, "requested": gov.get("requested")}


def _normalized_stem(value: str | None) -> str:
    stem = Path(value or "").name.lower()
    return re.sub(r"\.(stl|step|stp|iges|igs)$", "", stem)


async def _manifest_match(
    session: AsyncSession, decision: CostDecision
) -> dict[str, Any] | None:
    stem = _normalized_stem(decision.filename)
    if not stem:
        return None
    rows = (
        await session.execute(
            select(ManifestPart)
            .where(ManifestPart.org_id == decision.org_id)
            .order_by(ManifestPart.part_id.asc())
        )
    ).scalars().all()
    for row in rows:
        if _normalized_stem(row.part_id) == stem:
            from src.services.manifest_service import part_to_public

            return {
                "match": "normalized-stem, exact",
                "basis": {
                    "decision_filename": decision.filename,
                    "manifest_part_id": row.part_id,
                },
                "part": part_to_public(row),
            }
    return None


async def _part_context(
    session: AsyncSession, decision: CostDecision
) -> dict[str, Any] | None:
    row = (
        await session.execute(
            select(PartContext).where(
                PartContext.org_id == decision.org_id,
                PartContext.mesh_hash == decision.mesh_hash,
            )
        )
    ).scalars().first()
    if row is None:
        return None
    annual = row.annual_volume
    try:  # the yearly volume the part page shows (a BOM rollup when the part names one)
        from src.services import bom_service

        async with _savepoint(session):
            annual = (await bom_service.annual_volume_for_context(session, decision.org_id, row))[
                "annual_volume"] or annual
    except Exception:  # noqa: BLE001 - the declared figure is the honest fallback
        pass
    return {
        "program": row.program,
        "parent_assembly": row.parent_assembly,
        "units_per_parent": row.units_per_parent,
        "annual_volume": annual,
        "service_environment": row.service_environment,
        "part_specs": row.part_specs,
        "provenance": "user_declared",
    }


async def _run_facts(session: AsyncSession, decision: CostDecision) -> dict[str, Any]:
    """What the catalog run that checked this part was told about it: the quantity
    (the parts list's, else the run's) and the list's part number, description
    and material. A record re-checked later is the same part, so any record of
    the part in a run counts; the newest run wins. Empty when it wasn't in one."""
    try:
        async with _savepoint(session):
            row = (
                await session.execute(
                    select(BatchItem.filename, Batch)
                    .join(Batch, Batch.id == BatchItem.batch_id)
                    .join(CostDecision, CostDecision.id == BatchItem.cost_decision_id)
                    .where(
                        CostDecision.org_id == decision.org_id,
                        CostDecision.mesh_hash == decision.mesh_hash,
                        Batch.job_type == "catalog",
                    )
                    .order_by(Batch.created_at.desc(), BatchItem.id.desc())
                    .limit(1)
                )
            ).first()
    except Exception:  # noqa: BLE001 - best effort; the record's own facts remain
        return {}
    try:
        filename, batch = row[0], row[1]
    except (TypeError, IndexError, KeyError):
        return {}
    if not isinstance(filename, str):
        return {}
    meta = dict(((getattr(batch, "manifest_json", None) or {}).get("catalog")) or {})
    listed = ((meta.get("items") or {}).get(filename)) or {}
    out = {k: listed.get(k) for k in ("part_number", "description", "material") if listed.get(k)}
    qty = listed.get("quantity") or meta.get("quantity")
    if isinstance(qty, int) and qty > 0:
        out["quantity"] = qty
    return out


def _declared_quantity(quantities: Any) -> int | None:
    """The one quantity a record was priced at that isn't on ScaleCAD's own ladder."""
    off = [q for q in quantities or [] if isinstance(q, int) and q > 0 and q not in _LADDER]
    return off[0] if len(off) == 1 else None


def _material_words(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return _MATERIAL_WORDS.get(value.strip().lower(), value.strip())


def _request(
    decision: CostDecision,
    requested: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
    context: dict[str, Any] | None,
    run: dict[str, Any],
    override: int | None,
) -> dict[str, Any]:
    """The part as a supplier is asked to quote it (see the module doc)."""
    part = (manifest or {}).get("part") or {}
    yearly = (context or {}).get("annual_volume") or part.get("annual_volume")
    yearly = yearly if isinstance(yearly, int) and yearly > 0 else None
    quantity, source = None, None
    for value, why in (
        (override, "package"),
        ((requested or {}).get("quantity"), "outside_route"),
        (yearly, "yearly_volume"),
        (run.get("quantity"), "run"),
        (_declared_quantity(decision.quantities or (decision.result_json or {}).get("quantities")), "record"),
    ):
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            quantity, source = value, why
            break
    material = (
        (requested or {}).get("material")
        or run.get("material")
        or _material_words(part.get("material_class"))
        or _material_words((decision.result_json or {}).get("material_class"))
    )
    return {
        "name": decision.label or decision.filename,
        "filename": decision.filename,
        "part_number": part.get("part_id") or run.get("part_number"),
        "description": part.get("description") or run.get("description"),
        "material": material,
        "quantity": quantity,
        "quantity_source": source,
        "yearly_volume": yearly,
        "process": (requested or {}).get("process"),
    }


def _cad_name(decision_filename: str | None, suffix: str) -> str:
    stem = _safe_name(decision_filename or "", "part")
    return f"{stem}{suffix}"


async def _raw_cad_payload(
    session: AsyncSession, decision: CostDecision, include_requested: bool, *, read: bool = True
) -> tuple[str | None, bytes | None, dict[str, Any]]:
    """The part's CAD for the supplier: ``(file name, bytes, what the package says)``.

    The organization's kept source first (every check and cost run keeps it),
    else, for a part from before files were kept, its catalog run's ZIP.
    ``read=False`` only says whether it is there (building the package doesn't
    read the file; the download does).
    """
    if not include_requested:
        return None, None, {"included": False, "reason": "not_requested"}

    from src.services import kept_part_jobs
    from src.services.source_artifact_service import read_source_artifact

    try:
        info = await kept_part_jobs.kept_source_info(decision.org_id, decision.mesh_hash)
    except Exception:  # noqa: BLE001 - a storage error reads as "not kept", never a crash
        info = None
    if info is not None:
        name = _cad_name(decision.filename, info.suffix)
        if info.size > _cad_max_bytes():
            return None, None, {"included": False, "reason": "too_large", "filename": name, "bytes": info.size}
        meta = {"included": True, "source": "kept_source", "filename": name, "bytes": info.size}
        if not read:
            return name, None, meta
        try:
            data, _suffix = await read_source_artifact(decision.org_id, decision.mesh_hash, info.suffix)
        except Exception:  # noqa: BLE001
            return None, None, {"included": False, "reason": "kept_source_unreadable", "filename": name}
        return name, data, meta

    row = (
        await session.execute(
            select(BatchItem, Batch)
            .join(Batch, Batch.id == BatchItem.batch_id)
            .where(
                BatchItem.org_id == decision.org_id,
                BatchItem.cost_decision_id == decision.id,
                Batch.input_mode == "zip",
                BatchItem.status == "completed",
            )
            .order_by(BatchItem.completed_at.desc().nullslast(), BatchItem.id.desc())
        )
    ).first()
    if row is None:
        return None, None, {"included": False, "reason": "not_kept"}
    item, batch = row
    try:
        from src.services.batch_service import read_batch_blob

        data = await asyncio.to_thread(read_batch_blob, batch.ulid, item.filename)
    except (OSError, KeyError):
        return None, None, {"included": False, "reason": "not_kept", "filename": item.filename}
    return item.filename, data, {
        "included": True,
        "source": "same_org_batch_zip_blob",
        "filename": item.filename,
        "bytes": len(data),
    }


async def _requester(session: AsyncSession, user_id: int, org_id: str) -> dict[str, str | None]:
    """Who asks: the requester's name and email, and the organization's name as the
    company (a personal workspace has no company name)."""
    from src.db.models import Organization, User

    out: dict[str, str | None] = {"name": None, "company": None, "email": None}
    try:
        async with _savepoint(session):
            user = await session.get(User, user_id)
            org = await session.get(Organization, org_id)
    except Exception:  # noqa: BLE001
        return out
    name, email = getattr(user, "full_name", None), getattr(user, "email", None)
    out["name"] = name.strip() or None if isinstance(name, str) else None
    out["email"] = email if isinstance(email, str) else None
    org_name = getattr(org, "name", None)
    if isinstance(org_name, str) and getattr(org, "is_personal", None) is not True:
        out["company"] = org_name.strip() or None
    return out


def _clean_requester(given: dict | None, account: dict[str, str | None]) -> dict[str, str | None]:
    """The builder's "Requested by" (prefilled from the account, editable)."""
    if not isinstance(given, dict):
        return account
    return {k: _clean_text(given.get(k), max_len=200) for k in ("name", "company", "email")}


def _part_size(item: dict[str, Any], unit: str) -> str | None:
    """The part's measured size for the supplier, the copy's unit first (mm alongside in inches)."""
    geo = ((item.get("cost_decision") or {}).get("geometry") or {})
    text = lu.dims_with_mm(geo.get("bbox_mm"), unit)
    return None if text == "—" else text


async def _supplier_unit(session: AsyncSession, package: RfqPackage) -> str:
    """The unit the package was built in (saved on it), else its requester's current choice."""
    unit = (package.metadata_json or {}).get("length_unit")
    if unit in ("mm", "in"):
        return unit
    return await lu.length_unit_for(session, package.user_id)


def includes_cost(package: Any) -> bool:
    """Whether the buyer chose to send our cost estimate with this package."""
    return (getattr(package, "metadata_json", None) or {}).get("include_cost_estimate") is True


def _part_dir(index: int, item: dict[str, Any]) -> str:
    stem = _safe_name((item.get("decision") or {}).get("filename") or "", f"part-{index}")
    return f"parts/{index:02d}-{stem}"


def _estimate_at(cost: dict[str, Any], quantity: int | None) -> dict[str, Any] | None:
    """Our should-cost at the quantity asked for: the engine's pick there (only when
    the buyer included the cost estimate). None when that quantity wasn't priced."""
    rec = ((cost or {}).get("decision") or {}).get("recommendation") or {}
    if quantity is None:
        return None
    row = rec.get(str(quantity)) or rec.get(quantity)
    if not isinstance(row, dict) or row.get("unit_cost_usd") is None:
        return None
    return {"quantity": quantity, "process": row.get("process"), "material": row.get("material"),
            "unit_cost_usd": row.get("unit_cost_usd")}


def supplier_view(package: Any, items: list[dict[str, Any]] | None = None, unit: str = "mm") -> dict[str, Any]:
    """The package as its supplier reads it: the brief, the line items, the manifest
    and the package link all come from this. Nothing of our cost is in it unless
    the buyer included the cost estimate, and no review state ever is."""
    from src.analysis.process_names import process_label

    meta = getattr(package, "metadata_json", None) or {}
    with_cost = includes_cost(package)
    parts = []
    for index, item in enumerate(items or [], start=1):
        dec = item.get("decision") or {}
        req = item.get("request") or {}
        ctx = item.get("part_context") or {}
        raw = item.get("raw_cad") or {}
        folder = _part_dir(index, item)
        cad = None
        if raw.get("included") and raw.get("filename"):
            cad = {"filename": raw["filename"], "path": f"{folder}/{raw['filename']}", "bytes": raw.get("bytes")}
        part = {
            "line": index,
            "name": req.get("name") or dec.get("label") or dec.get("filename"),
            "filename": dec.get("filename"),
            "part_number": req.get("part_number"),
            "description": req.get("description"),
            "material": req.get("material"),
            "quantity": req.get("quantity"),
            "yearly_volume": req.get("yearly_volume"),
            "process": process_label(req["process"]) if req.get("process") else None,
            "size": _part_size(item, unit),
            "specs": [str(x) for x in ctx.get("spec_summary") or []],
            "must_hold": [str(x) for x in ctx.get("supplier_must_hold") or []],
            "cad": cad,
            "folder": folder,
        }
        if with_cost:
            est = _estimate_at(item.get("cost_decision") or {}, req.get("quantity"))
            if est and est.get("process"):
                est["process"] = process_label(est["process"])
            part["estimate"] = est
        parts.append(part)
    requester = meta.get("requested_by") if isinstance(meta.get("requested_by"), dict) else {}
    return {
        "title": getattr(package, "title", None),
        "supplier": getattr(package, "supplier_name", None),
        "requested_by": {k: requester.get(k) for k in ("name", "company", "email")},
        "reply_by": meta.get("reply_by"),
        "sent_on": getattr(package, "created_at", None).date().isoformat()
        if isinstance(getattr(package, "created_at", None), datetime) else None,
        "note": meta.get("note"),
        "includes_cost_estimate": with_cost,
        "must_hold": sorted({c for p in parts for c in p["must_hold"]}),
        "parts": parts,
        "length_unit": unit,
    }


def _qty_text(n: Any) -> str:
    return f"{n:,}" if isinstance(n, int) else "not given"


def _requester_line(view: dict[str, Any]) -> str | None:
    r = view.get("requested_by") or {}
    bits = [r.get("name"), r.get("company"), r.get("email")]
    bits = [b for b in bits if b]
    return ", ".join(bits) if bits else None


def _usd(v: Any) -> str:
    return f"${v:,.2f}" if isinstance(v, (int, float)) else "not priced"


def _part_lines(p: dict[str, Any]) -> list[str]:
    """One part's facts as ``label: value`` lines (the brief, md and PDF alike)."""
    out = []
    if p.get("part_number"):
        out.append(f"Part number: {p['part_number']}")
    if p.get("description"):
        out.append(f"Description: {p['description']}")
    out.append(f"Material: {p.get('material') or 'not given'}")
    out.append(f"Quantity: {_qty_text(p.get('quantity'))}")
    if p.get("yearly_volume"):
        out.append(f"Yearly volume: {p['yearly_volume']:,} a year")
    if p.get("process"):
        out.append(f"Process asked for: {p['process']}")
    if p.get("size"):
        out.append(f"Size: {p['size']} (measured from the CAD)")
    out += list(p.get("specs") or [])
    out.append(f"CAD: {p['cad']['path']}" if p.get("cad") else "CAD: not in this package")
    if "estimate" in p:
        est = p.get("estimate")
        out.append(
            f"Our estimate: {_usd(est['unit_cost_usd'])} each at {est['quantity']:,}, {est.get('process') or 'process not named'}"
            if est else "Our estimate: not priced at this quantity")
    return out


def _contents(view: dict[str, Any]) -> list[tuple[str, str]]:
    """``(file, what it is)`` for every file in the ZIP, in order."""
    out = [
        ("supplier-brief.pdf", "this request for quote"),
        ("supplier-brief.md", "the same, as text"),
        ("line-items.csv", "one line per part"),
        ("package_manifest.json", "this list, as data"),
    ]
    for p in view["parts"]:
        if p.get("cad"):
            out.append((p["cad"]["path"], f"CAD for {p['name']}"))
        if view["includes_cost_estimate"]:
            out.append((f"{p['folder']}/should-cost-report.pdf", f"our cost estimate for {p['name']}"))
            out.append((f"{p['folder']}/cost-drivers.csv", "its price lines"))
            out.append((f"{p['folder']}/cost-decision.json", "the estimate as data"))
    return out


_COST_NOTE = ("The buyer included their own cost estimate for each part. It is an estimate "
              "made with ScaleCAD, not a quote, an offer or a target you are held to.")


def _supplier_brief(package: Any, items: list[dict[str, Any]] | None = None, unit: str = "mm") -> str:
    view = supplier_view(package, items, unit)
    lines = [f"# {view['title']}", "", "Request for quote.", ""]
    who = _requester_line(view)
    lines.append(f"- Requested by: {who or 'not given'}")
    if view.get("supplier"):
        lines.append(f"- Supplier: {view['supplier']}")
    lines.append(f"- Reply by: {_day(view.get('reply_by')) or 'not given'}")
    if view.get("sent_on"):
        lines.append(f"- Date: {_day(view['sent_on'])}")
    lines.append(f"- Parts: {len(view['parts'])}")
    if view.get("must_hold"):
        lines.append(f"- The supplier must hold: {', '.join(view['must_hold'])}")
    if view.get("note"):
        lines += ["", "## Note from the buyer", "", str(view["note"])]
    lines += ["", "## Parts"]
    for p in view["parts"]:
        lines += ["", f"### {p['line']}. {p['name']}", ""] + [f"- {x}" for x in _part_lines(p)]
    if view["includes_cost_estimate"]:
        lines += ["", "## Cost estimate", "", _COST_NOTE]
    lines += ["", "## In this package", ""] + [f"- {f}: {what}" for f, what in _contents(view)]
    lines += ["", "Prepared with ScaleCAD."]
    return "\n".join(lines) + "\n"


def _supplier_brief_html(package: Any, items: list[dict[str, Any]] | None = None, unit: str = "mm") -> str:
    """The brief as a printable page. Every text is escaped: titles, names, notes and
    file names are typed by people."""
    view = supplier_view(package, items, unit)
    e = lambda v: html.escape(str(v))  # noqa: E731
    head = [("Requested by", _requester_line(view) or "not given")]
    if view.get("supplier"):
        head.append(("Supplier", view["supplier"]))
    head.append(("Reply by", _day(view.get("reply_by")) or "not given"))
    if view.get("sent_on"):
        head.append(("Date", _day(view["sent_on"])))
    head.append(("Parts", str(len(view["parts"]))))
    if view.get("must_hold"):
        head.append(("The supplier must hold", ", ".join(view["must_hold"])))
    head_rows = "".join(f"<tr><th>{e(k)}</th><td>{e(v)}</td></tr>" for k, v in head)
    note = f"<h2>Note from the buyer</h2><p class=\"note\">{e(view['note'])}</p>" if view.get("note") else ""
    parts = "".join(
        f"<h3>{p['line']}. {e(p['name'])}</h3><ul>" + "".join(f"<li>{e(x)}</li>" for x in _part_lines(p)) + "</ul>"
        for p in view["parts"]
    )
    cost = f"<h2>Cost estimate</h2><p>{e(_COST_NOTE)}</p>" if view["includes_cost_estimate"] else ""
    files = "".join(f"<li><code>{e(f)}</code>: {e(what)}</li>" for f, what in _contents(view))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <style>
    @page {{ size: Letter; margin: 0.65in; }}
    body {{ color: #172033; font: 10.5pt/1.45 sans-serif; }}
    h1 {{ font-size: 20pt; margin: 0 0 4pt; }}
    h2 {{ font-size: 13pt; margin: 18pt 0 6pt; }}
    h3 {{ font-size: 11pt; margin: 12pt 0 4pt; }}
    .sub {{ color: #475467; margin: 0 0 12pt; }}
    .note {{ white-space: pre-wrap; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border-bottom: 1px solid #d0d5dd; padding: 5pt; text-align: left; vertical-align: top; }}
    th {{ width: 34%; font-weight: 600; }}
    li {{ margin-bottom: 3pt; }}
    code {{ font-size: 9pt; }}
    .foot {{ color: #667085; font-size: 8.5pt; margin-top: 18pt; }}
  </style>
</head>
<body>
  <h1>{e(view['title'])}</h1>
  <p class="sub">Request for quote</p>
  <table>{head_rows}</table>
  {note}
  <h2>Parts</h2>
  {parts}
  {cost}
  <h2>In this package</h2>
  <ul>{files}</ul>
  <p class="foot">Prepared with ScaleCAD.</p>
</body>
</html>"""


def _render_supplier_brief_pdf_sync(package: Any, items: list[dict[str, Any]] | None = None, unit: str = "mm") -> bytes:
    from weasyprint import HTML

    return HTML(string=_supplier_brief_html(package, items, unit)).write_pdf()


async def _supplier_brief_pdf(package: Any, items: list[dict[str, Any]] | None = None, unit: str = "mm") -> bytes:
    async with _RFQ_PDF_SEMAPHORE:
        return await asyncio.to_thread(_render_supplier_brief_pdf_sync, package, items, unit)


_LINE_COLUMNS = ["line", "part", "part_number", "description", "material", "quantity", "yearly_volume",
                 "process", "size", "cad_file", "part_specs", "supplier_must_hold"]
_COST_COLUMNS = ["our_estimate_usd_each", "our_estimate_process"]


def _line_items_csv(items: list[dict[str, Any]], unit: str = "mm", package: Any = None) -> str:
    view = supplier_view(package, items, unit)
    with_cost = view["includes_cost_estimate"]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_LINE_COLUMNS + (_COST_COLUMNS if with_cost else []))
    for p in view["parts"]:
        specs = [s for s in p["specs"] if not s.startswith("Supplier must hold:")]
        row = [p["line"], p["name"], p["part_number"], p["description"], p["material"], p["quantity"],
               p["yearly_volume"], p["process"], p["size"], (p.get("cad") or {}).get("path"),
               "; ".join(specs), "; ".join(p["must_hold"])]
        if with_cost:
            est = p.get("estimate") or {}
            row += [est.get("unit_cost_usd"), est.get("process")]
        writer.writerow([cost_decision_service.spreadsheet_safe_cell(v) for v in row])
    return buf.getvalue()


def _manifest(view: dict[str, Any]) -> dict[str, Any]:
    """``package_manifest.json``: the plain list of what the package holds."""
    return {
        "title": view["title"],
        "supplier": view["supplier"],
        "requested_by": view["requested_by"],
        "reply_by": view["reply_by"],
        "date": view["sent_on"],
        "includes_cost_estimate": view["includes_cost_estimate"],
        "parts": [
            {k: p.get(k) for k in ("line", "name", "part_number", "material", "quantity", "yearly_volume")}
            | {"cad_file": (p.get("cad") or {}).get("path")}
            for p in view["parts"]
        ],
        "files": [f for f, _what in _contents(view)],
    }


async def _decision_item(
    session: AsyncSession,
    decision: CostDecision,
    *,
    include_raw_cad: bool,
    include_cost: bool = False,
    quantity: int | None = None,
    terms: tuple[str, ...] = (),
) -> tuple[dict[str, Any], list[dict[str, Any]], tuple[str | None, bytes | None]]:
    status = _decision_status(decision)
    raw_name, raw_bytes, raw_meta = await _raw_cad_payload(
        session, decision, include_raw_cad, read=False
    )
    requested = outbound.requested_route(status["user_disposition"], status["disposition_basis"])
    manifest = await _manifest_match(session, decision)
    context = await _part_context(session, decision)
    run = await _run_facts(session, decision)
    item = outbound.rfq_item(
        {
            "decision": {
                "id": decision.ulid,
                "filename": decision.filename,
                "file_type": decision.file_type,
                "label": decision.label,
                "engine_version": decision.engine_version,
                "created_at": decision.created_at.isoformat() if decision.created_at else None,
                "quantities": decision.quantities or [],
                "approval_status": status["approval_status"],
                "is_stale": status["is_stale"],
                # "Make outside" on a route: what the supplier is asked to quote.
                "requested": requested,
            },
            "cost_decision": decision.result_json or {},
            "declared_part": manifest,
            "part_context": context,
            "raw_cad": raw_meta,
            "request": _request(decision, requested, manifest, context, run, quantity),
        },
        terms=terms,
    )
    name = decision.label or decision.filename
    # For the buyer, in ScaleCAD only: none of these go in the supplier's files.
    warnings: list[dict[str, Any]] = []
    if not status["approved"]:
        warnings.append({"code": "decision_unapproved", "decision_id": decision.ulid,
                         "message": f"{name} isn't approved in ScaleCAD. The supplier isn't told."})
    if status["stale"]:
        warnings.append({"code": "decision_stale", "decision_id": decision.ulid,
                         "message": f"{name} is out of date: its rates or specs changed after it was checked."})
    if include_cost and item["decision"]["unvalidated_confidence"]:
        warnings.append({"code": "confidence_unvalidated", "decision_id": decision.ulid,
                         "message": f"{name}: the cost estimate you're sending is a stated range, not measured."})
    if include_raw_cad and not raw_meta.get("included"):
        why = ("it is over the package's CAD size limit" if raw_meta.get("reason") == "too_large"
               else "ScaleCAD has no copy of the file")
        warnings.append({"code": "raw_cad_unavailable", "decision_id": decision.ulid,
                         "message": f"{name}: no CAD in the package, {why}. Attach it yourself."})
    if item["request"]["quantity"] is None:
        warnings.append({"code": "quantity_missing", "decision_id": decision.ulid,
                         "message": f"{name}: no quantity. Set one in the package."})
    return item, warnings, (raw_name, raw_bytes)


def _quantities(options: RfqPackageOptions) -> dict[str, int]:
    out: dict[str, int] = {}
    for key, value in (options.quantities or {}).items():
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        if not 1 <= value <= 10_000_000:
            raise HTTPException(status_code=400, detail="A quantity is a whole number from 1 to 10,000,000.")
        out[str(key)] = value
    return out


async def create_package(
    session: AsyncSession,
    user: AuthedUser,
    decision_ids: list[str],
    options: RfqPackageOptions,
) -> RfqPackage:
    org_id = await resolve_org(session, user.user_id)
    if not org_id:
        raise HTTPException(status_code=403, detail="No organization for caller.")
    ids = [d.strip() for d in decision_ids if d and d.strip()]
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise HTTPException(status_code=400, detail="At least one decision id is required.")
    if len(ids) > MAX_ITEMS:
        raise HTTPException(status_code=400, detail=f"At most {MAX_ITEMS} decisions per package.")
    if options.reply_by is not None and options.reply_by < _now().date():
        raise HTTPException(status_code=400, detail="The reply-by date has passed. Pick today or later.")
    overrides = _quantities(options)

    rows = (
        await session.execute(
            select(CostDecision).where(
                CostDecision.org_id == caller_org_subquery(user.user_id),
                CostDecision.ulid.in_(ids),
            )
        )
    ).scalars().all()
    by_id = {row.ulid: row for row in rows}
    missing = [did for did in ids if did not in by_id]
    if missing:
        raise HTTPException(status_code=404, detail="One or more cost decisions were not found.")

    items: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    cad_count = 0
    terms = await outbound.org_names(session, org_id)
    # The supplier's copy reads in the requester's unit (see the module doc).
    unit = await lu.length_unit_for(session, user.user_id)
    for did in ids:
        item, item_warnings, _raw = await _decision_item(
            session, by_id[did], include_raw_cad=options.include_raw_cad,
            include_cost=options.include_cost_estimate, quantity=overrides.get(did), terms=terms,
        )
        items.append(item)
        warnings.extend(item_warnings)
        if (item.get("raw_cad") or {}).get("included"):
            cad_count += 1

    title = _clean_text(options.title, max_len=200) or (
        f"RFQ package - {by_id[ids[0]].label or by_id[ids[0]].filename}"
    )
    requester = _clean_requester(options.requested_by, await _requester(session, user.user_id, org_id))
    package = RfqPackage(
        ulid=str(ULID()),
        org_id=org_id,
        user_id=user.user_id,
        title=title,
        supplier_name=_clean_text(options.supplier_name, max_len=200),
        item_count=len(items),
        approved_count=sum(1 for i in items if i["decision"]["approval_status"] == "approved"),
        stale_count=sum(1 for i in items if i["decision"]["is_stale"]),
        unvalidated_count=sum(1 for i in items if i["decision"]["unvalidated_confidence"]),
        raw_cad_included=cad_count > 0,
        live_supplier_send=False,
        items_json=items,
        warnings_json=warnings,
        metadata_json={
            "note": _clean_text(options.note, max_len=2000),
            "raw_cad_requested": bool(options.include_raw_cad),
            "include_cost_estimate": bool(options.include_cost_estimate),
            "reply_by": options.reply_by.isoformat() if options.reply_by else None,
            "requested_by": requester,
            "contract": "should_cost_evidence_not_supplier_quote",
            "length_unit": unit,
            "length_unit_basis": "requester",
            "raw_payload_count": cad_count,
        },
    )
    session.add(package)
    await session.flush()

    if options.include_cost_estimate:
        # The cost reports render once, off the request path, so a download
        # streams stored bytes (25 items × ~4 s of WeasyPrint would time out).
        # build_zip still renders on a miss, so a download that races the warm
        # is correct, only slower for that one item.
        decisions_to_warm = [
            (_snapshot_decision(item), _supplier_governance(item["decision"])) for item in items
        ]

        async def _warm() -> None:
            await asyncio.gather(*(precompute_cost_pdf(d, gov, unit) for d, gov in decisions_to_warm))

        try:
            asyncio.get_running_loop()
            _WARM_TASKS.add(task := asyncio.create_task(_warm()))
            task.add_done_callback(_WARM_TASKS.discard)
        except RuntimeError:  # pragma: no cover - no running loop (sync callers)
            await _warm()

    return package


PREVIEW_MAX = 100


def page_quantity(quantities: Any) -> int | None:
    """The quantity a part's page opens on: 10 if priced, else the smallest priced
    run of 10 or more, else the largest (frontend part/model.ts ``defaultQty``)."""
    qs = sorted({q for q in quantities or [] if isinstance(q, int) and q > 0})
    if not qs:
        return None
    if 10 in qs:
        return 10
    return next((q for q in qs if q >= 10), qs[-1])


def price_at(result_json: Any, quantity: int | None, *, fallback: bool = False) -> dict[str, Any] | None:
    """The engine's pick and its price at the quantity asked for (the part page's
    pick at that quantity); None when that quantity wasn't priced. With
    ``fallback`` and no quantity asked for, at the quantity the part's page opens
    on (``basis: "part_page"``). For the buyer in ScaleCAD only: never in a
    supplier's copy unless they include the cost."""
    rj = result_json or {}
    rec = ((rj.get("decision") or {}).get("recommendation")) or {}
    basis = "asked"
    if quantity is None and fallback:
        quantity, basis = page_quantity(rj.get("quantities") or [int(k) for k in rec if str(k).isdigit()]), "part_page"
    if quantity is None:
        return None
    row = rec.get(str(quantity))
    if not isinstance(row, dict) or row.get("unit_cost_usd") is None:
        return None
    return {"quantity": quantity, "unit_cost_usd": row.get("unit_cost_usd"), "process": row.get("process"),
            "dfm_ready": row.get("dfm_ready"), "basis": basis}


async def preview_items(
    session: AsyncSession, user: AuthedUser, decision_ids: list[str], *, cad: bool = True
) -> list[dict[str, Any]]:
    """What the builder shows for each picked record before the package is built:
    the part as the supplier would be asked to quote it (quantity prefilled,
    editable), our price and pick at that quantity (for the buyer only), and
    whether ScaleCAD has its CAD (``cad=False`` skips that look at the store)."""
    ids = list(dict.fromkeys(d.strip() for d in decision_ids if d and d.strip()))[:PREVIEW_MAX]
    if not ids:
        return []
    rows = (
        await session.execute(
            select(CostDecision).where(
                CostDecision.org_id == caller_org_subquery(user.user_id),
                CostDecision.ulid.in_(ids),
            )
        )
    ).scalars().all()
    out = []
    by_id = {row.ulid: row for row in rows}
    for did in ids:
        d = by_id.get(did)
        if d is None:
            continue
        status = _decision_status(d)
        requested = outbound.requested_route(status["user_disposition"], status["disposition_basis"])
        manifest = await _manifest_match(session, d)
        context = await _part_context(session, d)
        req = _request(d, requested, manifest, context, await _run_facts(session, d), None)
        kept = (await _raw_cad_payload(session, d, True, read=False))[2] if cad else {}
        specs = outbound.part_specs((context or {}).get("part_specs"))
        from src.costing.part_specs import spec_summary

        out.append({
            "id": d.ulid, **{k: req[k] for k in ("name", "part_number", "material", "quantity",
                                                  "quantity_source", "yearly_volume")},
            "specs": spec_summary(specs) if specs else [],
            "price": price_at(d.result_json, req["quantity"], fallback=True),
            "cad_kept": bool(kept.get("included")) if cad else None,
            "cad_too_large": kept.get("reason") == "too_large",
        })
    return out


async def requester_defaults(session: AsyncSession, user: AuthedUser) -> dict[str, str | None]:
    """The builder's "Requested by", prefilled: the account's name and email, the organization's name."""
    org_id = await resolve_org(session, user.user_id)
    return await _requester(session, user.user_id, org_id) if org_id else {"name": None, "company": None, "email": None}


def serialize_package(package: RfqPackage, *, include_items: bool = False) -> dict[str, Any]:
    out = {
        "id": package.ulid,
        "title": package.title,
        "supplier_name": package.supplier_name,
        "status": package.status,
        "item_count": package.item_count,
        "approved_count": package.approved_count,
        "stale_count": package.stale_count,
        "unvalidated_count": package.unvalidated_count,
        "raw_cad_included": package.raw_cad_included,
        "live_supplier_send": package.live_supplier_send,
        "warnings": package.warnings_json or [],
        "metadata": package.metadata_json or {},
        "created_at": package.created_at.isoformat() if package.created_at else None,
        "updated_at": package.updated_at.isoformat() if package.updated_at else None,
    }
    if hasattr(package, "share_short_id"):
        from src.services import share_links

        out.update(share_links.fields(package))
    if include_items:
        # Saved as the supplier's copy; one saved before that is cleaned here.
        out["items"] = [outbound.rfq_item(item) for item in package.items_json or []]
    return out


async def list_packages(
    session: AsyncSession, user_id: int, *, limit: int = 50
) -> list[RfqPackage]:
    limit = max(1, min(limit, 100))
    return (
        await session.execute(
            select(RfqPackage)
            .where(RfqPackage.org_id == caller_org_subquery(user_id))
            .order_by(RfqPackage.created_at.desc(), RfqPackage.id.desc())
            .limit(limit)
        )
    ).scalars().all()


async def get_package(
    session: AsyncSession, package_id: str, user_id: int
) -> RfqPackage:
    package = (
        await session.execute(
            select(RfqPackage).where(
                RfqPackage.ulid == package_id,
                RfqPackage.org_id == caller_org_subquery(user_id),
            )
        )
    ).scalars().first()
    if package is None:
        raise HTTPException(status_code=404, detail="RFQ package not found.")
    return package


async def _live_decision(session: AsyncSession, org_id: str, ulid: Any) -> CostDecision | None:
    if not ulid:
        return None
    return (
        await session.execute(
            select(CostDecision).where(CostDecision.org_id == org_id, CostDecision.ulid == ulid)
        )
    ).scalars().first()


async def part_cad(session: AsyncSession, package: RfqPackage, item: dict[str, Any]) -> tuple[str, bytes] | None:
    """One part's CAD file as the package holds it, or None when it isn't there (any more)."""
    raw = item.get("raw_cad") or {}
    if not raw.get("included"):
        return None
    decision = await _live_decision(session, package.org_id, (item.get("decision") or {}).get("id"))
    if decision is None:
        return None
    name, data, _meta = await _raw_cad_payload(session, decision, True)
    if not (name and data):
        return None
    return raw.get("filename") or name, data


async def supplier_files(session: AsyncSession, package: RfqPackage) -> list[tuple[str, bytes]]:
    """Every file of the supplier's copy, in order: what the ZIP and a package link hand out."""
    unit = await _supplier_unit(session, package)
    terms = await outbound.org_names(session, package.org_id)
    items = [outbound.rfq_item(item, terms=terms) for item in package.items_json or []]
    view = supplier_view(package, items, unit)
    try:
        brief_pdf = ("supplier-brief.pdf", await _supplier_brief_pdf(package, items, unit))
    except Exception:  # noqa: BLE001
        brief_pdf = ("supplier-brief-pdf-unavailable.txt",
                     b"The PDF of this brief couldn't be made. supplier-brief.md holds the same text.\n")
    files: list[tuple[str, bytes]] = [
        brief_pdf,
        ("supplier-brief.md", _supplier_brief(package, items, unit).encode()),
        ("line-items.csv", _line_items_csv(items, unit, package).encode()),
        ("package_manifest.json", json.dumps(_manifest(view), indent=2, default=str).encode()),
    ]
    with_cost = includes_cost(package)
    for item, part in zip(items, view["parts"]):
        folder = part["folder"]
        if part.get("cad"):
            cad = await part_cad(session, package, item)
            if cad is not None:
                files.append((part["cad"]["path"], cad[1]))
            else:
                files.append((f"{folder}/cad-not-included.txt",
                              b"ScaleCAD no longer holds this part's CAD file. Ask the buyer for it.\n"))
        if not with_cost:
            continue
        files.append((f"{folder}/cost-decision.json",
                      json.dumps(item["cost_decision"], indent=2, sort_keys=True, default=str).encode()))
        files.append((f"{folder}/cost-drivers.csv", cost_decision_service.build_estimates_csv(
            item["cost_decision"], governance=_supplier_governance(item["decision"]), outbound=True,
        ).encode()))
        try:
            files.append((f"{folder}/should-cost-report.pdf", await cached_cost_pdf(
                _snapshot_decision(item), _supplier_governance(item["decision"]), length_unit=unit,
            )))
        except Exception:  # noqa: BLE001
            files.append((f"{folder}/should-cost-report-unavailable.txt",
                          b"The PDF of this estimate couldn't be made. cost-decision.json holds the same figures.\n"))
    return files


async def build_zip(
    session: AsyncSession,
    package: RfqPackage,
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in await supplier_files(session, package):
            zf.writestr(name, data)
    return buf.getvalue()
