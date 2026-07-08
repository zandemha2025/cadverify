"""API route handlers for CADVerify."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import structlog

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.analysis.models import AnalysisResult, Issue, ProcessType
from src.analysis.rules import available_rule_packs, get_rule_pack
from src.api.metrics_registry import observe_analysis_duration, record_cost_decision
from src.obs import tracing
from src.api.upload_validation import (
    demo_max_triangles,
    enforce_stl_triangle_count_cap,
    enforce_triangle_cap,
    validate_magic,
)
from src.auth.kill_switch import require_kill_switch_open
from src.auth.rate_limit import limiter
from src.auth.rbac import Role, require_role
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session
from src.fixes.fix_suggester import get_priority_fixes
from src.parsers import mesh_cache
from src.parsers.step_mesher import is_step_supported, step_to_trimesh_from_bytes
from src.parsers.stl_parser import parse_stl_from_bytes
from src.profiles.database import MACHINES, MATERIALS, get_all_processes
from src.services import analysis_service, repair_service

logger = logging.getLogger("cadverify.routes")

# Structured logger for the cost-decision endpoint. Routes through the app's
# structlog pipeline (merge_contextvars -> add_log_level -> TimeStamper ->
# scrub_processor -> JSONRenderer), so every event auto-carries the request_id
# bound by RequestIDMiddleware and is scrubbed of cv_live_*/Authorization. We
# log ONLY non-PII aggregates here (hashed file id, suffix, counts, outcome) —
# never the raw filename, mesh bytes, or any geometry beyond face_count.
slog = structlog.get_logger("cadverify.cost")

router = APIRouter()


# ──────────────────────────────────────────────────────────────
# Upload handling
# ──────────────────────────────────────────────────────────────
_CHUNK = 1024 * 1024  # 1 MiB


def _max_upload_bytes() -> int:
    """Read limit lazily so tests can override via monkeypatch."""
    try:
        mb = int(os.getenv("MAX_UPLOAD_MB", "100"))
    except ValueError:
        mb = 100
    return max(1, mb) * 1024 * 1024


def _analysis_timeout_sec() -> float:
    """Read ANALYSIS_TIMEOUT_SEC lazily so tests can override via monkeypatch."""
    try:
        return max(0.1, float(os.getenv("ANALYSIS_TIMEOUT_SEC", "60")))
    except ValueError:
        return 60.0


async def _read_capped(file: UploadFile) -> bytes:
    """Stream-read the upload, rejecting anything over MAX_UPLOAD_MB."""
    limit = _max_upload_bytes()
    buf = bytearray()
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds {limit // (1024 * 1024)}MB limit",
            )
    if not buf:
        raise HTTPException(status_code=400, detail="Empty file uploaded")
    return bytes(buf)


def _parse_mesh(data: bytes, filename: str):
    suffix = Path(filename).suffix.lower()
    if suffix not in (".stl", ".step", ".stp", ".iges", ".igs"):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type: {suffix}. "
                "Use .stl, .step, .stp, .iges, or .igs"
            ),
        )
    # CORE-07: defense-in-depth — verify magic bytes before dispatching
    # to parser libs (cadquery/trimesh can crash on adversarial input).
    # Kept BEFORE the cache lookup so unsupported/corrupt uploads still 400
    # exactly as today (same bytes => same magic result on a hit).
    validate_magic(data, suffix)

    # PERF: mutation-safe parsed-mesh cache. The SAME part is re-parsed by the
    # validate + cost + preview burst; gmsh/OCC tessellation is ~seconds. On a
    # HIT we return a deep copy (never the shared object); on a MISS we return
    # the freshly-parsed original (byte-identical to pre-cache behavior) and the
    # cache retains an independent copy. See parsers/mesh_cache.py for the full
    # correctness argument, bounds, and opt-out (MESH_PARSE_CACHE_DISABLED).
    cache = None
    cache_key = None
    if not mesh_cache.is_disabled():
        cache = mesh_cache.get_cache()
        cache_key = mesh_cache.key_for(data, suffix)

    try:
        if cache is not None:
            cached = cache.get(cache_key)
            if cached is not None:
                # HIT: the cache stores only the PARSE. The triangle cap is a
                # per-REQUEST policy (MAX_TRIANGLES is read from env each call),
                # so re-enforce it on the copy — a cap lowered since the entry
                # was populated must still 400, exactly as a fresh parse would.
                enforce_triangle_cap(cached)
                return cached, suffix
        if suffix == ".stl":
            enforce_stl_triangle_count_cap(data)
            mesh = parse_stl_from_bytes(data, filename)
            enforce_triangle_cap(mesh)
        else:
            if not is_step_supported():
                raise HTTPException(
                    status_code=501,
                    detail="STEP parsing is unavailable on this server (gmsh not installed).",
                )
            # gmsh -> triangulated shell (DFM + cost path). The post-mesh
            # triangle cap is the hard stop for runaway tessellation.
            mesh = step_to_trimesh_from_bytes(data, filename)
            enforce_triangle_cap(mesh)  # 400 if tessellation exceeded MAX_TRIANGLES
    except HTTPException:
        raise
    except ValueError as e:
        # Parser-provided message is safe to expose.
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Mesh parsing failed for %s", filename)
        raise HTTPException(status_code=400, detail="Failed to parse mesh file")

    if cache is not None:
        cache.put(cache_key, mesh)
    return mesh, suffix


async def _parse_mesh_async(data: bytes, filename: str):
    """Run _parse_mesh off the event loop, bounded by ANALYSIS_TIMEOUT_SEC.

    gmsh STEP meshing is CPU-bound and can be slow on complex parts; this keeps
    the worker responsive and turns a runaway tessellation into a clean 504
    instead of blocking the event loop. STL parsing is sub-second; it simply
    runs in a thread now with no behavioural change.
    """
    import asyncio

    loop = asyncio.get_event_loop()
    timeout = _analysis_timeout_sec()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _parse_mesh, data, filename),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"File parsing exceeded {timeout:.0f}s timeout.",
        )


def _resolve_target_processes(processes: Optional[str]) -> list[ProcessType]:
    if not processes:
        return list(ProcessType)
    out: list[ProcessType] = []
    for token in processes.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            out.append(ProcessType(token))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown process: {token}")
    return out


# ──────────────────────────────────────────────────────────────
# Cost decision engine + options parsing (POST /validate/cost)
# ──────────────────────────────────────────────────────────────
def _run_cost_engine(mesh, filename: str):
    """Score every registered process for the cost decision layer (mirrors
    cli._run_engine but from an already-parsed in-memory mesh; no narrowing,
    no persistence, no network)."""
    import src.analysis.processes  # noqa: F401  populate registry
    from src.analysis.base_analyzer import (
        analyze_geometry,
        decimation_issue,
        run_universal_checks,
    )
    from src.analysis.context import GeometryContext
    from src.analysis.features import detect_all as detect_features
    from src.matcher.profile_matcher import rank_processes, score_process
    from src.analysis.processes.base import get_analyzer
    from src.analysis.processes import base as pbase
    from src.analysis.models import AnalysisResult

    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    # Features must be detected on the same mesh the context arrays derive from
    # (ctx.mesh == mesh unless build() decimated an oversize mesh) so feature
    # face-indices stay aligned with the per-face arrays the analyzers consume.
    ctx.features = detect_features(ctx.mesh)
    universal = run_universal_checks(mesh)
    # Honestly surface to the user when the mesh was decimated for analysis.
    dec_issue = decimation_issue(ctx)
    if dec_issue is not None:
        universal.append(dec_issue)
    scores = [
        score_process(get_analyzer(p).analyze(ctx), geometry, p)
        for p in pbase._REGISTRY
        if get_analyzer(p)
    ]
    result = AnalysisResult(
        filename=filename,
        file_type="stl",
        geometry=geometry,
        segments=ctx.segments,
        universal_issues=universal,
        process_scores=scores,
    )
    rank_processes(result)
    return result, mesh, ctx.features


_COMPLEXITY = {"simple", "moderate", "complex", "very_complex"}
_MATERIAL_CLASSES = {"polymer", "aluminum", "steel", "stainless", "titanium"}
_REGIONS = {"US", "EU", "MX", "CN", "IN", "SA"}
_TOLERANCE_CLASSES = {"standard", "precision", "tight"}
# Declared CAD source units (B5). STL/mesh vertices carry no unit metadata; the
# engine has always interpreted them as mm. A caller may DECLARE the source units
# so an inch-authored part is scaled ×25.4 into mm at the parse seam (exactly once)
# instead of silently mis-costing by ~16,000×. Unset => mm (byte-identical default).
_SOURCE_UNITS = {"mm", "inch"}
_MAX_QTYS = 6
_MAX_QTY = 10_000_000
_MAX_OVERRIDES = 64  # cap ad-hoc rate/driver overrides per request


def _parse_owned_processes(raw: Optional[str]) -> frozenset:
    """Parse the comma-separated `owned_processes` form field into a
    frozenset[ProcessType] (the engine processes the org already OWNS in-house).

    Absent / blank => empty frozenset => byte-identical (nothing owned). Each
    token is an engine process id (e.g. "cnc_3axis,injection_molding"); an
    unknown id is a 400, mirroring the region/material validation.
    """
    if not raw or not raw.strip():
        return frozenset()
    from src.costing.rates import _resolve_process_token

    out = set()
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        pt = _resolve_process_token(tok)
        if pt is None:
            raise HTTPException(
                status_code=400,
                detail=(f"Unknown process {tok!r} in owned_processes. Use engine "
                        f"process ids, e.g. cnc_3axis,injection_molding."),
            )
        out.add(pt)
    return frozenset(out)


def _available_shops() -> list[dict]:
    """The local shop-calibration profiles available to bind (F1).

    Reads backend/data/shop_profiles/ (CAD-as-IP: a local JSON store, no network).
    Each entry carries the slug `id` (what callers pass back as ?shop=), the
    display `name`, the shop's `region`, and a short provenance `source`.
    """
    from src.costing import list_profiles
    from src.costing.shop_profile import load_profile

    out: list[dict] = []
    for slug in list_profiles():
        try:
            p = load_profile(slug)
        except Exception:
            logger.warning("shop profile %r failed to load; skipping", slug)
            continue
        out.append({
            "id": slug,
            "name": p.name,
            "region": p.region,
            "source": p.source or None,
        })
    return out


def _resolve_shop_param(shop: Optional[str]) -> Optional[str]:
    """Resolve a caller-supplied shop (display name OR slug) to a known profile
    slug, or None when unset. Raises 400 for an unknown shop.

    SECURITY: only profiles that already exist in the local store are accepted
    (matched by slug or case-insensitive display name) — never an arbitrary
    filesystem path — so this cannot be turned into a path-traversal read.
    """
    if not shop or not shop.strip():
        return None
    from src.costing.shop_profile import _slug

    req = shop.strip()
    req_slug = _slug(req)
    for s in _available_shops():
        if req == s["id"] or req_slug == s["id"] or req.lower() == s["name"].lower():
            return s["id"]
    raise HTTPException(
        status_code=400,
        detail=(f"Unknown shop {req!r}. Available: "
                f"{[s['id'] for s in _available_shops()] or '(none)'}"),
    )


async def _resolve_governed_shop(session, user_id, shop):
    """Governed (DB) shop binding for the caller's org + slug, or None (W4 slice 2).

    When ``SHOP_LIBRARY_ENABLED`` is on AND the caller's org has a PUBLISHED shop
    profile for the requested slug in effect now, return a ShopProfile-like
    binding carrying that org's DECLARED overrides (bound as SHOP provenance by
    ``build_rate_card``). Otherwise ``None`` — the caller falls through to the
    flat-file ``resolve_shop`` allowlist, byte-identical to pre-W4. The flag is
    checked FIRST so an off flag adds no DB work and no behaviour change.
    """
    raw = (shop or "").strip()
    if not raw:
        return None
    from src.services.shop_library_service import (
        governed_shop_profile,
        resolve_shop_overrides_for,
        shop_library_enabled,
    )

    if not shop_library_enabled():
        return None
    from src.auth.org_context import resolve_org
    from src.costing.shop_profile import _slug

    org_id = await resolve_org(session, user_id)
    if not isinstance(org_id, str) or not org_id:
        return None
    slug = _slug(raw)
    payload = await resolve_shop_overrides_for(session, org_id, slug)
    if payload is None:
        return None
    return governed_shop_profile(slug, payload)


def _parse_overrides(overrides: Optional[str]) -> dict:
    """Parse the optional `overrides` Form field (a JSON object of dotted rate /
    driver keys -> numbers) into the engine's rate_overrides dict.

    This is what makes F3's "edit an assumption/driver -> the number truly
    re-costs" real: the same override surface the CLI exposes via --set / --labor-
    rate / --tooling (e.g. {"labor_rate": 40, "machine_rate.SLS": 25,
    "material_price.@polymer": 6.5, "margin": 0.25}). Values must be finite
    numbers; keys are validated against the rate card (see _validate_overrides),
    so a bad key/value is a clean 400, never a 500.
    """
    if not overrides or not overrides.strip():
        return {}
    try:
        parsed = json.loads(overrides)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="overrides must be a JSON object")
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="overrides must be a JSON object")
    if len(parsed) > _MAX_OVERRIDES:
        raise HTTPException(
            status_code=400,
            detail=f"At most {_MAX_OVERRIDES} overrides allowed",
        )
    out: dict = {}
    import math as _math

    for k, v in parsed.items():
        if not isinstance(k, str) or not k.strip():
            raise HTTPException(status_code=400, detail="override keys must be non-empty strings")
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise HTTPException(
                status_code=400,
                detail=f"override {k!r} must be a number",
            )
        if not _math.isfinite(float(v)):
            raise HTTPException(status_code=400, detail=f"override {k!r} must be finite")
        out[k.strip()] = float(v)
    return out


def _validate_overrides(overrides: dict) -> None:
    """Fail fast on unknown override keys (a clean 400 before any mesh work).

    The cost engine rebuilds the rate card inside estimate_decision; here we do a
    cheap dry-run bind so an unknown dotted key (which build_rate_card raises on)
    surfaces as a 400 instead of a 500 deep in the executor.
    """
    if not overrides:
        return
    from src.costing.rates import build_rate_card

    try:
        build_rate_card(overrides)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid override: {e}")


def _parse_qty_list(qty: str) -> list[int]:
    out: list[int] = []
    for tok in (qty or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            v = int(tok)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid quantity '{tok}' (must be an integer)",
            )
        if not (1 <= v <= _MAX_QTY):
            raise HTTPException(
                status_code=400,
                detail=f"Quantity {v} out of range [1, {_MAX_QTY}]",
            )
        out.append(v)
    if not out:
        raise HTTPException(
            status_code=400,
            detail="At least one quantity required (e.g. qty=50,5000)",
        )
    if len(out) > _MAX_QTYS:
        raise HTTPException(
            status_code=400,
            detail=f"At most {_MAX_QTYS} quantities allowed",
        )
    return out


# ──────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────
@router.post("/validate", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("60/hour;500/day")
async def validate_file(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    processes: Optional[str] = Query(
        None,
        description="Comma-separated process types to check. Leave empty for all.",
    ),
    rule_pack: Optional[str] = Query(
        None,
        description="Industry rule pack: aerospace, automotive, oil_gas, medical.",
    ),
    segmentation: Optional[str] = Query(
        None,
        description="Segmentation method: 'sam3d' for async SAM-3D (returns 202).",
    ),
    include_thickness: bool = Query(
        False,
        description=(
            "Opt-in: include the per-face wall-thickness map "
            "(wall_thickness_map) for a heatmap. Off by default to keep "
            "responses lean; the map is never persisted/cached."
        ),
    ),
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Upload an STL, STEP/STP, or IGES/IGS file and get manufacturing validation results."""
    # Validate rule pack early (before reading file bytes)
    if rule_pack:
        pack = get_rule_pack(rule_pack)
        if pack is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown rule pack '{rule_pack}'. Available: {available_rule_packs()}",
            )

    data = await _read_capped(file)
    result = await analysis_service.run_analysis(
        file_bytes=data,
        filename=file.filename or "unknown",
        processes=processes,
        rule_pack=rule_pack,
        user=user,
        session=session,
        include_thickness=include_thickness,
    )

    if segmentation == "sam3d":
        from fastapi.responses import JSONResponse

        from src.jobs.arq_backend import get_job_queue
        from src.services import job_service

        # Compute mesh hash (same algorithm as analysis_service)
        mesh_hash = analysis_service.compute_mesh_hash(data)

        # Look up the just-persisted analysis row
        analysis_id = await analysis_service.get_latest_analysis_id(
            session, user.user_id, mesh_hash,
        )
        if analysis_id is None:
            # Defensive: analysis should have been persisted by run_analysis
            raise HTTPException(
                status_code=500,
                detail="Analysis row not found after persist -- cannot enqueue SAM-3D job.",
            )

        # Save mesh blob for worker retrieval
        await job_service.save_mesh_blob(mesh_hash, data)

        # Create job (idempotent by analysis_id + sam3d)
        job = await job_service.create_sam3d_job(
            session, analysis_id, user.user_id, mesh_hash,
        )
        await session.commit()

        # Enqueue arq job
        queue = await get_job_queue()
        await queue.enqueue("sam3d", {"mesh_hash": mesh_hash}, job.ulid)

        return JSONResponse(
            status_code=202,
            content={
                "analysis_id": analysis_id,
                "job_id": job.ulid,
                "poll_url": f"/api/v1/jobs/{job.ulid}",
                "result": result,
            },
        )

    return result


