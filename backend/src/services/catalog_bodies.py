"""A catalog run's multi-body files: each body shape becomes a part on the board.

A file that holds several bodies (``src.analysis.part_types``: separate bodies,
a part with its fixture, an assembly, a weldment) is not one part, and the
board must not price it as one block. In the worker, after the file's own
analysis, every distinct body shape is made a copy of its own (an STL that
ScaleCAD wrote, recorded as derived from the file, like a fix) and run through
the same two steps as any catalog part: the DFM analysis and the cost decision
with the org's machines. The board then shows one row per shape, at the file's
quantity times the copies in the file.

A weldment's members are cut stock: they get their analysis (a part page) and
their stock's weight and list-price material, and no machining price. Welding
isn't priced yet; their rows say so.

The file counts once toward a free run's allowance, whatever it holds. What each
file was split into is kept next to the file's stored source, one record per
run (``catalog-<run>.json``), so no schema change is needed.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("cadverify.catalog_bodies")

MAX_SHAPES = 24
STEP_SUFFIXES = (".step", ".stp", ".iges", ".igs")


def body_filename(parent: str, index: int, name: Optional[str]) -> str:
    stem = Path(parent).stem or "part"
    label = (name or "").strip() or f"body {index}"
    return f"{stem} - {label}.stl"


def scaled_ladder(quantities: str, copies: int) -> str:
    """The item's quantity ladder ("1;100;...") per body: copies in the file × each quantity."""
    out = []
    for tok in (quantities or "").replace(";", ",").split(","):
        tok = tok.strip()
        if tok.isdigit() and int(tok) > 0:
            out.append(str(int(tok) * max(1, int(copies))))
    return ",".join(out) or ",".join(str(q * max(1, int(copies))) for q in (1, 100, 1000, 2000, 5000, 10000))


