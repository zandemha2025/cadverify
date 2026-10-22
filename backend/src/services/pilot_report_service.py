"""The pilot report: one page for the person who decides what to make in-house.

It leads with the run's own answer, word for word and number for number as the
run page says it ("Make 20 parts in-house: save $398,445 a year against what
you pay today", ``catalog_run_service.make_or_buy_answer``), how many parts it
covers ("28 of 298 checked; 270 not checked", each not-checked part listed with
why) and what the prices assume (your machines' running rates, the rates, where
buy prices come from). Then, for a set of parts (one catalog run, or every part
the organization checked): how many parts, sorted into make in-house / buy
outside / needs a new machine / can't be made as drawn; the machine hours the
in-house parts need against each machine's hours a year, and which machines
would be overloaded; the biggest wins, against what you pay today where you
gave a price; the decisions recorded and who recorded them (by name); and how
close ScaleCAD came to the organization's own actuals, shown only with enough
actuals and saying what it compares, with the caveats that apply.

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
    """In-house parts that cost less to make than to buy, largest saving first.

    Against what you pay today where the part has a current price (the run's own
    saving: price - make, times the quantity, ``vs`` "you" or "parts_list");
    else against the cheapest outside route, both ScaleCAD estimates at the same
    quantity (decision.options, ``vs`` "model"). A part recorded as bought is
    never a win; a part without both sides is never counted.
    """
    from src.services.catalog_run_service import is_decided_buy

    out = []
    for r in rows:
        if r.get("bucket") != "in_house" or is_decided_buy(r):
            continue
        qty = int(r.get("quantity") or 1)
        make = r.get("make") if isinstance(r.get("make"), dict) else {}
        saving = r.get("saving") if isinstance(r.get("saving"), dict) else None
        price = r.get("current_price") if isinstance(r.get("current_price"), dict) else None
        if saving is not None and price is not None and _num(make.get("unit_cost_usd")) is not None:
            if _num(saving.get("total")) is None or saving["total"] <= 0:
                continue
            out.append({
                "file_name": r.get("filename"), "part_number": r.get("part_number"), "part_key": r.get("part_key"),
                "quantity": qty, "process": make.get("process"),
                "machine": (r.get("route") or {}).get("machine") or make.get("machine"),
                "in_house_each": round(float(make["unit_cost_usd"]), 2),
                "outside_each": round(float(price["usd_each"]), 2), "outside_process": None,
                "vs": saving.get("vs") or price.get("source"),
                "saving_total": round(float(saving["total"]), 2), "hours_total": r.get("hours_total"),
            })
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
            "vs": "model",
            "saving_total": round((b - a) * qty, 2),
            "hours_total": r.get("hours_total"),
        })
    out.sort(key=lambda w: -w["saving_total"])
    return out[:MAX_WINS]


def machine_hours(rows: list[dict]) -> list[dict]:
    """In-house machine hours per machine (only parts with a machine time; a part recorded as bought adds none)."""
    from src.services.catalog_run_service import is_decided_buy

    by: dict[str, dict] = {}
    for r in rows:
        if r.get("bucket") != "in_house" or is_decided_buy(r) or _num(r.get("hours_total")) is None:
            continue
        route = r.get("route") or {}
        name = route.get("machine") or route.get("process") or "Your machines"
        m = by.setdefault(name, {"machine": name, "process": route.get("process"), "hours": 0.0, "parts": 0})
        m["hours"] = round(m["hours"] + float(r["hours_total"]), 4)
        m["parts"] += 1
    return sorted(by.values(), key=lambda m: -m["hours"])


async def _rows_for_all_parts(session: AsyncSession, org_id: str) -> tuple[list[dict], dict[str, dict]]:
    """Every part's row from its newest record, at its yearly quantity when the record priced it (else
    the quantity its page opens at), with what you pay today and the outcome recorded on it."""
    from src.db.models import CostDecision, PartContext
    from src.services.catalog_run_service import _org_machines, derive_part_row
    from src.services.machine_load_service import load_quantity

    records = await acc.latest_records(session, org_id)
    machines = await _org_machines(session, org_id)
    facts = {k: (v, p) for k, v, p in (await session.execute(
        select(PartContext.mesh_hash, PartContext.annual_volume, PartContext.buy_price)
        .where(PartContext.org_id == org_id))).all()}
    outcomes = dict((await session.execute(
        select(CostDecision.mesh_hash, CostDecision.user_disposition)
        .where(CostDecision.org_id == org_id, CostDecision.user_disposition.isnot(None))
        .distinct(CostDecision.mesh_hash)
        .order_by(CostDecision.mesh_hash, CostDecision.disposition_updated_at.desc().nulls_last(),
                  CostDecision.created_at.desc()))).all())
    rows = []
    for key, rec in records.items():
        yearly, price = facts.get(key, (None, None))
        qty, basis = load_quantity(rec["result_json"] or {}, yearly, ALL_PARTS_QUANTITY)
        meta = {"part_number": rec.get("label")} if rec.get("label") else {}
        if basis == "yearly":
            meta["quantity"] = qty
        row = derive_part_row(
            item={"ulid": rec["id"], "filename": rec["filename"], "status": "completed",
                  "error_message": None, "duration_ms": None},
            analysis=None,
            decision={"ulid": rec["id"], "mesh_hash": key, "result_json": rec["result_json"]},
            meta=meta or None,
            machines=machines,
            default_quantity=qty,
            buy_price=price if isinstance(price, dict) else None,
        )
        row["outcome"] = outcomes.get(key)
        rows.append(row)
    rows.sort(key=lambda r: (r.get("filename") or "").lower())
    return rows, records


async def _run_records(session: AsyncSession, org_id: str, rows: list[dict]) -> dict[str, dict]:
    from src.db.models import CostDecision

    ids = sorted({r["cost_decision_id"] for r in rows if r.get("cost_decision_id")})
    if not ids:
        return {}
    out = {}
    for mesh_hash, ulid, result in (await session.execute(
        select(CostDecision.mesh_hash, CostDecision.ulid, CostDecision.result_json)
        .where(CostDecision.org_id == org_id, CostDecision.ulid.in_(ids))
    )).all():
        out[mesh_hash] = {"id": ulid, "result_json": result or {}}
    return out


async def _decisions(session: AsyncSession, org_id: str, keys: set[str], names: dict[str, dict]) -> list[dict]:
    from src.db.models import CostDecision
    from src.services.cost_decision_service import DISPOSITION_LABELS

    if not keys:
        return []
    rows = (await session.execute(
        select(CostDecision.mesh_hash, CostDecision.filename, CostDecision.user_disposition,
               CostDecision.disposition_note, CostDecision.disposition_updated_at,
               CostDecision.disposition_updated_by_user_id, CostDecision.disposition_basis,
               CostDecision.approval_status, CostDecision.approved_by_user_id, CostDecision.approved_at,
               CostDecision.approval_note, CostDecision.stale_at, CostDecision.stale_reason)
        .where(CostDecision.org_id == org_id, CostDecision.mesh_hash.in_(sorted(keys)),
               CostDecision.user_disposition.isnot(None))
        .distinct(CostDecision.mesh_hash)
        .order_by(CostDecision.mesh_hash, CostDecision.disposition_updated_at.desc().nulls_last(),
                  CostDecision.created_at.desc())
    )).all()
    from src.services import signoff_service as so

    # "By" is the person's name, as "Signed off" is (op-21); the email only when no name is known.
    who = await so.names_for(session, [r[5] for r in rows])
    signers = await so.names_for(session, [r[8] for r in rows])
    now = datetime.now(timezone.utc)
    out = []
    for (key, filename, disp, note, at, by, basis,
         approval, signer, signed_at, signoff_note, stale_at, stale_reason) in rows:
        meta = names.get(key) or {}
        if stale_at is not None and stale_at.tzinfo is None:
            stale_at = stale_at.replace(tzinfo=timezone.utc)
        signoff = so.signoff_view({
            "approval_status": approval, "approved_by_user_id": signer,
            "approved_at": signed_at.isoformat() if signed_at else None, "approval_note": signoff_note,
            "is_stale": stale_at is not None and stale_at <= now, "stale_reason": stale_reason,
            "stale_at": stale_at.isoformat() if stale_at else None}, signers)
        out.append({
            "part_key": key,
            "file_name": meta.get("filename") or filename,
            "part_number": meta.get("part_number"),
            "decision": DISPOSITION_LABELS.get(disp, disp),
            "code": disp,
            "process": (basis or {}).get("process") if isinstance(basis, dict) else None,
            "quantity": (basis or {}).get("quantity") if isinstance(basis, dict) else None,
            "note": note,
            "by": who.get(by),
            "at": at.isoformat() if at else None,
            "signoff": signoff,
        })
    out.sort(key=lambda d: d.get("at") or "", reverse=True)
    return out[:MAX_DECISIONS]


def _usd0(v: float) -> str:
    return f"{'−' if v < 0 else ''}${abs(v):,.0f}"


def not_priced_text(groups: Optional[list], show: int = 3) -> Optional[str]:
    """frontend many/catalog-model.ts ``notPricedText``: the materials ScaleCAD doesn't price yet,
    once each with their parts (op-03)."""
    if not groups:
        return None
    said = []
    for g in groups:
        shown = list(g.get("parts") or [])[:show]
        more = g["count"] - len(shown)
        if more > 0:
            names = f"{', '.join(shown)} and {more} more"
        elif len(shown) > 1:
            names = f"{', '.join(shown[:-1])} and {shown[-1]}"
        else:
            names = shown[0] if shown else ""
        said.append(f"{g['material']} ({g['count']:,} {'part' if g['count'] == 1 else 'parts'}"
                    f"{': ' + names if names else ''})")
    total = sum(g["count"] for g in groups)
    tail = ("Its shape was checked; it isn’t" if total == 1 else "Their shapes were checked; they aren’t")
    return f"Not priced yet: {'; '.join(said)}. {tail} priced as anything else."


def answer_words(a: Optional[dict], has_list: bool) -> Optional[dict]:
    """The run's answer as the run page says it (frontend many/catalog-model.ts ``answerText``):
    ``{head, sub, missing}``, e.g. "Make 20 parts in-house: save $398,445 a year against what
    you pay today (on the 17 with a current price)". Same counts, same money, same words."""
    if not a:
        return None

    def n(k: int, one: str, many: Optional[str] = None) -> str:
        return f"{k:,} {one if k == 1 else (many or one + 's')}"

    year = " a year" if has_list else ""
    make, buy, saving, saved = a.get("make", 0), a.get("buy", 0), a.get("saving_usd"), a.get("saving_parts", 0)
    without = a.get("make_without_price", 0)
    if saving is not None and saved:
        these = f"these {n(make, 'part')}" if make == saved else n(make, "part")
        head = (f"Make {these} in-house: save {_usd0(saving)}{year} against what you pay today"
                + (f" (on the {saved} with a current price)" if without else ""))
    elif make:
        head = f"Make {n(make, 'part')} in-house, buy {buy}"
    elif buy:
        head = f"Buy all {n(buy, 'part')} that could be decided"
    elif a.get("checking"):
        head = f"Checking {n(a['checking'], 'part')}: the answer fills in as each one finishes"
    else:
        head = "No part could be decided yet" if a.get("parts") else "No parts yet"
    rest = []
    if saving is not None and saved:
        rest.append(f"Buy {buy}")
    if a.get("new_machine"):
        rest.append(f"{a['new_machine']} need a new machine")
    if a.get("undecided"):
        unsorted = (a.get("not_sorted") or 0) - (a.get("not_priced") or 0)
        why = ", ".join(w for w in (
            f"{a['cant_make']} can’t be made as drawn" if a.get("cant_make") else None,
            f"{a['not_checked']} not checked" if a.get("not_checked") else None,
            f"{a['not_priced']} not priced yet" if a.get("not_priced") else None,
            f"{unsorted} not sorted" if unsorted else None,
            f"{a['checking']} still checking" if a.get("checking") else None) if w)
        rest.append(f"{a['undecided']} can’t be decided yet ({why})")
    if has_list:
        rest.append("parts on your list, at their listed quantities")
    if saving is None:
        missing = ("No saving yet: it needs what you pay today. Add a Current price column to the parts list, "
                   "or type the price on a part’s Decision view.") if make else None
    elif without:
        missing = (f"{n(without, 'in-house part')} {'has' if without == 1 else 'have'} no current price, so "
                   f"{'it isn’t' if without == 1 else 'they aren’t'} in the saving.")
    else:
        missing = None
    missing = " ".join(w for w in (missing, not_priced_text(a.get("not_priced_materials"))) if w) or None
    return {"head": head, "sub": " · ".join(rest), "missing": missing}


