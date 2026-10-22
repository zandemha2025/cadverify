"use client";

/** Shop: your machines, whether each can make it and why, and the part drawn to scale inside one. */
import * as React from "react";
import Link from "next/link";
import { R } from "../routes";
import { Empty, cx } from "../ui";
import { usePart } from "./ctx";
import { dimsText, machineViews, money, priceMeta, qtyWord, type MachineView } from "./model";
import { CostLines } from "./lens-cost";
import { RunNotice, SheetTop, useShopChange, type FigItem } from "./sheet-bits";
import { asOfCheck } from "./shop-change";
import { useChoice } from "./choose";
import { hoursText, massText, routeResources, runLine } from "./resources";
import { useFix } from "../fix/ctx";
import { problemForIssue } from "../fix/problems";
import { dims as unitDims, inText, len } from "../units/units";
import { useUnits } from "../units/use-units";
import { pairAt } from "./choice";
import { machineSummary, pickedMachineId, rankMachines } from "./machine-rank";

function bboxOf(p: ReturnType<typeof usePart>): [number, number, number] | null {
  const b = p.data.validation?.geometry.bounding_box_mm ?? p.data.cost?.geometry.bbox_mm ?? null;
  return b && b.length === 3 ? [b[0], b[1], b[2]] : null;
}

/** A machine's verdict as its chip says it: one declared for other materials reads so, not "Not set up". */
function machineChip(verdict: string): string {
  return verdict === "Not set up" ? "Material not declared" : verdict;
}

/**
 * Your machines in the order the In-house view shows them (me-08): the machine the in-house answer is on
 * at this quantity first (the engine's cheapest route on a machine of yours), then the others that can make
 * it, cheapest first, then the ones that can't confirm, aren't set up or can't.
 */
export function useMachineViews(): MachineView[] {
  const p = usePart();
  const bbox = bboxOf(p);
  const side = pairAt(p.data.cost, p.q)?.in_house ?? null;
  const change = useShopChange();
  return React.useMemo(() => {
    // A machine changed since the check says its reason as of the check, never next to its new value as if current (me-11).
    const since = new Set(change?.machines.map((m) => m.id) ?? []);
    const views = machineViews(p.data.machines, p.methods, p.data.cost, p.q, bbox).map((v) => (since.has(v.id) && v.tone !== "ok" ? { ...v, why: asOfCheck(v.why, true) } : v));
    return rankMachines(views, pickedMachineId(views, side));
  }, [p.data.machines, p.methods, p.data.cost, p.q, bbox, side, change]);
}

function useSelectedMachine(views: MachineView[]): MachineView | null {
  const p = usePart();
  return views.find((v) => v.id === p.machinePick) ?? views.find((v) => v.tone === "ok") ?? views[0] ?? null;
}

const C30 = Math.cos(Math.PI / 6);
const S30 = 0.5;

