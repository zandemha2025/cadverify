"use client";

/**
 * Cost: what the part takes on each route, then its price. Machine time (each and for the run), the material it
 * uses (mass, volume, grade) and whose machine it runs on lead; the model price and its range follow. A chart you
 * can drag, every process at the quantity, where the money goes, tooling, and the way into the cost breakdown.
 */
import * as React from "react";
import { howText } from "../fix/problems";
import Link from "next/link";
import { R } from "../routes";
import { Empty, cx } from "../ui";
import { usePart } from "./ctx";
import {
  VERDICT_LABEL,
  biggestTypicalNote,
  chartModel,
  cheapestAt,
  costLines,
  days,
  groundedCount,
  isPriced,
  money,
  otherQtyNote,
  shouldCostWords,
  priceAt,
  qtyWord,
  replacedBy,
  trimNum,
  type Method,
} from "./model";
import { RunNotice, SheetTop, type FigItem } from "./sheet-bits";
import { useFix } from "../fix/ctx";
import { problemForIssue } from "../fix/problems";
import { wbHref } from "../workbench/chrome";
import { followed, recordedChoice } from "./choice";
import { PartActuals } from "../validation/part-actuals";
import { cm3Text, hoursText, massText, materialShort, ownershipOf, routeResources, type RouteResources } from "./resources";

/** The process the chart and its lines show: one you picked here, else your choice for the part, else ScaleCAD's pick, else the cheapest. */
export function useChartSel(): Method | null {
  const p = usePart();
  const picked = p.costPick ? p.methods.find((m) => m.code === p.costPick && isPriced(m)) ?? null : null;
  const f = followed(p.data.cost, p.q, recordedChoice(p.data.decision));
  const follows = f ? p.methods.find((m) => m.code === f.process && isPriced(m) && m.prices.has(p.q)) ?? null : null;
  return picked ?? follows ?? cheapestAt(p.methods, p.q) ?? p.methods.find((m) => isPriced(m) && m.prices.has(p.q)) ?? null;
}

