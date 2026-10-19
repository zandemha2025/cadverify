/**
 * What fixing each problem makes possible, and the order problems are shown in.
 *
 * Rule (board K4): a new lowest price first (cheapest first), then methods added
 * (most first), then warnings cleared (most first), then problems no design change
 * fixes. "Added" means a method this problem alone stops: every other finding on
 * that method is a warning, so fixing this one makes it possible. Prices are the
 * cost engine's own estimates for that method on today's shape (the engine prices
 * blocked routes "if redesigned"), never a new number.
 *
 * Pure: no React, no fetch (runs under node --test).
 */
import type { CostReport } from "@/lib/api";
import { METHODS, cheapestAt, money, priceAt, qtyWord, trimNum, type Method } from "../part/model.ts";
import type { Problem, ProblemSet } from "./problems.ts";

export interface Priced {
  m: Method;
  price: number;
}

export interface Unlock {
  problem: Problem;
  q: number;
  /** Methods this problem alone stops. */
  added: Method[];
  /** Added methods with a price at q, cheapest first. */
  priced: Priced[];
  /** Methods it stops together with other problems. */
  partial: { m: Method; others: Problem[] }[];
  /** Methods it stops that the part's service conditions rule out anyway. */
  excluded: Method[];
  /** The cheapest method you could order today at q. */
  today: Priced | null;
  best: Priced | null;
  newLow: boolean;
  tier: 0 | 1 | 2 | 3;
  key: number;
  value: string;
  sub: string;
}

function lower(s: string): string {
  return s.charAt(0).toLowerCase() + s.slice(1);
}

function joinWords(xs: string[]): string {
  const u = [...new Set(xs)];
  if (u.length <= 1) return u[0] ?? "";
  return `${u.slice(0, -1).join(", ")} and ${u[u.length - 1]}`;
}

/** "Nylon powder printing (MJF)" only where two methods share a name; else just the name. */
export function methodLabel(m: Method, all: Method[]): string {
  return all.filter((x) => x.name === m.name).length > 1 ? `${m.name} (${m.short})` : m.name;
}

/** "A, B, C and 4 more". */
export function someWords(xs: string[], max = 3): string {
  const u = [...new Set(xs)];
  if (u.length <= max) return joinWords(u);
  return `${u.slice(0, max).join(", ")} and ${u.length - max} more`;
}

/** Single-process methods only (the Make lens groups some for display). */
function singles(methods: Method[]): Method[] {
  return methods.filter((m) => m.members.length === 1);
}

/** Which problems stop each method. */
export function blockersByMethod(set: ProblemSet): Map<string, Problem[]> {
  const out = new Map<string, Problem[]>();
  for (const p of set.problems) for (const code of p.blocks) (out.get(code) ?? out.set(code, []).get(code)!).push(p);
  return out;
}