export function ShopLayer() {
  const p = usePart();
  const views = useMachineViews();
  const m = useSelectedMachine(views);
  const on = p.lens === "shop" && !p.interrupted;
  const part = bboxOf(p);
  const env = m?.envelope ?? null;
  const { unit } = useUnits();
  const caps = (m ? p.data.machines.find((x) => x.id === m.id)?.capabilities : null) ?? null;
  const swing = typeof caps?.swing_dia === "number" ? caps.swing_dia : null;
  const between = typeof caps?.between_centers === "number" ? caps.between_centers : null;
  let drawing: React.ReactNode = null;
  const bendLen = caps?.sheet_kind === "press_brake" && typeof caps?.max_bend_length_mm === "number" ? caps.max_bend_length_mm : null;
  if (m && part && m.process === "cnc_turning" && swing && between) {
    // A lathe is drawn as a lathe (me-08): the chuck, the swing over the bed and the length between centres.
    drawing = <LatheDrawing name={m.name} swing={swing} between={between} part={part} />;
  } else if (m && part && bendLen) {
    // A press brake as a press brake (me-02): its bed, with the part to scale on it.
    drawing = <BrakeDrawing name={m.name} bend={bendLen} part={part} />;
  } else if (m && env && part) {
    const [W, D, H] = env;
    const sc = Math.min(470 / ((W + D) * C30), 400 / ((W + D) * S30 + H));
    const ox = 100 + D * C30 * sc;
    const oy = 330 + H * sc;
    const P = (x: number, y: number, z: number): [number, number] => [ox + (x - y) * C30 * sc, oy + (x + y) * S30 * sc - z * sc];
    const pt = (q: [number, number]) => `${q[0].toFixed(1)},${q[1].toFixed(1)}`;
    const L = (a: [number, number], b: [number, number]) => `M${pt(a)} L${pt(b)}`;
    const c = { o: P(0, 0, 0), x: P(W, 0, 0), y: P(0, D, 0), xy: P(W, D, 0), z: P(0, 0, H), xz: P(W, 0, H), yz: P(0, D, H), xyz: P(W, D, H) };
    const [bx, by, bz] = part;
    const px0 = W / 2 - bx / 2;
    const py0 = D / 2 - by / 2;
    const poly = [P(px0, py0, bz), P(px0 + bx, py0, bz), P(px0 + bx, py0 + by, bz), P(px0 + bx, py0 + by, 0), P(px0, py0 + by, 0), P(px0, py0 + by, bz)];
    const pc = P(px0 + bx / 2, py0 + by / 2, bz / 2);
    drawing = (
      <>
        <svg width="948" height="944" viewBox="0 0 948 944" role="img" aria-label={`${m.name} work area ${(unitDims(env, unit, 0) ?? "").replace(/ × /g, " by ")}, with the ${(unitDims(part, unit) ?? "").replace(/ × /g, " by ")} part drawn to scale inside`} style={{ position: "absolute", left: 0, top: 0 }}>
          <polygon points={[c.o, c.x, c.xy, c.y].map(pt).join(" ")} fill="#E3E7EC" fillOpacity="0.85" />
          <path d={[L(c.o, c.x), L(c.o, c.y), L(c.o, c.z)].join(" ")} stroke="#AEB5BE" strokeWidth="1.2" strokeDasharray="4 5" fill="none" />
          <path d={[L(c.x, c.xy), L(c.y, c.xy), L(c.x, c.xz), L(c.y, c.yz), L(c.xy, c.xyz), L(c.z, c.xz), L(c.z, c.yz), L(c.xz, c.xyz), L(c.yz, c.xyz)].join(" ")} stroke="#5F656E" strokeWidth="1.6" fill="none" strokeLinejoin="round" />
          <polygon points={poly.map(pt).join(" ")} fill="#141414" />
          <line x1={pc[0]} y1={pc[1]} x2={661 - 118 * 0.7} y2={226 + 118 * 0.7} stroke="#141414" strokeWidth="1.2" strokeDasharray="3 4" />
          <circle cx="661" cy="226" r="118" fill="none" stroke="#141414" strokeOpacity="0.28" strokeWidth="1.2" />
        </svg>
        {[
          { x: (c.x[0] + c.xy[0]) / 2 + 26, y: (c.x[1] + c.xy[1]) / 2 + 20, t: whole(D, unit) },
          { x: (c.y[0] + c.xy[0]) / 2 - 20, y: (c.y[1] + c.xy[1]) / 2 + 24, t: whole(W, unit) },
          { x: c.xy[0] + 36, y: (c.xy[1] + c.xyz[1]) / 2, t: whole(H, unit) },
        ].map((d) => (
          <span key={d.t + d.x} className="num" style={{ position: "absolute", left: d.x, top: d.y, transform: "translate(-50%, -50%)", fontSize: 12.5, fontWeight: 600, color: "var(--ink2)", whiteSpace: "nowrap" }}>
            {d.t}
          </span>
        ))}
        <span style={{ position: "absolute", left: 661, top: 360, transform: "translateX(-50%)", fontSize: 12.5, color: "var(--ink2)", whiteSpace: "nowrap" }}>
          Your part, magnified. It is drawn to true scale inside the {m.name}.
        </span>
      </>
    );
  }
  return (
    <div className={cx("layer", !on && "off")} style={{ inset: 0, overflow: "hidden" }} aria-hidden={!on}>
      <div className="shopdraw">{drawing}</div>
    </div>
  );
}

/** A turned part's diameter and length from its box: the odd one out of three extents is the axis, else the longest. */
function turnedSize(box: [number, number, number]): { dia: number; length: number } {
  const [a, b, c] = [...box].sort((x, y) => x - y);
  const close = (x: number, y: number) => Math.abs(x - y) <= 0.02 * Math.max(x, y);
  if (close(b, c) && !close(a, b)) return { dia: b, length: a };
  return { dia: b, length: c };
}