def coverage(rows: list[dict]) -> dict:
    """How many parts the answer covers: ``28 of 298 checked; 270 not checked``, with each part
    not checked and why (op-20), and parts checked without an answer said apart."""
    from src.services.catalog_run_service import BUCKETS

    answered = [r for r in rows if r.get("bucket") in BUCKETS]
    unchecked = [r for r in rows if r.get("bucket") in ("not_checked", "checking")]
    unsorted = [r for r in rows if r.get("bucket") == "not_sorted"]
    reasons: dict[str, int] = {}
    for r in unchecked:
        why = r.get("reason") or "Not checked"
        reasons[why] = reasons.get(why, 0) + 1
    text = f"{len(answered):,} of {len(rows):,} checked"
    if unchecked:
        text += f"; {len(unchecked):,} not checked"
    if unsorted:
        text += f"; {len(unsorted):,} checked without a machine verdict"
    return {
        "parts": len(rows), "checked": len(answered), "not_checked": len(unchecked), "not_sorted": len(unsorted),
        "text": text,
        "reasons": [{"reason": k, "parts": v} for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])],
        "unchecked": [{"part": r.get("part_number") or r.get("filename"), "reason": r.get("reason")}
                      for r in unchecked[:500]],
        "unsorted": [{"part": r.get("part_number") or r.get("filename"), "reason": r.get("reason")}
                     for r in unsorted[:200]],
        # The same, said once per reason with its parts ("Brass C360 isn't priced in ScaleCAD yet ...": 3 parts).
        "unsorted_groups": _by_reason(unsorted[:200]),
    }


