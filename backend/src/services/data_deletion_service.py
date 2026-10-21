"""Deleting a part, or a whole organization: what goes, what stays, and the receipt.

Product decision (2026-10-21): a member can delete a part with its stored CAD
file and its results; an org admin can delete all of the organization's data.
Records were designed to be immutable, so the audit trail keeps the FACT of a
deletion (who, when, which file hash) and drops the content.

A part is ``(org_id, mesh_hash)``: the SHA-256 of the uploaded bytes, the same
key the catalog, the 3D view and the stored source use. Deleting it removes,
in that organization only:

* database: every check (``analyses``) and cost record (``cost_decisions``) of
  that file, by anyone in the org; its catalog row (``part_summaries``), part
  context (program/volume, ``part_contexts``), shape fingerprint
  (``part_signatures``), actual costs bound to the file by hash
  (``ground_truth_records.evidence_sha256``), SAM-3D jobs, notifications about
  it, the batch items that produced it (rows, extracted input files, their
  webhook delivery logs; the batch's counters drop accordingly) and its items in
  RFQ packages (a package left empty is deleted). Share links on those rows
  stop working (their rows are gone: the public page is a plain "not found").
* object store: everything under ``<org>/<sha256>/`` in ``source-artifacts``
  (the exact upload, the mm/inch STL derivatives, fix/repair attempt records,
  ``derived-from.json``), cached cost-report PDFs, this machine's cached check
  PDFs, the extracted batch input files and the SAM-3D mesh blob when no other
  organization uploaded the same bytes.
* the copies ScaleCAD fixed or repaired from it (followed through their
  ``derived-from.json``), unless the caller keeps them; a kept copy loses the
  original's file name from its lineage record.
* process caches: the 3D view, orientation, analysed-geometry and parse caches
  in this API process. Other processes' caches are bounded and keyed by the
  bytes; the 3D-view and orientation caches also re-check the stored source on
  every hit, so they never serve a deleted part.

What stays, and why:

* the audit trail keeps every event row but each one about the part has its
  detail (file names, parameters) and result summary replaced with
  ``{"redacted": "part_deleted"}``; a ``part.deleted`` row records who deleted
  which SHA-256 and when, and the counts. No file name is kept.
* ``data_deletions`` keeps the receipt (hash, counts, progress), no file name.
* ``usage_events`` (metering: event type, time, hash, face count, duration).
* ``trial_checks`` and ``catalog_parts``: the per-account free-check and
  free-catalog ledgers (account id + file hash). Deleting a part never gives a
  free check back; otherwise delete-and-rerun would be unlimited.
* actual costs logged by part number only (not bound to the file's hash), the
  declared parts manifest and BOM trees: they are the customer's own declared
  data, not this file.
* backups and the storage provider's earlier object versions: not touched by
  the application (see ``docs`` / data facts): on the AWS plane the durable
  bucket is versioned and the app role cannot delete versions by design.

Organization deletion removes every row that belongs to the organization (all
org-scoped tables cascade from ``organizations``), every stored file under the
org's prefixes, members' memberships and the org's API keys. Members are
signed out (their session version is bumped); a member left without an
organization gets a new empty personal one, as at sign-up. Accounts, billing
records (Stripe customer/subscription rows and the invoices Stripe keeps) and
the free-check ledgers stay: they belong to the person, not the organization.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.db.models import (
    Analysis,
    AuditLog,
    Batch,
    BatchItem,
    CostDecision,
    DataDeletion,
    GroundTruthRecordRow,
    Job,
    Membership,
    Notification,
    Organization,
    PartContext,
    PartSignature,
    PartSummary,
    RfqPackage,
    User,
    WebhookDelivery,
)

logger = logging.getLogger("cadverify.data_deletion")

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ORG = re.compile(r"^[0-9A-Za-z_-]{1,128}$")
MAX_FIXED_COPIES = 500
MAX_ATTEMPTS = 10
# A worker may still write a source for a check that was running when the org
# was deleted (analysis timeout plus slack). One more pass empties it.
ORG_FINAL_SWEEP_DELAY = timedelta(minutes=15)
LEASE = timedelta(minutes=5)

PART = "part"
ORGANIZATION = "organization"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def valid_hash(mesh_hash: str) -> Optional[str]:
    digest = str(mesh_hash or "").strip().lower()
    return digest if _SHA256.fullmatch(digest) else None


# ---------------------------------------------------------------------------
# Object stores (each factory honors the same env the writers use)
# ---------------------------------------------------------------------------


def _store(name: str):
    if name == "source-artifacts":
        from src.services.source_artifact_service import _store as source_store

        return source_store()
    if name == "cost-pdf":
        from src.services.cost_pdf_service import _pdf_store

        return _pdf_store()
    if name == "batch":
        from src.services.batch_service import _batch_store

        return _batch_store()
    if name == "designs":
        from src.services.design_service import _design_store

        return _design_store()
    if name == "reconstruct":
        from src.services.reconstruction_service import _reconstruction_store

        return _reconstruction_store()
    if name == "meshes":
        from src.services.job_service import MESH_BLOB_DIR
        from src.storage import get_object_store

        return get_object_store("meshes", default_root=os.getenv("MESH_BLOB_DIR", MESH_BLOB_DIR))
    if name == "direct-uploads":
        from src.storage.factory import get_direct_upload_store

        return get_direct_upload_store()
    raise ValueError(f"unknown store {name!r}")


def _dfm_pdf_dir() -> Path:
    from src.services import pdf_service

    return Path(os.getenv("PDF_CACHE_DIR", pdf_service.PDF_CACHE_DIR))


# ---------------------------------------------------------------------------
# Fixed copies: followed through each copy's own derived-from.json
# ---------------------------------------------------------------------------


async def _read_json(org_id: str, mesh_hash: str, name: str) -> Optional[dict]:
    from src.services import cad_fix_service as fx

    try:
        return await fx._get_json(fx._record_key(org_id, mesh_hash, name))
    except ValueError:
        return None


async def _child_candidates(session: AsyncSession, org_id: str, parent: str) -> set[str]:
    """Copies the evidence says were made from ``parent`` (verified by the caller)."""
    found: set[str] = set()
    rows = (
        await session.execute(
            select(AuditLog.resource_id).where(
                AuditLog.org_id == org_id,
                AuditLog.action.in_(("part.fix_applied", "part.repair_applied")),
                AuditLog.detail_json["parent_mesh_hash"].astext == parent,
            )
        )
    ).scalars().all()
    found.update(r for r in rows if r)
    # The parent's own attempt records name the copy each fix produced.
    prefix = f"{org_id}/{parent}/fixes"
    try:
        keys = await asyncio.to_thread(_store("source-artifacts").list_keys, prefix)
    except Exception:  # noqa: BLE001 - a missing namespace lists nothing
        keys = []
    for key in keys:
        if not key.endswith(".json"):
            continue
        name = key[len(f"{org_id}/{parent}/"):]
        record = await _read_json(org_id, parent, name)
        child = (record or {}).get("fixed_mesh_hash")
        if isinstance(child, str):
            found.add(child)
    return {h for h in (valid_hash(c) for c in found) if h and h != parent}


async def fixed_copies(session: AsyncSession, org_id: str, root: str) -> list[str]:
    """Every copy ScaleCAD made from ``root`` (and from those copies), in this org.

    A candidate counts only when its own ``derived-from.json`` names the parent.
    """
    seen = {root}
    order: list[str] = []
    frontier = [root]
    while frontier and len(order) < MAX_FIXED_COPIES:
        parent = frontier.pop(0)
        for child in sorted(await _child_candidates(session, org_id, parent)):
            if child in seen:
                continue
            link = await _read_json(org_id, child, "derived-from.json")
            if not link or str(link.get("parent_mesh_hash", "")).lower() != parent:
                continue
            seen.add(child)
            order.append(child)
            frontier.append(child)
    return order


# ---------------------------------------------------------------------------
# What a part owns
# ---------------------------------------------------------------------------


@dataclass
class PartRows:
    org_id: str
    root: str
    hashes: list[str]
    copies: list[str]
    analyses: list[Any] = field(default_factory=list)
    decisions: list[Any] = field(default_factory=list)
    items: list[Any] = field(default_factory=list)
    actuals: int = 0
    contexts: int = 0
    summaries: int = 0
    signatures: int = 0
    packages: list[RfqPackage] = field(default_factory=list)
    source_kept: bool = False

    @property
    def analysis_ids(self) -> list[int]:
        return [a.id for a in self.analyses]

    @property
    def decision_ids(self) -> list[int]:
        return [d.id for d in self.decisions]

    @property
    def ulids(self) -> list[str]:
        return [a.ulid for a in self.analyses] + [d.ulid for d in self.decisions]

    @property
    def share_ids(self) -> list[str]:
        return [r.share_short_id for r in (*self.analyses, *self.decisions) if r.share_short_id]

    def exists(self) -> bool:
        return bool(
            self.analyses or self.decisions or self.summaries or self.contexts
            or self.signatures or self.actuals or self.source_kept
        )


def _package_refs(package: RfqPackage, hashes: set[str], decision_ulids: set[str]) -> bool:
    for item in package.items_json or []:
        dec = (item or {}).get("decision") or {}
        if dec.get("id") in decision_ulids or str(dec.get("mesh_hash") or "").lower() in hashes:
            return True
    return False


async def _gather(session: AsyncSession, org_id: str, hashes: list[str], *, lock: bool) -> PartRows:
    rows = PartRows(org_id=org_id, root=hashes[0], hashes=hashes, copies=hashes[1:])
    a_stmt = select(Analysis).where(Analysis.org_id == org_id, Analysis.mesh_hash.in_(hashes))
    d_stmt = select(CostDecision).where(CostDecision.org_id == org_id, CostDecision.mesh_hash.in_(hashes))
    if lock:
        a_stmt, d_stmt = a_stmt.with_for_update(), d_stmt.with_for_update()
    rows.analyses = list((await session.execute(a_stmt)).scalars().all())
    rows.decisions = list((await session.execute(d_stmt)).scalars().all())
    if rows.analysis_ids or rows.decision_ids:
        conds = []
        if rows.analysis_ids:
            conds.append(BatchItem.analysis_id.in_(rows.analysis_ids))
        if rows.decision_ids:
            conds.append(BatchItem.cost_decision_id.in_(rows.decision_ids))
        rows.items = list(
            (
                await session.execute(
                    select(BatchItem.id, BatchItem.ulid, BatchItem.filename, BatchItem.status,
                           BatchItem.batch_id, Batch.ulid.label("batch_ulid"))
                    .join(Batch, Batch.id == BatchItem.batch_id)
                    .where(BatchItem.org_id == org_id, or_(*conds))
                )
            ).all()
        )

    async def count(model, column) -> int:
        return int(
            (
                await session.execute(
                    select(func.count()).select_from(model).where(model.org_id == org_id, column.in_(hashes))
                )
            ).scalar_one()
        )

    rows.actuals = await count(GroundTruthRecordRow, GroundTruthRecordRow.evidence_sha256)
    rows.contexts = await count(PartContext, PartContext.mesh_hash)
    rows.summaries = await count(PartSummary, PartSummary.mesh_hash)
    rows.signatures = await count(PartSignature, PartSignature.mesh_hash)
    packages = (
        await session.execute(select(RfqPackage).where(RfqPackage.org_id == org_id))
    ).scalars().all()
    hs, ds = set(hashes), {d.ulid for d in rows.decisions}
    rows.packages = [p for p in packages if _package_refs(p, hs, ds)]
    from src.services.source_artifact_service import find_source_artifact_suffix

    for h in hashes:
        if await find_source_artifact_suffix(org_id, h):
            rows.source_kept = True
            break
    return rows


def _latest_name(rows: PartRows) -> Optional[str]:
    named = [r for r in (*rows.analyses, *rows.decisions) if r.mesh_hash == rows.root]
    named.sort(key=lambda r: r.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return named[0].filename if named else None


def _uploaders(rows: PartRows) -> set[int]:
    return {r.user_id for r in (*rows.analyses, *rows.decisions) if r.user_id is not None}


def _deletable_by(rows: PartRows, user_id: int, org_role: Optional[str]) -> tuple[bool, Optional[str]]:
    """Admins delete any part; members a part only they checked or costed."""
    if org_role == "admin":
        return True, None
    if org_role != "member":
        return False, "Viewers can't delete parts."
    others = _uploaders(rows) - {user_id}
    if others:
        return False, "Members can delete only parts no one else checked or costed. An admin can delete this one."
    return True, None


def _active_links(rows: PartRows) -> int:
    from src.services import share_links

    return sum(1 for r in (*rows.analyses, *rows.decisions) if share_links.status(r) == "active")


def _counts(rows: PartRows) -> dict[str, int]:
    return {
        "checks": len(rows.analyses),
        "cost_records": len(rows.decisions),
        "fixed_copies": len(rows.copies),
        "active_share_links": _active_links(rows),
        "actual_costs": rows.actuals,
        "part_context": rows.contexts,
        "batch_items": len(rows.items),
        "rfq_packages_touched": len(rows.packages),
    }


async def _receipt_for(session: AsyncSession, org_id: str, scope: str, target: str) -> Optional[DataDeletion]:
    return (
        await session.execute(
            select(DataDeletion)
            .where(DataDeletion.org_id == org_id, DataDeletion.scope == scope, DataDeletion.target == target)
            .order_by(DataDeletion.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def part_deletion_preview(
    session: AsyncSession, org_id: str, mesh_hash: str, user_id: int, org_role: Optional[str],
    *, include_copies: bool = True,
) -> dict[str, Any]:
    """What deleting this part would remove, for the confirmation. 404 when unknown."""
    root = valid_hash(mesh_hash)
    if root is None or not org_id:
        raise HTTPException(status_code=404, detail="No part with this fingerprint in your organization.")
    all_copies = await fixed_copies(session, org_id, root)
    copies = all_copies if include_copies else []
    rows = await _gather(session, org_id, [root, *copies], lock=False)
    if not rows.exists():
        receipt = await _receipt_for(session, org_id, PART, root)
        if receipt is not None:
            return {"mesh_hash": root, "exists": False, "already_deleted": serialize_receipt(receipt)}
        raise HTTPException(status_code=404, detail="No part with this fingerprint in your organization.")
    can, why = _deletable_by(rows, user_id, org_role)
    return {
        "mesh_hash": root,
        "exists": True,
        "file_name": _latest_name(rows),
        "source_kept": rows.source_kept,
        "will_remove": _counts(rows),
        "fixed_copies": all_copies,
        "can_delete": can,
        "reason": why,
        "kept": KEPT_AFTER_PART_DELETE,
    }


KEPT_AFTER_PART_DELETE = [
    "A deletion record: who deleted the file with this SHA-256 fingerprint, and when. Not its name or results.",
    "Audit events about the part, with their details removed.",
    "Usage counts (time, fingerprint, face count) and your free-check count: deleting a part doesn't give a check back.",
    "Actual costs logged by part number only, your parts manifest and BOM trees.",
    "Backups and the storage provider's earlier versions of stored files: the application doesn't change them.",
]

KEPT_AFTER_ORG_DELETE = [
    "Each member's sign-in account and their other organizations.",
    "Plans and billing records: each account's plan and subscription (not cancelled by this; cancel in Plan and billing), and the invoices the payment processor (Stripe) keeps.",
    "Each account's free-check count.",
    "A deletion record: who deleted the organization and when, with counts. Not its name, files or results.",
    "Audit events, with their details removed.",
    "Backups and the storage provider's earlier versions of stored files: the application doesn't change them.",
]


# ---------------------------------------------------------------------------
# Database phase
# ---------------------------------------------------------------------------


async def _redact_audit(session: AsyncSession, org_id: str, *, hashes: Iterable[str], ids: Iterable[str],
                        reason: str, deletion_ulid: str) -> int:
    hashes, ids = list(hashes), [i for i in ids if i]
    conds = []
    if hashes:
        conds += [
            AuditLog.file_hash.in_(hashes),
            AuditLog.resource_id.in_(hashes),
            AuditLog.detail_json["parent_mesh_hash"].astext.in_(hashes),
        ]
    if ids:
        conds += [
            AuditLog.resource_id.in_(ids),
            AuditLog.detail_json["analysis_ulid"].astext.in_(ids),
            AuditLog.detail_json["cost_decision_ulid"].astext.in_(ids),
        ]
    if not conds:
        return 0
    result = await session.execute(
        update(AuditLog)
        .where(AuditLog.org_id == org_id, or_(*conds))
        .values(detail_json={"redacted": reason, "deletion_id": deletion_ulid}, result_summary=None)
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


def _rfq_without(package: RfqPackage, hashes: set[str], decision_ulids: set[str]) -> list[dict]:
    keep = []
    for item in package.items_json or []:
        dec = (item or {}).get("decision") or {}
        if dec.get("id") in decision_ulids or str(dec.get("mesh_hash") or "").lower() in hashes:
            continue
        keep.append(item)
    return keep


async def _delete_part_rows(session: AsyncSession, rows: PartRows, deletion_ulid: str,
                            names: set[str]) -> dict[str, int]:
    org_id = rows.org_id
    hashes = rows.hashes
    removed: dict[str, int] = {}

    async def run(name: str, stmt) -> None:
        result = await session.execute(stmt.execution_options(synchronize_session=False))
        removed[name] = removed.get(name, 0) + int(result.rowcount or 0)

    item_ulids = [i.ulid for i in rows.items]
    if item_ulids:
        await run("webhook_deliveries", delete(WebhookDelivery).where(
            WebhookDelivery.org_id == org_id, WebhookDelivery.payload_json["item_ulid"].astext.in_(item_ulids)))
        await run("batch_items", delete(BatchItem).where(BatchItem.id.in_([i.id for i in rows.items])))
        per_batch: dict[int, dict[str, int]] = {}
        for i in rows.items:
            agg = per_batch.setdefault(i.batch_id, {"total": 0, "completed": 0, "failed": 0})
            agg["total"] += 1
            if i.status == "completed":
                agg["completed"] += 1
            elif i.status == "failed":
                agg["failed"] += 1
        for batch_id, agg in per_batch.items():
            await session.execute(
                update(Batch).where(Batch.id == batch_id).values(
                    total_items=func.greatest(Batch.total_items - agg["total"], 0),
                    completed_items=func.greatest(Batch.completed_items - agg["completed"], 0),
                    failed_items=func.greatest(Batch.failed_items - agg["failed"], 0),
                ).execution_options(synchronize_session=False)
            )
    job_conds = [Job.params_json["mesh_hash"].astext.in_(hashes)]
    if rows.analysis_ids:
        job_conds.append(Job.analysis_id.in_(rows.analysis_ids))
    await run("jobs", delete(Job).where(Job.org_id == org_id, or_(*job_conds)))

    hs, ds = set(hashes), {d.ulid for d in rows.decisions}
    for package in rows.packages:
        keep = _rfq_without(package, hs, ds)
        removed["rfq_package_items"] = removed.get("rfq_package_items", 0) + len(package.items_json or []) - len(keep)
        if not keep:
            await session.delete(package)
            removed["rfq_packages"] = removed.get("rfq_packages", 0) + 1
            continue
        package.items_json = keep
        package.warnings_json = [w for w in (package.warnings_json or []) if (w or {}).get("decision_id") not in ds]
        package.item_count = len(keep)
        package.approved_count = sum(1 for i in keep if (i.get("decision") or {}).get("approval_status") == "approved")
        package.stale_count = sum(1 for i in keep if (i.get("decision") or {}).get("is_stale"))
        package.unvalidated_count = sum(1 for i in keep if (i.get("decision") or {}).get("unvalidated_confidence"))
        if any(n and n in (package.title or "") for n in names):
            package.title = "RFQ package"
        package.metadata_json = {**(package.metadata_json or {}), "items_removed_by_part_deletion": deletion_ulid}
        package.updated_at = now_utc()

    await run("notifications", delete(Notification).where(
        Notification.org_id == org_id, Notification.source_id.in_([*rows.ulids, *hashes])))
    await run("actual_costs", delete(GroundTruthRecordRow).where(
        GroundTruthRecordRow.org_id == org_id, GroundTruthRecordRow.evidence_sha256.in_(hashes)))
    await run("part_contexts", delete(PartContext).where(PartContext.org_id == org_id, PartContext.mesh_hash.in_(hashes)))
    await run("part_summaries", delete(PartSummary).where(PartSummary.org_id == org_id, PartSummary.mesh_hash.in_(hashes)))
    await run("part_signatures", delete(PartSignature).where(PartSignature.org_id == org_id, PartSignature.mesh_hash.in_(hashes)))
    if rows.decision_ids:
        await run("cost_decisions", delete(CostDecision).where(CostDecision.id.in_(rows.decision_ids)))
    if rows.analysis_ids:
        await run("analyses", delete(Analysis).where(Analysis.id.in_(rows.analysis_ids)))
    removed["audit_events_redacted"] = await _redact_audit(
        session, org_id, hashes=hashes, ids=[*rows.ulids, *rows.share_ids, *item_ulids],
        reason="part_deleted", deletion_ulid=deletion_ulid,
    )
    return removed


async def _hashes_elsewhere(session: AsyncSession, org_id: str, hashes: list[str]) -> set[str]:
    """Hashes another organization also has (their SAM-3D blob is shared)."""
    if not hashes:
        return set()
    rows = (
        await session.execute(
            select(Analysis.mesh_hash).where(Analysis.org_id != org_id, Analysis.mesh_hash.in_(hashes)).distinct()
        )
    ).scalars().all()
    return set(rows)


def _pdf_steps(analysis_ulids: list[str], decision_ulids: list[str]) -> list[dict]:
    steps = []
    if decision_ulids:
        steps.append({"kind": "cost_pdf", "ulids": decision_ulids})
    if analysis_ulids:
        steps.append({"kind": "dfm_pdf", "ulids": analysis_ulids})
    return steps


async def delete_part(
    session: AsyncSession,
    *,
    org_id: str,
    mesh_hash: str,
    user_id: int,
    org_role: Optional[str],
    include_copies: bool = True,
) -> DataDeletion:
    """Delete one part (and, by default, the copies ScaleCAD fixed from it).

    Idempotent: a part already deleted returns its receipt. Concurrency: an
    advisory lock per (org, hash) serializes two deletes of the same part, and
    the organization row is share-locked so an org deletion can't interleave.
    The database phase commits here; the caller then runs ``process`` to empty
    the object store (retried by the worker until done).
    """
    root = valid_hash(mesh_hash)
    if root is None or not org_id or not _SAFE_ORG.fullmatch(org_id):
        raise HTTPException(status_code=404, detail="No part with this fingerprint in your organization.")
    org = (
        await session.execute(select(Organization.id).where(Organization.id == org_id).with_for_update(read=True))
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="No part with this fingerprint in your organization.")
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"part-delete:{org_id}:{root}"}
    )
    all_copies = await fixed_copies(session, org_id, root)
    copies = all_copies if include_copies else []
    rows = await _gather(session, org_id, [root, *copies], lock=True)
    if not rows.exists():
        # Already deleted (or never here). The transaction ends with the session.
        receipt = await _receipt_for(session, org_id, PART, root)
        if receipt is not None:
            return receipt
        raise HTTPException(status_code=404, detail="No part with this fingerprint in your organization.")
    can, why = _deletable_by(rows, user_id, org_role)
    if not can:
        raise HTTPException(status_code=403, detail={"code": "part_delete_not_allowed", "message": why})

    deletion_ulid = str(ULID())
    names = {r.filename for r in (*rows.analyses, *rows.decisions) if r.filename}
    counts = _counts(rows)
    removed = await _delete_part_rows(session, rows, deletion_ulid, names)

    elsewhere = await _hashes_elsewhere(session, org_id, rows.hashes)
    steps: list[dict] = [{"kind": "prefix", "store": "source-artifacts", "value": f"{org_id}/{h}"} for h in rows.hashes]
    steps += _pdf_steps([a.ulid for a in rows.analyses], [d.ulid for d in rows.decisions])
    steps += [{"kind": "key", "store": "batch", "value": f"{i.batch_ulid}/{i.filename}"} for i in rows.items]
    steps += [{"kind": "key", "store": "meshes", "value": f"{h}.bin"} for h in rows.hashes if h not in elsewhere]
    deleted = set(rows.hashes)
    # A deleted copy whose original stays: the original's attempt records stop pointing at it.
    parents: set[str] = set()
    for h in rows.hashes:
        link = await _read_json(org_id, h, "derived-from.json")
        parent = valid_hash((link or {}).get("parent_mesh_hash") or "")
        if parent and parent not in deleted:
            parents.add(parent)
    steps += [{"kind": "unlink_copies", "value": p, "copies": sorted(deleted)} for p in sorted(parents)]
    if not include_copies:
        steps += [{"kind": "scrub_lineage", "value": c} for c in all_copies]

    session.add(
        AuditLog(
            user_id=user_id,
            org_id=org_id,
            user_email=await _email(session, user_id),
            action="part.deleted",
            resource_type="part",
            resource_id=root,
            file_hash=root,
            detail_json={
                "deletion_id": deletion_ulid,
                "fixed_copies": copies,
                "removed": {**counts, **removed},
            },
        )
    )
    receipt = DataDeletion(
        ulid=deletion_ulid,
        scope=PART,
        org_id=org_id,
        target=root,
        requested_by=user_id,
        status="removing_files",
        removed_json={**counts, **removed, "fixed_copy_hashes": copies, "kept_fixed_copies": [] if include_copies else all_copies},
        steps_json=steps,
        steps_total=len(steps),
        steps_done=0,
    )
    session.add(receipt)
    await session.commit()
    forget_cached(org_id, rows.hashes)
    logger.info("part %s deleted in org %s by user %d (%d copies)", root[:12], org_id, user_id, len(copies))
    return receipt


async def _email(session: AsyncSession, user_id: Optional[int]) -> str:
    if user_id is None:
        return "system"
    return (await session.execute(select(User.email).where(User.id == user_id))).scalar_one_or_none() or f"user:{user_id}"


# ---------------------------------------------------------------------------
# Organization
# ---------------------------------------------------------------------------


async def _org_counts(session: AsyncSession, org_id: str) -> dict[str, int]:
    async def n(model) -> int:
        return int((await session.execute(select(func.count()).select_from(model).where(model.org_id == org_id))).scalar_one())

    from src.db.models import ApiKey, DesignProject, OrgInvite

    parts = int(
        (
            await session.execute(
                select(func.count(func.distinct(Analysis.mesh_hash))).where(Analysis.org_id == org_id)
            )
        ).scalar_one()
    )
    record_parts = int(
        (
            await session.execute(
                select(func.count(func.distinct(CostDecision.mesh_hash))).where(
                    CostDecision.org_id == org_id,
                    CostDecision.mesh_hash.not_in(select(Analysis.mesh_hash).where(Analysis.org_id == org_id)),
                )
            )
        ).scalar_one()
    )
    from src.services import share_links

    active = 0
    for model in (Analysis, CostDecision):
        for row in (
            await session.execute(select(model).where(model.org_id == org_id, model.share_short_id.is_not(None)))
        ).scalars():
            active += share_links.status(row) == "active"
    return {
        "parts": parts + record_parts,
        "checks": await n(Analysis),
        "cost_records": await n(CostDecision),
        "batches": await n(Batch),
        "designs": await n(DesignProject),
        "actual_costs": await n(GroundTruthRecordRow),
        "members": await n(Membership),
        "pending_invites": int((await session.execute(
            select(func.count()).select_from(OrgInvite).where(
                OrgInvite.org_id == org_id, OrgInvite.accepted_at.is_(None),
                OrgInvite.revoked_at.is_(None), OrgInvite.expires_at > func.now(),
            )
        )).scalar_one()),
        "api_keys": int((await session.execute(
            select(func.count()).select_from(ApiKey).where(ApiKey.org_id == org_id, ApiKey.revoked_at.is_(None))
        )).scalar_one()),
        "active_share_links": active,
    }


async def org_deletion_preview(session: AsyncSession, org_id: str) -> dict[str, Any]:
    org = (await session.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return {
        "org_id": org.id,
        "name": org.name,
        "will_remove": await _org_counts(session, org_id),
        "kept": KEPT_AFTER_ORG_DELETE,
    }


async def delete_organization(
    session: AsyncSession, *, org_id: str, user_id: int, confirm_name: str,
) -> DataDeletion:
    """Delete the organization and everything in it. The caller is its admin.

    ``confirm_name`` must equal the organization's name (surrounding spaces
    ignored). The org row is locked FOR UPDATE, which waits for any part
    deletion holding its share lock. Idempotent at the HTTP layer: a second
    call finds no organization (the caller's active org is then another one).
    """
    if not org_id or not _SAFE_ORG.fullmatch(org_id):
        raise HTTPException(status_code=404, detail="Organization not found")
    org = (
        await session.execute(select(Organization).where(Organization.id == org_id).with_for_update())
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    if (confirm_name or "").strip() != (org.name or "").strip():
        raise HTTPException(
            status_code=400,
            detail={"code": "confirm_name_mismatch", "message": "Type the organization's name exactly to delete it."},
        )

    deletion_ulid = str(ULID())
    counts = await _org_counts(session, org_id)
    batches = (await session.execute(select(Batch.ulid).where(Batch.org_id == org_id))).scalars().all()
    recon_jobs = (
        await session.execute(select(Job.ulid).where(Job.org_id == org_id, Job.job_type == "reconstruction"))
    ).scalars().all()
    members = (
        await session.execute(
            select(Membership.user_id, User.email).join(User, User.id == Membership.user_id).where(Membership.org_id == org_id)
        )
    ).all()

    steps: list[dict] = [
        {"kind": "prefix", "store": "source-artifacts", "value": org_id},
        {"kind": "prefix", "store": "designs", "value": org_id},
    ]
    steps += [{"kind": "prefix", "store": "batch", "value": b} for b in batches]
    steps += [{"kind": "prefix", "store": "reconstruct", "value": j} for j in recon_jobs]
    # PDFs and SAM-3D blobs aren't keyed by organization: after the rows are
    # gone, every one whose record no longer exists is removed (bounded receipt
    # size for an organization of any size; the same rule also clears any
    # earlier orphan, which nothing could reach anyway).
    steps += [{"kind": "orphans", "store": "cost-pdf"}, {"kind": "orphans", "store": "dfm-pdf"},
              {"kind": "orphans", "store": "meshes"}]
    steps.append({"kind": "prefix", "store": "direct-uploads", "value": f"incoming/{org_id}", "optional": True})

    redacted = await session.execute(
        update(AuditLog)
        .where(AuditLog.org_id == org_id)
        .values(detail_json={"redacted": "organization_deleted", "deletion_id": deletion_ulid, "org_id": org_id},
                result_summary=None)
        .execution_options(synchronize_session=False)
    )
    counts["audit_events_redacted"] = int(redacted.rowcount or 0)
    # Written without an org FK so the organization's removal leaves it intact.
    session.add(
        AuditLog(
            user_id=user_id,
            org_id=None,
            user_email=await _email(session, user_id),
            action="organization.deleted",
            resource_type="organization",
            resource_id=org_id,
            detail_json={"deletion_id": deletion_ulid, "org_id": org_id, "removed": counts},
        )
    )
    await session.execute(delete(Organization).where(Organization.id == org_id).execution_options(synchronize_session=False))

    # Every member lands in an organization that still exists, and is signed out.
    from src.auth.org_context import ensure_personal_org

    moved: dict[int, str] = {}
    for member_id, email in members:
        remaining = (
            await session.execute(
                select(Membership.org_id).where(Membership.user_id == member_id)
                .order_by(Membership.created_at.asc(), Membership.id.asc()).limit(1)
            )
        ).scalar_one_or_none()
        target = remaining or await ensure_personal_org(session, member_id, email)
        await session.execute(update(User).where(User.id == member_id).values(current_org_id=target))
        moved[int(member_id)] = target
    others = [m for m in moved if m != user_id]
    if others:
        await session.execute(
            update(User).where(User.id.in_(others)).values(session_version=User.session_version + 1)
            .execution_options(synchronize_session=False)
        )
    for member_id in others:
        session.add(
            AuditLog(
                user_id=member_id, org_id=moved[member_id], user_email=await _email(session, member_id),
                action="user.sessions_revoked", resource_type="user", resource_id=str(member_id),
                detail_json={"reason": "organization_deleted", "deletion_id": deletion_ulid},
            )
        )

    receipt = DataDeletion(
        ulid=deletion_ulid,
        scope=ORGANIZATION,
        org_id=org_id,
        target=org_id,
        requested_by=user_id,
        status="removing_files",
        removed_json={**counts, "members_signed_out": len(others), "now_in_org": moved.get(user_id)},
        steps_json=steps,
        steps_total=len(steps),
        steps_done=0,
        final_sweep_due_at=now_utc() + ORG_FINAL_SWEEP_DELAY,
    )
    session.add(receipt)
    await session.commit()
    forget_cached(org_id, None)
    logger.info("organization %s deleted by user %d (%d members)", org_id, user_id, len(members))
    return receipt


# ---------------------------------------------------------------------------
# Object-store phase (after commit; idempotent; resumable)
# ---------------------------------------------------------------------------


def _run_step_sync(org_id: str, step: dict) -> int:
    kind = step.get("kind")
    value = str(step.get("value") or "")
    if kind == "prefix":
        if not value or ".." in value.split("/"):
            raise ValueError("unsafe prefix")
        try:
            store = _store(step["store"])
        except Exception:
            if step.get("optional"):
                return 0  # that store isn't configured on this deployment
            raise
        return int(store.delete_prefix(value) or 0)
    if kind == "key":
        store = _store(step["store"])
        if not store.exists(value):
            return 0
        store.delete(value)
        return 1
    if kind == "cost_pdf":
        store = _store("cost-pdf")
        wanted = tuple(f"cost-{u}-" for u in step.get("ulids") or [])
        n = 0
        for key in store.list_keys(""):
            if key.startswith(wanted):
                store.delete(key)
                n += 1
        return n
    if kind == "dfm_pdf":
        root = _dfm_pdf_dir()
        n = 0
        for ulid in step.get("ulids") or []:
            if not re.fullmatch(r"[0-9A-Za-z]{10,40}", str(ulid)):
                continue
            for path in root.glob(f"{ulid}.*.pdf"):
                path.unlink(missing_ok=True)
                n += 1
        return n
    raise ValueError(f"unknown step {kind!r}")


_ORPHAN_CHUNK = 500
_PDF_KEY = re.compile(r"^cost-([0-9A-Za-z]{26})-[0-9a-f]{8,64}\.pdf$")
_DFM_PDF = re.compile(r"^([0-9A-Za-z]{26})\.[^/]+\.pdf$")
_MESH_KEY = re.compile(r"^([0-9a-f]{64})\.bin$")


async def _sweep_orphans(store_name: str) -> int:
    """Remove cached PDFs / SAM-3D blobs whose record no longer exists anywhere."""
    from src.db.engine import get_session_factory

    if store_name == "dfm-pdf":
        root = _dfm_pdf_dir()
        paths = await asyncio.to_thread(lambda: [p for p in root.glob("*.pdf")] if root.exists() else [])
        found = [(m.group(1), p) for p in paths if (m := _DFM_PDF.match(p.name))]
        column, pattern = Analysis.ulid, None
    else:
        store = _store(store_name)
        keys = await asyncio.to_thread(store.list_keys, "")
        pattern = _PDF_KEY if store_name == "cost-pdf" else _MESH_KEY
        found = [(m.group(1), k) for k in keys if (m := pattern.match(k))]
        column = CostDecision.ulid if store_name == "cost-pdf" else Analysis.mesh_hash
    removed = 0
    async with get_session_factory()() as session:
        for start in range(0, len(found), _ORPHAN_CHUNK):
            chunk = found[start:start + _ORPHAN_CHUNK]
            ids = list({i for i, _ in chunk})
            alive = set(
                (await session.execute(select(column).where(column.in_(ids)).distinct())).scalars().all()
            )
            for ident, where in chunk:
                if ident in alive:
                    continue
                if store_name == "dfm-pdf":
                    await asyncio.to_thread(where.unlink, True)
                else:
                    await asyncio.to_thread(store.delete, where)
                removed += 1
    return removed


async def _run_step(org_id: str, step: dict) -> int:
    kind = step.get("kind")
    if kind == "orphans":
        return await _sweep_orphans(step["store"])
    if kind == "unlink_copies":
        return await _unlink_copies(org_id, step["value"], set(step.get("copies") or []))
    if kind == "scrub_lineage":
        return await _scrub_lineage(org_id, step["value"])
    return await asyncio.to_thread(_run_step_sync, org_id, step)


async def _unlink_copies(org_id: str, parent: str, copies: set[str]) -> int:
    """The original's fix/repair records stop pointing at deleted copies."""
    from src.services import cad_fix_service as fx

    prefix = f"{org_id}/{parent}/fixes"
    keys = await asyncio.to_thread(_store("source-artifacts").list_keys, prefix)
    n = 0
    for key in keys:
        name = key[len(f"{org_id}/{parent}/"):]
        record = await _read_json(org_id, parent, name)
        if record and record.get("fixed_mesh_hash") in copies:
            record["fixed_mesh_hash"] = None
            record["fixed_copy_deleted_at"] = now_utc().isoformat()
            await fx._put_json(fx._record_key(org_id, parent, name), record)
            n += 1
    logger.info("unlinked %d attempt record(s) of %s from deleted copies", n, parent[:12])
    return 0  # records were rewritten, not removed


async def _scrub_lineage(org_id: str, copy_hash: str) -> int:
    """A kept copy no longer names the deleted original's file."""
    from src.services import cad_fix_service as fx

    link = await _read_json(org_id, copy_hash, "derived-from.json")
    if not link:
        return 0
    link.pop("parent_filename", None)
    link["parent_deleted_at"] = now_utc().isoformat()
    await fx._put_json(fx._record_key(org_id, copy_hash, "derived-from.json"), link)
    return 0


async def _claim(session: AsyncSession, deletion_ulid: str, *, force: bool) -> Optional[DataDeletion]:
    cond = [DataDeletion.ulid == deletion_ulid, DataDeletion.status == "removing_files"]
    if not force:
        cond.append(DataDeletion.updated_at < now_utc() - LEASE)
    row = (
        await session.execute(
            update(DataDeletion).where(*cond)
            .values(updated_at=func.now(), attempts=DataDeletion.attempts + 1)
            .returning(DataDeletion.id)
        )
    ).scalar_one_or_none()
    await session.commit()
    if row is None:
        return None
    return (await session.execute(select(DataDeletion).where(DataDeletion.id == row))).scalar_one()


async def process(deletion_ulid: str, *, force: bool = False, session_factory=None) -> Optional[DataDeletion]:
    """Run the remaining object-store steps of a deletion; safe to repeat.

    Each finished step is committed (progress survives a crash). A failure
    leaves the row ``removing_files`` with ``last_error`` for the worker to
    retry; after ``MAX_ATTEMPTS`` it becomes ``failed`` (an operator alert).
    """
    from src.db.engine import get_session_factory

    factory = session_factory or get_session_factory()
    async with factory() as session:
        row = await _claim(session, deletion_ulid, force=force)
        if row is None:
            return None
        steps = list(row.steps_json or [])
        try:
            for index in range(row.steps_done, len(steps)):
                removed = await _run_step(row.org_id, steps[index])
                row.steps_done = index + 1
                row.files_removed = (row.files_removed or 0) + removed
                row.updated_at = now_utc()
                await session.commit()
        except Exception as exc:  # noqa: BLE001 - recorded and retried
            await session.rollback()
            row = (await session.execute(select(DataDeletion).where(DataDeletion.ulid == deletion_ulid))).scalar_one()
            row.last_error = f"{type(exc).__name__}: {str(exc)[:300]}"
            row.updated_at = now_utc()
            if (row.attempts or 0) >= MAX_ATTEMPTS:
                row.status = "failed"
            await session.commit()
            logger.warning("deletion %s step %d failed: %s", deletion_ulid, row.steps_done, row.last_error)
            return row
        row.status = "done"
        row.last_error = None
        row.completed_at = now_utc()
        row.updated_at = now_utc()
        await session.commit()
        return row


async def final_sweep(deletion_ulid: str, *, session_factory=None) -> Optional[DataDeletion]:
    """One more pass over an organization's prefixes after in-flight work ended."""
    from src.db.engine import get_session_factory

    factory = session_factory or get_session_factory()
    async with factory() as session:
        row = (
            await session.execute(
                select(DataDeletion).where(
                    DataDeletion.ulid == deletion_ulid,
                    DataDeletion.status == "done",
                    DataDeletion.final_sweep_due_at.is_not(None),
                    DataDeletion.final_sweep_due_at <= now_utc(),
                ).with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        extra = 0
        for step in row.steps_json or []:
            if step.get("kind") == "prefix" and step.get("store") in {"source-artifacts", "designs"}:
                extra += await _run_step(row.org_id, step)
        row.files_removed = (row.files_removed or 0) + extra
        row.final_sweep_due_at = None
        row.updated_at = now_utc()
        await session.commit()
        return row


async def pending_deletions(session: AsyncSession, *, limit: int = 20) -> tuple[list[str], list[str]]:
    """(receipts still removing files and idle past the lease, org receipts due a final sweep)."""
    stale = (
        await session.execute(
            select(DataDeletion.ulid).where(
                DataDeletion.status == "removing_files", DataDeletion.updated_at < now_utc() - LEASE
            ).order_by(DataDeletion.id).limit(limit)
        )
    ).scalars().all()
    sweeps = (
        await session.execute(
            select(DataDeletion.ulid).where(
                DataDeletion.status == "done",
                DataDeletion.final_sweep_due_at.is_not(None),
                DataDeletion.final_sweep_due_at <= now_utc(),
            ).order_by(DataDeletion.id).limit(limit)
        )
    ).scalars().all()
    return list(stale), list(sweeps)


# ---------------------------------------------------------------------------
# Process caches
# ---------------------------------------------------------------------------


def forget_cached(org_id: str, hashes: Optional[Iterable[str]]) -> None:
    """Drop this process's cached views of the part(s), or of the whole org."""
    from src.api import part_orientation, part_preview
    from src.parsers import mesh_cache
    from src.services import part_geometry_cache

    wanted = set(hashes) if hashes is not None else None

    def hit(key: tuple) -> bool:
        return key[0] == org_id and (wanted is None or key[1] in wanted)

    for cache in (part_preview._cache, part_orientation._cache):
        for key in [k for k in list(cache) if hit(k)]:
            cache.pop(key, None)
    if wanted:
        part_geometry_cache.forget_hashes(wanted)
        mesh_cache.forget_hashes(wanted)


# ---------------------------------------------------------------------------
# Receipt
# ---------------------------------------------------------------------------


def serialize_receipt(row: DataDeletion) -> dict[str, Any]:
    removed = dict(row.removed_json or {})
    return {
        "id": row.ulid,
        "scope": row.scope,
        "target": row.target,
        "status": row.status,
        "removed": removed,
        "files": {
            "steps_total": row.steps_total,
            "steps_done": row.steps_done,
            "removed": row.files_removed,
            "retrying": row.status == "removing_files" and bool(row.last_error),
        },
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "kept": KEPT_AFTER_PART_DELETE if row.scope == PART else KEPT_AFTER_ORG_DELETE,
    }


async def get_receipt(session: AsyncSession, deletion_ulid: str, user_id: int) -> DataDeletion:
    """The requester's own receipt, or an admin's of their current org; else 404."""
    row = (await session.execute(select(DataDeletion).where(DataDeletion.ulid == deletion_ulid))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Deletion not found")
    if row.requested_by == user_id:
        return row
    role = (
        await session.execute(
            select(Membership.org_role).where(Membership.org_id == row.org_id, Membership.user_id == user_id)
        )
    ).scalar_one_or_none()
    if role == "admin":
        return row
    raise HTTPException(status_code=404, detail="Deletion not found")