# ──────────────────────────────────────────────────────────────
# Browser preview mesh (POST /validate/preview-mesh)
# ──────────────────────────────────────────────────────────────
# The Verify stage renders a dropped STL from its real geometry, but a STEP/IGES
# part cannot be parsed in the browser, so the stage historically fell back to a
# bounding-BOX envelope — a real trust hit ("my part became a box"). The backend
# already tessellates STEP/IGES to a real triangle shell (gmsh/OCC) for the DFM +
# cost engine; this endpoint streams that SAME shell back, decimated to a budget a
# WebGL canvas can render at 60fps, so the part looks like itself.
#
# Zero-egress: the CAD is parsed + tessellated in-process and the GLB is returned
# straight through the authed same-origin proxy. Nothing is written to disk, put
# in an external cache, or sent to any third party — the mesh is served from OUR
# backend only. This is a MESH-LEVEL (triangulated shell) preview, NOT B-rep /
# GD&T / PMI: it makes the part LOOK right, it does not assert analytic-surface
# semantics.
def _preview_faces_target() -> int:
    """Target triangle count for the browser shell (default 50k)."""
    try:
        return max(1000, int(os.getenv("PREVIEW_MESH_TARGET_FACES", "50000")))
    except ValueError:
        return 50000


def _preview_faces_max() -> int:
    """Hard ceiling for the browser shell (default 150k)."""
    try:
        return max(1000, int(os.getenv("PREVIEW_MESH_MAX_FACES", "150000")))
    except ValueError:
        return 150000