def _by_reason(rows: list[dict]) -> list[dict]:
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(r.get("reason") or "Checked; no price or machine verdict", []).append(
            r.get("part_number") or r.get("filename"))
    return [{"reason": k, "parts": v} for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))]


def basis_lines(machines: list[dict], *, rates_version: int, answer: Optional[dict], parts: int) -> list[str]:
    """What the prices assume, in plain lines: each machine's running rate, the rates, where buy prices come from."""
    from src.costing.rates import build_rate_card

    out = []
    for m in machines:
        if _num(m.get("running_rate_usd")) is not None and _num(m.get("hourly_rate_usd")) is not None:
            share = round((m.get("capital_frac") or 0) * 100)
            typical = "" if m.get("capital_frac_set") else " (a typical share)"
            out.append(f"{m['name']}: ${m['hourly_rate_usd']:,.2f}/h you set, less {share}% that pays for the machine "
                       f"itself{typical}: ${m['running_rate_usd']:,.2f}/h running rate")
        elif m.get("name"):
            out.append(f"{m['name']}: no rate set, so the typical rate for its process")
    if rates_version:
        out.append(f"Rates: your published rates v{rates_version}.")
    else:
        labor = build_rate_card().g("labor_rate")
        out.append(f"Rates: ScaleCAD's typical rates (v0), labor ${labor:,.0f}/h; publish your own in Rates.")
    with_price = (answer or {}).get("with_price") or 0
    out.append(f"What you pay today: {with_price:,} of {parts:,} parts have a current price, from your parts list "
               "or typed on the part; the saving counts only those. Other buy prices are ScaleCAD's model of an "
               "outside shop, not quotes.")
    return out


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
    out.append("What you made is compared with ScaleCAD's estimate for the same part, method and quantity, before any "
               "calibration; what you paid a supplier with ScaleCAD's outside price at the same quantity, never with "
               "the cost of making it.")
    bought = summary.get("bought") or {}
    if bought.get("actuals"):
        out.append(f"{bought['actuals']} supplier {'invoice is' if bought['actuals'] == 1 else 'invoices are'} "
                   "kept apart from the figures for what you made, and none of them calibrates your machines.")
    if calibration:
        out.append("A calibration from your actuals is applied to new estimates; figures here are from before it, "
                   "and its effect was measured with each part held out.")
    if scope_kind == "all":
        out.append("Hours, material and cost for all parts are at each part's yearly quantity where it has one "
                   "its record priced, else at the quantity its page opens at.")
    out.append("Estimates are ScaleCAD's model of your machines and rates, not quotes.")
    return out


