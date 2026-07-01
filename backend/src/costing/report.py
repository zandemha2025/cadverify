"""Report rendering (spec §10) — the decision card + JSON sidecar.

render_text(report) -> human-readable decision card.
report_to_dict(report) -> JSON-serializable dict.

Every figure carries a provenance-tagged source; line items sum to the unit
total; no naked numbers.
"""

from __future__ import annotations

from dataclasses import asdict


def report_to_dict(report) -> dict:
    d = {
        "filename": report.filename,
        "status": report.status,
        "reason": report.reason,
        "geometry": report.geometry,
        "material_class": report.material_class,
        "quantities": report.quantities,
        "estimates": report.estimates,
        "engine_feasibility": report.engine_feasibility,
        "routing": getattr(report, "routing", None),
        "notes": report.notes,
        "assumptions": [
            {"name": a.name, "value": a.value, "unit": a.unit,
             "provenance": a.provenance.value, "source": a.source}
            for a in report.assumptions
        ],
        "decision": asdict(report.decision) if report.decision else None,
    }
    return d


def _fmt_money(x: float) -> str:
    return f"${x:,.2f}"


def render_text(report) -> str:
    L = []
    L.append(f"CadVerify Decision — {report.filename}")
    L.append("=" * 72)
    geo = report.geometry
    bbox = "×".join(f"{v:g}" for v in geo["bbox_mm"])
    wt = "✓" if geo["watertight"] else "✗"
    L.append(f"Geometry: {geo['volume_cm3']:g} cm³ · {bbox} mm · watertight {wt} · "
             f"{geo['face_count']} faces        [MEASURED]")

    if report.status == "GEOMETRY_INVALID":
        L.append("")
        L.append("GEOMETRY INVALID — repair required (volume ≤ 0 / non-watertight). "
                 "No cost produced.")
        L.append(f"  Reason: {report.reason}")
        L.append("")
        L.append(_feasibility_line(report))
        return "\n".join(L)

    L.append(f"Material class: {report.material_class}")

    rt = getattr(report, "routing", None)
    if rt:
        L.append("")
        L.append(f"GEOMETRIC ROUTING → {rt['recommended_process']} "
                 f"(archetype: {rt['archetype']}, confidence {rt['confidence']:g})")
        L.append(f"  {rt['reasoning']}")
        if rt.get("alternatives"):
            L.append(f"  alternatives: {', '.join(rt['alternatives'])}")
    L.append("")

    # group estimates by process
    by_proc = {}
    for e in report.estimates:
        by_proc.setdefault(e["process"], []).append(e)

    L.append("PROCESS OPTIONS (should-cost, USD)")
    for proc, ests in by_proc.items():
        ests = sorted(ests, key=lambda e: e["quantity"])
        head = ests[0]
        qty_bits = "   ".join(
            f"qty {e['quantity']}: {_fmt_money(e['unit_cost_usd'])}/unit" for e in ests)
        flag = "" if head["dfm_ready"] else "  ⚠ NOT DFM-ready as-modeled (design-for-process required)"
        L.append(f"  {proc} / {head['material']}    {qty_bits}    "
                 f"±{head['est_error_band_pct']:g}%{flag}")
        # itemized drivers for the smallest-qty estimate
        for d in head["drivers"]:
            if d["name"] in ("cycle_time",):
                continue
            band = f" ±{d['error_band_pct']:g}%" if d.get("error_band_pct") else ""
            L.append(f"      {d['name']:<16} {_fmt_value(d)}  "
                     f"[{d['provenance']} {d['source']}{band}]")
        # line-item sum check shown (dynamic — handles min_charge_floor when it bites)
        li = head["line_items"]
        parts = " + ".join(f"{k} {_fmt_money(v)}" for k, v in li.items())
        L.append(f"      line items Σ = {_fmt_money(sum(li.values()))} (= {parts})")
        ci = head.get("confidence")
        if ci:
            tag = "MEASURED" if ci.get("validated") else (ci.get("label") or ci.get("method"))
            L.append(f"      confidence {int(ci['level']*100)}%: "
                     f"{_fmt_money(ci['low_usd'])}–{_fmt_money(ci['high_usd'])}/unit "
                     f"(±{ci['half_width_pct']:g}%) [{tag}; {ci['basis']}]")
        if "min_charge_floor" in li:
            L.append(f"      ↳ min charge floor applied (+{_fmt_money(li['min_charge_floor'])}/unit "
                     f"— order below shop minimum)")
        lt = head["lead_time"]
        c = lt["components"]
        comp = " + ".join(f"{k} {int(v)}" for k, v in c.items() if v)
        cap = lt.get("capacity", {})
        cap_str = ""
        if cap:
            cap_str = (f" · capacity {cap['n_machines']} machines × "
                       f"{cap['machine_hours_per_day']:g} hr/day [{cap['provenance']}]")
        L.append(f"      lead time qty {head['quantity']}: "
                 f"{lt['low_days']:g}–{lt['high_days']:g} days [{comp}]{cap_str}")
        if head["dfm_blockers"]:
            L.append(f"      DFM blockers: {head['dfm_blockers'][0]}")
        L.append("")

    # DECISION
    dec = report.decision
    if dec:
        L.append("DECISION")
        L.append(f"  {dec.note}")
        for q in report.quantities:
            r = dec.recommendation.get(q)
            if not r:
                continue
            lead = ""
            if r.get("lead_low_days") is not None:
                lead = f", {r['lead_low_days']:g}–{r['lead_high_days']:g} d"
            L.append(f"  @ qty {q:<6} → {r['process']} / {r['material']} "
                     f"({_fmt_money(r['unit_cost_usd'])}/unit{lead})  (make-as-is, recommended)")
            alt = (dec.if_redesigned or {}).get(q)
            if alt:
                cav = f" ({alt['caveat']})" if alt.get("caveat") else ""
                tag = "← crossover" if dec.crossover_qty and alt["process"] == dec.tooling_process else ""
                L.append(f"             cheaper if redesigned: {alt['process']} "
                         f"{_fmt_money(alt['unit_cost_usd'])}/unit{cav} {tag}".rstrip())
        L.append("")

    # ASSUMPTIONS
    L.append("ASSUMPTIONS (DEFAULT = generic fallback · SHOP = your calibrated profile "
             "· USER = ad-hoc override; every one editable)")
    a_bits = " · ".join(
        f"{a.name} {_fmt_assumption(a)} [{a.provenance.value}]" for a in report.assumptions)
    L.append(f"  {a_bits}")
    for n in report.notes:
        L.append(f"  • {n}")
    L.append("")
    L.append(_feasibility_line(report))
    return "\n".join(L)


def _fmt_value(d) -> str:
    if d["unit"] == "$":
        return _fmt_money(d["value"])
    if d["unit"] in ("hr", "×", "kg"):
        return f"{d['value']:g} {d['unit']}"
    return f"{d['value']:g} {d['unit']}"


def _fmt_assumption(a) -> str:
    if a.unit == "$/hr":
        return f"${a.value:g}/hr"
    if a.unit in ("×", "frac", "hr/day", "cav"):
        suffix = "" if a.unit == "frac" else a.unit
        return f"{a.value:g}{suffix}"
    return f"{a.unit}"


def _feasibility_line(report) -> str:
    bits = []
    for f in report.engine_feasibility:
        tag = "" if f["costed"] else "*"
        bits.append(f"{f['process']} {f['verdict']}({f['score']:g}){tag}")
    return ("ENGINE FEASIBILITY (DFM, all processes; * = feasibility-only, not costed):\n  "
            + " · ".join(bits))
