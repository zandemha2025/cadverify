/**
 * The tooling sheet and capability cards, as pure functions over a part's own
 * saved cost check and the org's capability ranking. Only figures the engine
 * computed are shown: unit costs at costed quantities, the crossover, the
 * tooling route's DFM state. No machine or mold price exists, so none is shown.
 */
import type { CostReport } from "@/lib/api";
import { makeNowEstimate, unitCostByQty } from "../../../lib/verify/derive.ts";
import { machineFor, procName, routeName, type Machine } from "./makeability.ts";
import { machineKind } from "../process-names.ts";

export const Q_MIN = 1;
export const Q_MAX = 10000;

export interface ToolingView {
  makeProc: string | null;
  makeMat: string | null;
  toolProc: string | null;
  ready: boolean;
  crossover: number | null;
  quantities: number[];
  draftDeg: number | null;
  /** Make-now unit cost at each costed quantity (the engine's pick for that quantity). */
  make: Map<number, number>;
  /** Tooling route unit cost (tooling amortized) at each costed quantity. */
  tool: Map<number, number>;
  materialClass: string | null;
  note: string | null;
}

export function toolingView(cost: CostReport | null | undefined): ToolingView | null {
  if (!cost || !cost.decision) return null;
  const d = cost.decision;
  const quantities = [...new Set((cost.quantities ?? []).filter((q) => Number.isFinite(q) && q > 0))].sort((a, b) => a - b);
  const make = new Map<number, number>();
  for (const q of quantities) {
    const e = makeNowEstimate(cost, q);
    if (e && Number.isFinite(e.unit_cost_usd)) make.set(q, e.unit_cost_usd);
  }
  const tool = d.tooling_process ? unitCostByQty(cost, d.tooling_process) : new Map<number, number>();
  const crossover = d.crossover_qty != null && Number.isFinite(d.crossover_qty) ? d.crossover_qty : null;
  return {
    makeProc: d.make_now_process ?? null,
    makeMat: d.make_now_material ?? null,
    toolProc: d.tooling_process ?? null,
    ready: !!d.tooling_dfm_ready,
    crossover,
    quantities,
    draftDeg: draftOf(cost, d.tooling_process),
    make,
    tool,
    materialClass: cost.material_class ?? null,
    note: d.note ?? null,
  };
}

/** The draft angle the tooling route's DFM blocker asks for, e.g. 1 from "… below 1.0° draft for injection_molding". */
export function draftOf(cost: CostReport, toolProc: string | null | undefined): number | null {
  if (!toolProc) return null;
  const texts: string[] = [];
  for (const e of cost.estimates ?? []) if (e.process === toolProc) texts.push(...(e.dfm_blockers ?? []));
  if (cost.decision?.note) texts.push(cost.decision.note);
  for (const t of texts) {
    const m = /below ([0-9]+(?:\.[0-9]+)?)\s*°\s*draft/i.exec(t);
    if (m) return Number(m[1]);
  }
  return null;
}

/** Slider position 0..1000 on a log axis from 1 to 10,000. */
export function posToQty(pos: number): number {
  const p = Math.min(1000, Math.max(0, pos));
  return Math.max(Q_MIN, Math.round(Math.pow(10, (4 * p) / 1000)));
}

export function qtyToPos(q: number): number {
  return Math.round((Math.log10(Math.min(Q_MAX, Math.max(Q_MIN, q))) / 4) * 1000);
}

/** The costed quantity nearest q on the log axis. */
export function nearestCosted(quantities: readonly number[], q: number): number | null {
  if (!quantities.length) return null;
  return quantities.reduce((b, x) => (Math.abs(Math.log(x) - Math.log(q)) < Math.abs(Math.log(b) - Math.log(q)) ? x : b), quantities[0]);
}

export interface Chart {
  grid: string;
  makePath: string;
  toolPath: string;
  xLine: string | null;
  qLine: string;
  makeDots: [number, number][];
  toolDots: [number, number][];
}

/** SVG paths (420 × 150) through the real costed points only, log-log. */
export function chartOf(v: ToolingView, q: number): Chart {
  const X = (x: number) => 14 + (Math.log10(Math.min(Q_MAX, Math.max(Q_MIN, x))) / 4) * 392;
  const vals = [...v.make.values(), ...v.tool.values()].filter((u) => u > 0);
  const lo = vals.length ? Math.log10(Math.min(...vals)) : 0;
  const hi = vals.length ? Math.log10(Math.max(...vals)) : 1;
  const Y = (u: number) => 128 - ((Math.log10(Math.max(u, 1e-6)) - lo) / Math.max(0.1, hi - lo)) * 118;
  const pts = (m: Map<number, number>) => [...m.entries()].filter(([, u]) => u > 0).sort((a, b) => a[0] - b[0]).map(([x, u]) => [X(x), Y(u)] as [number, number]);
  const path = (p: [number, number][]) => p.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const md = pts(v.make);
  const td = pts(v.tool);
  const line = (x: number) => `M${X(x).toFixed(1)} 8 L${X(x).toFixed(1)} 132`;
  return {
    grid: [1, 10, 100, 1000, 10000].map(line).join(" "),
    makePath: md.length > 1 ? path(md) : "",
    toolPath: td.length > 1 ? path(td) : "",
    xLine: v.crossover != null && v.crossover >= Q_MIN && v.crossover <= Q_MAX ? line(v.crossover) : null,
    qLine: line(q),
    makeDots: md,
    toolDots: td,
  };
}