async def build_report(session: AsyncSession, org_id: str, run_id: Optional[str] = None) -> dict:
    from src.db.models import Batch, Organization
    from src.services import calibration_service as cal
    from src.services import rate_card_basis
    from src.services.catalog_run_service import (
        BUCKET_WORDS, _org_machines, bucket_breakdown, build_board, bucket_totals, make_or_buy_answer,
    )
    from src.services.machine_load_service import org_capacity, overloaded_words, with_capacity

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
        # The run's own records: its wins compare the prices the run sorted on.
        records = await _run_records(session, org_id, rows)
        scope = {"kind": "run", "run_id": batch.ulid, "created_at": board.get("created_at"),
                 "completed_at": board.get("completed_at"), "status": board.get("status"),
                 "quantity": board.get("quantity"), "material_class": board.get("material_class"),
                 "parts_list": board.get("parts_list")}
        totals = board["totals"]
        breakdown = board.get("breakdown") or bucket_breakdown(rows)
        # The run's own answer, the one its page leads with; with a parts list, the parts on it.
        scoped = [r for r in rows if r.get("listed")] if board.get("has_list") else rows
        answer = board.get("answer") or make_or_buy_answer(scoped)
        has_list = bool(board.get("has_list"))
        machines = board.get("machines") or []
    else:
        rows, records = await _rows_for_all_parts(session, org_id)
        keys = {r["part_key"] for r in rows if r.get("part_key")}
        scope = {"kind": "all", "run_id": None, "quantity": ALL_PARTS_QUANTITY}
        totals = bucket_totals(rows)
        breakdown = bucket_breakdown(rows)
        scoped = rows
        answer = make_or_buy_answer(rows)
        has_list = any(r.get("quantity_source") == "list" for r in rows)
        machines = await _org_machines(session, org_id)
    rates_version = rate_card_basis.in_effect(await rate_card_basis.org_rate_rows(session, org_id),
                                              datetime.now(timezone.utc))
    hours_by_machine = with_capacity(machine_hours(scoped), await org_capacity(session, org_id))

    # Resources first: each bucket's machine hours by machine (or by process outside),
    # material by grade, and for "needs a new machine" the capability missing.
    buckets = [{"key": k, "label": BUCKET_WORDS[k], **totals.get(k, {}), **breakdown.get(k, {})} for k in BUCKET_ORDER]
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
        # Page one: the run's answer as its page says it, what it covers, and what the prices assume.
        "answer": answer,
        "headline": answer_words(answer, has_list),
        "coverage": coverage(scoped),
        "basis": basis_lines(machines, rates_version=rates_version, answer=answer, parts=len(scoped)),
        "overloaded": overloaded_words(hours_by_machine),
        # The parts the answer is about (with a parts list, the ones on it), as the buckets count them.
        "parts": len(scoped),
        "files": len(rows),
        "buckets": buckets,
        "other": other,
        "in_house": {
            "parts": in_house.get("parts", 0),
            "hours": in_house.get("hours"),
            "hours_parts": in_house.get("hours_parts", 0),
            "mass_kg": in_house.get("mass_kg"),
            "mass_parts": in_house.get("mass_parts", 0),
            "used_kg": in_house.get("used_kg"),
            "used_parts": in_house.get("used_parts", 0),
            "cost_usd": in_house.get("cost_usd"),
            # Hours needed against each machine's hours a year (its schedule × count, else the default, said).
            "machines": hours_by_machine,
            "materials": (breakdown.get("in_house") or {}).get("materials", []),
        },
        # The capability parts lack: machines you'd need (none fits) and processes you don't own.
        "missing": (breakdown.get("new_machine") or {}).get("missing", []),
        "outside": (breakdown.get("outside") or {}).get("machines", []),
        "wins": wins(scoped, records),
        "decisions": (decisions := await _decisions(session, org_id, keys, names)),
        "signoffs": {
            "signed_off": sum(1 for d in decisions if d.get("signoff")),
            "out_of_date": sum(1 for d in decisions if (d.get("signoff") or {}).get("stale")),
            "recorded": len(decisions),
        },
        "accuracy": summary,
        # The figures only with enough actuals to say something (op-20); fewer are counted, not judged.
        "accuracy_shown": bool(summary.get("enough")),
        "bought_shown": bool((summary.get("bought") or {}).get("enough")),
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
    if f * 60 < 1:
        return f"{max(1, round(f * 3600))} s"
    if f < 1:
        return f"{f * 60:.1f} min" if f * 60 < 10 else f"{f * 60:.0f} min"
    return f"{f:,.1f} h" if f < 100 else f"{f:,.0f} h"