/** Side view of a lathe: chuck, the swing envelope between centres, and the part drawn to scale in the chuck. */
function LatheDrawing({ name, swing, between, part }: { name: string; swing: number; between: number; part: [number, number, number] }) {
  const { unit } = useUnits();
  const { dia, length } = turnedSize(part);
  const sc = Math.min(460 / between, 300 / swing);
  const x0 = 150;
  const cy = 560;
  const chuckH = Math.max(swing * sc * 0.55, 40);
  const ex = x0 + between * sc;
  const top = cy - (swing / 2) * sc;
  const bot = cy + (swing / 2) * sc;
  const pw = Math.max(length * sc, 2);
  const ph = Math.max(dia * sc, 2);
  const pc: [number, number] = [x0 + pw / 2, cy];
  return (
    <>
      <svg width="948" height="944" viewBox="0 0 948 944" role="img" aria-label={`${name}: swing ${len(swing, unit, 0)} diameter, ${len(between, unit, 0)} between centres, with the ${len(dia, unit)} diameter by ${len(length, unit)} part drawn to scale in the chuck`} style={{ position: "absolute", left: 0, top: 0 }}>
        <rect x={x0} y={top} width={between * sc} height={bot - top} fill="#E3E7EC" fillOpacity="0.85" stroke="#5F656E" strokeWidth="1.6" />
        <line x1={x0 - 70} y1={cy} x2={ex + 40} y2={cy} stroke="#AEB5BE" strokeWidth="1.2" strokeDasharray="10 4 2 4" />
        <rect x={x0 - 64} y={cy - chuckH / 2} width={64} height={chuckH} rx="4" fill="#5F656E" />
        <path d={`M${ex} ${cy - 14} L${ex + 26} ${cy} L${ex} ${cy + 14} Z`} fill="#5F656E" />
        <rect x={x0} y={cy - ph / 2} width={pw} height={ph} fill="#141414" />
        <line x1={pc[0]} y1={pc[1]} x2={661 - 118 * 0.7} y2={226 + 118 * 0.7} stroke="#141414" strokeWidth="1.2" strokeDasharray="3 4" />
        <circle cx="661" cy="226" r="118" fill="none" stroke="#141414" strokeOpacity="0.28" strokeWidth="1.2" />
      </svg>
      {[
        { x: (x0 + ex) / 2, y: bot + 24, t: `${whole(between, unit)} between centres` },
        { x: ex + 70, y: (top + cy) / 2, t: `Swing Ø${whole(swing, unit)}` },
      ].map((d) => (
        <span key={d.t} className="num" style={{ position: "absolute", left: d.x, top: d.y, transform: "translate(-50%, -50%)", fontSize: 12.5, fontWeight: 600, color: "var(--ink2)", whiteSpace: "nowrap" }}>
          {d.t}
        </span>
      ))}
      <span style={{ position: "absolute", left: 661, top: 360, transform: "translateX(-50%)", fontSize: 12.5, color: "var(--ink2)", whiteSpace: "nowrap" }}>
        Your part, Ø{len(dia, unit)} × {len(length, unit)}, magnified. It is drawn to true scale in the {name}’s chuck.
      </span>
    </>
  );
}

/** A machine size without trailing zeros: "120 in", "3048 mm". */
function whole(mm: number, unit: "mm" | "in"): string {
  return unit === "in" ? `${Number((mm / 25.4).toFixed(2))} in` : `${Number(mm.toFixed(1))} mm`;
}

