"""Each body of a multi-body file checked as its own part.

A file can hold several bodies (``src.analysis.part_types``): separate parts saved
together, a part with its fixture, an assembly, or a weldment's members. Pricing
that file as one block is wrong (a CNC quote for the box around two cubes, or a
"not a closed solid" for a welded frame whose members each are closed). This
module runs the SAME single-part engine a check uses (``routes._run_cost_engine_ctx``
then ``costing.estimate_decision``) on every body, once per distinct shape, and
adds what the file's own geometry says:

* separate bodies and assemblies: each body's process verdicts and its
  cheapest makeable route per quantity, and the sum of the bodies, each made as
  its own part;
* weldments: each member's stock (plate, sheet, tube, bar, angle, from its
  cross-section and length), its weight and material at list price, the joints
  where members touch (count, and a weld length labelled as an estimate) and
  the fabrication route (cut, prep, weld, finish). ScaleCAD has no weld pricing:
  the response says so and gives no number for it.

Quantities are per file: at a quantity of 10 frames, a tube that appears twice
in the frame is costed at 20. Bounded by a design cap and a deadline; a body not
checked in time is reported as such, never priced by guess.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np

from src.analysis import part_types

logger = logging.getLogger("cadverify.body_checks")

MULTI_KINDS = frozenset({"separate_bodies", "weldment", "assembly", "bodies"})
_MAX_QTYS = 6


def max_designs() -> int:
    try:
        value = int(os.getenv("BODY_CHECK_MAX_DESIGNS", "24"))
    except ValueError:
        return 24
    return max(1, value)


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _stock_material(body: part_types.Body, material_class: str, rates) -> Optional[dict]:
    """Weight and list-price material of a stock member: net volume × density × price per kg."""
    from src.analysis.models import ProcessType as PT
    from src.costing.routing import select_material, select_sheet_material

    stock = body.stock or {}
    kind = stock.get("kind")
    if kind not in part_types.STOCK_KINDS or body.volume <= 0:
        return None
    mat = None
    if kind in ("plate", "sheet"):
        try:
            mat = select_sheet_material(material_class, rates)
        except Exception:
            mat = None
    if mat is None:
        mat = select_material(PT.CNC_3AXIS, material_class, rates)
    if mat is None or not mat.density or not mat.cost_per_kg:
        return None
    mass = body.volume / 1000.0 * float(mat.density) / 1000.0
    return {
        "material": mat.name,
        "density_g_cm3": round(float(mat.density), 3),
        "usd_per_kg": round(float(mat.cost_per_kg), 2),
        "mass_kg": round(mass, 3),
        "usd": round(mass * float(mat.cost_per_kg), 2),
        "basis": "net weight × list price per kg; no offcut, kerf or cutting",
    }


def _cots(body: part_types.Body, features) -> Optional[dict]:
    """Standard hardware by name and size (the assembly check's own reader)."""
    if not body.name:
        return None
    from src.services.assembly_analysis_service import classify_cots_fastener

    size = [float(d) for d in (body.hi - body.lo)]
    try:
        return classify_cots_fastener(body.name, "", features=features, max_dim_mm=max(size),
                                      bbox_size_mm=size, volume_mm3=float(body.volume))
    except Exception:
        return None


def _check_design(body: part_types.Body, copies: int, *, stem: str, quantities: list[int],
                  material_class: str, material_class_is_user: bool, region: str,
                  owned_processes: frozenset, rates, weldment: bool) -> dict:
    """One distinct body shape through the single-part engine."""
    from src.api.routes import _run_cost_engine_ctx
    from src.costing import EstimateOptions, estimate_decision, report_to_dict
    from src.services.assembly_analysis_service import _dfm_summary

    row: dict[str, Any] = {
        "design": body.design,
        "copies": copies,
        "stock": body.stock,
        "stock_material": _stock_material(body, material_class, rates),
    }
    if not body.closed or body.mesh is None:
        row.update(status="open", reason="This body isn't a closed solid on its own, so nothing is priced from it.")
        return row
    started = time.monotonic()
    result, m, ctx = _run_cost_engine_ctx(body.mesh.copy(), f"{stem}-body-{body.index}.stl")
    scores = sorted(result.process_scores, key=lambda s: -float(s.score))
    can = [s for s in scores if s.verdict != "fail"]
    cost_qtys = sorted({max(1, int(q) * copies) for q in quantities})[:_MAX_QTYS]
    options = EstimateOptions(
        quantities=cost_qtys, material_class=material_class,
        material_class_is_user=material_class_is_user, region=region,
        region_is_user=region != "US", owned_processes=owned_processes,
    )
    rd = report_to_dict(estimate_decision(result, m, ctx.features, options))
    dec = rd.get("decision") or {}
    routing = rd.get("routing") or {}
    prefer = [p for p in (dec.get("make_now_process"), routing.get("recommended_process")) if p]
    row.update(
        status="ok" if rd.get("status") == "OK" else "geometry_invalid",
        verdict=result.overall_verdict,
        dfm=_dfm_summary(result, material_class, prefer=prefer),
        processes={"can_make": len(can), "of": len(scores),
                   "verdicts": [{"process": s.process.value, "verdict": s.verdict, "score": round(float(s.score), 1)}
                                for s in scores]},
        tooling_process=dec.get("tooling_process"),
        crossover_qty=_num(dec.get("crossover_qty")),
        routing={"recommended_process": routing.get("recommended_process"), "reasoning": routing.get("reasoning")},
    )
    if rd.get("status") != "OK":
        row["reason"] = rd.get("reason")
    rec = dec.get("recommendation") or {}
    by_q: dict[str, Any] = {}
    for q in quantities:
        each = max(1, int(q) * copies)
        r = rec.get(each) or rec.get(str(each))
        unit = _num(r.get("unit_cost_usd")) if r else None
        if r and unit is not None:
            by_q[str(q)] = {
                "quantity_each": each,
                "process": r.get("process"), "material": r.get("material"),
                "unit_cost_usd": unit,
                "per_file_usd": round(unit * copies, 2),
                "dfm_verdict": r.get("dfm_verdict"),
                "lead_days": [r.get("lead_low_days"), r.get("lead_high_days")],
            }
        else:
            by_q[str(q)] = None
    row["by_quantity"] = by_q
    if weldment and (body.stock or {}).get("kind") in ("plate", "sheet"):
        # A plate member is a cut blank: the engine's sheet-metal route prices that when it can.
        cut = {}
        for e in rd.get("estimates") or []:
            if e.get("process") == "sheet_metal" and e.get("dfm_ready") and _num(e.get("unit_cost_usd")) is not None:
                for q in quantities:
                    if int(e.get("quantity") or 0) == max(1, int(q) * copies):
                        cut[str(q)] = {"unit_cost_usd": _num(e["unit_cost_usd"]), "material": e.get("material")}
        row["cut_blank"] = cut or None
    cots = _cots(body, ctx.features)
    if cots:
        row["cots"] = cots
    row["elapsed_sec"] = round(time.monotonic() - started, 2)
    return row


def _totals(designs: list[dict], quantities: list[int], key: str = "per_file_usd") -> dict:
    out: dict[str, Any] = {}
    priced = [d for d in designs if d.get("status") == "ok"]
    for q in quantities:
        vals = []
        for d in priced:
            cots = d.get("cots")
            if cots and _num(cots.get("buy_price_usd")) is not None:
                vals.append(_num(cots["buy_price_usd"]) * d["copies"])
                continue
            r = (d.get("by_quantity") or {}).get(str(q))
            if r and r.get(key) is not None:
                vals.append(float(r[key]))
        out[str(q)] = round(sum(vals), 2) if vals and len(vals) == len(designs) else None
    return out


def resolve_bodies(mesh, model=None) -> tuple[Any, list[part_types.Body], dict]:
    """The file's bodies: a STEP product tree's own parts when it has two or more
    with meshes (names, true per-part solids), else the analysis mesh split into
    bodies. Returns (the mesh ``Body.faces`` index, bodies, where they came from).
    """
    if model is not None and getattr(model, "kind", None) == "assembly":
        parts = []
        for p in model.parts:
            if getattr(p, "mesh", None) is None:
                continue
            gs = getattr(p, "geometry_summary", None)
            key = (p.name, round(float(p.world.volume), 3), int(getattr(gs, "num_boundary_faces", 0) or 0))
            parts.append((p.mesh, p.name, key, {"tree_path": p.tree_path, "part_id": p.id}))
        combined, bodies = part_types.bodies_from_parts(parts, view_mesh=mesh)
        if combined is not None and len(bodies) >= 2:
            return combined, bodies, {
                "source": "step_product_tree",
                "parts": int(model.part_count),
                "designs": dict(model.unique_designs or {}),
                "truncated": bool(model.truncated),
                "parts_without_mesh": int(model.part_count) - len(bodies),
            }
    bodies, info = part_types.split_bodies(mesh)
    return mesh, bodies, {"source": "mesh", "shells": info.get("shells")}


def check_bodies_sync(
    mesh,
    *,
    filename: str,
    model=None,
    quantities: Iterable[int] = (1, 100, 1000),
    material_class: str = "polymer",
    material_class_is_user: bool = False,
    region: str = "US",
    owned_processes: frozenset = frozenset(),
    names: Optional[dict[int, str]] = None,
    product_tree: Optional[dict] = None,
    time_budget_sec: float = 50.0,
) -> dict:
    """Every body of the file checked as its own part, plus the file's total."""
    from src.costing.rates import build_rate_card

    started = time.monotonic()
    deadline = started + max(2.0, float(time_budget_sec))
    quantities = [int(q) for q in quantities][:_MAX_QTYS] or [1]
    space, bodies, source = resolve_bodies(mesh, model)
    if product_tree is None and source.get("source") == "step_product_tree":
        product_tree = source
    pt = part_types.describe(space, bodies=bodies, names=names, product_tree=product_tree,
                             time_budget_sec=max(2.0, min(20.0, float(time_budget_sec) / 3)))
    pt["source"] = source.get("source")
    out: dict[str, Any] = {
        "filename": filename,
        "part_type": pt,
        "quantities": quantities,
        "checks_used": 0,
    }
    if pt.get("kind") not in MULTI_KINDS:
        out.update(designs=[], total=None,
                   note=("One body: the part's own check is the answer." if pt.get("body_count") == 1
                         else pt.get("summary")))
        return out
    weldment = pt["kind"] == "weldment"
    mclass, basis = material_class, ("request" if material_class_is_user else "default")
    if weldment and not material_class_is_user and material_class == "polymer":
        # A welded frame of plate and tube is metal; plastic is only the app's default answer.
        mclass, basis = "steel", "weldment_default"
    out["material_class"] = mclass
    out["material_basis"] = basis
    rates = build_rate_card()
    stem = Path(filename or "part").stem or "part"
    groups: dict[int, list[part_types.Body]] = {}
    for b in bodies:
        groups.setdefault(b.design, []).append(b)
    designs: list[dict] = []
    cap = max_designs()
    for n, (design, members) in enumerate(groups.items()):
        ids = [b.index for b in members]
        if n >= cap:
            designs.append({"design": design, "bodies": ids, "copies": len(members), "status": "not_checked",
                            "reason": f"Only the first {cap} distinct shapes are checked in one go."})
            continue
        if time.monotonic() > deadline:
            designs.append({"design": design, "bodies": ids, "copies": len(members), "status": "not_checked",
                            "reason": "The time for this check ran out before this body was reached."})
            continue
        try:
            row = _check_design(members[0], len(members), stem=stem, quantities=quantities,
                                material_class=mclass, material_class_is_user=basis != "default",
                                region=region, owned_processes=owned_processes, rates=rates,
                                weldment=weldment)
        except Exception as exc:
            logger.warning("body check failed for %s body %s", filename, members[0].index, exc_info=True)
            row = {"design": design, "copies": len(members), "status": "error",
                   "reason": f"The engine stopped on this body ({type(exc).__name__})."}
        row["bodies"] = ids
        designs.append(row)
    out["designs"] = designs
    checked = sum(len(d["bodies"]) for d in designs if d.get("status") == "ok")
    out["checked"] = {"bodies": checked, "of": len(bodies), "designs": len(designs)}
    if weldment:
        members = [d for d in designs if d.get("stock_material")]
        material = round(sum(d["stock_material"]["usd"] * d["copies"] for d in members), 2) if members else None
        mass = round(sum(d["stock_material"]["mass_kg"] * d["copies"] for d in members), 3) if members else None
        complete = len(members) == len(designs)
        joints = pt.get("joints") or {}
        uncut: dict[Any, int] = {}
        for d in designs:
            if not d.get("cut_blank"):
                kind = (d.get("stock") or {}).get("kind")
                uncut[kind] = uncut.get(kind, 0) + int(d.get("copies") or 1)
        cut_n = sum(int(d.get("copies") or 1) for d in designs if d.get("cut_blank"))
        cut_usd = {}
        for q in quantities:
            vals = [d["cut_blank"][str(q)]["unit_cost_usd"] * d["copies"]
                    for d in designs if d.get("cut_blank") and (d["cut_blank"].get(str(q)) or {}).get("unit_cost_usd") is not None]
            cut_usd[str(q)] = round(sum(vals), 2) if vals else None
        not_priced = ([f"cutting {part_types._count_words(uncut)}"] if uncut else []) + ["edge prep", "welding", "finishing"]
        out["weldment"] = {
            "route": ["cut", "prep", "weld", "finish"],
            "members": len(bodies),
            "material_usd": material,
            "material_kg": mass,
            "material_complete": complete,
            "cut_blanks": cut_n,
            "cut_blanks_usd": cut_usd if cut_n else None,
            "joints": joints.get("count"),
            "weld_length_mm_estimate": joints.get("weld_length_mm_estimate"),
            "not_priced": not_priced,
            "words": (
                "ScaleCAD doesn't price welding yet. The members' material is at list price per kg"
                + ("" if complete else " (for the members read as stock)")
                + (f"; {cut_n} plate{'s' if cut_n != 1 else ''} priced as laser-cut blanks on the sheet-metal route"
                   if cut_n else "")
                + "; " + (", ".join(not_priced[:-1]) + " and " + not_priced[-1]) + " aren't priced."
            ),
        }
        out["total"] = None
    else:
        out["total"] = {
            "per_file_usd": _totals(designs, quantities),
            "basis": "the sum of the bodies, each made as its own part by its cheapest route at that quantity",
            "complete": all(d.get("status") == "ok" for d in designs),
        }
    if pt["kind"] == "assembly":
        out["assembly"] = {
            "words": ("Fit, interference between the parts and quantities read from the product tree "
                      "are in the assembly check, a pilot tool. The bodies here are checked one by one."),
            "pilot": True,
        }
    out["elapsed_sec"] = round(time.monotonic() - started, 2)
    out["basis"] = (
        "Each distinct body shape is checked once with the same engine as a single-part check "
        "(typical rates, not your machines); copies are counted, not checked again. "
        "Open a body as its own part for your machines and every detail."
    )
    return out


def body_stl_bytes(mesh, body_id: int, model=None) -> tuple[bytes, dict]:
    """One body of the file as a binary STL (millimetres, the file's own coordinates).

    Numbered as ``check_bodies_sync`` numbers them (same file, same bodies).
    """
    _space, bodies, _source = resolve_bodies(mesh, model)
    for b in bodies:
        if b.index == int(body_id):
            if b.mesh is None or not b.closed:
                raise ValueError("That body isn't a closed solid on its own.")
            data = b.mesh.export(file_type="stl")
            if isinstance(data, str):
                data = data.encode()
            if not isinstance(data, (bytes, bytearray)):
                raise ValueError("That body couldn't be written as an STL.")
            return bytes(data), {"id": b.index, "name": b.name, "faces": int(len(b.faces)),
                                 "volume_mm3": round(b.volume, 1),
                                 "bbox_mm": [round(float(d), 2) for d in (b.hi - b.lo)], "of": len(bodies)}
    raise LookupError(f"This file has no body {body_id}.")
