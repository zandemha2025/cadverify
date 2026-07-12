"""Confirmed-identity API (identity Slice 1 — the human-in-the-loop seam).

The retrieval-grounding engine only ever SUGGESTS an identity (a provenance-tagged,
confidence-scored neighbour). This route is where a human turns a suggestion into an
ASSERTION: ``POST /identity/confirm`` stamps the declared part number / name /
program onto the org's corpus row for a part's ``mesh_hash`` and flips its source to
``user_confirmed`` — so a future retrieval of a similar part carries the human-
confirmed identity, not just a guess.

Tenancy: ORG-SCOPED. The caller's org is resolved (``resolve_org``) and every write
is filtered by ``org_id`` (``part_signature_service.confirm_identity``), so a caller
can NEVER touch another org's row — a cross-tenant confirm finds no row and 404s.
Requires the ``analyst`` role (the same role that authors decisions / declares
context).

Honesty: a confirmed identity is a USER assertion (``provenance: "USER"``), never
inferred from the mesh. The route confirms an EXISTING corpus row (a part the org has
already analyzed / seen); it never fabricates a signature it cannot measure — a mesh
not yet in the corpus is a 404, not a silent create.
"""
from __future__ import annotations

import logging
import os
from typing import List, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.kill_switch import require_kill_switch_open
from src.auth.org_context import resolve_org
from src.auth.rate_limit import limiter
from src.auth.rbac import Role, require_role
from src.auth.require_api_key import AuthedUser
from src.db.engine import get_db_session
from src.services import part_signature_service as sigsvc
from src.services import parts_master_service as pmsvc

logger = logging.getLogger("cadverify.identity")

router = APIRouter(tags=["identity"])

# Onboarding batch size cap for the whole multipart upload (streamed reject). A part
# library is CAD files, so this is generous but bounded — a single request can't
# exhaust memory. Reuse the ZIP path for large libraries.
_ONBOARD_MAX_BYTES = int(os.getenv("PARTS_MASTER_MAX_MB", "512")) * 1024 * 1024


class ConfirmIdentityBody(BaseModel):
    mesh_hash: str
    declared_part_id: Optional[str] = None
    declared_name: Optional[str] = None
    program: Optional[str] = None