/** Front view of a press brake: ram and bed over the bend length, with the part to scale on the bed. */
function BrakeDrawing({ name, bend, part }: { name: string; bend: number; part: [number, number, number] }) {
  const { unit } = useUnits();
  const longest = Math.max(...part);
  const sc = 600 / bend;
  const x0 = 120;
  const x1 = x0 + bend * sc;
  const bedTop = 600;
  const pw = Math.max(longest * sc, 2);
  const ph = Math.max(Math.min(...part) * sc, 2);
  const px = (x0 + x1) / 2 - pw / 2;
  const pc: [number, number] = [px + pw / 2, bedTop - ph / 2];
  return (
    <>
      <svg width="948" height="944" viewBox="0 0 948 944" role="img" aria-label={`${name}: ${len(bend, unit, 0)} bend length, with the part, ${len(longest, unit)} at its longest, drawn to scale on the bed`} style={{ position: "absolute", left: 0, top: 0 }}>
        <rect x={x0} y={bedTop - 150} width={x1 - x0} height={60} rx="4" fill="#E3E7EC" stroke="#5F656E" strokeWidth="1.6" />
        <path d={`M${x0} ${bedTop - 90} L${x1} ${bedTop - 90} L${(x0 + x1) / 2 + 30} ${bedTop - 64} L${(x0 + x1) / 2 - 30} ${bedTop - 64} Z`} fill="#AEB5BE" />
        <rect x={x0} y={bedTop} width={x1 - x0} height={70} rx="4" fill="#E3E7EC" stroke="#5F656E" strokeWidth="1.6" />
        <rect x={px} y={bedTop - ph} width={pw} height={ph} fill="#141414" />
        <line x1={pc[0]} y1={pc[1]} x2={661 - 118 * 0.7} y2={226 + 118 * 0.7} stroke="#141414" strokeWidth="1.2" strokeDasharray="3 4" />
        <circle cx="661" cy="226" r="118" fill="none" stroke="#141414" strokeOpacity="0.28" strokeWidth="1.2" />
      </svg>
      <span className="num" style={{ position: "absolute", left: (x0 + x1) / 2, top: bedTop + 96, transform: "translate(-50%, -50%)", fontSize: 12.5, fontWeight: 600, color: "var(--ink2)", whiteSpace: "nowrap" }}>
        {whole(bend, unit)} bend length
      </span>
      <span style={{ position: "absolute", left: 661, top: 360, transform: "translateX(-50%)", fontSize: 12.5, color: "var(--ink2)", whiteSpace: "nowrap" }}>
        Your part, {len(longest, unit)} at its longest, magnified. Drawn to true scale on the bed.
      </span>
    </>
  );
}

