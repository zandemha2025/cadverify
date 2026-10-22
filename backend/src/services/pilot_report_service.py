"""The pilot report: one page for the person who decides what to make in-house.

For a set of parts (one catalog run, or every part the organization checked):
how many parts, sorted into make in-house / buy outside / needs a new machine /
can't be made as drawn; the machine hours and material the in-house parts need;
the biggest wins (in-house parts that cost less than the cheapest outside route
at the same quantity); the decisions recorded on the parts and who recorded
them; and how close ScaleCAD came to the organization's own actuals, with the
caveats that apply.

Every figure is ScaleCAD's engine output or the organization's own numbers;
nothing is extrapolated past what was checked. The same dict feeds the
printable page in the app and the PDF (WeasyPrint, as the cost report).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.services import accuracy_service as acc

logger = logging.getLogger("cadverify.pilot_report")

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "pdf"
_pdf_semaphore = asyncio.Semaphore(2)
ALL_PARTS_QUANTITY = 100
MAX_WINS = 5
MAX_DECISIONS = 50

BUCKET_ORDER = ("in_house", "outside", "new_machine", "cant_make")


class ReportNotFound(LookupError):
    """The run isn't the caller org's, or doesn't exist."""


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def wins(rows: list[dict], records: dict[str, dict]) -> list[dict]:
    """In-house parts that cost less than the cheapest outside route, largest saving first.

    The two prices are the record's own side-by-side at the part's quantity
    (decision.options): the owned machine at its marginal rate vs the cheapest
    outside route. A part without both sides is never counted as a win.
    """
    out = []
    for r in rows:
        if r.get("bucket") != "in_house":
            continue
        rec = records.get(r.get("part_key") or "") or {}
        options = ((rec.get("result_json") or {}).get("decision") or {}).get("options") or {}
        opt = options.get(str(r.get("quantity"))) or options.get(r.get("quantity"))
        if not opt:
            continue
        ins, outs = opt.get("in_house") or {}, opt.get("outside") or {}
        a, b = _num(ins.get("unit_cost_usd")), _num(outs.get("unit_cost_usd"))
        if a is None or b is None or b <= a:
            continue
        qty = int(r.get("quantity") or 1)
        out.append({
            "file_name": r.get("filename"),
            "part_number": r.get("part_number"),
            "part_key": r.get("part_key"),
            "quantity": qty,
            "process": ins.get("process"),
            "machine": (r.get("route") or {}).get("machine") or ins.get("machine"),
            "in_house_each": round(a, 2),
            "outside_each": round(b, 2),
            "outside_process": outs.get("process"),
            "saving_total": round((b - a) * qty, 2),
            "hours_total": r.get("hours_total"),
        })
    out.sort(key=lambda w: -w["saving_total"])
    return out[:MAX_WINS]


def machine_hours(rows: list[dict]) -> list[dict]:
    """In-house machine hours per machine (only parts with a machine time)."""
    by: dict[str, dict] = {}
    for r in rows:
        if r.get("bucket") != "in_house" or _num(r.get("hours_total")) is None:
            continue
        route = r.get("route") or {}
        name = route.get("machine") or route.get("process") or "Your machines"
        m = by.setdefault(name, {"machine": name, "process": route.get("process"), "hours": 0.0, "parts": 0})
        m["hours"] = round(m["hours"] + float(r["hours_total"]), 4)
        m["parts"] += 1
    return sorted(by.values(), key=lambda m: -m["hours"])


async def _rows_for_all_parts(session: AsyncSession, org_id: str) -> tuple[list[dict], dict[str, dict]]:
    from src.services.catalog_run_service import _org_machines, derive_part_row

    records = await acc.latest_records(session, org_id)
    machines = await _org_machines(session, org_id)
    rows = []
    for key, rec in records.items():
        rows.append(derive_part_row(
            item={"ulid": rec["id"], "filename": rec["filename"], "status": "completed",
                  "error_message": None, "duration_ms": None},
            analysis=None,
            decision={"ulid": rec["id"], "mesh_hash": key, "result_json": rec["result_json"]},
            meta={"part_number": rec.get("label")} if rec.get("label") else None,
            machines=machines,
            default_quantity=ALL_PARTS_QUANTITY,
        ))
    rows.sort(key=lambda r: (r.get("filename") or "").lower())
    return rows, records