/* ------------------------------------------------------------------ */
/*  Capability ranking cards                                           */
/* ------------------------------------------------------------------ */

export interface RankEntry {
  acquisition: {
    kind: "acquire" | "upgrade" | string;
    process: string;
    process_label?: string;
    gate: string | null;
    spec?: { gate?: string; summary?: string; qualify_materials?: string[]; work_envelope_mm_min?: unknown; recorded_bounds?: string[]; [k: string]: unknown };
  };
  parts_unlocked: number;
  stale: boolean;
  stale_parts: number;
}

/** "Part minimum width is at least 268.8mm > smallest chamber span 254mm. …" → {need, have} */
export function boundsOf(text: string | undefined): { need: number; have: number } | null {
  if (!text) return null;
  const m = /at least\s*([0-9]+(?:\.[0-9]+)?)\s*mm\s*>\s*[^0-9]*?([0-9]+(?:\.[0-9]+)?)\s*mm/i.exec(text);
  return m ? { need: Number(m[1]), have: Number(m[2]) } : null;
}

/** The caveat sentence(s) after the measured bound. */
export function caveatOf(text: string | undefined): string | null {
  if (!text) return null;
  const i = text.search(/\.\s/);
  const rest = i > 0 ? text.slice(i + 1).trim() : "";
  return rest || null;
}

export interface CapCard {
  title: string;
  kind: "material" | "envelope" | "other";
  machine: Machine | null;
  materials: string[];
  bounds: { need: number; have: number } | null;
  caveat: string | null;
  summary: string | null;
}

export function capCard(e: RankEntry, machines: readonly Machine[] | null | undefined): CapCard {
  const a = e.acquisition;
  const spec = a.spec ?? {};
  const machine = machineFor(a.process, machines);
  const where = routeName(a.process, machines);
  const materials = Array.isArray(spec.qualify_materials) ? spec.qualify_materials.filter((m) => typeof m === "string") : [];
  const bound = Array.isArray(spec.recorded_bounds) ? spec.recorded_bounds.find((b) => typeof b === "string") : undefined;
  const bounds = boundsOf(bound);
  const minEnv = typeof spec.work_envelope_mm_min === "number" ? spec.work_envelope_mm_min : null;
  if (a.gate === "material" && materials.length) {
    return { title: `Qualify ${where} for ${materials.join(", ")}`, kind: "material", machine, materials, bounds: null, caveat: null, summary: spec.summary ?? null };
  }
  if (a.gate === "envelope") {
    const need = bounds?.need ?? minEnv;
    const title = need != null ? `${machineKind(a.process)} wider than ${Math.round(need).toLocaleString("en-US")} mm` : `${machineKind(a.process)} with a larger work area`;
    return { title, kind: "envelope", machine, materials, bounds, caveat: caveatOf(bound), summary: spec.summary ?? null };
  }
  const verb = a.kind === "acquire" ? "Add" : "Upgrade";
  const label = a.kind === "acquire" ? procName(a.process) : where;
  return { title: `${verb} ${label}${spec.summary ? `: ${spec.summary}` : ""}`, kind: "other", machine, materials, bounds, caveat: caveatOf(bound), summary: spec.summary ?? null };
}

/** Isometric box of a machine's work area (x × y × z mm), scaled into a 210 × 118 frame. */
export function isoBox(x: number, y: number, z: number): { floor: string; back: string; front: string } {
  const c30 = Math.cos(Math.PI / 6);
  const sc = Math.min(210 / ((x + y) * c30), 118 / ((x + y) * 0.5 + z));
  const ox = 8 + y * c30 * sc;
  const oy = 4 + z * sc;
  const Q = (a: number, b: number, h: number) => [ox + (a - b) * c30 * sc, oy + (a + b) * 0.5 * sc - h * sc];
  const pt = (p: number[]) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`;
  const L = (p: number[], q: number[]) => `M${pt(p)} L${pt(q)}`;
  const o = Q(0, 0, 0), X = Q(x, 0, 0), Y = Q(0, y, 0), XY = Q(x, y, 0), Z = Q(0, 0, z), XZ = Q(x, 0, z), YZ = Q(0, y, z), XYZ = Q(x, y, z);
  return {
    floor: [o, X, XY, Y].map(pt).join(" "),
    back: [L(o, X), L(o, Y), L(o, Z)].join(" "),
    front: [L(X, XY), L(Y, XY), L(X, XZ), L(Y, YZ), L(XY, XYZ), L(Z, XZ), L(Z, YZ), L(XZ, XYZ), L(YZ, XYZ)].join(" "),
  };
}
