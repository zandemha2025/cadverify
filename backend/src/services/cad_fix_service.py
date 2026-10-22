"""Fixes ScaleCAD applies itself to a COPY of a part's stored source CAD.

Two entry points, both organization-scoped through the stored source artifact
(``source_artifact_service``), mirroring the mesh repair endpoint
(``repair_service``):

* ``fix_options``: per finding of the part's saved check, whether ScaleCAD has a
  fix it can apply to this file itself, which one, and with what parameters.
* ``apply_fix``: makes ONE fix on a copy in an isolated, hard-killable CAD
  worker, re-checks the copy in the same request through
  ``analysis_service.run_analysis`` (the pipeline behind ``POST /validate``),
  prices both, and returns before/after evidence plus the fixed file. The
  original bytes are never written; the copy is a new part (its own SHA-256)
  and is linked to its parent by a ``derived-from.json`` record stored next to
  its source artifact (no schema change).

What ships, and why only this (round-6 spike on the repo's real parts; numbers
in the coordinator report):

* ``drain_holes`` (STEP/IGES via OCC cut, STL via manifold3d): opened every
  sealed cavity it planned, re-checked clean.
* ``fillet_inside_corners`` (STEP/IGES via OCC fillet): reliable on straight
  inside edges; small radii on circular edges and on large parts can still read
  as sharp, or push the copy's tessellation past the engine's analysis budget.
  The re-check catches both and the result says so (``outcome`` and
  ``verification.comparable``); it is never shown as fixed then.
* ``heal_brep``: OCC sewing/healing for files whose faces arrive unsewn.
* ``add_draft``: only when the full OCP bindings import (``draft_ocp``); not a
  production dependency today, so production lists it as unavailable.

Not offered: thickening thin walls (moves faces, so it needs a decision about
which side of each wall to keep, and needs OCP), and enlarging an existing
undersized drain.

Like mesh repair this is a pilot tool: it needs the pilot entitlement and never
reserves or consumes a part check.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import math
import multiprocessing
import os
import re
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.storage import ObjectNotFoundError

logger = logging.getLogger("cadverify.cad_fix_service")

BREP = (".step", ".stp", ".iges", ".igs")
MESH = (".stl",)
# Same disclosure threshold as mesh repair: a fix changing the volume by more
# than this is called out in words, even when the change is the point (draft).
VOLUME_WARN_PCT = 2.0
DEFAULT_QUANTITIES = (1, 100, 1000, 2000, 5000, 10000)  # the app's quantity ladder
MEDIA_TYPES = {".step": "model/step", ".stp": "model/step", ".iges": "model/iges",
               ".igs": "model/iges", ".stl": "model/stl"}
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _env_float(name: str, default: float, low: float) -> float:
    try:
        return max(low, float(os.getenv(name, str(default))))
    except ValueError:
        return default


def fix_timeout_sec() -> float:
    """CAD_FIX_TIMEOUT_SEC: wall-clock cap on the CAD edit itself (default 60 s)."""
    return _env_float("CAD_FIX_TIMEOUT_SEC", 60.0, 1.0)


def fix_max_bytes() -> int:
    """CAD_FIX_MAX_MB: largest stored source a fix will open (default 50 MB)."""
    return int(_env_float("CAD_FIX_MAX_MB", 50.0, 0.001) * 1024 * 1024)


def inline_max_bytes() -> int:
    """CAD_FIX_INLINE_MAX_MB: largest fixed file also returned inline as base64."""
    return int(_env_float("CAD_FIX_INLINE_MAX_MB", 8.0, 0.0) * 1024 * 1024)


# ---------------------------------------------------------------------------
# The catalog
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FixSpec:
    id: str
    label: str
    codes: frozenset[str]
    formats: tuple[str, ...]
    param: str | None
    unit: str | None
    bounds: tuple[float, float] | None
    method: str

    def available(self) -> tuple[bool, str | None]:
        if self.id == "add_draft":
            from src.fixes.draft_ocp import available

            if not available():
                return False, ("Adding draft needs the full OpenCASCADE bindings (cadquery-ocp), "
                               "which this server doesn't have yet.")
            # Even with OCP, the spike's re-check cleared the draft finding on only
            # 7 of 10 parts (with a 0.5 degree margin) and added edge thin-wall
            # warnings on most: off until someone decides to turn it on.
            if os.getenv("CAD_FIX_DRAFT_ENABLED", "0").strip().lower() not in ("1", "true", "yes", "on"):
                return False, "Adding draft is off on this server (CAD_FIX_DRAFT_ENABLED)."
        return True, None


FIXES: dict[str, FixSpec] = {
    "fillet_inside_corners": FixSpec(
        "fillet_inside_corners", "Round the inside corners",
        frozenset({"SHARP_INTERNAL_CORNERS", "MISSING_FILLETS"}), BREP,
        "radius_mm", "mm", (0.05, 25.0), "OpenCASCADE fillet (gmsh)"),
    "drain_holes": FixSpec(
        "drain_holes", "Add drain holes",
        frozenset({"TRAPPED_VOLUME", "MULTIPLE_BODIES"}), BREP + MESH,
        "diameter_mm", "mm", (0.5, 50.0), "OpenCASCADE cut (gmsh); manifold3d for STL"),
    "add_draft": FixSpec(
        "add_draft", "Add draft to the side walls",
        frozenset({"INSUFFICIENT_DRAFT"}), BREP,
        "angle_deg", "deg", (0.25, 10.0), "OpenCASCADE draft angle (OCP)"),
    "heal_brep": FixSpec(
        "heal_brep", "Sew the faces into a solid",
        frozenset({"NON_WATERTIGHT", "NOT_SOLID_VOLUME", "MULTIPLE_BODIES"}), BREP,
        None, None, None, "OpenCASCADE shape healing (gmsh)"),
}

# The app's problem families (frontend v4 fix/problems.ts), so a client can
# wire a finding to its row without re-deriving the grouping.
FAMILY_BY_CODE = {
    "NON_WATERTIGHT": "open", "NOT_SOLID_VOLUME": "solid", "THIN_WALL": "thin",
    "THIN_WALL_MOLDING": "thin", "INSUFFICIENT_DRAFT": "draft", "TRAPPED_VOLUME": "drain",
    "SHARP_INTERNAL_CORNERS": "corners", "MISSING_FILLETS": "corners", "MULTIPLE_BODIES": "bodies",
}

# Minimum drain diameter per process, as the analyzers state it. Used only when
# a sealed-cavity finding's message doesn't carry the number itself.
_DRAIN_MIN_MM = {"fdm": 3.0, "sla": 3.5, "dlp": 3.5, "sls": 3.5, "mjf": 5.0,
                 "dmls": 5.0, "slm": 5.0, "ebm": 5.0}
_NEEDS_MM = re.compile(r">=\s*([0-9]+(?:\.[0-9]+)?)\s*mm")


def _iter_findings(result: dict):
    for issue in result.get("universal_issues") or []:
        yield "*", issue
    for score in result.get("process_scores") or []:
        for issue in score.get("issues") or []:
            yield score.get("process") or issue.get("process") or "?", issue


def _is_sealed_cavity(issue: dict) -> bool:
    """TRAPPED_VOLUME comes in two variants; only a sealed cavity gets new holes."""
    return issue.get("code") == "TRAPPED_VOLUME" and issue.get("measured_value") is None


def _required(process: str, issue: dict) -> float | None:
    value = issue.get("required_value")
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    if _is_sealed_cavity(issue):
        match = _NEEDS_MM.search(f"{issue.get('message', '')} {issue.get('fix_suggestion', '')}")
        if match:
            return float(match.group(1))
        return _DRAIN_MIN_MM.get(process)
    return None


def _fix_for(code: str, issue: dict, suffix: str, result: dict) -> tuple[str | None, str | None]:
    """``(fix_id, why_not)`` for one finding on a file of ``suffix``."""
    brep = suffix in BREP
    if code in ("SHARP_INTERNAL_CORNERS", "MISSING_FILLETS"):
        if not brep:
            return None, "An STL has no edges to round. Round the corners in your CAD tool, or upload STEP."
        return "fillet_inside_corners", None
    if code == "TRAPPED_VOLUME":
        if not _is_sealed_cavity(issue):
            return None, "The cavity already has a drain that is too small. ScaleCAD doesn't enlarge existing holes yet."
        return "drain_holes", None
    if code == "MULTIPLE_BODIES":
        sealed = any(_is_sealed_cavity(i) for _p, i in _iter_findings(result) if i.get("code") == "TRAPPED_VOLUME")
        if sealed:
            return "drain_holes", None
        open_shell = any(i.get("code") == "NON_WATERTIGHT" for _p, i in _iter_findings(result))
        if open_shell and brep:
            return "heal_brep", None  # loose, unsewn faces read as many bodies
        return None, "The bodies are separate parts, not a cavity. Split them or join them in your CAD tool."
    if code == "INSUFFICIENT_DRAFT":
        if not brep:
            return None, "An STL has no faces to tilt. Add draft in your CAD tool, or upload STEP."
        return "add_draft", None
    if code in ("NON_WATERTIGHT", "NOT_SOLID_VOLUME"):
        if brep:
            return "heal_brep", None
        return None, "Use mesh repair for an open STL."
    if code in ("THIN_WALL", "THIN_WALL_MOLDING"):
        return None, ("ScaleCAD doesn't thicken walls of an uploaded file: it would have to move faces, "
                      "and which side to keep is a design decision. Thicken them in your CAD tool.")
    return None, None


# The engine tessellates at 12 points per circle, so a 0.5 mm fillet's facets
# still turn by about 30 degrees, the sharp-corner threshold: in the spike only
# 5 of 13 parts read clean at 0.5 mm against 10 of 12 at 1.0 mm. Rounding at
# 1.0 mm still meets every 0.5 mm rule, so 1.0 mm is the smallest default.
FILLET_MIN_DEFAULT_MM = 1.0
# The draft check is strict (a face at exactly the required angle can read a
# hair under it after tessellation), so drafts default to a small margin.
DRAFT_MARGIN_DEG = 0.5


def _params_for(spec: FixSpec, required: list[float]) -> dict:
    if spec.param is None:
        return {}
    defaults = {"radius_mm": FILLET_MIN_DEFAULT_MM, "diameter_mm": 5.0, "angle_deg": 1.0 + DRAFT_MARGIN_DEG}
    if not required:
        return {spec.param: defaults[spec.param]}
    value = max(required)
    if spec.param == "radius_mm":
        value = max(value, FILLET_MIN_DEFAULT_MM)
    elif spec.param == "angle_deg":
        value = min(value + DRAFT_MARGIN_DEG, (spec.bounds or (0, 10))[1])
    return {spec.param: value}


def fix_options(result: dict | None, suffix: str, attempts: dict[str, dict] | None = None) -> dict:
    """Per finding: can ScaleCAD fix it itself, with which fix and parameters.

    Pure: reads a saved analysis dict and the source suffix only. ``can_fix`` is
    true when ScaleCAD has a fix for that finding on this kind of file and this
    server can run it, and the last attempt of that fix on this part (when there
    was one) did not fail to clear it. It means ScaleCAD will make the edit on a
    copy and re-check it; ``attempt`` carries what the last re-check said.
    """
    attempts = attempts or {}
    groups: dict[tuple[str, str | None], dict] = {}
    for process, issue in _iter_findings(result or {}):
        code = issue.get("code") or "?"
        fix_id, why = _fix_for(code, issue, suffix, result or {})
        if fix_id is None and why is None:
            continue  # not a design finding ScaleCAD has a view on
        key = (code, fix_id)
        g = groups.setdefault(key, {
            "code": code, "family": FAMILY_BY_CODE.get(code), "severity": issue.get("severity"),
            "whole_part": process == "*", "processes": [],
            "required": {}, "unit": issue.get("measurement_unit"),
            "fix": fix_id, "why_not": why,
        })
        if process != "*" and process not in g["processes"]:
            g["processes"].append(process)
        if g["severity"] != "error" and issue.get("severity") == "error":
            g["severity"] = "error"
        req = _required(process, issue)
        if req is not None:
            g["required"][process] = req
            if code == "TRAPPED_VOLUME":
                g["unit"] = "mm"
    findings = []
    per_fix: dict[str, list[float]] = {}
    for g in groups.values():
        fix_id = g["fix"]
        if fix_id is None:
            g.update(can_fix=False, params=None, attempt=None)
            findings.append(g)
            continue
        spec = FIXES[fix_id]
        ok, why = spec.available()
        params = _params_for(spec, list(g["required"].values()))
        attempt = attempts.get(fix_id)
        failed_before = bool(attempt) and g["code"] in set(attempt.get("targeted_remaining_codes") or [])
        g.update(
            can_fix=ok and not failed_before,
            params=params,
            why_not=why if not ok else (attempt.get("summary") if failed_before else None),
            attempt=attempt,
        )
        if ok:
            per_fix.setdefault(fix_id, []).extend(g["required"].values())
        findings.append(g)
    findings.sort(key=lambda g: (not g["can_fix"], g["severity"] != "error", g["code"]))
    fixes = []
    for spec in FIXES.values():
        ok, why = spec.available()
        applies = suffix in spec.formats
        fixes.append({
            "id": spec.id, "label": spec.label, "method": spec.method,
            "available": ok and applies,
            "why_not": why if not ok else (None if applies else f"Not for {suffix.lstrip('.').upper()} files."),
            "codes": sorted(spec.codes),
            "param": spec.param, "unit": spec.unit,
            "bounds": list(spec.bounds) if spec.bounds else None,
            "params": _params_for(spec, per_fix.get(spec.id, [])),
            "applies_to_this_part": spec.id in per_fix,
        })
    return {
        "findings": findings,
        "fixes": fixes,
        "families": sorted({g["family"] for g in findings if g["can_fix"] and g["family"]}),
        "can_fix_count": sum(1 for g in findings if g["can_fix"]),
        "finding_count": len(findings),
    }


# ---------------------------------------------------------------------------
# Isolated CAD worker
# ---------------------------------------------------------------------------


def _fix_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_event_loop()
    sem = getattr(loop, "_cadverify_fix_sem", None)
    if sem is None:
        try:
            n = max(1, int(os.getenv("CAD_FIX_CONCURRENCY", "2")))
        except ValueError:
            n = 2
        sem = asyncio.Semaphore(n)
        setattr(loop, "_cadverify_fix_sem", sem)
    return sem


def _worker(fix_id: str, data: bytes, suffix: str, params: dict):
    from src.fixes.brep_fixes import run_fix

    started = time.perf_counter()
    out = run_fix(fix_id, data, suffix, params)
    return out, round((time.perf_counter() - started) * 1000, 1)


async def run_fix_isolated(fix_id: str, data: bytes, suffix: str, params: dict, cap: float):
    """Run one fix in a fresh single-worker spawn process, hard-killed at ``cap``.

    gmsh/OCC calls are uninterruptible C; only SIGKILL of a process that owns
    nothing else bounds them. A crash surfaces as ``BrokenProcessPool``.
    """
    from src.parsers.parse_pool import _hard_kill

    async with _fix_semaphore():
        ex = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
        try:
            future = ex.submit(_worker, fix_id, data, suffix, params)
            try:
                return await asyncio.wait_for(asyncio.wrap_future(future), cap)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                _hard_kill(ex)
                raise
        finally:
            ex.shutdown(wait=False, cancel_futures=True)


# ---------------------------------------------------------------------------
# Stored records (object store, next to the source artifacts; no schema change)
# ---------------------------------------------------------------------------


def _store():
    from src.services.source_artifact_service import _store as source_store

    return source_store()


def _record_key(org_id: str, mesh_hash: str, name: str) -> str:
    from src.services.source_artifact_service import artifact_key

    # artifact_key validates org and digest; swap only the fixed basename.
    return artifact_key(org_id, mesh_hash, ".stl").replace("/source.stl", f"/{name}")


async def _put_json(key: str, payload: dict) -> None:
    body = json.dumps(payload, sort_keys=True, default=str).encode()
    await asyncio.to_thread(_store().put, key, body, content_type="application/json")


async def _get_json(key: str) -> dict | None:
    try:
        raw = await asyncio.to_thread(_store().get, key)
    except (ObjectNotFoundError, FileNotFoundError, KeyError):
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


async def read_lineage(org_id: str, mesh_hash: str) -> dict | None:
    """The ``derived-from`` record of a fixed copy, or None for an original."""
    return await _get_json(_record_key(org_id, mesh_hash, "derived-from.json"))


async def read_attempts(org_id: str, mesh_hash: str) -> dict[str, dict]:
    out = {}
    for fix_id in FIXES:
        record = await _get_json(_record_key(org_id, mesh_hash, f"fixes/{fix_id}.json"))
        if record:
            out[fix_id] = record
    return out


# ---------------------------------------------------------------------------
# Re-check helpers
# ---------------------------------------------------------------------------


def _finding_index(result: dict) -> dict[tuple[str, str], dict]:
    index: dict[tuple[str, str], dict] = {}
    for process, issue in _iter_findings(result):
        index.setdefault((issue.get("code") or "?", process), issue)
    return index


def _brief(code: str, process: str, issue: dict) -> dict:
    out = {"code": code, "process": None if process == "*" else process,
           "severity": issue.get("severity"), "message": issue.get("message")}
    for k in ("measured_value", "required_value", "measurement_unit"):
        if issue.get(k) is not None:
            out[k] = issue[k]
    return out


def _methods(result: dict) -> dict:
    scores = result.get("process_scores") or []
    ok = [s.get("process") for s in scores if s.get("verdict") in ("pass", "issues")]
    return {"count": len(ok), "of": len(scores), "processes": ok}


def _decimated(result: dict) -> bool:
    return any(i.get("code") == "DECIMATED_MESH" for i in result.get("universal_issues") or [])


def _side(result: dict, data: bytes, suffix: str, mesh_hash: str) -> dict:
    geo = result.get("geometry") or {}
    return {
        "mesh_hash": mesh_hash,
        "sha256": hashlib.sha256(data).hexdigest(),
        "format": suffix.lstrip("."),
        "bytes": len(data),
        "verdict": result.get("overall_verdict"),
        "faces": geo.get("faces"),
        "volume_mm3": geo.get("volume_mm3"),
        "is_watertight": geo.get("is_watertight"),
        "bounding_box_mm": geo.get("bounding_box_mm"),
        "methods_can_make": _methods(result),
        "decimated_for_analysis": _decimated(result),
    }


def _cheapest(report: dict | None) -> list[dict] | None:
    """Lowest DFM-ready unit price per quantity from a cost report dict."""
    if not report or report.get("status") == "GEOMETRY_INVALID":
        return None
    out = []
    for q in report.get("quantities") or []:
        best = None
        for e in report.get("estimates") or []:
            if e.get("quantity") != q or not e.get("dfm_ready") or e.get("dfm_verdict") == "fail":
                continue
            if e.get("unit_cost_usd") is None:
                continue
            if best is None or e["unit_cost_usd"] < best["unit_cost_usd"]:
                best = e
        out.append({
            "qty": q,
            "process": best.get("process") if best else None,
            "material": best.get("material") if best else None,
            "unit_cost_usd": best.get("unit_cost_usd") if best else None,
        })
    return out


async def _price(data: bytes, filename: str, quantities: list[int], material_class: str) -> dict | None:
    """Model prices for one file, in-process (no persistence, no check).

    Same engine pass as ``POST /validate/cost`` with default options; the
    caller's saved quantities and material class are passed through.
    """
    from src.api.routes import _analysis_timeout_sec, _parse_mesh_async, _run_cost_engine_ctx
    from src.costing import EstimateOptions, estimate_decision, report_to_dict
    from src.services import compute_budget

    from fastapi import HTTPException

    async with compute_budget.hold_for_data(data, filename, label="fix price"):
        try:
            mesh, _suffix = await _parse_mesh_async(data, filename)
        except HTTPException:
            return None

        def run():
            result, m, ctx = _run_cost_engine_ctx(mesh, filename)
            rep = estimate_decision(result, m, ctx.features, EstimateOptions(
                quantities=quantities, material_class=material_class,
                material_class_is_user=material_class != "polymer"))
            return report_to_dict(rep)

        try:
            return await compute_budget.run_within_budget(run, timeout=_analysis_timeout_sec(), label="fix price")
        except asyncio.TimeoutError:
            return None


async def _saved_cost_inputs(session, org_id: str, mesh_hash: str) -> tuple[list[int], str, str]:
    """Quantities and material class of the part's latest saved cost check."""
    from sqlalchemy import desc, select

    from src.db.models import CostDecision

    try:
        row = (await session.execute(
            select(CostDecision.result_json)
            .where(CostDecision.org_id == org_id, CostDecision.mesh_hash == mesh_hash)
            .order_by(desc(CostDecision.created_at)).limit(1)
        )).scalar_one_or_none()
    except Exception:
        row = None
    if isinstance(row, dict):
        qs = [int(q) for q in row.get("quantities") or [] if isinstance(q, (int, float)) and q > 0]
        material = row.get("material_class")
        if qs:
            return qs[:6], material if isinstance(material, str) else "polymer", "saved_cost_check"
    return list(DEFAULT_QUANTITIES), "polymer", "default_ladder"