async def _decisions(session: AsyncSession, org_id: str, keys: set[str], names: dict[str, dict]) -> list[dict]:
    from src.db.models import CostDecision, User
    from src.services.cost_decision_service import DISPOSITION_LABELS

    if not keys:
        return []
    rows = (await session.execute(
        select(CostDecision.mesh_hash, CostDecision.filename, CostDecision.user_disposition,
               CostDecision.disposition_note, CostDecision.disposition_updated_at,
               CostDecision.disposition_updated_by_user_id, CostDecision.disposition_basis)
        .where(CostDecision.org_id == org_id, CostDecision.mesh_hash.in_(sorted(keys)),
               CostDecision.user_disposition.isnot(None))
        .distinct(CostDecision.mesh_hash)
        .order_by(CostDecision.mesh_hash, CostDecision.disposition_updated_at.desc().nulls_last(),
                  CostDecision.created_at.desc())
    )).all()
    ids = {r[5] for r in rows if r[5]}
    who = dict((await session.execute(select(User.id, User.email).where(User.id.in_(ids)))).all()) if ids else {}
    out = []
    for key, filename, disp, note, at, by, basis in rows:
        meta = names.get(key) or {}
        out.append({
            "part_key": key,
            "file_name": meta.get("filename") or filename,
            "part_number": meta.get("part_number"),
            "decision": DISPOSITION_LABELS.get(disp, disp),
            "code": disp,
            "process": (basis or {}).get("process") if isinstance(basis, dict) else None,
            "note": note,
            "by": who.get(by),
            "at": at.isoformat() if at else None,
        })
    out.sort(key=lambda d: d.get("at") or "", reverse=True)
    return out[:MAX_DECISIONS]


def caveats(summary: dict, scope_kind: str, calibration: Optional[dict]) -> list[str]:
    """The plain statements that must travel with the accuracy figures."""
    out = []
    n = summary.get("parts") or 0
    if n == 0:
        out.append("No actuals from your shop are matched to these parts yet, so ScaleCAD's accuracy on them isn't known.")
    elif not summary.get("enough"):
        out.append(f"{n} {'part' if n == 1 else 'parts'} with actuals: not enough to say how accurate ScaleCAD is for you; "
                   f"{summary.get('min_parts')} or more give a fair picture.")
    else:
        out.append(f"Checked against your actuals on {n} parts.")
    if summary.get("test"):
        t = summary["test"]
        out.append(f"{t} test {'row is' if t == 1 else 'rows are'} shown in Actual costs but not counted here.")
    out.append("Each actual is compared with ScaleCAD's estimate for the same part, method and quantity, before any calibration.")
    if calibration:
        out.append("A calibration from your actuals is applied to new estimates; figures here are from before it, "
                   "and its effect was measured with each part held out.")
    if scope_kind == "all":
        out.append(f"Hours, material and cost for all parts are at {ALL_PARTS_QUANTITY} of each part.")
    out.append("Estimates are ScaleCAD's model of your machines and rates, not quotes.")
    return out