export function ShopSheet() {
  const p = usePart();
  const views = useMachineViews();
  const m = useSelectedMachine(views);
  const can = views.filter((v) => v.tone === "ok");
  const groups = machineSummary(views);
  const figs: FigItem[] = [];
  if (can.length) figs.push({ k: "Can make", v: can.map((v) => v.name).join(", "), tone: "ok" });
  else if (views.length) figs.push({ k: "Can make", v: "None", s: "no machine of yours clears every check", tone: "bad" });
  // The in-house answer: the machine it is on leads the list (views are ranked), with its hours and price.
  const ih = can.find((v) => v.cost != null);
  const vol = p.data.cost?.geometry?.volume_cm3 ?? null;
  if (ih) {
    const e = ih.method?.prices.get(p.q);
    // On your machine the run's machine time leads; the material, the running cost and its range follow.
    const r = !p.costOff ? routeResources(e, vol) : null;
    const price = e && !p.costOff ? `${money(ih.cost)} each, ${priceMeta(ih.method!, p.q)?.replace(/^Could be /, "") ?? ""}` : "";
    if (r?.hoursRun != null) figs.push({ k: `In-house at ${qtyWord(p.q)}`, v: hoursText(r.hoursRun), s: [`machine time on your ${ih.name}`, r.kgRun != null ? `${massText(r.kgRun)} ${r.grade}` : null, price].filter(Boolean).join(" · ") });
    else figs.push({ k: `In-house at ${qtyWord(p.q)}`, v: p.costOff ? "Not priced" : money(ih.cost), s: e && !p.costOff ? priceMeta(ih.method!, p.q)?.replace(/^Could be /, "") ?? "" : "" });
  }
  // Every machine left out of Can make is named here with its reason (me-10), not only inside its row.
  for (const g of groups) {
    if (g.k === "Can make") continue;
    figs.push({ k: g.k, v: g.names, s: g.why ?? undefined, tone: g.tone ?? undefined });
  }
  const { unit } = useUnits();
  const box = bboxOf(p);
  const dims = box ? unitDims(box, unit) : dimsText(box);
  const est = m && m.tone === "ok" && !p.costOff ? m.method?.prices.get(p.q) ?? null : null;
  const ch = useChoice();
  const fx = useFix();
  const mine = !!m?.method && ch.choice?.process === m.method.code;
  // A machine whose process can't make the part as drawn: why, on the part, for that process.
  const blockedBy = m?.method && m.method.verdict === "bad" && !p.checking ? problemForIssue(fx.set, m.method.finding?.issue.code) ?? fx.set.problems.find((x) => x.blocks.includes(m.method!.code)) ?? null : null;
  return (
    <>
      <SheetTop title="Your machines" meta={`${views.length} machine${views.length === 1 ? "" : "s"} · fit by size, weight and material`} figs={figs} sure="shop" />
      <div className="scroll">
        <RunNotice />
        {p.interrupted ? null : (
          <div className="swap">
            <div className="gh">
              <span>Your machines</span>
              <span>
                <Link href={R.shop}>Set up</Link>
              </span>
            </div>
            {!views.length ? (
              <Empty title="No machines yet" actions={<Link className="btn sm ink" href={`${R.shop}?add=1`}>Add a machine</Link>}>
                Add your machines and printers to see which can make this part, at your rates.
              </Empty>
            ) : (
              views.map((v) => (
                <button key={v.id} type="button" className={cx("mr", m?.id === v.id && "on")} aria-pressed={m?.id === v.id} onClick={() => p.setMachinePick(v.id)}>
                  <span>
                    <b>{v.name}</b>
                    <small>{inText(v.sub, unit)}</small>
                    {v.verdict === "Not set up" ? <small className="mr-why">{inText(v.why, unit)}</small> : null}
                    {v.tone === "ok" && v.method && !p.costOff ? (
                      (() => {
                        const takes = runLine(routeResources(v.method.prices.get(p.q), vol));
                        return takes ? <small className="num">{inText(`This part: ${takes} for ${qtyWord(p.q)}`, unit)}</small> : null;
                      })()
                    ) : null}
                  </span>
                  <span className={`chip c-${v.tone}`}>
                    <i />
                    {machineChip(v.verdict)}
                  </span>
                  <span className="c num">{p.costOff || v.cost == null ? "—" : money(v.cost)}</span>
                </button>
              ))
            )}
            {views.length ? (
              <p style={{ margin: "6px 12px 0", color: "var(--ink3)", fontSize: 12.5 }}>
                {dims ? `Part ${dims}, measured from the file. ` : ""}Fit checks work area (a press brake: bend length, press force and thickest sheet), weight and declared materials, from this check.
              </p>
            ) : null}
            {est && m?.method && (mine || ch.canChoose(m.method)) ? (
              <div className="note">
                <b>{mine ? `Your choice: ${m.name}` : `${m.name}: ${money(est.unit_cost_usd)} each at ${qtyWord(p.q)}`}</b>
                <span>
                  {mine ? "Prices, lead time and next steps on this part follow it." : `In-house, ${priceMeta(m.method, p.q)?.replace(/^Could be /, "could be ") ?? ""}.`}
                </span>
                <span style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {ch.readOnly ? null : mine ? (
                    <button className="btn sm ghost" type="button" disabled={!!ch.busy} onClick={() => void ch.backToPick()}>
                      {ch.busy === "back" ? "Going back…" : "Back to ScaleCAD’s pick"}
                    </button>
                  ) : (
                    <button className="btn sm ink" type="button" disabled={!!ch.busy} onClick={() => void ch.makeThisWay(m.method!)}>
                      {ch.busy === m.method.code ? "Saving…" : `Make it this way, on your ${m.name}`}
                    </button>
                  )}
                </span>
                {ch.err ? (
                  <span role="alert" style={{ color: "var(--bad)", fontSize: 12.5 }}>
                    {ch.err}
                  </span>
                ) : null}
              </div>
            ) : null}
            {est ? (
              <CostLines estimate={est} where="in-house" />
            ) : m ? (
              <div className="note">
                <b>
                  {m.name}: {machineChip(m.verdict).toLowerCase()}
                </b>
                <span>{inText(m.why, unit)}</span>
                {m.verdict === "Not set up" ? (
                  <span>
                    <Link className="lk" href={R.shop}>
                      Add the material to {m.name} in Your shop
                    </Link>
                    , then check the part again.
                  </span>
                ) : null}
                {m.checks ? <span className="num" style={{ color: "var(--ink3)", fontSize: 12.5 }}>{m.checks}</span> : null}
                {blockedBy && m.method ? (
                  <span>
                    <button className="btn sm fwhy" type="button" onClick={() => fx.openProblem(blockedBy.id, m.method!.members.length === 1 ? m.method!.code : null)}>
                      Why it can’t, on the part
                    </button>
                  </span>
                ) : null}
              </div>
            ) : null}
          </div>
        )}
      </div>
    </>
  );
}