async def latest_analysis(session, org_id: str, mesh_hash: str):
    from sqlalchemy import desc, select

    from src.db.models import Analysis

    return (await session.execute(
        select(Analysis).where(Analysis.org_id == org_id, Analysis.mesh_hash == mesh_hash)
        .order_by(desc(Analysis.created_at)).limit(1)
    )).scalars().first()


def _fixed_filename(original_name: str, fix_id: str, suffix: str) -> str:
    stem = _SAFE.sub("-", Path(original_name or "part").stem).strip(".-") or "part"
    slug = {"fillet_inside_corners": "rounded", "drain_holes": "drained",
            "add_draft": "drafted", "heal_brep": "healed",
            "mesh_repair": "repaired"}.get(fix_id, "fixed")
    return f"{stem}-{slug}{suffix}"


def _meets_rule(spec: FixSpec, params: dict, issue: dict, process: str) -> bool | None:
    """Did the applied parameter meet what this finding's rule asks for?"""
    if spec.param is None:
        return None
    req = _required(process, issue)
    if req is None:
        return None
    return float(params[spec.param]) + 1e-9 >= req


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


class FixRequestError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


_FILLET_EDGES = ("corners", "all")


def fillet_edges(result: dict, asked: str | None = None) -> str:
    """Which edges the corner fix rounds: ``corners`` (the inside corners a milling
    cutter leaves rounded, the ones the milling finding counts) when the part has
    that finding, else ``all`` sharp inside edges (casting's fillets)."""
    if asked is not None:
        if asked not in _FILLET_EDGES:
            raise FixRequestError(400, f"edges must be one of {list(_FILLET_EDGES)}.")
        return asked
    milled = any(issue.get("code") == "SHARP_INTERNAL_CORNERS" for _p, issue in _iter_findings(result))
    return "corners" if milled else "all"