async def build_report(session: AsyncSession, org_id: str, run_id: Optional[str] = None) -> dict:
    from src.db.models import Batch, Organization
    from src.services import calibration_service as cal
    from src.services.catalog_run_service import BUCKET_WORDS, build_board, bucket_totals

    org_name = (await session.execute(select(Organization.name).where(Organization.id == org_id))).scalar_one_or_none()
    if run_id:
        batch = (await session.execute(
            select(Batch).where(Batch.ulid == run_id, Batch.org_id == org_id)
        )).scalar_one_or_none()
        if batch is None:
            raise ReportNotFound(run_id)
        board = await build_board(session, batch)
        rows = board["rows"]
        keys = {r["part_key"] for r in rows if r.get("part_key")}
        records = await acc.latest_records(session, org_id, keys)
        scope = {"kind": "run", "run_id": batch.ulid, "created_at": board.get("created_at"),
                 "completed_at": board.get("completed_at"), "status": board.get("status"),
                 "quantity": board.get("quantity"), "material_class": board.get("material_class"),
                 "parts_list": board.get("parts_list")}
        totals = board["totals"]
    else:
        rows, records = await _rows_for_all_parts(session, org_id)
        keys = {r["part_key"] for r in rows if r.get("part_key")}
        scope = {"kind": "all", "run_id": None, "quantity": ALL_PARTS_QUANTITY}
        totals = bucket_totals(rows)

    buckets = [{"key": k, "label": BUCKET_WORDS[k], **totals.get(k, {})} for k in BUCKET_ORDER]
    other = {k: totals[k]["parts"] for k in ("not_sorted", "not_checked", "checking") if totals.get(k, {}).get("parts")}
    names = {r["part_key"]: {"filename": r.get("filename"), "part_number": r.get("part_number")} for r in rows if r.get("part_key")}

    comp = await acc.comparisons(session, org_id, acc.Scope(keys=keys))
    summary = acc.summarize(comp)
    active = await cal.active_calibration(session, org_id)
    calibration = None
    if active is not None:
        hist = await cal.public_history(session, org_id)
        calibration = next((h for h in hist if h["in_effect"]), None)

    in_house = totals.get("in_house", {})
    return {
        "organization": org_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": scope,
        "parts": len(rows),
        "buckets": buckets,
        "other": other,
        "in_house": {
            "parts": in_house.get("parts", 0),
            "hours": in_house.get("hours"),
            "hours_parts": in_house.get("hours_parts", 0),
            "mass_kg": in_house.get("mass_kg"),
            "mass_parts": in_house.get("mass_parts", 0),
            "cost_usd": in_house.get("cost_usd"),
            "machines": machine_hours(rows),
        },
        "wins": wins(rows, records),
        "decisions": await _decisions(session, org_id, keys, names),
        "accuracy": summary,
        "accuracy_rows": [r for r in comp if not r.get("test")][:200],
        "calibration": calibration,
        "caveats": caveats(summary, scope["kind"], calibration),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=select_autoescape(("html", "xml")))


def _money(v) -> str:
    f = _num(v)
    if f is None:
        return "—"
    return f"${f:,.0f}" if abs(f) >= 1000 else f"${f:,.2f}"


def _hours(v) -> str:
    f = _num(v)
    if f is None:
        return "—"
    if f < 1:
        return f"{f * 60:.0f} min"
    return f"{f:,.1f} h" if f < 100 else f"{f:,.0f} h"


def _kg(v) -> str:
    f = _num(v)
    if f is None:
        return "—"
    return f"{f:,.2f} kg" if f < 100 else f"{f:,.0f} kg"


def _pct(v) -> str:
    f = _num(v)
    if f is None:
        return "—"
    return f"{'+' if f > 0 else ''}{f:.0f}%"


def _proc(v) -> str:
    from src.services.catalog_run_service import process_words

    return process_words(v) if v else "—"


_env.filters.update({"money": _money, "hours": _hours, "kg": _kg, "pct": _pct, "proc": _proc})


def render_html(report: dict) -> str:
    return _env.get_template("pilot_report.html").render(r=report)


def _pdf_sync(html: str) -> bytes:
    from weasyprint import HTML

    return HTML(string=html, base_url=str(_TEMPLATE_DIR)).write_pdf()


async def render_pdf(report: dict) -> bytes:
    html = render_html(report)
    async with _pdf_semaphore:
        return await asyncio.get_event_loop().run_in_executor(None, _pdf_sync, html)
