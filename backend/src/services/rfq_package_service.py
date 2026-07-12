"""RFQ / supplier evidence package service.

Builds a durable, downloadable package from saved should-cost decisions. This is
not live procurement: it creates evidence for an RFQ handoff and explicitly
records that no supplier was contacted and raw CAD is absent unless already
recoverable from same-org batch storage.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.auth.org_context import caller_org_subquery, resolve_org
from src.auth.require_api_key import AuthedUser
from src.db.models import Batch, BatchItem, CostDecision, ManifestPart, PartContext, RfqPackage
from src.services import cost_decision_service
from src.services.cost_pdf_service import cached_cost_pdf, precompute_cost_pdf

MAX_ITEMS = 25

# Strong refs to in-flight cache-warm tasks so they are not GC'd mid-render.
_WARM_TASKS: set = set()


@dataclass(frozen=True)
class RfqPackageOptions:
    title: str | None = None
    supplier_name: str | None = None
    note: str | None = None
    include_raw_cad: bool = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_text(value: str | None, *, max_len: int = 200) -> str | None:
    clean = (value or "").strip()
    return clean[:max_len] if clean else None


def _safe_name(value: str, fallback: str) -> str:
    stem = Path(value or fallback).stem or fallback
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._")
    return safe or fallback


def _decision_status(decision: CostDecision) -> dict[str, Any]:
    gov = cost_decision_service.governance_fields(decision)
    return {
        **gov,
        "approved": gov["approval_status"] == cost_decision_service.APPROVAL_APPROVED,
        "stale": bool(gov["is_stale"]),
    }


def _confidence_unvalidated(result_json: dict[str, Any]) -> bool:
    for estimate in result_json.get("estimates", []) or []:
        confidence = estimate.get("confidence") or {}
        if confidence.get("validated") is not True:
            return True
    return False


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
    return {
        "program": row.program,
        "parent_assembly": row.parent_assembly,
        "units_per_parent": row.units_per_parent,
        "annual_volume": row.annual_volume,
        "service_environment": row.service_environment,
        "provenance": "user_declared",
    }


async def _raw_cad_payload(
    session: AsyncSession, decision: CostDecision, include_requested: bool
) -> tuple[str | None, bytes | None, dict[str, Any]]:
    if not include_requested:
        return None, None, {
            "included": False,
            "reason": "not_requested",
        }

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
        return None, None, {
            "included": False,
            "reason": "no_same_org_completed_batch_blob",
        }
    item, batch = row
    try:
        from src.services.batch_service import read_batch_blob

        data = await asyncio.to_thread(read_batch_blob, batch.ulid, item.filename)
    except (OSError, KeyError):
        return None, None, {
            "included": False,
            "reason": "same_org_batch_blob_missing",
            "filename": item.filename,
        }
    return item.filename, data, {
        "included": True,
        "source": "same_org_batch_zip_blob",
        "filename": item.filename,
        "bytes": len(data),
    }


def _line_items_csv(items: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "decision_id",
            "filename",
            "approval_status",
            "is_stale",
            "unvalidated_confidence",
            "make_now_process",
            "crossover_qty",
            "manifest_part_id",
            "program",
            "raw_cad_included",
        ]
    )
    for item in items:
        decision = item["decision"]
        manifest = item.get("declared_part")
        context = item.get("part_context") or {}
        raw = item.get("raw_cad") or {}
        writer.writerow(
            [
                decision["id"],
                decision["filename"],
                decision["approval_status"],
                decision["is_stale"],
                decision["unvalidated_confidence"],
                decision["make_now_process"],
                decision["crossover_qty"],
                ((manifest or {}).get("part") or {}).get("part_id"),
                context.get("program"),
                raw.get("included") is True,
            ]
        )
    return buf.getvalue()


def _supplier_brief(package: RfqPackage) -> str:
    lines = [
        f"# {package.title}",
        "",
        "This package is should-cost evidence for an RFQ handoff. It is not a supplier quote, supplier commitment, or live procurement transaction.",
        "",
        f"- Supplier target: {package.supplier_name or 'not specified'}",
        f"- Decisions included: {package.item_count}",
        f"- Approved decisions: {package.approved_count}",
        f"- Stale decisions: {package.stale_count}",
        f"- Decisions with unvalidated confidence bands: {package.unvalidated_count}",
        f"- Raw CAD included: {'yes' if package.raw_cad_included else 'no'}",
        f"- Live supplier send: {'yes' if package.live_supplier_send else 'no'}",
    ]
    note = (package.metadata_json or {}).get("note")
    if note:
        lines += ["", "## Buyer note", "", str(note)]
    if package.warnings_json:
        lines += ["", "## Warnings"]
        lines += [f"- {w.get('code')}: {w.get('message')}" for w in package.warnings_json]
    return "\n".join(lines) + "\n"


async def _decision_item(
    session: AsyncSession,
    decision: CostDecision,
    *,
    include_raw_cad: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]], tuple[str | None, bytes | None]]:
    status = _decision_status(decision)
    unvalidated = _confidence_unvalidated(decision.result_json or {})
    warnings: list[dict[str, Any]] = []
    if not status["approved"]:
        warnings.append(
            {
                "code": "decision_unapproved",
                "decision_id": decision.ulid,
                "message": f"{decision.filename} is not approved.",
            }
        )
    if status["stale"]:
        warnings.append(
            {
                "code": "decision_stale",
                "decision_id": decision.ulid,
                "message": f"{decision.filename} predates governed assumption changes.",
            }
        )
    if unvalidated:
        warnings.append(
            {
                "code": "confidence_unvalidated",
                "decision_id": decision.ulid,
                "message": f"{decision.filename} includes assumption-based confidence bands.",
            }
        )

    raw_name, raw_bytes, raw_meta = await _raw_cad_payload(
        session, decision, include_raw_cad
    )
    if include_raw_cad and not raw_meta.get("included"):
        warnings.append(
            {
                "code": "raw_cad_unavailable",
                "decision_id": decision.ulid,
                "message": "Raw CAD was requested but is not available for this saved decision.",
            }
        )

    item = {
        "decision": {
            "id": decision.ulid,
            "filename": decision.filename,
            "file_type": decision.file_type,
            "label": decision.label,
            "engine_version": decision.engine_version,
            "created_at": decision.created_at.isoformat() if decision.created_at else None,
            "make_now_process": decision.make_now_process,
            "crossover_qty": decision.crossover_qty,
            "quantities": decision.quantities or [],
            "approval_status": status["approval_status"],
            "approved_at": status["approved_at"],
            "approved_by_user_id": status["approved_by_user_id"],
            "is_stale": status["is_stale"],
            "stale_at": status["stale_at"],
            "stale_reason": status["stale_reason"],
            "unvalidated_confidence": unvalidated,
        },
        "cost_decision": decision.result_json or {},
        "declared_part": await _manifest_match(session, decision),
        "part_context": await _part_context(session, decision),
        "raw_cad": raw_meta,
    }
    return item, warnings, (raw_name, raw_bytes)


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
    raw_included = False
    raw_payloads: list[tuple[str, bytes]] = []
    for did in ids:
        item, item_warnings, raw = await _decision_item(
            session, by_id[did], include_raw_cad=options.include_raw_cad
        )
        items.append(item)
        warnings.extend(item_warnings)
        if raw[0] and raw[1]:
            raw_included = True
            raw_payloads.append((raw[0], raw[1]))

    title = _clean_text(options.title, max_len=200) or (
        f"RFQ package - {by_id[ids[0]].filename}"
    )
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
        raw_cad_included=raw_included,
        live_supplier_send=False,
        items_json=items,
        warnings_json=warnings,
        metadata_json={
            "note": _clean_text(options.note, max_len=2000),
            "raw_cad_requested": bool(options.include_raw_cad),
            "contract": "should_cost_evidence_not_supplier_quote",
        },
    )
    session.add(package)
    await session.flush()
    package.metadata_json = {
        **(package.metadata_json or {}),
        "raw_payload_count": len(raw_payloads),
    }
    await session.flush()

    # Precompute + cache each item's cost-report PDF ONCE, off the request path.
    # The package is immutable (its items never change), so a create-time
    # snapshot never goes stale; every later download.zip then STREAMS the stored
    # bytes instead of re-rendering all items on every request (the W9-F1
    # gateway-timeout risk — 25 items × ~4s WeasyPrint = ~90s per download).
    #
    # Warming runs as a background cache task so create itself stays ~tens of ms
    # — pushing ~90s of
    # rendering into create would only relocate the timeout. The decision ORM
    # rows are already fully loaded, so rendering never touches the (closing)
    # session. build_zip still renders-on-miss, so a download that races the warm
    # is correct (just slower for that one item), and steady state is all-cache.
    import asyncio as _asyncio

    decisions_to_warm = [by_id[did] for did in ids]

    async def _warm() -> None:
        await _asyncio.gather(
            *(precompute_cost_pdf(d) for d in decisions_to_warm)
        )

    try:
        _asyncio.get_running_loop()
        _WARM_TASKS.add(task := _asyncio.create_task(_warm()))
        task.add_done_callback(_WARM_TASKS.discard)
    except RuntimeError:  # pragma: no cover - no running loop (sync callers)
        await _warm()

    return package


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
    if include_items:
        out["items"] = package.items_json or []
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


async def build_zip(
    session: AsyncSession,
    package: RfqPackage,
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        manifest = serialize_package(package, include_items=False)
        manifest["included_files"] = [
            "package_manifest.json",
            "line-items.csv",
            "supplier-brief.md",
            "cost-decisions.json",
        ]
        zf.writestr(
            "package_manifest.json",
            json.dumps(manifest, indent=2, sort_keys=True, default=str),
        )
        zf.writestr("line-items.csv", _line_items_csv(package.items_json or []))
        zf.writestr("supplier-brief.md", _supplier_brief(package))
        zf.writestr(
            "cost-decisions.json",
            json.dumps(package.items_json or [], indent=2, sort_keys=True, default=str),
        )

        for index, item in enumerate(package.items_json or [], start=1):
            decision_meta = item["decision"]
            decision_ulid = decision_meta["id"]
            stem = _safe_name(decision_meta["filename"], f"decision-{index}")
            zf.writestr(
                f"decisions/{index:02d}-{stem}/cost-decision.json",
                json.dumps(item["cost_decision"], indent=2, sort_keys=True, default=str),
            )
            zf.writestr(
                f"decisions/{index:02d}-{stem}/cost-drivers.csv",
                cost_decision_service.build_estimates_csv(item["cost_decision"]),
            )
            if item.get("declared_part"):
                zf.writestr(
                    f"decisions/{index:02d}-{stem}/declared-part.json",
                    json.dumps(item["declared_part"], indent=2, sort_keys=True, default=str),
                )
            if item.get("part_context"):
                zf.writestr(
                    f"decisions/{index:02d}-{stem}/part-context.json",
                    json.dumps(item["part_context"], indent=2, sort_keys=True, default=str),
                )
            decision = (
                await session.execute(
                    select(CostDecision).where(
                        CostDecision.org_id == package.org_id,
                        CostDecision.ulid == decision_ulid,
                    )
                )
            ).scalars().first()
            if decision is not None:
                try:
                    # Stream the cached PDF bytes (rendered once at package
                    # create time). No per-request WeasyPrint render — a 25-item
                    # download stays well under the gateway timeout.
                    zf.writestr(
                        f"decisions/{index:02d}-{stem}/should-cost-report.pdf",
                        await cached_cost_pdf(decision),
                    )
                except Exception:
                    zf.writestr(
                        f"decisions/{index:02d}-{stem}/pdf-unavailable.txt",
                        "PDF generation failed for this local package export.\n",
                    )
            raw = item.get("raw_cad") or {}
            if raw.get("included"):
                filename, data = None, None
                if decision is not None:
                    filename, data, _meta = await _raw_cad_payload(
                        session, decision, True
                    )
                if filename and data:
                    zf.writestr(
                        f"decisions/{index:02d}-{stem}/raw-cad/{_safe_name(filename, 'part')}{Path(filename).suffix}",
                        data,
                    )
                else:
                    zf.writestr(
                        f"decisions/{index:02d}-{stem}/raw-cad-unavailable.txt",
                        "Raw CAD was marked available when the package was created, but the blob is no longer readable.\n",
                    )
            else:
                zf.writestr(
                    f"decisions/{index:02d}-{stem}/raw-cad-unavailable.txt",
                    f"Raw CAD not included: {raw.get('reason') or 'not_available'}.\n",
                )
    return buf.getvalue()