def resolve_params(spec: FixSpec, given: float | None, result: dict, suffix: str,
                   edges: str | None = None) -> dict:
    if spec.param is None:
        return {}
    extra: dict = {}
    codes = None
    if spec.id == "fillet_inside_corners":
        extra["edges"] = fillet_edges(result, edges)
        if extra["edges"] == "corners":
            codes = {"SHARP_INTERNAL_CORNERS"}
    if given is not None:
        lo, hi = spec.bounds or (0.0, math.inf)
        if not (math.isfinite(given) and lo <= given <= hi):
            raise FixRequestError(400, f"{spec.param} must be from {lo:g} to {hi:g} {spec.unit}.")
        return {spec.param: float(given), **extra}
    required = []
    for process, issue in _iter_findings(result):
        if codes is not None and issue.get("code") not in codes:
            continue
        fix_id, _why = _fix_for(issue.get("code") or "", issue, suffix, result)
        if fix_id == spec.id:
            req = _required(process, issue)
            if req is not None:
                required.append(req)
    return {**_params_for(spec, required), **extra}


async def apply_fix(**kwargs) -> dict:
    """Apply one fix to a copy of the part's kept source (``_apply_fix``), within the compute budget.

    The whole fix holds room in the compute budget once its file is read: the
    original's analysis, the fix itself (in its own process) and the re-check.
    A web request waits at most ``COMPUTE_WAIT_SECONDS``, then answers 429.
    """
    from src.services import compute_budget

    async with compute_budget.deferred_hold(label="fix") as room:
        return await _apply_fix(**kwargs, room=room)