@router.post("/confirm")
@limiter.limit("120/hour;600/day")
async def confirm_identity(
    request: Request,
    response: Response,
    body: ConfirmIdentityBody,
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Confirm (or correct) a part's identity in the caller's org corpus.

    Upserts the declared identity onto the ``(org, mesh_hash)`` corpus row and
    stamps ``source='user_confirmed'`` (provenance USER). A ``mesh_hash`` with no
    corpus row in this org — including another org's part — is a 404, never a write.
    """
    org_id = await resolve_org(session, user.user_id)
    if not org_id:
        raise HTTPException(status_code=400, detail="no organization for caller")

    mesh_hash = (body.mesh_hash or "").strip()
    if not mesh_hash:
        raise HTTPException(status_code=400, detail="mesh_hash is required")

    # At least one declared field must be supplied — a confirm asserts SOMETHING.
    if not any((body.declared_part_id, body.declared_name, body.program)):
        raise HTTPException(
            status_code=400,
            detail="supply at least one of declared_part_id, declared_name, program",
        )

    row = await sigsvc.confirm_identity(
        session,
        org_id,
        mesh_hash,
        declared_part_id=body.declared_part_id,
        declared_name=body.declared_name,
        program=body.program,
    )
    if row is None:
        # No corpus row for this (org, mesh) — you can only confirm a part your org
        # has already seen. Never a cross-tenant write, never a fabricated signature.
        raise HTTPException(
            status_code=404,
            detail="no part in your library for that mesh_hash (analyze it first)",
        )
    from src.services.audit_service import emit_event

    await emit_event(
        session,
        actor_id=user.user_id,
        action="identity.confirm",
        resource_type="part_signature",
        resource_id=mesh_hash,
        detail={
            "declared_part_id": body.declared_part_id,
            "declared_name": body.declared_name,
            "program": body.program,
        },
        org_id=org_id,
    )
    await session.commit()

    return sigsvc.serialize_signature(row)


# ---------------------------------------------------------------------------
# Parts-master feeder (identity Slice 2) — bulk-onboard a customer's part
# library so the org corpus has REAL declared identities on day one.
# ---------------------------------------------------------------------------


async def _read_onboard_zip_files(zip_upload: UploadFile) -> tuple[list, list]:
    """Reuse the batch ZIP path (stream-to-tempfile + guarded extraction) and read
    each extracted CAD file's bytes. Returns ``(files, skipped)`` where ``files`` is
    ``[(filename, bytes)]`` and ``skipped`` carries the extractor's own skips
    (unsupported native CAD, oversize) as ``{filename, reason}`` — no reinvented ZIP
    handling, no reinvented CAD parsing."""
    import asyncio
    import os as _os

    from src.services import batch_service
    from ulid import ULID

    files: list[tuple[str, bytes]] = []
    skipped: list[dict] = []
    # A fixed "parts-master" prefix lets simultaneous org imports overwrite or
    # delete each other's same-named CAD files. Give every request an isolated
    # temporary namespace; the durable org-scoped rows are created later.
    object_namespace = f"parts-master-{ULID()}"
    tmp_path = await batch_service.stream_upload_to_tempfile(
        zip_upload, batch_service.BATCH_MAX_ZIP_BYTES
    )
    try:
        items = await asyncio.to_thread(
            batch_service.extract_zip_path_to_items,
            tmp_path,
            object_namespace,
        )
        for item in items:
            if item.get("status") == "skipped":
                skipped.append({
                    "filename": item.get("filename", "?"),
                    "reason": item.get("error", "skipped by extractor"),
                })
                continue
            files.append(
                (
                    item["filename"],
                    await asyncio.to_thread(
                        batch_service.read_batch_blob,
                        object_namespace,
                        item["filename"],
                    ),
                )
            )
            try:
                await asyncio.to_thread(
                    batch_service.delete_batch_blob,
                    object_namespace,
                    item["filename"],
                )
            except (OSError, KeyError):
                pass
    finally:
        try:
            await asyncio.to_thread(
                batch_service.cleanup_batch_files,
                object_namespace,
            )
        except Exception:
            logger.exception(
                "Failed to clean temporary parts-master objects under %s",
                object_namespace,
            )
        try:
            _os.unlink(tmp_path)
        except OSError:
            pass
    return files, skipped


@router.post("/library/onboard", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("20/hour;60/day")
async def onboard_library(
    request: Request,
    response: Response,
    files: Optional[List[UploadFile]] = File(None),
    zip: Optional[UploadFile] = File(None),
    mapping: Optional[UploadFile] = File(None),
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Bulk-onboard a customer's part library into the org identity corpus.

    Multipart body:
      * ``files`` — one or more CAD files (STL/STEP/IGES), OR
      * ``zip`` — a ZIP archive of CAD files (reuses the batch ZIP path + guards);
      * ``mapping`` — an identity mapping (CSV or JSON) binding each ``filename`` to
        its declared ``part_id`` / ``name`` / ``program`` / ``material_class``. Every
        column except ``filename`` is optional. Contract: ``GET /library/template``.

    Each file enters the corpus WITH its declared identity (``source='parts_master'``)
    and, when a ``part_id`` is declared, the reused declared-master registry
    (``ManifestPart``). HONEST throughout: a missing name onboards bare geometry (no
    guess); an unparseable file / unknown material is SKIPPED (never aborts the
    batch). Returns ``{onboarded, skipped:[{filename, reason}], library_size, ...}``.
    """
    org_id = await resolve_org(session, user.user_id)
    if not org_id:
        raise HTTPException(status_code=403, detail="No organization for caller.")

    # ── assemble the files (direct multipart and/or a ZIP) ──────────────────
    onboard_files: list[tuple[str, bytes]] = []
    extractor_skipped: list[dict] = []
    total_bytes = 0

    if files:
        for up in files:
            data = await up.read()
            total_bytes += len(data)
            if total_bytes > _ONBOARD_MAX_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"onboarding upload exceeds {_ONBOARD_MAX_BYTES // (1024 * 1024)}MB "
                        "— use the ZIP form for a large library"
                    ),
                )
            onboard_files.append((up.filename or "unnamed", data))

    if zip is not None:
        zip_files, extractor_skipped = await _read_onboard_zip_files(zip)
        onboard_files.extend(zip_files)

    if not onboard_files:
        raise HTTPException(
            status_code=400,
            detail="Provide CAD files (files=…) or a ZIP archive (zip=…) to onboard.",
        )
    if len(onboard_files) > pmsvc.ONBOARD_MAX_FILES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"onboarding batch of {len(onboard_files)} files exceeds the "
                f"{pmsvc.ONBOARD_MAX_FILES} cap — split it into smaller batches"
            ),
        )

    # ── parse the identity mapping (CSV or JSON; tolerant, honest) ──────────
    identity_map: dict = {}
    mapping_errors: list = []
    if mapping is not None:
        raw = await mapping.read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=400, detail="mapping must be UTF-8 encoded text (CSV or JSON)."
            )
        identity_map, mapping_errors = pmsvc.parse_identity_mapping(
            text, content_hint=(mapping.filename or "") + " " + (mapping.content_type or "")
        )

    # ── onboard (per-file try/except lives in the service) ──────────────────
    summary = await pmsvc.onboard_library(
        session, org_id, user.user_id, onboard_files, identity_map
    )
    await session.commit()

    # Fold the ZIP-extractor's own skips + the mapping parse errors into the honest
    # summary so nothing is silently dropped.
    summary["skipped"] = extractor_skipped + summary["skipped"]
    summary["mapping_errors"] = mapping_errors + summary.get("manifest_errors", [])
    summary.pop("manifest_errors", None)
    return summary


@router.get("/library")
@limiter.limit("120/hour;1000/day")
async def get_library(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """The org's identity corpus size + a recent slice (declared identity only).

    ``{library_size, recent:[{mesh_hash, declared_part_id, declared_name, program,
    source, provenance, ...}]}`` — org-scoped; the raw signature vector is never
    emitted. Falsy org → 403 (mirrors the manifest surface)."""
    org_id = await resolve_org(session, user.user_id)
    if not org_id:
        raise HTTPException(status_code=403, detail="No organization for caller.")
    size = await pmsvc.library_size(session, org_id)
    recent = await pmsvc.recent_library(session, org_id)
    return {"library_size": size, "recent": recent}


@router.get("/library/template", response_class=Response)
@limiter.limit("120/hour;1000/day")
async def library_template(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
):
    """The identity-mapping CSV contract for the parts-master feeder.

    Required column: ``filename`` (binds a mapping row to an uploaded CAD file).
    Optional declared identity: ``part_id``, ``name``, ``program``, ``material_class``
    (must be a known cost-engine class if present). A JSON list of the same fields is
    also accepted at onboard time."""
    body = pmsvc.MAPPING_HEADER + "\n" + pmsvc._example_mapping_row() + "\n"
    return Response(content=body, media_type="text/csv")