async def check_file_bodies(
    session,
    *,
    user,
    org_id: str,
    file_bytes: bytes,
    filename: str,
    quantities: str,
    material_class: Optional[str],
    owned: Optional[str],
    part_type: dict,
    budget_sec: float = 120.0,
    material_name: Optional[str] = None,
) -> Optional[dict]:
    """Check each body shape of a multi-body file; the manifest entry, or None to price the file whole.

    None when the file turns out to be one body after all (nothing to split).
    """
    from fastapi import HTTPException, UploadFile
    from starlette.datastructures import Headers

    from src.analysis import part_types
    from src.api.routes import _parse_mesh_async, _run_cost_decision
    from src.costing.rates import build_rate_card
    from src.services import analysis_service, cad_fix_service
    from src.services.body_check_service import MULTI_KINDS, _stock_material, resolve_bodies

    if part_type.get("kind") not in MULTI_KINDS:
        return None
    loop = asyncio.get_event_loop()
    started = loop.time()
    mesh, _suffix = await _parse_mesh_async(file_bytes, filename)
    model = None
    tree_note = None
    if Path(filename).suffix.lower() in STEP_SUFFIXES:
        from src.parsers import parse_pool

        try:
            async with parse_pool.pool_slot():  # the timer starts once a pool worker is free
                model = await asyncio.wait_for(
                    parse_pool.submit_assembly_async(file_bytes, Path(filename).suffix.lower()),
                    timeout=max(10.0, budget_sec / 3))
        except Exception:
            tree_note = "Its product tree couldn't be read; bodies come from its geometry."
    from src.services import compute_budget

    # Inside the catalog part's hold in the compute budget (joined, not a second one).
    space, bodies, source = await compute_budget.run_within_budget(resolve_bodies, mesh, model, label="bodies")
    product_tree = source if source.get("source") == "step_product_tree" else None
    pt = await compute_budget.run_within_budget(part_types.describe, space, bodies=bodies, product_tree=product_tree,
                                                time_budget_sec=20.0, label="bodies")
    kind = pt.get("kind")
    if kind not in MULTI_KINDS:
        return None
    weldment = kind == "weldment"
    mclass, basis = material_class or "polymer", "file"
    if weldment and mclass == "polymer":
        mclass, basis = "steel", "weldment_default"
    rates = build_rate_card() if weldment else None
    records = {b["id"]: b for b in pt.get("bodies") or []}
    groups: dict[int, list] = {}
    for b in bodies:
        groups.setdefault(b.design, []).append(b)
    parent_hash = hashlib.sha256(file_bytes).hexdigest()
    designs: list[dict] = []
    for n, (design, members) in enumerate(groups.items()):
        rep = members[0]
        rec = records.get(rep.index) or {}
        from src.services.catalog_run_service import plain_body_name

        # The product tree's own name, never an exporter's stamp ("Open CASCADE STEP translator 7.8 1.1").
        name = plain_body_name(rep.name)
        entry: dict[str, Any] = {
            "design": design, "bodies": [b.index for b in members], "copies": len(members),
            "name": name, "shape": rec.get("shape"), "stock": rec.get("stock"),
            "filename": body_filename(filename, rep.index, name),
            "mesh_hash": None, "analysis_id": None, "decision_ulid": None,
            "status": "not_checked", "reason": None, "stock_material": None,
        }
        designs.append(entry)
        if n >= MAX_SHAPES:
            entry["reason"] = f"Only the first {MAX_SHAPES} distinct shapes of a file are checked."
            continue
        if loop.time() - started > budget_sec:
            entry["reason"] = "The time for this file ran out before this body was reached."
            continue
        if not rep.closed or rep.mesh is None:
            entry.update(status="open", reason="This body isn't a closed solid on its own.")
            continue
        data = rep.mesh.export(file_type="stl")
        if isinstance(data, str):
            data = data.encode()
        if not isinstance(data, (bytes, bytearray)):
            entry["reason"] = "This body couldn't be written as an STL."
            continue
        data = bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        entry["mesh_hash"] = digest
        await cad_fix_service._put_json(cad_fix_service._record_key(org_id, digest, "derived-from.json"), {
            "parent_mesh_hash": parent_hash, "parent_format": Path(filename).suffix.lstrip(".").lower(),
            "parent_filename": filename, "fix": "body",
            "params": {"body": rep.index, "of": len(bodies), "name": rep.name, "copies": len(members)},
            "method": "one body of a multi-body file, as an STL in the file's own coordinates (catalog run)",
            "created_at": datetime.now(timezone.utc).isoformat(), "created_by_user_id": user.user_id,
        })
        try:
            run = await analysis_service.run_analysis(
                file_bytes=data, filename=entry["filename"], processes=None, rule_pack=None,
                user=user, session=session, org_id=org_id, return_persisted_id=True,
            )
            entry["analysis_id"] = getattr(run, "analysis_id", None)
        except HTTPException as exc:
            entry.update(status="error", reason=str(exc.detail)[:300])
            continue
        if weldment and rep.stock:
            entry["stock_material"] = _stock_material(rep, mclass, rates)
            entry["status"] = "member"
            continue
        upload = UploadFile(file=io.BytesIO(data), filename=entry["filename"],
                            headers=Headers({"content-type": "application/octet-stream"}))
        try:
            report = await _run_cost_decision(
                file=upload, qty=scaled_ladder(quantities, len(members)), region=None, cavities=1,
                complexity="moderate", material_class=mclass, owned_processes=owned or None,
                user=user, session=session, material_name=material_name if mclass == material_class else None,
                org_id=org_id,
            )
            entry["decision_ulid"] = ((report or {}).get("saved") or {}).get("id")
            entry["status"] = "ok"
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            if exc.status_code == 400 and detail.get("code") == "GEOMETRY_INVALID":
                entry.update(status="geometry_invalid", reason=str(detail.get("message") or "the geometry needs repair"))
            else:
                entry.update(status="error", reason=str(detail.get("message") if detail else exc.detail)[:300])
    return {
        "kind": kind,
        "summary": pt.get("summary"),
        "body_count": pt.get("body_count"),
        "shapes": len(designs),
        "source": source.get("source"),
        "product_tree_note": tree_note,
        "material_class": mclass,
        "material_basis": basis,
        "joints": pt.get("joints"),
        "parent_mesh_hash": parent_hash,
        "designs": designs,
        "allowance": "counted once, as one file",
    }


def _key(org_id: str, batch_ulid: str, parent_hash: str) -> str:
    from src.services.cad_fix_service import _record_key

    safe = "".join(ch for ch in str(batch_ulid) if ch.isalnum())
    return _record_key(org_id, parent_hash, f"catalog-{safe}.json")


async def record_file_bodies(org_id: str, batch_ulid: str, entry: dict) -> None:
    """Keep what a run split a file into, next to the file's stored source (per run)."""
    from src.services.cad_fix_service import _put_json

    await _put_json(_key(org_id, batch_ulid, entry["parent_mesh_hash"]), entry)


async def read_file_bodies(org_id: str, batch_ulid: str, parent_hash: str) -> Optional[dict]:
    from src.services.cad_fix_service import _get_json

    try:
        return await _get_json(_key(org_id, batch_ulid, parent_hash))
    except Exception:
        logger.warning("split record unreadable for run %s part %.12s", batch_ulid, parent_hash, exc_info=True)
        return None