async def _apply_fix(
    *,
    org_id: str,
    mesh_hash: str,
    fix_id: str,
    value: float | None,
    processes: str | None,
    edges: str | None = None,
    rule_pack: str | None,
    quantities: list[int] | None,
    material_class: str | None,
    with_cost: bool,
    user,
    session,
    room=None,
) -> dict:
    from src.services import analysis_service
    from src.services.source_artifact_service import read_source_artifact

    spec = FIXES.get(fix_id)
    if spec is None:
        raise FixRequestError(404, f"Unknown fix '{fix_id}'. Available: {sorted(FIXES)}")
    ok, why = spec.available()
    if not ok:
        raise FixRequestError(409, why or "This fix isn't available on this server.")
    try:
        data, suffix = await read_source_artifact(org_id, mesh_hash)
    except (ObjectNotFoundError, FileNotFoundError, ValueError):
        raise FixRequestError(404, "No stored source for this part in your organization.")
    if suffix not in spec.formats:
        raise FixRequestError(422, f"{spec.label} works on {', '.join(f.lstrip('.').upper() for f in spec.formats)} "
                                   f"files; this part is {suffix.lstrip('.').upper()}.")
    if len(data) > fix_max_bytes():
        raise FixRequestError(413, f"The stored file is {len(data) / 1048576:.1f} MB, over the "
                                   f"{fix_max_bytes() / 1048576:.0f} MB limit for fixes.")
    if room is not None:
        await room.take_for_data(data, f"part{suffix}")

    saved = await latest_analysis(session, org_id, mesh_hash)
    original_name = (saved.filename if saved is not None else None) or f"part{suffix}"
    if Path(original_name).suffix.lower() != suffix:
        original_name = f"{Path(original_name).stem or 'part'}{suffix}"

    # The original, through the same pipeline as an upload (a cache hit when the
    # caller already checked it on this engine version).
    original = await analysis_service.run_analysis(
        data, original_name, processes, rule_pack, user, session, org_id=org_id)
    assert isinstance(original, dict)
    params = resolve_params(spec, value, original, suffix, edges)
    lineage = await read_lineage(org_id, mesh_hash)

    base = {
        "fix": {"id": spec.id, "label": spec.label, "method": spec.method, "params": params},
        "original": {**_side(original, data, suffix, mesh_hash), "filename": original_name},
        "derived_from": lineage,
    }

    def refused(reason: str, details: dict | None = None, duration_ms: float | None = None) -> dict:
        return {**base, "applied": False, "outcome": "not_applied", "reason": reason,
                "details": {**(details or {}), **({"duration_ms": duration_ms} if duration_ms else {})},
                "fixed": None, "findings_cleared": [], "findings_new": [], "new_error_count": 0,
                "targeted": None, "volume_change_pct": None, "volume_warning": None, "prices": None,
                "notes": [], "verification": None, "lineage": None, "download": None,
                "fixed_file_b64": None}

    cap = fix_timeout_sec()
    started = time.perf_counter()
    outcome = None
    # Like the engine's tessellation ladder: when gmsh's primary 2D mesher
    # crashes the worker (periodic surfaces), retry once with MeshAdapt.
    for attempt_params in (params, {**params, "_uniform_mesh": True}):
        remaining = cap - (time.perf_counter() - started)
        if remaining <= 0:
            break
        try:
            outcome, duration_ms = await run_fix_isolated(spec.id, data, suffix, attempt_params, remaining)
            break
        except asyncio.TimeoutError:
            break
        except BrokenProcessPool:
            logger.warning("cad fix worker crashed fix=%s hash=%.12s; retrying with MeshAdapt", spec.id, mesh_hash)
            continue
        except Exception:
            logger.exception("cad fix worker failed fix=%s hash=%.12s", spec.id, mesh_hash)
            return refused("The CAD edit stopped with an internal error before producing a file.")
    if outcome is None:
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        timed_out = elapsed >= cap * 1000 - 50
        reason = (f"The CAD edit timed out after {cap:g} s." if timed_out
                  else "The CAD kernel crashed on this file, twice. Nothing was made.")
        await _record_attempt(org_id, mesh_hash, spec, params, None, reason)
        return refused(reason, duration_ms=elapsed)
    if not outcome.applied or not outcome.data:
        await _record_attempt(org_id, mesh_hash, spec, params, None, outcome.reason)
        return refused(outcome.reason or "The fix did not produce a file.", outcome.details, duration_ms)

    fixed_bytes, out_suffix = outcome.data, outcome.suffix
    fixed_hash = hashlib.sha256(fixed_bytes).hexdigest()
    if fixed_hash == mesh_hash:
        return refused("The edit produced a byte-identical file.", outcome.details, duration_ms)
    fixed_name = _fixed_filename(original_name, spec.id, out_suffix)

    # Re-check the copy exactly like an upload. This persists it as a new part
    # (analysis row, source artifact, usage event) in the caller's org, as mesh
    # repair's re-check does. No part check is reserved.
    from fastapi import HTTPException

    try:
        fixed = await analysis_service.run_analysis(
            fixed_bytes, fixed_name, processes, rule_pack, user, session, org_id=org_id)
    except HTTPException as exc:
        # A copy the engine can't read back is not a fix; nothing is offered.
        detail = exc.detail if isinstance(exc.detail, str) else (exc.detail or {}).get("message")
        reason = f"The fixed copy didn't pass the re-check's import ({detail or exc.status_code})."
        await _record_attempt(org_id, mesh_hash, spec, params, None, reason)
        return refused(reason, outcome.details, duration_ms)
    assert isinstance(fixed, dict)

    before_idx, after_idx = _finding_index(original), _finding_index(fixed)
    cleared, new = [], []
    for key in sorted(set(before_idx) - set(after_idx)):
        item = _brief(*key, before_idx[key])
        if key[0] in spec.codes:
            item["targeted"] = True
            item["meets_rule"] = _meets_rule(spec, params, before_idx[key], key[1])
        cleared.append(item)
    for key in sorted(set(after_idx) - set(before_idx)):
        new.append(_brief(*key, after_idx[key]))

    targeted_before = [k for k in before_idx if k[0] in spec.codes and _applies(spec, before_idx[k], suffix, original)]
    targeted_left = [k for k in targeted_before if k in after_idx]
    honest_cleared = [k for k in targeted_before if k not in after_idx
                      and _meets_rule(spec, params, before_idx[k], k[1]) is not False]
    comparable = not (_decimated(fixed) and not _decimated(original))
    if not comparable:
        honest_cleared = []
    new_errors = [k for k in set(after_idx) - set(before_idx) if after_idx[k].get("severity") == "error"]
    if not targeted_before:
        verdict = "nothing_to_clear"
    elif comparable and not targeted_left and len(honest_cleared) == len(targeted_before):
        verdict = "cleared"
    elif comparable and honest_cleared:
        verdict = "partly_cleared"
    else:
        verdict = "not_cleared"

    vb = (original.get("geometry") or {}).get("volume_mm3")
    va = (fixed.get("geometry") or {}).get("volume_mm3")
    volume_change_pct, volume_warning = None, None
    if isinstance(vb, (int, float)) and vb > 0 and isinstance(va, (int, float)):
        volume_change_pct = round((va - vb) / vb * 100.0, 2)
        if abs(volume_change_pct) > VOLUME_WARN_PCT:
            volume_warning = (
                f"The fix changed the part's volume by {volume_change_pct:+.1f}% "
                f"({vb:,.0f} → {va:,.0f} mm³), more than {VOLUME_WARN_PCT:g}%. "
                "Compare the fixed copy with your design before using it.")

    notes = []
    if outcome.details.get("format_note"):
        notes.append(outcome.details["format_note"])
    if not comparable:
        notes.append(
            f"The fixed copy tessellates to {(fixed.get('geometry') or {}).get('faces'):,} faces, over the "
            "engine's analysis budget, so it was checked on a simplified mesh. Wall, edge and draft "
            "findings can't be compared with your file's; this fix isn't shown as working.")
    for k in targeted_before if comparable else []:
        req = _required(k[1], before_idx[k])
        if k not in after_idx and req is not None and _meets_rule(spec, params, before_idx[k], k[1]) is False:
            notes.append(
                f"{k[0]} for {k[1]} no longer shows, but its rule asks for {req:g} {spec.unit} and the fix "
                f"used {params[spec.param]:g} {spec.unit}. The check counts sharp edges; it doesn't measure "
                "the radius, so this one isn't counted as cleared.")

    if new_errors:
        codes = ", ".join(sorted({k[0] for k in new_errors}))
        if (original.get("geometry") or {}).get("is_watertight") is False:
            notes.append(f"Your file isn't a closed solid, so some checks couldn't measure it. On the fixed "
                         f"copy they can, and they report: {codes}.")
        else:
            notes.append(f"The fixed copy has new error findings: {codes}. Compare both before using it.")
    if _decimated(original):
        notes.append(
            f"Your file tessellates to {(original.get('geometry') or {}).get('faces'):,} faces, over the engine's "
            "analysis budget, so it was checked on a simplified mesh; some differences between the two lists "
            "come from that, not from the fix.")

    prices = None
    if with_cost:
        basis = "request"
        if quantities is None or material_class is None:
            saved_q, saved_m, saved_basis = await _saved_cost_inputs(session, org_id, mesh_hash)
            if quantities is None:
                quantities, basis = saved_q, saved_basis
            material_class = material_class or saved_m
        before_cost, after_cost = await asyncio.gather(
            _price(data, original_name, quantities, material_class),
            _price(fixed_bytes, fixed_name, quantities, material_class),
        )
        prices = {
            "quantities": quantities, "material_class": material_class, "basis": basis,
            "before": _cheapest(before_cost), "after": _cheapest(after_cost),
            "note": "Model prices, not quotes. Cheapest method the check doesn't block, per quantity.",
        }

    now = datetime.now(timezone.utc).isoformat()
    link = {
        "parent_mesh_hash": mesh_hash, "parent_format": suffix.lstrip("."),
        "parent_filename": original_name, "fix": spec.id, "params": params,
        "method": spec.method, "created_at": now, "created_by_user_id": user.user_id,
    }
    await _put_json(_record_key(org_id, fixed_hash, "derived-from.json"), link)
    summary = {
        "cleared": "Re-check cleared every targeted finding.",
        "partly_cleared": "Re-check cleared some targeted findings.",
        "not_cleared": "Re-check still shows the targeted findings." if comparable else
        "The fixed copy was checked on a simplified mesh, so the fix couldn't be confirmed.",
        "nothing_to_clear": "The saved check had no finding this fix targets.",
    }[verdict]
    await _record_attempt(org_id, mesh_hash, spec, params, {
        "outcome": verdict, "fixed_mesh_hash": fixed_hash,
        "targeted_remaining_codes": sorted({k[0] for k in targeted_left}) if comparable else
        sorted({k[0] for k in targeted_before}),
    }, summary)

    from src.services.audit_service import emit_event

    try:
        await emit_event(
            session, actor_id=user.user_id, action="part.fix_applied", resource_type="part",
            resource_id=fixed_hash, file_hash=fixed_hash, result_summary=verdict,
            detail={"parent_mesh_hash": mesh_hash, "fix": spec.id, "params": params},
            org_id=org_id,
        )
    except Exception:
        logger.warning("audit event for cad fix failed", exc_info=True)

    inline = fixed_bytes if len(fixed_bytes) <= inline_max_bytes() else None
    return {
        **base,
        "applied": True,
        "outcome": verdict,
        "reason": None,
        "details": {**outcome.details, "duration_ms": duration_ms},
        "fixed": {**_side(fixed, fixed_bytes, out_suffix, fixed_hash), "filename": fixed_name},
        "targeted": {
            "codes": sorted(spec.codes),
            "before": [_brief(*k, before_idx[k]) for k in sorted(targeted_before)],
            "cleared": [_brief(*k, before_idx[k]) for k in sorted(honest_cleared)],
            "remaining": [_brief(*k, after_idx[k]) for k in sorted(targeted_left)],
        },
        "findings_cleared": cleared,
        "findings_new": new,
        "new_error_count": len(new_errors),
        "volume_change_pct": volume_change_pct,
        "volume_warning": volume_warning,
        "prices": prices,
        "notes": notes,
        "verification": {
            "validation_path": "/api/v1/validate",
            "reverified": True,
            "comparable": comparable,
            "original_verdict": original.get("overall_verdict"),
            "fixed_verdict": fixed.get("overall_verdict"),
            "original_sha256": hashlib.sha256(data).hexdigest(),
            "fixed_sha256": fixed_hash,
            "checks_used": 0,
        },
        "lineage": link,
        "download": {
            "url": f"/api/v1/parts/{fixed_hash}/fixed-file",
            "filename": fixed_name,
            "media_type": MEDIA_TYPES.get(out_suffix, "application/octet-stream"),
            "bytes": len(fixed_bytes),
        },
        "fixed_file_b64": base64.b64encode(inline).decode("ascii") if inline is not None else None,
    }