export function CostLayer() {
  const p = usePart();
  const sel = useChartSel();
  const on = p.lens === "cost" && !p.costOff && !p.interrupted && !!p.data.cost;
  const d = p.data.cost?.decision ?? null;
  const chart = React.useMemo(
    () => chartModel(p.methods, p.qs, p.q, sel?.code ?? null, d?.tooling_process && d.crossover_qty ? d.crossover_qty : null),
    [p.methods, p.qs, p.q, sel, d],
  );
  const drag = React.useRef(false);
  const fromEvent = (e: React.PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const x = ((e.clientX - r.left) * chart.width) / Math.max(1, r.width);
    return chart.qFromX(x);
  };
  const qi = p.qs.indexOf(p.q);
  const priced = p.methods.filter(isPriced);
  const lblY = sel && priceAt(sel, p.q) != null ? chart.y(priceAt(sel, p.q)!) : null;
  const selHours = routeResources(sel?.prices.get(p.q), null)?.hoursEach ?? null;
  const crossName = d?.tooling_process ? p.methods.find((m) => m.code === d.tooling_process)?.name.toLowerCase() ?? "tooling" : "tooling";
  return (
    <div className={cx("layer", !on && "off")} style={{ left: 64, top: 270, width: 800, height: 480 }} aria-hidden={!on}>
      <div className="card" style={{ position: "absolute", inset: 0, padding: "16px 18px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
          <b style={{ fontWeight: 600 }}>Cost each, by how many you make</b>
          <span className="seg" role="group" aria-label="Quantity">
            {p.qs.map((qq) => (
              <button key={qq} type="button" className={cx("num", qq === p.q && !p.oq && "on")} aria-pressed={qq === p.q && !p.oq} tabIndex={on ? 0 : -1} onClick={() => { p.setQ(qq); p.setOq(""); }}>
                {qtyWord(qq)}
              </button>
            ))}
          </span>
        </div>
        <div style={{ position: "relative", width: 760, height: 400, marginTop: 6 }}>
          <svg width="760" height="400" viewBox="0 0 760 400" aria-hidden="true" style={{ position: "absolute", left: 0, top: 0 }}>
            <path d={chart.gridY.map((g) => `M40 ${g.y.toFixed(1)} H740`).join(" ")} stroke="#E3E6EA" strokeWidth="1" fill="none" />
            {chart.crossoverX != null ? <line x1={chart.crossoverX} x2={chart.crossoverX} y1="16" y2="340" stroke="#7A4FD6" strokeOpacity="0.7" strokeWidth="1" strokeDasharray="2 4" /> : null}
            <line x1={chart.x(p.q)} x2={chart.x(p.q)} y1="16" y2="340" stroke="#141414" strokeOpacity="0.18" strokeWidth="2" />
            {chart.lines.map((l) => (
              <g key={l.code}>
                <polyline points={l.pts} fill="none" stroke={l.stroke} strokeWidth={l.w} strokeDasharray={l.dash} strokeLinejoin="round" strokeLinecap="round" />
                {l.cy != null ? <circle cx={l.cx} cy={l.cy} r={l.r} fill={l.stroke} stroke="#fff" strokeWidth="2" /> : null}
              </g>
            ))}
          </svg>
          {chart.gridY.map((g) => (
            <span key={g.label} className="num" style={{ position: "absolute", right: 726, top: g.y - 8, fontSize: 11.5, color: "var(--ink3)" }}>
              {g.label}
            </span>
          ))}
          {chart.gridX.map((g) => (
            <span key={g.label} className="num" style={{ position: "absolute", left: g.x, top: 352, transform: "translateX(-50%)", fontSize: 12, color: "var(--ink3)" }}>
              {g.label}
            </span>
          ))}
          {chart.crossoverX != null && d?.crossover_qty ? (
            <span className="num" style={{ position: "absolute", left: chart.crossoverX, top: 18, transform: "translateX(6px)", fontSize: 11.5, color: "#7A4FD6", whiteSpace: "nowrap" }}>
              {crossName} crossover ≈ {qtyWord(Math.round(d.crossover_qty))}
            </span>
          ) : null}
          <span style={{ position: "absolute", left: 40, top: 376, display: "flex", gap: 16, fontSize: 11.5, color: "var(--ink3)" }}>
            <span>
              <b style={{ display: "inline-block", width: 16, height: 3, borderRadius: 2, background: "#141414", verticalAlign: 3 }} /> picked
            </span>
            <span>
              <b style={{ display: "inline-block", width: 16, height: 2, background: "#5B3FC4", verticalAlign: 3 }} /> on your machine
            </span>
            <span>
              <b style={{ display: "inline-block", width: 16, borderTop: "2px dashed #7A4FD6", verticalAlign: 3 }} /> only after a design change
            </span>
          </span>
          <span style={{ position: "absolute", right: 20, top: 376, fontSize: 11.5, color: "var(--ink3)" }}>parts per order, log scale</span>
          {sel && lblY != null ? (
            <span className="lbl num" style={{ left: chart.x(p.q), top: lblY }}>
              {sel.name} · {selHours != null ? `${hoursText(selHours)} · ` : ""}
              {money(priceAt(sel, p.q))}
            </span>
          ) : null}
          <div
            className="chart-hit"
            role="slider"
            tabIndex={on ? 0 : -1}
            aria-label="Quantity"
            aria-valuemin={p.qs[0]}
            aria-valuemax={p.qs[p.qs.length - 1]}
            aria-valuenow={p.q}
            aria-valuetext={`${qtyWord(p.q)} parts; cheapest ${sel ? `${sel.name.toLowerCase()} at ${money(priceAt(sel, p.q))}` : "none"}; ${priced.length} methods priced`}
            onPointerDown={(e) => {
              drag.current = true;
              e.currentTarget.setPointerCapture?.(e.pointerId);
              const qq = fromEvent(e);
              if (qq !== p.q) p.setQ(qq);
              p.setOq("");
            }}
            onPointerMove={(e) => {
              if (!drag.current) return;
              const qq = fromEvent(e);
              if (qq !== p.q) p.setQ(qq);
            }}
            onPointerUp={() => (drag.current = false)}
            onPointerCancel={() => (drag.current = false)}
            onKeyDown={(e) => {
              const step = e.key === "ArrowRight" || e.key === "ArrowUp" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowDown" ? -1 : 0;
              if (!step && e.key !== "Home" && e.key !== "End") return;
              e.preventDefault();
              const i = e.key === "Home" ? 0 : e.key === "End" ? p.qs.length - 1 : Math.max(0, Math.min(p.qs.length - 1, qi + step));
              p.setQ(p.qs[i]);
              p.setOq("");
            }}
          />
        </div>
      </div>
    </div>
  );
}

export function CostLines({ estimate, where }: { estimate: NonNullable<ReturnType<Method["prices"]["get"]>>; where: string }) {
  const [open, setOpen] = React.useState<string | null>(null);
  // Every line, so they add up to the price above them (ce-01).
  const lines = costLines(estimate);
  const g = groundedCount(estimate);
  const note = biggestTypicalNote(estimate, where);
  if (!lines.length) return null;
  return (
    <>
      <div className="gh">
        <span>
          Where the {money(estimate.unit_cost_usd)} comes from, at {qtyWord(estimate.quantity)}
        </span>
        <span>
          {g.grounded} of {g.total} from your file or shop
        </span>
      </div>
      <div className="lines">
        {lines.map((l) => (
          <React.Fragment key={l.key}>
            <button type="button" className="ln btnln" aria-expanded={open === l.key} onClick={() => setOpen(open === l.key ? null : l.key)}>
              <span>
                {open === l.key ? "▾" : "▸"} {l.name}
              </span>
              <span className={`src s-${l.src.kind}`}>{l.src.label}</span>
              <b className="num">{money(l.value)}</b>
            </button>
            {open === l.key ? (
              <span className="lnhow swap">
                <span className="num">{howText(l.how)}</span>
                <br />
                <span style={{ color: "var(--ink3)" }}>{l.band}</span>
              </span>
            ) : null}
          </React.Fragment>
        ))}
      </div>
      {note ? (
        <div className="note">
          <b>{note.title}</b>
          <span>{note.text}</span>
          <span>
            <Link className="btn sm" href={R.rates}>
              {lines[0].key === "labor_cost" ? "Add your labor rate" : "Add your rates"}
            </Link>
          </span>
        </div>
      ) : null}
    </>
  );
}

/** Why the sheet shows this route: picked here, your recorded choice, ScaleCAD's pick, or the cheapest. */
function selWhy(p: ReturnType<typeof usePart>, sel: Method): string {
  if (p.costPick === sel.code) return "picked here";
  const choice = recordedChoice(p.data.decision);
  if (choice?.process === sel.code) return "your choice";
  const f = followed(p.data.cost, p.q, choice);
  if (f?.process === sel.code) return "ScaleCAD’s pick";
  return cheapestAt(p.methods, p.q)?.code === sel.code ? "cheapest" : "";
}

/** The sheet's top: what the shown route takes at this quantity (machine time, material, whose machine), then its price and range. */
export function costTop(p: ReturnType<typeof usePart>, sel: Method | null): { title: string; meta: string; figs: FigItem[] } {
  if (p.costOff) return { title: "Cost per part", meta: "Prices didn’t finish", figs: [] };
  const e = sel?.prices.get(p.q) ?? null;
  if (!sel || !e) return { title: "Cost per part", meta: "Machine time, material and price by process · model estimates, not quotes", figs: [] };
  const r = routeResources(e, p.data.cost?.geometry?.volume_cm3 ?? null);
  const d = p.data.cost?.decision ?? null;
  const own = ownershipOf(sel, r, p.data.machines, d?.tooling_process === sel.code ? d.crossover_qty : null);
  const figs: FigItem[] = [];
  const many = p.q > 1 ? ` for ${qtyWord(p.q)}` : "";
  figs.push({
    k: "Machine time",
    v: r?.hoursEach != null ? hoursText(r.hoursEach) : "Not estimated",
    s: r?.hoursEach != null
      ? `each${r.hoursFirstLot != null ? " on average" : ""}${r.hoursRun != null && p.q > 1 ? ` · ${hoursText(r.hoursRun)}${many}` : ""}${r.hoursFirstLot != null ? ` · ${hoursText(r.hoursFirstLot)} each on the first lot, shorter with practice` : ""}`
      : undefined,
  });
  figs.push({
    k: "Material",
    v: r?.kgEach != null ? massText(r.kgEach) : e.material,
    s: r?.kgEach != null ? `${materialShort(r)} each${r.kgRun != null && p.q > 1 ? ` · ${massText(r.kgRun)}${many}` : ""}` : r?.partCm3 != null ? `part ${cm3Text(r.partCm3)}` : undefined,
  });
  figs.push({ k: "Machine", v: own.v, s: own.s, tone: own.kind === "owned" ? "ok" : undefined });
  const lo = e.confidence?.low_usd;
  const hi = e.confidence?.high_usd;
  figs.push({
    k: "Price each",
    v: money(e.unit_cost_usd),
    s: lo != null && hi != null ? `${money(lo)}–${money(hi)} · ±${trimNum(e.confidence!.half_width_pct, 0)}%, ${e.confidence!.validated ? "checked against your jobs" : "typical values"}` : undefined,
  });
  const why = selWhy(p, sel);
  return { title: "Cost per part", meta: `${sel.name} at ${qtyWord(p.q)}${why ? `, ${why}` : ""} · drag the chart or pick a process · model estimates, not quotes`, figs };
}

/** The price comparison under the routes: the cheapest at this quantity, its range, and your choice or your machine. */
function priceFigs(p: ReturnType<typeof usePart>): FigItem[] {
  const figs: FigItem[] = [];
  const c = cheapestAt(p.methods, p.q);
  if (c) {
    const e = c.prices.get(p.q)!;
    figs.push({ k: `Cheapest at ${qtyWord(p.q)}`, v: money(e.unit_cost_usd), s: c.name });
    const lo = e.confidence?.low_usd;
    const hi = e.confidence?.high_usd;
    if (lo != null && hi != null) figs.push({ k: "Range", v: `${money(lo)}–${money(hi)}`, s: `±${trimNum(e.confidence!.half_width_pct, 0)}%, ${e.confidence!.validated ? "checked against your jobs" : "typical values"}` });
  }
  const choice = recordedChoice(p.data.decision);
  const mine = choice ? p.methods.find((m) => m.code === choice.process && m.prices.has(p.q)) ?? null : null;
  const ih = p.methods.find((m) => m.inHouse && m.prices.has(p.q));
  if (mine && mine.code !== c?.code) figs.push({ k: "Your choice", v: money(priceAt(mine, p.q)), s: `${mine.name}${mine.inHouse ? ` · your ${mine.inHouse}` : " · outside"}` });
  else if (ih) figs.push({ k: ih.inHouse!, v: money(priceAt(ih, p.q)), s: `in-house · ${days(ih.prices.get(p.q)!.lead_time?.low_days, ih.prices.get(p.q)!.lead_time?.high_days)}` });
  return figs;
}

/** One route's row line: "MJF · 33 min · your HP Jet Fusion 5200 · 24 g PA12", "FDM/FFF · 31 min · 13.6 g PLA · outside". */
function rowLine(m: Method, r: RouteResources | null, material: string): string {
  const bits: string[] = [m.short];
  if (r?.hoursEach != null) bits.push(hoursText(r.hoursEach));
  if (m.inHouse) bits.push(`your ${m.inHouse}`);
  bits.push(r?.kgEach != null ? `${massText(r.kgEach)} ${material}` : material);
  if (!m.inHouse) bits.push("outside");
  return bits.join(" · ");
}

function insightOf(p: ReturnType<typeof usePart>, fx: ReturnType<typeof useFix>) {
  const d = p.data.cost?.decision ?? null;
  const qs = p.qs;
  const qMax = qs[qs.length - 1];
  const tooling = d?.tooling_process ? p.methods.find((m) => m.code === d.tooling_process) ?? null : null;
  if (tooling && d?.crossover_qty) {
    const atMax = priceAt(tooling, qMax);
    const blocked = tooling.verdict === "bad";
    return {
      title: `${tooling.name} is cheaper from about ${qtyWord(Math.round(d.crossover_qty))} parts`,
      text: `${atMax != null ? `${money(atMax)} each at ${qtyWord(qMax)} by ${tooling.name.toLowerCase()}` : tooling.name}${blocked ? `, once what blocks it is fixed (${tooling.blockedReason ?? "see Process"})` : ""}. Below that the tooling doesn’t pay back.`,
      btn: blocked ? "Show what blocks it" : "See it in Process",
      go: () => {
        p.setSel(tooling.code);
        // What blocks the tooling process opens on the part, for that process.
        const why = blocked ? problemForIssue(fx.set, tooling.finding?.issue.code) ?? fx.set.problems.find((x) => x.blocks.includes(tooling.code)) ?? null : null;
        if (why) fx.openProblem(why.id, tooling.code);
        else p.setLens("make");
      },
    };
  }
  const first = cheapestAt(p.methods, qs[0]);
  const rest = qs.slice(1).map((qq) => cheapestAt(p.methods, qq)?.code ?? null);
  const steady = rest.length && rest.every((c) => c && c === rest[0]) ? p.methods.find((m) => m.code === rest[0]) ?? null : null;
  const ih = p.methods.find((m) => m.inHouse && m.prices.has(p.q));
  if (steady) {
    const q2 = qs[Math.min(2, qs.length - 1)];
    const parts = [`${money(priceAt(steady, q2))} each at ${qtyWord(q2)}.`];
    if (first && first.code !== steady.code) parts.push(`${first.name} is cheapest for ${qs[0] === 1 ? "a single part" : `${qtyWord(qs[0])} parts`}, at ${money(priceAt(first, qs[0]))}.`);
    if (ih) parts.push(`Your ${ih.inHouse} is ${money(priceAt(ih, p.q))} at ${qtyWord(p.q)}.`);
    return {
      title: `${steady.name} stays cheapest from ${qtyWord(qs[1])} parts up`,
      text: parts.join(" "),
      btn: ih ? `Compare with your ${ih.inHouse}` : "See the processes",
      go: () => p.setLens(ih ? "shop" : "make"),
    };
  }
  const c = cheapestAt(p.methods, p.q);
  if (!c) return null;
  return {
    title: `${c.name} is cheapest at ${qtyWord(p.q)}`,
    text: `The cheapest process changes with quantity: ${qs.map((qq) => `${qtyWord(qq)}: ${cheapestAt(p.methods, qq)?.name.toLowerCase() ?? "none"}`).join("; ")}.`,
    btn: "See the processes",
    go: () => p.setLens("make"),
  };
}

export function CostSheet() {
  const p = usePart();
  const sel = useChartSel();
  const [toolOpen, setToolOpen] = React.useState(false);
  const [engOpen, setEngOpen] = React.useState(false);
  const top = costTop(p, sel);
  const cost = p.data.cost;
  const priced = p.methods.filter((m) => isPriced(m) && m.prices.has(p.q));
  const ranked = [...priced].sort((a, b) => priceAt(a, p.q)! - priceAt(b, p.q)!);
  const order = new Map(ranked.map((m, i) => [m.code, i]));
  const stable = [...priced].sort((a, b) => a.code.localeCompare(b.code));
  const oq = otherQtyNote(p.methods, p.qs, p.oq);
  const oqRaw = Number.parseInt(p.oq, 10);
  const oqN = Number.isFinite(oqRaw) && oqRaw >= 1 && oqRaw <= 1_000_000 ? oqRaw : null;
  // A check prices six quantities: say which one a new quantity replaces before pricing it (ce-08).
  const oqOut = oqN != null ? replacedBy(p.data.cost?.quantities ?? [], oqN) : null;
  const fx = useFix();
  const insight = cost ? insightOf(p, fx) : null;
  const d = cost?.decision ?? null;
  const tooling = d?.tooling_process ? p.methods.find((m) => m.code === d.tooling_process) ?? null : null;
  const qMax = p.qs[p.qs.length - 1];
  const tMax = tooling?.prices.get(qMax) ?? null;
  const cheapest = cheapestAt(p.methods, p.q);
  const ctx = p.data.context;
  const annual = ctx?.resolved_annual_volume ?? ctx?.annual_volume ?? null;
  const selEst = sel?.prices.get(p.q) ?? null;
  const vol = cost?.geometry?.volume_cm3 ?? null;
  const pf = priceFigs(p);
  const selRes = routeResources(selEst, vol);
  const own = sel && selEst ? ownershipOf(sel, selRes, p.data.machines, d?.tooling_process === sel.code ? d.crossover_qty : null) : null;
  const annualRes = annual != null && p.qs.includes(annual) && cheapestAt(p.methods, annual) ? routeResources(cheapestAt(p.methods, annual)!.prices.get(annual), vol) : null;
  return (
    <>
      <SheetTop {...top} sure="cost" route={sel?.code ?? null} />
      <div className="scroll">
        <RunNotice />
        {p.askedQty != null && cost ? (
          <p className="note" role="status">
            <span>
              This check priced {p.qs.map(qtyWord).join(", ")}, not {qtyWord(p.askedQty)}. Showing {qtyWord(p.q)}, the nearest.{" "}
              {p.canRecheck ? (
                <button className="btn sm" type="button" disabled={p.checking} onClick={() => p.recheck({ qty: p.askedQty! })}>
                  Price {qtyWord(p.askedQty)}
                </button>
              ) : (
                `Drop the file on the part to price ${qtyWord(p.askedQty)}.`
              )}
            </span>
          </p>
        ) : null}
        {p.interrupted || p.costOff ? null : !cost ? (
          <Empty
            title={p.checking ? "Pricing…" : "Not priced yet"}
            actions={
              !p.checking && p.canRecheck ? (
                <button className="btn ink sm" type="button" onClick={() => p.recheck()}>
                  Price it
                </button>
              ) : undefined
            }
          >
            {p.checking ? "Prices arrive with the record." : p.canRecheck ? "This part has an analysis but no priced record. Pricing it uses the file kept with the part, in your machines and conditions · no check used." : "This part has an analysis but no priced record. Drop the file on the part to price it."}
          </Empty>
        ) : (
          <div className="swap">
            <div className="gh">
              <span>At {qtyWord(p.q)}, cheapest first</span>
              <span>price each</span>
            </div>
            <div className="rank" style={{ height: priced.length * 56 }}>
              {stable.map((m) => {
                const line = rowLine(m, routeResources(m.prices.get(p.q), vol), m.prices.get(p.q)!.material);
                return (
                <button
                  key={m.code}
                  type="button"
                  className={cx("mr", sel?.code === m.code && "on")}
                  aria-pressed={sel?.code === m.code}
                  onClick={() => {
                    p.setCostPick(m.code);
                    p.setSel(m.code);
                  }}
                  style={{ transform: `translateY(${(order.get(m.code) ?? 0) * 56}px)` }}
                >
                  <span>
                    <b>{m.name}</b>
                    <small className="num" title={line}>
                      {line}
                    </small>
                  </span>
                  <span className={`chip c-${m.verdict === "bad" ? "bad" : m.verdict}`}>
                    <i />
                    {m.verdict === "bad" ? "If redesigned" : VERDICT_LABEL[m.verdict]}
                  </span>
                  <span className="c num">{money(priceAt(m, p.q))}</span>
                </button>
                );
              })}
            </div>
            {pf.length ? (
              <>
                <div className="gh" style={{ marginTop: 4 }}>
                  <span>Price at {qtyWord(p.q)}</span>
                  <span>each</span>
                </div>
                <div className="kv">
                  {pf.map((f) => (
                    <React.Fragment key={f.k}>
                      <span>
                        {f.k}
                        {f.s ? <small style={{ display: "block", fontSize: 12 }}>{f.s}</small> : null}
                      </span>
                      <b className="num">{f.v}</b>
                    </React.Fragment>
                  ))}
                </div>
              </>
            ) : null}
            {own && sel && own.kind !== "owned" ? (
              <div className="note">
                <b>
                  {own.kind === "not_owned"
                    ? `${sel.name} isn’t on a machine you own`
                    : own.kind === "no_machines"
                      ? "No machines of yours to compare"
                      : own.kind === "unconfirmed"
                        ? `${sel.name} isn’t confirmed on a machine of yours`
                        : `${sel.name} doesn’t fit a machine of yours as declared`}
                </b>
                <span>
                  {own.kind === "no_machines"
                    ? "Add your machines and their rates: a route on a machine you own is priced at its running cost, with the machine itself already paid for."
                    : own.kind === "unconfirmed"
                      ? `${own.s[0].toUpperCase()}${own.s.slice(1)}. Declare what it needs in Your shop, or check the part again, to price it at your running cost.`
                      : `${own.s[0].toUpperCase()}${own.s.slice(1)}. ScaleCAD doesn’t price machines, so no purchase cost or payback is shown for one${d?.tooling_process === sel.code && d.crossover_qty ? "; the payback above is the mold or die against routes without tooling" : ""}.`}
                </span>
                <span style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {own.kind === "no_machines" ? (
                    <Link className="btn sm" href={`${R.shop}?add=1`}>
                      Add machines
                    </Link>
                  ) : own.kind === "not_owned" ? (
                    <Link className="btn sm" href={R.triage}>
                      Weigh a new machine
                    </Link>
                  ) : (
                    <button className="btn sm" type="button" onClick={() => p.setLens("shop")}>
                      See your machines
                    </button>
                  )}
                </span>
              </div>
            ) : null}
            <p style={{ margin: "6px 12px 0", color: "var(--ink3)", fontSize: 12.5 }}>
              {cheapest ? `${days(cheapest.prices.get(p.q)!.lead_time?.low_days, cheapest.prices.get(p.q)!.lead_time?.high_days)} for the cheapest. ` : ""}
              {p.methods.some((m) => m.inHouse && m.prices.has(p.q)) ? "In-house lead time is print time on the machines you declared, with no shipping; your own queue isn’t included. " : ""}
              Outside lead times are a queue model, not a quote. {shouldCostWords(cost?.assumptions)}
            </p>
            {p.data.key ? <PartActuals partKey={p.data.key} /> : null}
            <div style={{ display: "grid", gridTemplateColumns: "132px minmax(0,1fr)", gap: 10, alignItems: "end", padding: "10px 12px 0" }}>
              <label className="field">
                Other quantity
                <input
                  type="number"
                  min={1}
                  step={1}
                  inputMode="numeric"
                  placeholder="250"
                  value={p.oq}
                  onChange={(e) => p.setOq(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key !== "Enter" || oqN == null) return;
                    e.preventDefault();
                    // A quantity this record already priced is shown (op-08: 800 + Enter stayed at 100);
                    // a new one is priced, as its button does.
                    if (p.qs.includes(oqN)) {
                      p.setQ(oqN);
                      p.setOq("");
                    } else if (oq.on && p.canRecheck && !p.checking) p.recheck({ qty: oqN });
                  }}
                  onBlur={() => {
                    if (oqN != null && p.qs.includes(oqN)) {
                      p.setQ(oqN);
                      p.setOq("");
                    }
                  }}
                />
              </label>
              <span className="num" style={{ fontSize: 12.5, color: "var(--ink2)", paddingBottom: 9, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }} aria-live="polite">
                <span>{oq.text}</span>
                {oq.on && oqN != null ? (
                  p.canRecheck ? (
                    <>
                      <button className="btn sm ink" type="button" disabled={p.checking} onClick={() => p.recheck({ qty: oqN })}>
                        {p.checking ? `Pricing ${qtyWord(oqN)}…` : oqOut != null ? `Price ${qtyWord(oqN)} in place of ${qtyWord(oqOut)}` : `Price ${qtyWord(oqN)}`}
                      </button>
                      {oqOut != null && !p.checking ? (
                        <span style={{ flexBasis: "100%", color: "var(--ink3)" }}>
                          A check prices six quantities, so {qtyWord(oqOut)} gives way. Its price stays on the earlier record.
                        </span>
                      ) : null}
                    </>
                  ) : (
                    <span>Drop the file on the part to price {qtyWord(oqN)}.</span>
                  )
                ) : null}
              </span>
            </div>
            {insight ? (
              <div className="note">
                <b>{insight.title}</b>
                <span>{insight.text}</span>
                <span style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <button className="btn sm" type="button" onClick={insight.go}>
                    {insight.btn}
                  </button>
                  {tooling ? (
                    <button className="btn sm" type="button" aria-expanded={toolOpen} onClick={() => setToolOpen((o) => !o)}>
                      Tooling payback
                    </button>
                  ) : null}
                </span>
                {toolOpen && tooling ? (
                  <>
                    <span className="kv swap" style={{ padding: "4px 0 0" }}>
                      <span>{tooling.verdict === "bad" ? `${tooling.name}, after redesign` : tooling.name}</span>
                      <b className="num">{tMax ? `${money(tMax.unit_cost_usd)} at ${qtyWord(qMax)}` : "—"}</b>
                      <span>Crossover against no-tooling routes</span>
                      <b className="num">{d?.crossover_qty ? `≈ ${qtyWord(Math.round(d.crossover_qty))} parts` : "None found"}</b>
                      <span>Tooling, spread over the order</span>
                      <b className="num">{tMax ? `≈ ${money(tMax.fixed_cost_usd)}` : "—"}</b>
                      <span>Ready to quote today</span>
                      <b>{d?.tooling_dfm_ready ? "Yes" : `No: ${tooling.blockedReason ?? "blocked by DFM"}`}</b>
                    </span>
                    <span>
                      <Link href={R.triage}>Weigh buying the capability</Link>
                    </span>
                  </>
                ) : null}
              </div>
            ) : null}
            {selEst ? <CostLines estimate={selEst} where={sel?.inHouse ? "in-house" : "process’s"} /> : null}
            {p.data.key && p.data.decisionId ? (
              <div className="note">
                <b>Cost breakdown</b>
                <span>Every line of this price, its source and rate; change a rate, compare processes and quantities, save scenarios.</span>
                <span>
                  <Link className="btn sm" href={wbHref("glass", p.data.key, { decision: p.data.decisionId, proc: sel?.code, q: p.q })}>
                    Open the cost breakdown
                  </Link>
                </span>
              </div>
            ) : null}
            <div className="gh" style={{ marginTop: 4 }}>
              <span>Yearly volume</span>
              <span>{p.data.key ? <Link href={R.partHistory(p.data.key)}>Declare</Link> : null}</span>
            </div>
            <p style={{ margin: "0 12px", color: "var(--ink3)", fontSize: 12.5 }}>
              {annual == null
                ? "Not declared, so no cost per year is shown. Prices are per order."
                : p.qs.includes(annual) && cheapestAt(p.methods, annual)
                  ? `${qtyWord(annual)} a year (${ctx?.annual_volume_basis === "bom_rollup" ? "from your BOM" : "declared"}): ${annualRes?.hoursRun != null ? `${hoursText(annualRes.hoursRun)} machine time${annualRes.kgRun != null ? ` and ${massText(annualRes.kgRun)} of ${annualRes.grade}` : ""}, ` : ""}${money(priceAt(cheapestAt(p.methods, annual)!, annual)! * annual)} a year by ${cheapestAt(p.methods, annual)!.name.toLowerCase()}.`
                  : `${qtyWord(annual)} a year (${ctx?.annual_volume_basis === "bom_rollup" ? "from your BOM" : "declared"}). Not a computed quantity in this record, so no cost per year is shown; a new check prices it exactly.`}
            </p>
            {d?.note ? (
              <>
                <div className="gh" style={{ marginTop: 4 }}>
                  <span>Note from the cost model</span>
                  <span>
                    <button className="btn sm ghost" type="button" aria-expanded={engOpen} onClick={() => setEngOpen((o) => !o)} style={{ height: 24 }}>
                      {engOpen ? "Hide" : "Show"}
                    </button>
                  </span>
                </div>
                {engOpen ? <p className="engnote mono swap">{d.note}</p> : null}
              </>
            ) : null}
          </div>
        )}
      </div>
    </>
  );
}