export function unlockOf(p: Problem, set: ProblemSet, methods: Method[], q: number, blockers = blockersByMethod(set)): Unlock {
  const list = singles(methods);
  const added: Method[] = [];
  const partial: { m: Method; others: Problem[] }[] = [];
  const excluded: Method[] = [];
  for (const m of list) {
    const bs = blockers.get(m.code) ?? [];
    if (m.excludedReason) {
      if (bs.some((b) => b.id === p.id)) excluded.push(m);
      continue;
    }
    if (!bs.some((b) => b.id === p.id)) continue;
    const others = bs.filter((b) => b.id !== p.id);
    if (others.length) partial.push({ m, others });
    else if (m.verdict === "bad" || m.dfm === "fail") added.push(m);
  }
  const priced = added
    .map((m) => ({ m, price: priceAt(m, q) }))
    .filter((x): x is Priced => x.price != null)
    .sort((a, b) => a.price - b.price);
  const t = cheapestAt(list, q);
  const today = t ? { m: t, price: priceAt(t, q)! } : null;
  const best = priced[0] ?? null;
  const newLow = !!best && (!today || best.price < today.price - 1e-9);
  let tier: Unlock["tier"];
  let key: number;
  let value: string;
  let sub: string;
  if (p.noChange) {
    tier = 3;
    key = p.noChange === "shop" ? 1 : 2;
    if (p.noChange === "shop") {
      value = "Setup";
      sub = "Orientation or setup at the shop, not the design";
    } else {
      value = "No change";
      const workableMill = list.filter((m) => (m.code === "cnc_3axis" || m.code === "cnc_5axis") && (m.verdict === "ok" || m.verdict === "warn"));
      sub = p.id === "round" ? `The lathe needs a round part${workableMill.length ? "; milling can make it" : ""}` : `Only ${joinWords(p.blocks.map((c) => lower(METHODS[c]?.name ?? c)))} needs it`;
    }
  } else if (newLow && best) {
    tier = 0;
    key = best.price;
    const rest = priced.slice(1, 3);
    if (today) {
      value = `−${money(today.price - best.price)} each`;
      sub = `${methodLabel(best.m, list)} ${money(best.price)} against ${lower(methodLabel(today.m, list))} ${money(today.price)} · if redesigned`;
    } else {
      value = `${money(best.price)} each`;
      const short = (m: Method) => (rest.filter((x) => x.m.name === m.name).length > 1 || list.filter((x) => x.name === m.name).length > 1 ? m.short : lower(m.name));
      sub = `${methodLabel(best.m, list)} becomes possible${rest.length ? `; also ${rest.map((x) => `${short(x.m)} ${money(x.price)}`).join(", ")}` : ""}`;
    }
  } else if (added.length) {
    tier = 1;
    key = -added.length;
    value = `+${added.length} ${added.length === 1 ? "method" : "methods"}`;
    const names = someWords(added.map((m) => methodLabel(m, list)));
    const at = best ? `${methodLabel(best.m, list)} ${money(best.price)} each at ${qtyWord(q)}${today ? `, against ${lower(methodLabel(today.m, list))} ${money(today.price)}` : ""}` : null;
    sub = [names, at].filter(Boolean).join(" · ");
  } else if (p.warnCount > 0 || partial.length) {
    tier = 2;
    key = -(p.warnCount * 1000 + partial.length);
    if (p.warnCount > 0) {
      value = `${p.warnCount} ${p.warnCount === 1 ? "warning" : "warnings"}`;
      const who = [...p.warns, ...p.blocks].map((c) => list.find((m) => m.code === c)).map((m, i) => (m ? methodLabel(m, list) : [...p.warns, ...p.blocks][i]));
      sub = p.universal && !p.warns.length && !p.blocks.length ? "Every method" : `Clears it for ${someWords(who.map((w, i) => (i ? lower(w) : w)))}`;
    } else {
      value = "Still blocked";
      sub = `Each method it stops has another problem too: ${someWords([...new Set(partial.flatMap((x) => x.others.map((o) => lower(o.title))))])}`;
    }
  } else {
    tier = 3;
    key = 3;
    value = "No change";
    sub = "Nothing it stops or flags";
  }
  return { problem: p, q, added, priced, partial, excluded, today, best, newLow, tier, key, value, sub };
}

/** Every problem, ranked at quantity q (board K4's rule). */
export function rankProblems(set: ProblemSet, methods: Method[], q: number): Unlock[] {
  const blockers = blockersByMethod(set);
  const order = new Map(set.problems.map((p, i) => [p.id, i]));
  return set.problems
    .map((p) => unlockOf(p, set, methods, q, blockers))
    .sort((a, b) => a.tier - b.tier || a.key - b.key || (order.get(a.problem.id) ?? 0) - (order.get(b.problem.id) ?? 0));
}

/* ── places (K4 "By place") ────────────────────────────────────────────── */

export interface Place {
  /** "1", "2"…, or "·" for the whole part (no one place on it). */
  n: string;
  name: string;
  ids: string[];
  /** Has a 3D location (faces or a region) to pin. */
  located: boolean;
}

export function placeName(p: Problem): string {
  return !p.faces.length && !p.region ? "Whole part" : p.place;
}

/** Places in the order of their best-ranked problem; the whole part last. */
export function placesOf(ranked: Unlock[]): Place[] {
  const by = new Map<string, Place>();
  for (const u of ranked) {
    const name = placeName(u.problem);
    if (!by.has(name)) by.set(name, { n: "", name, ids: [], located: name !== "Whole part" });
    by.get(name)!.ids.push(u.problem.id);
  }
  const located = [...by.values()].filter((p) => p.located);
  located.forEach((p, i) => (p.n = String(i + 1)));
  const whole = by.get("Whole part");
  if (whole) whole.n = "·";
  return whole ? [...located, whole] : located;
}

/* ── K1: what fixing this one unlocks ──────────────────────────────────── */

export interface UnlockRow {
  k: string;
  v: string;
  s: string;
  ok?: boolean;
}

/** The quantity worth showing: the engine's own "if redesigned" quantity when it unlocks tooling, else q. */
export function unlockQty(p: Problem, set: ProblemSet, methods: Method[], cost: CostReport | null, q: number, qs: number[]): number {
  const d = cost?.decision;
  if (!d?.tooling_process) return q;
  const u = unlockOf(p, set, methods, q);
  if (!u.added.some((m) => m.code === d.tooling_process)) return q;
  const red = Object.entries(d.if_redesigned ?? {})
    .filter(([, v]) => v && v.process === d.tooling_process)
    .map(([k]) => Number(k))
    .filter((n) => qs.includes(n))
    .sort((a, b) => a - b);
  return red.length ? red[red.length - 1] : q;
}

function band(m: Method, q: number): string | null {
  const e = m.prices.get(q);
  return e ? `±${trimNum(e.est_error_band_pct, 0)}%` : null;
}