def _applies(spec: FixSpec, issue: dict, suffix: str, result: dict) -> bool:
    fix_id, _why = _fix_for(issue.get("code") or "", issue, suffix, result)
    return fix_id == spec.id


async def _record_attempt(org_id, mesh_hash, spec: FixSpec, params: dict, result: dict | None, summary: str | None):
    record = {
        "fix": spec.id, "params": params, "at": datetime.now(timezone.utc).isoformat(),
        "applied": result is not None, "summary": summary,
        **(result or {"outcome": "not_applied", "targeted_remaining_codes": sorted(spec.codes)}),
    }
    try:
        await _put_json(_record_key(org_id, mesh_hash, f"fixes/{spec.id}.json"), record)
    except Exception:
        logger.warning("could not store cad fix attempt record", exc_info=True)


async def read_fixed_file(org_id: str, mesh_hash: str) -> tuple[bytes, str, dict] | None:
    """Bytes of a ScaleCAD-fixed copy (only fixed copies are downloadable here)."""
    from src.services.source_artifact_service import read_source_artifact

    link = await read_lineage(org_id, mesh_hash)
    if link is None:
        return None
    try:
        data, suffix = await read_source_artifact(org_id, mesh_hash)
    except (ObjectNotFoundError, FileNotFoundError, ValueError):
        return None
    return data, suffix, link