def _build_preview_glb(mesh, filename: str) -> tuple[bytes, int, int, bool]:
    """Decimate the tessellated shell to the browser budget and export GLB bytes.

    Reuses the engine's quadric/vertex-cluster decimation (``_decimate_to``, the
    same path ``MAX_ANALYSIS_FACES`` uses) so the preview shares the analysis
    mesh's fidelity story. Returns ``(glb_bytes, original_faces, preview_faces,
    decimated)``. Pure in-process trimesh — no disk, no network (zero-egress).
    """
    from src.analysis.context import _decimate_to

    original = int(len(mesh.faces))
    out = mesh
    decimated = False
    target = _preview_faces_target()
    if original > target:
        reduced, _strategy = _decimate_to(mesh, target)
        if reduced is not None and 0 < len(reduced.faces) < original:
            out = reduced
            decimated = True
    glb = out.export(file_type="glb")
    return bytes(glb), original, int(len(out.faces)), decimated


@router.post("/validate/preview-mesh", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("120/hour;1000/day")
async def validate_preview_mesh(
    request: Request,
    file: UploadFile = File(...),
    user: AuthedUser = Depends(require_role(Role.analyst)),
):
    """Return a decimated, browser-renderable GLB of the part's REAL tessellated
    shell so the Verify stage renders STEP/IGES/STL parts as themselves, not a box.

    Keyed by the upload the stage already holds (the same File it sends to
    ``/validate`` + ``/validate/cost``); org-scoped + session-authed like every
    other data call. Zero-egress + mesh-level caveat: see the section header.
    """
    data = await _read_capped(file)
    mesh, suffix = await _parse_mesh_async(data, file.filename or "upload")
    try:
        glb, original_faces, preview_faces, decimated = _build_preview_glb(
            mesh, file.filename or "upload"
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Preview mesh export failed for %s", file.filename)
        raise HTTPException(
            status_code=400, detail="Could not build a preview mesh for this file."
        )

    headers = {
        "X-Mesh-Original-Faces": str(original_faces),
        "X-Mesh-Preview-Faces": str(preview_faces),
        "X-Mesh-Decimated": "true" if decimated else "false",
        "X-Mesh-Source": suffix.lstrip("."),
        "Cache-Control": "no-store",
    }
    return Response(content=glb, media_type="model/gltf-binary", headers=headers)


@router.post("/validate/quick", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("60/hour;500/day")
async def validate_quick(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Quick pass/fail check — universal checks only, no process-specific analysis."""
    data = await _read_capped(file)
    return await analysis_service.run_quick_analysis(
        file_bytes=data,
        filename=file.filename or "unknown",
        user=user,
        session=session,
    )


@router.post("/validate/demo", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("10/hour")
async def validate_demo(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    processes: Optional[str] = Query(
        None,
        description="Comma-separated process types. Leave empty for all.",
    ),
    include_thickness: bool = Query(
        False,
        description=(
            "Opt-in: include the per-face wall-thickness map "
            "(wall_thickness_map) for a heatmap. Off by default to keep "
            "responses lean."
        ),
    ),
):
    """Public demo — full analysis, no auth, no persistence, tight rate limit."""
    import asyncio
    import time

    from src.analysis.base_analyzer import (
        analyze_geometry,
        decimation_issue,
        run_universal_checks,
    )
    from src.analysis.context import GeometryContext
    from src.analysis.features import detect_all as detect_features
    from src.matcher.profile_matcher import rank_processes, score_process
    from src.fixes.fix_suggester import enhance_suggestions
    from src.analysis.processes.base import get_analyzer

    data = await _read_capped(file)
    filename = file.filename or "unknown"
    suffix = Path(filename).suffix.lower()
    if suffix == ".stl":
        enforce_stl_triangle_count_cap(
            data,
            limit=demo_max_triangles(),
            limit_name="DEMO_MAX_TRIANGLES",
            status_code=413,
            subject="Public demo STL",
        )
    mesh, suffix = await _parse_mesh_async(data, filename)
    enforce_triangle_cap(
        mesh,
        limit=demo_max_triangles(),
        limit_name="DEMO_MAX_TRIANGLES",
        status_code=413,
        subject="Public demo mesh",
    )
    target_processes = _resolve_target_processes(processes)

    start = time.time()

    def _run():
        geometry = analyze_geometry(mesh)
        ctx = GeometryContext.build(mesh, geometry)
        # ctx.mesh == mesh unless build() decimated an oversize mesh; detect on
        # ctx.mesh so feature indices align with the context per-face arrays.
        features = detect_features(ctx.mesh)
        ctx.features = features
        universal_issues = run_universal_checks(mesh)
        # Honestly surface to the user when the mesh was decimated for analysis.
        dec_issue = decimation_issue(ctx)
        if dec_issue is not None:
            universal_issues.append(dec_issue)
        process_scores = []
        for proc in target_processes:
            analyzer = get_analyzer(proc)
            if analyzer is None:
                continue
            try:
                proc_issues = analyzer.analyze(ctx)
            except Exception:
                logger.exception("Demo analyzer failed for %s", proc.value)
                continue
            ps = score_process(proc_issues, geometry, proc)
            process_scores.append(ps)
        return geometry, ctx, features, universal_issues, process_scores

    timeout = _analysis_timeout_sec()
    loop = asyncio.get_event_loop()
    try:
        geometry, ctx, features, universal_issues, process_scores = (
            await asyncio.wait_for(
                loop.run_in_executor(None, _run),
                timeout=timeout,
            )
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"Analysis exceeded {timeout:.0f}s timeout.",
        )

    duration_ms = round((time.time() - start) * 1000, 1)

    result = AnalysisResult(
        filename=file.filename or "unknown",
        file_type=suffix.lstrip("."),
        geometry=geometry,
        segments=ctx.segments,
        universal_issues=universal_issues,
        process_scores=process_scores,
        analysis_time_ms=duration_ms,
    )
    ranked = rank_processes(result)
    if ranked and ranked[0].score > 0:
        result.best_process = ranked[0].process
    result = enhance_suggestions(result)

    resp = _to_response(
        result,
        features,
        wall_thickness=ctx.wall_thickness if include_thickness else None,
        wall_thickness_decimation=(ctx.metadata or {}).get("decimation")
        if include_thickness else None,
    )
    resp["demo"] = True
    return resp


async def _run_cost_decision(
    *,
    file: UploadFile,
    qty: str,
    region: Optional[str],
    cavities: int,
    complexity: str,
    material_class: str,
    shop: Optional[str] = None,
    overrides: Optional[str] = None,
    owned_processes: Optional[str] = None,
    tolerance_class: Optional[str] = None,
    units: Optional[str] = None,
    user: Optional[AuthedUser] = None,
    session: Optional[AsyncSession] = None,
) -> dict:
    """Shared should-cost / make-vs-buy compute for the authed and public-demo
    cost routes.

    Validates options (fail fast), parses the mesh, runs the cost engine off
    the event loop, emits exactly one structured outcome event, and returns the
    glass-box decision dict — or raises a clean structured 400 (GEOMETRY_INVALID)
    / 504 (timeout). IP-local: the CAD is parsed, costed, and discarded
    in-process — nothing is persisted (no DB session, no mesh blob) and no
    network call is made (the costing layer opens zero sockets). The Σ=unit_cost
    invariant and every driver/assumption provenance tag come straight from the
    costing layer, so both routes carry identical guarantees.

    `shop` binds a per-shop calibration profile (F1): the response then carries
    the SHOP-calibrated number, SHOP-tagged drivers/assumptions, and the
    "calibrated to shop X" note. `overrides` threads ad-hoc rate/driver overrides
    (F3): the engine re-costs against them and tags the touched lines USER. When
    a shop is bound and the caller did not explicitly pass a region, the shop's
    own region is used.
    """
    import asyncio

    t0 = time.perf_counter()

    # Tracing (opt-in, no-op when off): stamp the already-bound request id onto
    # the active server span so a trace correlates with the structured logs. No
    # new PII — request_id is the same opaque correlation id RequestIDMiddleware
    # already bound to structlog.
    if tracing.is_active():
        _rid = structlog.contextvars.get_contextvars().get("request_id")
        tracing.set_current_attributes(**{"cadverify.request_id": _rid})

    # ---- validate options (fail fast, before reading bytes) --------------
    quantities = _parse_qty_list(qty)
    if complexity not in _COMPLEXITY:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown complexity '{complexity}'. Use one of {sorted(_COMPLEXITY)}",
        )
    if material_class not in _MATERIAL_CLASSES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown material_class '{material_class}'. Use one of {sorted(_MATERIAL_CLASSES)}",
        )
    if cavities < 1:
        raise HTTPException(status_code=400, detail="cavities must be >= 1")
    # tolerance_class: None => unset (DEFAULT "standard", byte-identical); a
    # supplied value must be one of the documented classes and is treated USER.
    tolerance_is_user = tolerance_class is not None
    if tolerance_class is not None and tolerance_class not in _TOLERANCE_CLASSES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown tolerance_class '{tolerance_class}'. Use one of {sorted(_TOLERANCE_CLASSES)}",
        )
    effective_tolerance = tolerance_class or "standard"
    # region: None => unset (DEFAULT US, and a bound shop's region may win); a
    # supplied region must be one of the documented vectors and is treated USER.
    region_is_user = region is not None
    if region is not None and region not in _REGIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown region '{region}'. Use one of {sorted(_REGIONS)}",
        )
    effective_region = region or "US"
    # units: None => unset (DEFAULT mm, byte-identical, silent as it always was); a
    # supplied value must be a known source unit and is treated USER. The DECLARATION
    # is what drives the exactly-once mm rescale at the parse seam below.
    units_is_user = units is not None
    if units is not None and units not in _SOURCE_UNITS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown units '{units}'. Use one of {sorted(_SOURCE_UNITS)}",
        )
    effective_units = units or "mm"
    # ── Shop binding: governed (DB) profile first, else the flat-file allowlist ──
    # W4 slice 2: when SHOP_LIBRARY_ENABLED and the caller's org has a PUBLISHED
    # shop profile for this slug in effect now, bind its DECLARED overrides as
    # SHOP provenance (the slug need not exist as a flat file). Flag off / no
    # governed profile for the slug => byte-identical: the flat-file resolve_shop
    # path (and its 400 on an unknown shop) is used unchanged.
    governed_shop = None
    if user is not None and session is not None:
        governed_shop = await _resolve_governed_shop(session, user.user_id, shop)
    if governed_shop is not None:
        shop_slug = governed_shop.slug           # string slug for logging / params_hash
        shop_binding = governed_shop             # ShopProfile-like object bound to engine
    else:
        shop_slug = _resolve_shop_param(shop)    # 400 on unknown shop
        shop_binding = shop_slug
    rate_overrides = _parse_overrides(overrides)  # 400 on bad JSON/value
    _validate_overrides(rate_overrides)           # 400 on unknown key (fail fast)
    owned = _parse_owned_processes(owned_processes)  # 400 on unknown process id

    # Span 1/4 — mesh parse: read the upload, tessellate/parse to a trimesh,
    # and rescale into mm. No-op context when tracing is off.
    with tracing.span("cost.parse_mesh") as _sp_parse:
        data = await _read_capped(file)  # 413 on size, 400 on empty
        mesh, suffix = await _parse_mesh_async(  # 400/413/501, 504 on parse timeout
            data, file.filename or "unknown"
        )
        # ── B5 units landmine: rescale the mesh into mm EXACTLY ONCE, here at the parse
        # seam, BEFORE any geometry/DFM/cost extraction. mm (default/unset) => the SAME
        # mesh object untouched => byte-identical; inch => a ×25.4 copy so volume
        # (×25.4³ ≈ 16,387×), area, bbox and wall thickness all stay coherent and every
        # downstream consumer (DFM, machine-fit, cost, analogy) reads the ONE real part.
        # This is the SINGLE geometry-scaling site: nothing downstream rescales
        # (EstimateOptions.units is declarative only), so there is exactly one
        # conversion, never a double.
        from src.costing.units import scale_mesh_to_mm
        mesh = scale_mesh_to_mm(mesh, effective_units)
        tracing.set_attr(_sp_parse, "cadverify.file.suffix", suffix)
        tracing.set_attr(_sp_parse, "cadverify.file.bytes", len(data))
        tracing.set_attr(_sp_parse, "cadverify.units", effective_units)

    from src.costing import estimate_decision, EstimateOptions, report_to_dict

    options = EstimateOptions(
        quantities=quantities,
        material_class=material_class,
        material_class_is_user=material_class != "polymer",
        region=effective_region,
        region_is_user=region_is_user,
        shop=shop_binding,
        rate_overrides=rate_overrides,
        n_cavities=cavities,
        n_cavities_is_user=cavities != 1,
        complexity=complexity,
        complexity_is_user=complexity != "moderate",
        owned_processes=owned,
        tolerance_class=effective_tolerance,
        tolerance_class_is_user=tolerance_is_user,
        units=effective_units,
        units_is_user=units_is_user,
    )

    # ---- MEASURED confidence band from a persisted org calibration (W5) ----
    # When the caller's org has a tuned calibration bundle built from REAL
    # held-out residuals, bind its ResidualModel so every estimate carries the
    # MEASURED empirical CI (validated=True comes ONLY from real residuals — the
    # honesty seam is inside the costing layer, unchanged). No bundle => the
    # residual_model stays None => the CI is the stated assumption band,
    # byte-identical to pre-W5 behaviour. Pure local disk read (no network); the
    # only added work is the org lookup, which never touches the response bytes.
    # The demo route passes no user/session, so it stays untouched and IP-local.
    # ── P1 analogy feed (loaded below only when the ensemble is on) ──────────
    # The caller org's ground-truth records, passed to ``ensemble_estimate`` so
    # the analogy-to-quote k-NN member can measure geometric distance to THIS
    # part. None => the analogy is never engaged and the band is byte-identical
    # (demo route, flag off, or an unprovisioned session).
    analogy_records = None
    if user is not None and session is not None:
        from src.auth.org_context import resolve_org
        from src.services.groundtruth_service import load_served_calibration

        cal_org_id = await resolve_org(session, user.user_id)
        # resolve_org's contract is Optional[str]; guard on the concrete type so
        # a mocked/unprovisioned session (no real org_id) is treated as "no
        # calibration" — leaving behaviour byte-identical to pre-W5.
        if isinstance(cal_org_id, str) and cal_org_id:
            # Tracing: stamp the resolved org id onto the server span (opaque
            # identifier already in scope, not new PII). No-op when off.
            tracing.set_current_attributes(**{"cadverify.org_id": cal_org_id})
            # ── Phase C: machine-inventory verification feed ─────────────────
            # Resolve the caller org's DECLARED owned machines + shop-level
            # secondary ops + THIS part's DECLARED service environment, and thread
            # them into the estimate so the decision report carries a machine-
            # grounded §0 makeability verdict and a PASSING owned machine re-costs
            # its process at its OWN marginal rate. An org with NO declared
            # machines AND NO declared environment leaves options.inventory ()
            # + service_environment None → the served response is BYTE-IDENTICAL
            # (the only added work is org-scoped SELECTs that never touch the
            # response bytes). Best-effort: a load failure must never break the
            # live decision — the machine lens simply stays absent.
            try:
                from src.services.analysis_service import (
                    compute_mesh_hash as _compute_mesh_hash,
                )
                from src.services.machine_inventory_service import (
                    load_org_inventory,
                    load_shop_caps,
                )
                from src.services.part_context_service import get_context

                _inventory = await load_org_inventory(session, cal_org_id)
                if _inventory:
                    options.inventory = tuple(_inventory)
                    options.shop_caps = await load_shop_caps(session, cal_org_id)
                _ctx = await get_context(
                    session, cal_org_id, _compute_mesh_hash(data)
                )
                _env = (
                    getattr(_ctx, "service_environment", None)
                    if _ctx is not None else None
                )
                if _env:
                    options.service_environment = _env
            except Exception:
                logger.warning(
                    "machine-inventory feed failed for org %s; decision proceeds "
                    "without the machine lens", cal_org_id, exc_info=True,
                )

            residual_model, calibration = load_served_calibration(cal_org_id)
            if residual_model is not None:
                options.residual_model = residual_model
            # Correct the served point by the per-process calibration factor so
            # the MEASURED band is centred coherently with its residuals (they
            # were measured on the CORRECTED prediction). None (no real ground
            # truth) => point stays uncorrected => byte-identical to pre-W5.
            if calibration is not None:
                options.calibration = calibration

            # ── W4 governed rate library ────────────────────────────────────
            # If RATE_LIBRARY_ENABLED is on AND the org has a PUBLISHED rate card
            # in effect now, use it as the base DEFAULT table under shop/user
            # overrides. Flag off / no published card => None => hardcoded
            # RATE_CARD_V0 => byte-identical to pre-W4. A governed card is a table
            # of DEFAULT assumptions — provenance stays DEFAULT, never validated.
            from src.services.rate_library_service import (
                resolve_rate_table_for_org,
            )

            base_table = await resolve_rate_table_for_org(session, cal_org_id)
            if base_table is not None:
                options.base_rate_table = base_table

            # ── W4 governed materials library ───────────────────────────────
            # If MATERIAL_LIBRARY_ENABLED is on AND the org has a PUBLISHED
            # materials catalog in effect now, OVERLAY its DECLARED per-kg prices
            # onto the base table's ``material_prices`` (the governed catalog wins
            # per material key). Flag off / no published catalog / empty catalog
            # => no overlay => the base table's own material_prices are used
            # unchanged => byte-identical to pre-W4. A governed catalog is DECLARED
            # default prices — provenance stays DEFAULT, never validated.
            import copy as _copy

            from src.costing.rates import RATE_CARD_V0 as _RATE_CARD_V0
            from src.services.material_library_service import (
                resolve_material_overrides_for,
            )

            mat_payload = await resolve_material_overrides_for(session, cal_org_id)
            mat_prices = (mat_payload or {}).get("material_prices") or {}
            mat_defs = (mat_payload or {}).get("materials") or {}
            if mat_prices or mat_defs:
                # Deep-copy before mutating: base_table may be the rate-library
                # cache's shared payload (returned by reference) — never corrupt it.
                base = _copy.deepcopy(
                    options.base_rate_table
                    if options.base_rate_table is not None
                    else _RATE_CARD_V0
                )
                if mat_prices:
                    merged = dict(base.get("material_prices") or {})
                    merged.update(mat_prices)
                    base["material_prices"] = merged
                if mat_defs:
                    merged_defs = dict(base.get("materials") or {})
                    merged_defs.update(mat_defs)
                    base["materials"] = merged_defs
                options.base_rate_table = base

            # ── P1 analogy-to-quote k-NN feed (org-scoped, cheap query) ──────
            # When the ensemble is enabled, load THIS org's ground-truth records
            # so the independent analogy member can contribute to the POINT via
            # BLUE. Loaded here (off the compute executor) as a single org-scoped
            # SELECT; the analogy itself filters to REAL (stand_in=False)
            # same-process neighbours that carry geometry and ABSTAINS otherwise,
            # so an org with no usable records leaves the band byte-identical.
            from src.costing.ensemble import ensemble_enabled as _ens_on
            if _ens_on():
                from src.services.groundtruth_service import (
                    load_org_ground_truth,
                )

                analogy_records = await load_org_ground_truth(session, cal_org_id)

    # ---- OPT-IN assumption-ensemble uncertainty band (Moat P1) -------------
    # Behind COST_ENSEMBLE_ENABLED (default OFF). When on, we ALSO run the same
    # estimator under K deterministic rate-card perturbations and attach the
    # HONEST spread as a NEW top-level `uncertainty` key. When off we never
    # construct it and never add the key -> the response is BYTE-IDENTICAL.
    # It reuses the SAME estimate inputs and runs inside the SAME off-loop
    # executor as the point estimate, so the (opt-in) latency never blocks the
    # event loop. It rides the RESPONSE only; the persisted result_json and the
    # dedup params_hash are untouched (the band is derived, not an input).
    from src.costing.ensemble import ensemble_enabled, ensemble_estimate

    # Gated on an authenticated caller too: the public demo route (no user) is
    # IP-local + ephemeral by contract and stays byte-identical regardless of
    # the flag — the band is an authed-product feature.
    run_ensemble = ensemble_enabled() and user is not None

    # Snapshot the OTel context on the event loop so the DFM / should-cost spans
    # created inside the executor thread nest under the compute span (contextvars
    # do not cross the thread boundary on their own). No-op / None when tracing
    # is off. _otel_ctx is captured below, inside the cost.compute span.
    _otel_ctx = None

    def _run():
        _otel_tok = tracing.attach_context(_otel_ctx)
        try:
            # Span 2/4 — DFM / geometry analysis (the cost engine's mesh pass).
            with tracing.span("cost.dfm_analysis") as _sp_dfm:
                result, m, features = _run_cost_engine(mesh, file.filename or "unknown")
                geo = result.geometry if isinstance(result.geometry, dict) else {}
                tracing.set_attr(_sp_dfm, "cadverify.face_count", geo.get("face_count"))
            # Span 3/4 — should-cost decision (make-vs-buy costing).
            with tracing.span("cost.should_cost") as _sp_cost:
                rep = estimate_decision(result, m, features, options)
                tracing.set_attr(_sp_cost, "cadverify.status", rep.status)
            unc = None
            if run_ensemble and rep.status != "GEOMETRY_INVALID":
                with tracing.span("cost.ensemble"):
                    unc = _run_ensemble_band(
                        result, m, features, options, analogy_records
                    )
            return rep, unc
        finally:
            tracing.detach_context(_otel_tok)

    def _run_ensemble_band(result, m, features, options, analogy_records):
        # ── P1 analogy query geometry ────────────────────────────────────
        # THIS part's MEASURED cost-drivers (analogy_estimator.FEATURE_KEYS),
        # extracted by the SAME engine extraction the records were populated
        # with. Only computed when the org actually has records to match
        # against — otherwise geometry stays None and the analogy is never
        # engaged (band byte-identical). Best-effort: an extraction failure
        # leaves geometry None (analogy abstains), never fails the estimate.
        geom_features = None
        if analogy_records:
            try:
                from src.costing.drivers import extract_drivers

                dr = extract_drivers(result.geometry, m, features)
                if (dr.volume_cm3 > 0 and dr.surface_area_cm2 > 0
                        and dr.max_bbox_mm > 0 and dr.face_count > 0):
                    geom_features = {
                        "volume_cm3": float(dr.volume_cm3),
                        "surface_area_cm2": float(dr.surface_area_cm2),
                        "max_bbox_mm": float(dr.max_bbox_mm),
                        "face_count": int(dr.face_count),
                    }
            except Exception:
                geom_features = None
        # Reuse the org's W5 residual_model when one was bound above; else
        # None -> the honest pre-data assumption spread (validated=False).
        # records + geometry activate the analogy-to-quote k-NN member: it
        # contributes to the POINT via BLUE ONLY when it finds >= min_real
        # REAL same-process neighbours WITH geometry; otherwise it ABSTAINS
        # and the band is byte-identical to the assumption spread. The
        # measured residual path (validated) is unchanged and still wins.
        ens = ensemble_estimate(
            result, m, features, options,
            residual_model=getattr(options, "residual_model", None),
            records=analogy_records,
            geometry=geom_features,
        )
        return ens.to_dict()

    timeout = _analysis_timeout_sec()
    loop = asyncio.get_event_loop()
    # Parent span for the off-loop compute; capture the OTel context INSIDE it so
    # the executor-thread DFM / should-cost child spans nest here. No-op when off.
    with tracing.span("cost.compute"):
        _otel_ctx = tracing.capture_context()
        try:
            report, uncertainty = await asyncio.wait_for(
                loop.run_in_executor(None, _run), timeout=timeout
            )
        except asyncio.TimeoutError:
            # Bounded compute that ran over budget — structured warning, then 504.
            slog.warning(
                "cost_timeout",
                file_sha8=hashlib.sha256(data).hexdigest()[:8],
                suffix=suffix,
                n_qty=len(quantities),
                region=effective_region,
                material_class=material_class,
                shop=shop_slug,
                timeout_sec=round(timeout, 1),
                duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
            # Observability: bounded compute over budget is an error outcome.
            record_cost_decision("error")
            raise HTTPException(
                status_code=504,
                detail=f"Cost analysis exceeded {timeout:.0f}s timeout.",
            )

    # One structured outcome event per costed request. status carries OK vs
    # GEOMETRY_INVALID, so this single emit covers both the success and the
    # clean-refusal branch below. No CAD/PII: the file is hashed, only
    # aggregate geometry (face_count) and the decision summary are logged.
    geo = report.geometry if isinstance(report.geometry, dict) else {}
    slog.info(
        "cost_estimate",
        file_sha8=hashlib.sha256(data).hexdigest()[:8],
        suffix=suffix,
        face_count=geo.get("face_count"),
        watertight=geo.get("watertight"),
        status=report.status,
        make_now=(report.decision.make_now_process if report.decision else None),
        crossover_qty=(report.decision.crossover_qty if report.decision else None),
        n_qty=len(quantities),
        region=effective_region,
        material_class=material_class,
        shop=shop_slug,
        duration_ms=round((time.perf_counter() - t0) * 1000, 1),
    )

    # Observability: the compute finished, so record its duration (both outcomes)
    # and the decision outcome. Real timings/counts only; no PII enters a label.
    observe_analysis_duration(time.perf_counter() - t0)

    if report.status == "GEOMETRY_INVALID":
        # G1 surfaced cleanly as a structured 400 (errors.py passes the
        # dict-with-code through unchanged), carrying the measured geometry
        # summary + repair reason so the buyer sees *why*.
        record_cost_decision("geometry_invalid")
        raise HTTPException(
            status_code=400,
            detail={
                "code": "GEOMETRY_INVALID",
                "message": report.reason,
                "geometry": report.geometry,
                "doc_url": "https://docs.cadverify.com/errors#GEOMETRY_INVALID",
            },
        )

    record_cost_decision("ok")
    # Span 4/4 — serialize the glass-box decision to the response dict.
    with tracing.span("cost.serialize"):
        result_dict = report_to_dict(report)

    # ---- persist for authenticated callers (Phase 2 gap #3) --------------
    # Turns the flagship decision into a durable artifact (list/export/share/
    # compare). The /demo route passes no user/session, so it stays IP-local
    # and ephemeral — honest to its docstring. Behind COST_PERSIST_ENABLED.
    if user is not None and session is not None:
        from src.services.cost_decision_service import (
            compute_params_hash,
            cost_persist_enabled,
            persist_cost_decision,
            record_persist_failure,
        )

        if cost_persist_enabled():
            from src import __version__ as _cv_version
            from src.services.analysis_service import compute_mesh_hash

            params_hash = compute_params_hash(
                quantities=quantities,
                region=region,
                cavities=cavities,
                complexity=complexity,
                material_class=material_class,
                shop=shop_slug,
                overrides=rate_overrides,
            )
            mesh_hash = compute_mesh_hash(data)
            try:
                saved = await persist_cost_decision(
                    session,
                    user,
                    mesh_hash=mesh_hash,
                    params_hash=params_hash,
                    engine_version=_cv_version,
                    filename=file.filename or "unknown",
                    file_type=suffix.lstrip("."),
                    result_json=result_dict,
                )
                # Non-destructive: the decision JSON is unchanged; we only add a
                # pointer to the saved artifact so the caller can open/export it.
                result_dict = dict(result_dict)
                result_dict["saved"] = {
                    "id": saved.ulid,
                    "url": f"/api/v1/cost-decisions/{saved.ulid}",
                }
            except Exception as exc:
                # Persistence must never break the live decision the buyer
                # sees (graceful degrade, unchanged) — but the failure must
                # be observable, not silent: warning log + usage_events row.
                await record_persist_failure(
                    session, user, mesh_hash=mesh_hash, error=exc
                )

    # RESPONSE-ONLY: attach the ensemble band (when the flag produced one) after
    # persistence so the stored result_json stays byte-identical to the flag-off
    # path. The block carries the ensemble's own honest labels verbatim
    # (method/validated/label/disagreement_cov); `validated` is measured ONLY
    # when a real residual_model produced measured bands. When the flag is off
    # `uncertainty` is None and the key is never added.
    if uncertainty is not None:
        result_dict = dict(result_dict)
        result_dict["uncertainty"] = uncertainty

    return result_dict


@router.post("/validate/cost", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("60/hour;500/day")
async def validate_cost(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    qty: str = Form("50,5000", description="Comma list of quantities, e.g. 50,5000"),
    region: Optional[str] = Form(
        None, description="US|EU|MX|CN|IN|SA (unset => US, or a bound shop's region)"
    ),
    cavities: int = Form(1, description="Formative tooling cavity count (DEFAULT 1)"),
    complexity: str = Form(
        "moderate", description="simple|moderate|complex|very_complex"
    ),
    material_class: str = Form(
        "polymer", description="polymer|aluminum|steel|stainless|titanium"
    ),
    shop: Optional[str] = Form(
        None,
        description="Per-shop calibration profile id or name (see GET /shops). "
                    "Binds the shop's real rates -> SHOP-tagged drivers + number.",
    ),
    overrides: Optional[str] = Form(
        None,
        description='JSON object of ad-hoc rate/driver overrides, e.g. '
                    '{"labor_rate": 40, "machine_rate.SLS": 25}. Tagged USER; '
                    'enables a true server re-cost on an edited assumption.',
    ),
    owned_processes: Optional[str] = Form(
        None,
        description="Comma-separated engine process ids the org OWNS in-house, "
                    "e.g. cnc_3axis,injection_molding. Costs those at the MARGINAL "
                    "machine rate (owned capital is sunk) — the make-it-ourselves "
                    "path. Tagged USER; unset => nothing owned (fully-loaded).",
    ),
    tolerance_class: Optional[str] = Form(
        None,
        description="Declared part tolerance: standard|precision|tight (unset => "
                    "standard, byte-identical). Applies an honest machining "
                    "multiplier to the tolerance-sensitive CNC terms (finish pass "
                    "+ inspection) and widens the confidence band. STATED input, "
                    "not measured GD&T; the factor is a DEFAULT assumption.",
    ),
    units: Optional[str] = Form(
        None,
        description="Declared CAD source units: mm|inch (unset => mm, byte-identical). "
                    "STL/mesh files carry NO units; an inch-authored part read as mm "
                    "mis-costs by ~16,000× (×25.4³ volume). Declaring inch scales the "
                    "mesh ×25.4 into mm ONCE before geometry/DFM/cost so the whole "
                    "decision reads the real part. STATED input; a plausibility WARNING "
                    "still fires if the mm-interpreted size looks wrong.",
    ),
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Explainable make-vs-buy should-cost decision for an uploaded STL/STEP part.

    IP-local compute: the CAD is parsed and costed in-process and no network call
    is made (the costing layer opens zero sockets). The glass-box decision is
    then PERSISTED for the authenticated user (Phase 2 gap #3, behind
    COST_PERSIST_ENABLED) so it can be listed, PDF/JSON/CSV exported, shared, and
    compared — the response carries a `saved: {id, url}` pointer to that artifact.
    Only the decision (geometry summary + estimates + assumptions) is stored; the
    raw CAD blob is never retained. Broken geometry is surfaced as a clean
    structured 400 (GEOMETRY_INVALID), never a 500.

    Pass `shop` to calibrate the number to a specific shop's real rates (the
    response carries SHOP-tagged drivers/assumptions + a "calibrated to shop X"
    note); pass `overrides` to re-cost against ad-hoc rate/driver edits.
    """
    return await _run_cost_decision(
        file=file,
        qty=qty,
        region=region,
        cavities=cavities,
        complexity=complexity,
        material_class=material_class,
        shop=shop,
        overrides=overrides,
        owned_processes=owned_processes,
        tolerance_class=tolerance_class,
        units=units,
        user=user,
        session=session,
    )


@router.post("/validate/cost/demo", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("240/hour")
async def validate_cost_demo(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    qty: str = Form("50,5000", description="Comma list of quantities, e.g. 50,5000"),
    region: Optional[str] = Form(
        None, description="US|EU|MX|CN|IN|SA (unset => US, or a bound shop's region)"
    ),
    cavities: int = Form(1, description="Formative tooling cavity count (DEFAULT 1)"),
    complexity: str = Form(
        "moderate", description="simple|moderate|complex|very_complex"
    ),
    material_class: str = Form(
        "polymer", description="polymer|aluminum|steel|stainless|titanium"
    ),
    shop: Optional[str] = Form(
        None,
        description="Per-shop calibration profile id or name (see GET /shops).",
    ),
    overrides: Optional[str] = Form(
        None,
        description='JSON object of ad-hoc rate/driver overrides (tagged USER).',
    ),
    tolerance_class: Optional[str] = Form(
        None,
        description="Declared part tolerance: standard|precision|tight (unset => "
                    "standard, byte-identical). Honest machining multiplier on the "
                    "tolerance-sensitive CNC terms + band widening. STATED input.",
    ),
    units: Optional[str] = Form(
        None,
        description="Declared CAD source units: mm|inch (unset => mm, byte-identical). "
                    "Inch-authored meshes are scaled ×25.4 into mm ONCE before costing; "
                    "otherwise an inch part read as mm mis-costs by ~16,000×.",
    ),
):
    """Public demo of the should-cost / make-vs-buy decision — NO auth.

    Mirrors POST /validate/cost exactly in security posture except it drops the
    analyst role gate: kill-switch dep only, tight public rate limit (same as
    /validate/demo), no DB/persistence, zero network egress. Reuses the same
    parse + cost-engine + serialization path so STL and STEP both work and every
    invariant (Σ=unit_cost, provenance, G1 broken-geometry -> clean 400
    GEOMETRY_INVALID) holds identically. Supports the same `shop` calibration and
    `overrides` re-cost params. Lets a local browser user get a costing decision
    with no API key while the CAD never leaves the machine.
    """
    return await _run_cost_decision(
        file=file,
        qty=qty,
        region=region,
        cavities=cavities,
        complexity=complexity,
        material_class=material_class,
        shop=shop,
        overrides=overrides,
        tolerance_class=tolerance_class,
        units=units,
    )


@router.post("/validate/repair", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("60/hour;500/day")
async def validate_repair(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    processes: Optional[str] = Query(
        None,
        description="Comma-separated process types for re-analysis. Leave empty for all.",
    ),
    rule_pack: Optional[str] = Query(
        None,
        description="Industry rule pack: aerospace, automotive, oil_gas, medical.",
    ),
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Upload an STL, STEP/STP, or IGES/IGS file, attempt mesh repair, and get before/after analysis."""
    if rule_pack:
        pack = get_rule_pack(rule_pack)
        if pack is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown rule pack '{rule_pack}'. Available: {available_rule_packs()}",
            )

    data = await _read_capped(file)
    return await repair_service.repair_mesh(
        file_bytes=data,
        filename=file.filename or "unknown",
        processes=processes,
        rule_pack=rule_pack,
        user=user,
        session=session,
    )


@router.get("/rule-packs")
@limiter.limit("60/hour;500/day")
async def list_rule_packs(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
):
    """List available industry rule packs."""
    packs = []
    for name in available_rule_packs():
        p = get_rule_pack(name)
        if p:
            packs.append({
                "name": p.name,
                "version": p.version,
                "description": p.description,
                "override_count": len(p.overrides),
                "mandatory_issue_count": len(p.mandatory_issues),
            })
    return {"rule_packs": packs}


@router.get("/processes")
@limiter.limit("60/hour;500/day")
async def list_processes(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
):
    return {"processes": get_all_processes()}


@router.get("/shops")
@limiter.limit("60/hour;500/day")
async def list_shops(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
):
    """Per-shop calibration profiles available to bind on POST /validate/cost (F1).

    The UI lists these so a buyer can pick a shop and re-cost against its real
    rates; each `id` is what you pass back as the `shop` form field. Local store
    only (CAD-as-IP) — no network. Default (no shop) stays a generic should-cost.
    """
    return {"shops": _available_shops()}


@router.get("/materials")
@limiter.limit("60/hour;500/day")
async def list_materials(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
):
    return {
        "materials": [
            {
                "name": m.name,
                "processes": [p.value for p in m.process_types],
                "min_wall_mm": m.min_wall_thickness,
                "tensile_mpa": m.tensile_strength,
                "cost_per_kg_usd": m.cost_per_kg,
                "notes": m.notes,
            }
            for m in MATERIALS
        ]
    }


@router.get("/machines")
@limiter.limit("60/hour;500/day")
async def list_machines(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
):
    return {
        "machines": [
            {
                "name": m.name,
                "manufacturer": m.manufacturer,
                "process": m.process_type.value,
                "build_volume_mm": list(m.build_volume),
                "min_layer_mm": m.min_layer_height,
                "materials": m.materials,
                "notes": m.notes,
            }
            for m in MACHINES
        ]
    }


# ──────────────────────────────────────────────────────────────
# Serialization
# ──────────────────────────────────────────────────────────────
def _to_response(
    result: AnalysisResult,
    features: list | None = None,
    pack=None,
    *,
    wall_thickness=None,
    wall_thickness_decimation=None,
) -> dict:
    """Serialize an AnalysisResult to the API response dict.

    ``wall_thickness`` is opt-in: pass ``ctx.wall_thickness`` (the per-face
    array) ONLY when a caller has explicitly requested the heatmap, so the
    default response stays lean and unchanged. When present it is serialized
    under ``wall_thickness_map``.
    """
    resp = {
        "filename": result.filename,
        "file_type": result.file_type,
        "overall_verdict": result.overall_verdict,
        "best_process": result.best_process.value if result.best_process else None,
        "analysis_time_ms": result.analysis_time_ms,
        "geometry": {
            "vertices": result.geometry.vertex_count,
            "faces": result.geometry.face_count,
            "volume_mm3": round(result.geometry.volume, 1),
            "surface_area_mm2": round(result.geometry.surface_area, 1),
            "bounding_box_mm": [round(d, 1) for d in result.geometry.bounding_box.dimensions],
            "is_watertight": result.geometry.is_watertight,
            "is_manifold": result.geometry.is_manifold,
            "center_of_mass": [
                round(c, 2) if c is not None else None
                for c in result.geometry.center_of_mass
            ],
            "units": result.geometry.units,
        },
        "segments": [
            {
                "id": s.segment_id,
                "type": s.feature_type.value,
                "face_count": len(s.face_indices),
                "centroid": [round(c, 2) for c in s.centroid],
                "confidence": round(s.confidence, 2),
            }
            for s in result.segments
        ],
        "features": [
            {
                "kind": f.kind.value,
                "face_count": len(f.face_indices),
                "centroid": [round(c, 3) for c in f.centroid],
                "radius": round(f.radius, 3) if f.radius is not None else None,
                "depth": round(f.depth, 3) if f.depth is not None else None,
                "area": round(f.area, 3) if f.area is not None else None,
                "confidence": round(f.confidence, 3),
            }
            for f in (features or [])
        ],
        "universal_issues": [_issue_to_dict(i) for i in result.universal_issues],
        "process_scores": [
            {
                "process": ps.process.value,
                "score": ps.score,
                "verdict": ps.verdict,
                "recommended_material": ps.recommended_material,
                "recommended_machine": ps.recommended_machine,
                "estimated_cost_factor": ps.estimated_cost_factor,
                # The analyzer's standards bibliography — the AMS/ASTM/ISO/NADCA/
                # vendor sources behind this process's thresholds. Declared on
                # every ProcessAnalyzer but previously never serialized; surfaced
                # here so the audit trail is inspectable.
                "standards": _analyzer_standards(ps.process),
                "issues": [_issue_to_dict(i) for i in ps.issues],
            }
            for ps in sorted(result.process_scores, key=lambda s: s.score, reverse=True)
        ],
        "priority_fixes": get_priority_fixes(result),
    }
    if pack:
        resp["rule_pack"] = {
            "name": pack.name,
            "version": pack.version,
        }
    # Include tolerance data when present on the AnalysisResult
    if hasattr(result, "tolerances") and result.tolerances is not None:
        from src.services.tolerance_service import tolerance_report_to_dict

        resp["tolerances"] = tolerance_report_to_dict(result.tolerances)
    # Opt-in per-face wall-thickness heatmap. Only serialized when the caller
    # explicitly passed the array (query-param gated upstream), keeping the
    # default response lean.
    if wall_thickness is not None:
        from src.analysis.serialization import serialize_wall_thickness

        resp["wall_thickness_map"] = serialize_wall_thickness(
            wall_thickness, decimation=wall_thickness_decimation
        )
    return resp


def _analyzer_standards(process) -> list[str]:
    """The standards bibliography declared by a process's analyzer (or [])."""
    from src.analysis.processes.base import get_analyzer

    analyzer = get_analyzer(process)
    return list(getattr(analyzer, "standards", []) or []) if analyzer else []


def _issue_to_dict(issue: Issue) -> dict:
    """Serialize an Issue for the API response.

    Delegates to the canonical ``serialize_issue`` (shared with the cost-view
    DFM-blocker serializer) so the two never drift. That serializer carries the
    untruncated affected-face list (up to a documented cap, with an honest
    truncation flag), the structured ``citation`` object, and the ``scope``
    marker for unlocalizable findings.
    """
    from src.analysis.serialization import serialize_issue

    return serialize_issue(issue)