export function unlockRows(
  u: Unlock,
  opts: { cost: CostReport | null; methodsTotal: number; picked: string | null; repairable: boolean; set?: ProblemSet },
): { rows: UnlockRow[]; foot: string } {
  const p = u.problem;
  const rows: UnlockRow[] = [];
  if (p.id === "open") {
    const priced = opts.cost?.estimates?.length ?? 0;
    rows.push({ k: "A verdict for each method", v: String(opts.methodsTotal), s: `Today all ${opts.methodsTotal} are blocked by the open shell`, ok: true });
    rows.push({ k: "A price for each one that can make it", v: "Priced", s: priced ? "Priced once the shape is closed" : "Today none: cost needs a watertight, positive volume", ok: true });
    if (opts.repairable) rows.push({ k: "Repair here", v: "Pilot", s: "ScaleCAD can try a mesh repair on a copy and shows both shapes, with any change to the volume" });
    return { rows, foot: priced ? "Prices on an open shell aren’t reliable; the check prices the closed shape." : "Nothing on this file is priced yet, so no price change can be shown until a closed shape is checked." };
  }
  const q = u.q;
  for (const x of u.priced.slice(0, 2)) {
    const e = x.m.prices.get(q)!;
    rows.push({
      k: x.m.name,
      v: money(x.price),
      s: [e.material, `each at ${qtyWord(q)}`, band(x.m, q), x === u.priced[0] ? "today Can’t as drawn" : null].filter(Boolean).join(" · "),
      ok: true,
    });
  }
  if (u.best && u.today && u.best.m.code !== u.today.m.code) {
    const diff = u.best.price - u.today.price;
    const d = opts.cost?.decision;
    const cross = d?.tooling_process === u.best.m.code && d.crossover_qty ? ` ${u.best.m.name} is cheaper from about ${qtyWord(Math.round(d.crossover_qty))} parts.` : "";
    rows.push({
      k: "Against today’s cheapest",
      v: `${diff < 0 ? "−" : "+"}${money(Math.abs(diff))}`,
      s: `${u.today.m.name} is ${money(u.today.price)} each at ${qtyWord(q)}.${cross}`,
      ok: diff < 0,
    });
  }
  if (u.partial.length) {
    const others = [...new Map(u.partial.flatMap((x) => x.others).map((o) => [o.id, o])).values()];
    rows.push({ k: someWords(u.partial.map((x) => methodLabel(x.m, u.partial.map((y) => y.m)))), v: "Still blocked", s: `Also need: ${joinWords(others.map((o) => lower(o.title)))}` });
  }
  if (u.best && opts.set) {
    // What the cheapest unlocked method still flags once this is fixed.
    const still = opts.set.problems.find((x) => x.id !== p.id && x.warns.includes(u.best!.m.code));
    const sm = still?.methods.find((x) => x.code === u.best!.m.code);
    if (still && sm) rows.push({ k: `Still flagged for ${lower(u.best.m.name)}`, v: sm.measured != null ? `${trimNum(sm.measured, 2)}${sm.unit === "mm" ? " mm" : sm.unit === "deg" ? "°" : ""}` : "Flagged", s: `${still.title}: ${still.where}` });
  }
  const unpriced = u.added.filter((m) => !m.prices.has(q));
  if (unpriced.length) {
    const metal = unpriced.every((m) => METHODS[m.code]?.metalOnly) && opts.cost?.material_class === "polymer";
    const names = joinWords(unpriced.map((m) => m.name));
    rows.push(
      unpriced.length > 2
        ? { k: `${unpriced.length} more methods`, v: "Possible", s: `${names}${metal ? ": they need a metal, so they aren’t priced in plastic" : `: not priced at ${qtyWord(q)}`}`, ok: true }
        : { k: names, v: "Possible", s: metal ? "Need a metal, so they aren’t priced in plastic" : `Not priced at ${qtyWord(q)}`, ok: true },
    );
  }
  if (u.excluded.length) rows.push({ k: joinWords(u.excluded.map((m) => m.name)), v: "Ruled out", s: `By this part’s service conditions: ${u.excluded[0].excludedReason}` });
  if (!u.added.length && !u.partial.length && rows.length === 0) {
    rows.push({ k: "Methods it flags", v: String(p.warns.length + p.blocks.length), s: p.warnCount ? `Clears ${p.warnCount} ${p.warnCount === 1 ? "warning" : "warnings"}; nothing it stops` : "Nothing it stops" });
  }
  const notes: string[] = ["Prices are the cost engine’s price if redesigned, on today’s shape."];
  const red = opts.cost?.decision?.if_redesigned?.[String(q)];
  if (red && u.added.some((m) => m.code === red.process)) notes.push(`From its price if redesigned: “${red.caveat}”.`);
  if (p.id === "thin") notes.push("Thicker walls add material, so re-check after the change.");
  return { rows: rows.slice(0, 4), foot: notes.join(" ") };
}
