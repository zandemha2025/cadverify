"use client";

/** Shop: your machines, whether each can make it and why, and the part drawn to scale inside one. */
import * as React from "react";
import Link from "next/link";
import { listMachines, type OwnedMachine } from "@/lib/verify/machine-api";
import { R } from "../routes";
import { Empty, cx } from "../ui";
import { usePart } from "./ctx";
import { dimsText, machineViews, money, priceMeta, qtyWord, trimNum, type MachineView } from "./model";
import { CostLines } from "./lens-cost";
import { RunNotice, SheetTop, type FigItem } from "./sheet-bits";

function bboxOf(p: ReturnType<typeof usePart>): [number, number, number] | null {
  const b = p.data.validation?.geometry.bounding_box_mm ?? p.data.cost?.geometry.bbox_mm ?? null;
  return b && b.length === 3 ? [b[0], b[1], b[2]] : null;
}

export function useMachineViews(): MachineView[] {
  const p = usePart();
  const bbox = bboxOf(p);
  return React.useMemo(() => machineViews(p.data.machines, p.methods, p.data.cost, p.q, bbox), [p.data.machines, p.methods, p.data.cost, p.q, bbox]);
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
  let drawing: React.ReactNode = null;
  if (m && env && part) {
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
        <svg width="948" height="944" viewBox="0 0 948 944" role="img" aria-label={`${m.name} work area ${env.map((n) => trimNum(n, 0)).join(" by ")} mm, with the ${part.map((n) => trimNum(n, 1)).join(" by ")} mm part drawn to scale inside`} style={{ position: "absolute", left: 0, top: 0 }}>
          <polygon points={[c.o, c.x, c.xy, c.y].map(pt).join(" ")} fill="#E3E7EC" fillOpacity="0.85" />
          <path d={[L(c.o, c.x), L(c.o, c.y), L(c.o, c.z)].join(" ")} stroke="#AEB5BE" strokeWidth="1.2" strokeDasharray="4 5" fill="none" />
          <path d={[L(c.x, c.xy), L(c.y, c.xy), L(c.x, c.xz), L(c.y, c.yz), L(c.xy, c.xyz), L(c.z, c.xz), L(c.z, c.yz), L(c.xz, c.xyz), L(c.yz, c.xyz)].join(" ")} stroke="#5F656E" strokeWidth="1.6" fill="none" strokeLinejoin="round" />
          <polygon points={poly.map(pt).join(" ")} fill="#141414" />
          <line x1={pc[0]} y1={pc[1]} x2={661 - 118 * 0.7} y2={226 + 118 * 0.7} stroke="#141414" strokeWidth="1.2" strokeDasharray="3 4" />
          <circle cx="661" cy="226" r="118" fill="none" stroke="#141414" strokeOpacity="0.28" strokeWidth="1.2" />
        </svg>
        {[
          { x: (c.x[0] + c.xy[0]) / 2 + 26, y: (c.x[1] + c.xy[1]) / 2 + 20, t: `${trimNum(D, 0)} mm` },
          { x: (c.y[0] + c.xy[0]) / 2 - 20, y: (c.y[1] + c.xy[1]) / 2 + 24, t: `${trimNum(W, 0)} mm` },
          { x: c.xy[0] + 36, y: (c.xy[1] + c.xyz[1]) / 2, t: `${trimNum(H, 0)} mm` },
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

function sig(ms: OwnedMachine[]): string {
  return ms.map((m) => `${m.id}:${m.updated_at ?? ""}`).sort().join("|");
}

export function ShopSheet() {
  const p = usePart();
  const views = useMachineViews();
  const m = useSelectedMachine(views);
  const [current, setCurrent] = React.useState<OwnedMachine[] | null>(null);
  React.useEffect(() => {
    let live = true;
    listMachines()
      .then((pg) => live && setCurrent(pg.machines))
      .catch(() => live && setCurrent(null));
    return () => {
      live = false;
    };
  }, []);
  const changed = current != null && p.data.cost != null && sig(current) !== sig(p.data.machines);
  const can = views.filter((v) => v.tone === "ok");
  const cant = views.filter((v) => v.tone === "bad");
  const figs: FigItem[] = [];
  if (can.length) figs.push({ k: "Can make", v: can.map((v) => v.name).join(", "), tone: "ok" });
  else if (views.length) figs.push({ k: "Can make", v: "None", s: "no machine of yours clears every check", tone: "bad" });
  const ih = can.find((v) => v.cost != null);
  if (ih) {
    const e = ih.method?.prices.get(p.q);
    figs.push({ k: `In-house at ${qtyWord(p.q)}`, v: p.costOff ? "Not priced" : money(ih.cost), s: e && !p.costOff ? priceMeta(ih.method!, p.q)?.replace(/^Could be /, "") ?? "" : "" });
  }
  const warn = views.filter((v) => v.tone === "warn");
  if (cant.length) figs.push({ k: "Can't", v: cant.map((v) => v.name).join(", "), s: cant.map((v) => (v.verdict === "Can't" ? "can't make it as drawn" : v.verdict.toLowerCase())).join(" · "), tone: "bad" });
  else if (warn.length) figs.push({ k: "Not set up", v: warn.map((v) => v.name).join(", "), tone: "warn" });
  const dims = dimsText(bboxOf(p));
  const est = m && m.tone === "ok" && !p.costOff ? m.method?.prices.get(p.q) ?? null : null;
  return (
    <>
      <SheetTop title="Your machines" meta={`${views.length} machine${views.length === 1 ? "" : "s"} · fit by size, weight and material`} figs={figs} />
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
                    <small>{v.sub}</small>
                  </span>
                  <span className={`chip c-${v.tone}`}>
                    <i />
                    {v.verdict}
                  </span>
                  <span className="c num">{p.costOff || v.cost == null ? "—" : money(v.cost)}</span>
                </button>
              ))
            )}
            {views.length ? (
              <p style={{ margin: "6px 12px 0", color: "var(--ink3)", fontSize: 12.5 }}>
                {dims ? `Part ${dims}, measured from the file. ` : ""}Fit checks work area, weight and declared materials, from this check.
              </p>
            ) : null}
            {changed ? (
              <div className="note" role="status">
                <b>Your machines changed after this check</b>
                <span>The fit above is from the check. Re-check to see it against the machines you have now.</span>
                <span>
                  {p.canRecheck ? (
                    <button className="btn sm ink" type="button" onClick={() => p.recheck()}>
                      Re-check with your machines
                    </button>
                  ) : (
                    <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>Drop the file on the part to re-check it.</span>
                  )}
                </span>
              </div>
            ) : null}
            {est ? (
              <CostLines estimate={est} where="in-house" />
            ) : m ? (
              <div className="note">
                <b>
                  {m.name}: {m.verdict.toLowerCase()}
                </b>
                <span>{m.why}</span>
                {m.checks ? <span className="num" style={{ color: "var(--ink3)", fontSize: 12.5 }}>{m.checks}</span> : null}
              </div>
            ) : null}
          </div>
        )}
      </div>
    </>
  );
}