def _kg(v) -> str:
    f = _num(v)
    if f is None:
        return "—"
    if 0 < f < 0.01:  # a tiny part's grams, never "0.00 kg"
        return "<1 g" if f < 0.001 else f"{f * 1000:.1f} g"
    return f"{f:,.2f} kg" if f < 100 else f"{f:,.0f} kg"


def _pct(v) -> str:
    f = _num(v)
    if f is None:
        return "—"
    return f"{'+' if f > 0 else ''}{f:.0f}%"


def _proc(v) -> str:
    from src.services.catalog_run_service import process_words

    return process_words(v) if v else "—"


def _factor(v) -> str:
    f = _num(v)
    if f is None:
        return "—"
    return f"{_pct((f - 1) * 100)} (× {f:.2f})"


def _stale(v) -> str:
    from src.services.signoff_service import stale_words

    return stale_words(v)


_env.filters.update({"money": _money, "hours": _hours, "kg": _kg, "pct": _pct, "proc": _proc, "factor": _factor,
                     "stale": _stale})


def render_html(report: dict) -> str:
    return _env.get_template("pilot_report.html").render(r=report)


def _pdf_sync(html: str) -> bytes:
    from weasyprint import HTML

    return HTML(string=html, base_url=str(_TEMPLATE_DIR)).write_pdf()


async def render_pdf(report: dict) -> bytes:
    html = render_html(report)
    async with _pdf_semaphore:
        return await asyncio.get_event_loop().run_in_executor(None, _pdf_sync, html)
