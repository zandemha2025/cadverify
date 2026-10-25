/**
 * Makeability, as the Many parts screens read it: bucket names, a part's reason,
 * its unit cost and flags, all from the org's makeability projection
 * (GET /catalog/makeability). Pure: no React, no fetch, so it runs under
 * `node --test`. Unknown bucket keys and verdict strings get a neutral bucket
 * of their own instead of being folded into a known one.
 */
import { PROCESS_NAME, processLabel } from "../process-names.ts";
import { wallWords } from "../home/words.ts";

export type Tone = "ok" | "warn" | "bad" | "unk";

/** One row of a bucket drill-down, as the API returns it (fields this UI reads). */
export interface MakeRow {
  part_key: string;
  filename: string | null;
  file_type?: string | null;
  analysis?: { id: string; url?: string } | null;
  cost_decision?: { id: string; url?: string } | null;
  unit_cost?: { qty?: number | null; usd?: number | null; withheld?: boolean; withheld_reason?: string | null } | number | null;
  recommended_route?: { process?: string | null; material?: string | null; source?: string | null } | null;
  findings?: { total?: number; critical?: number } | null;
  updated_at?: string;
  makeability: {
    verdict: string | null;
    stale: boolean | null;
    gap: MakeGap | null;
  } | null;
  /** The part's route and price at its own quantity (the yearly volume a run declared, else the record's). */
  at_quantity?: AtQuantity | null;
}

export interface AtQuantity {
  qty: number;
  basis: "declared" | "record";
  /** The engine keeps it on a machine of yours at this quantity. */
  in_house: boolean;
  /** The cheapest route on a machine of yours, when one makes it. */
  owned?: { process: string | null; machine: string | null; material: string | null; usd: number | null } | null;
  process?: string | null;
  material?: string | null;
  usd?: number | null;
  machine?: string | null;
  dfm_ready?: boolean;
  /** What you pay today, when the part has a price: it decides make or buy, as on a catalog run. */
  buy_price?: { usd_each: number; source: string | null } | null;
}

export interface GapEntry {
  axis?: string;
  gate?: string;
  have?: unknown;
  need?: unknown;
  human?: string;
}

export interface MakeGap {
  kind?: string;
  process?: string | null;
  gate?: string | null;
  single?: boolean;
  gap?: GapEntry[];
}

export interface Machine {
  id: string;
  name: string;
  process: string;
  capabilities?: { x?: number; y?: number; z?: number } | null;
  materials?: string[] | null;
}

export interface BucketDef {
  key: string;
  label: string;
  tone: Tone;
  color: string;
  /** Shown as a bucket button; the others sit in the "needs evaluation · invalid geometry" line. */
  primary: boolean;
  /** Empty-list copy. */
  empty: string;
}

const KNOWN: Record<string, Omit<BucketDef, "key">> = {
  makeable_in_house: { label: "On your machines", tone: "ok", color: "#146C43", primary: true, empty: "A part lands here when one of your machines can make it." },
  makeable_outside: { label: "Outside only", tone: "unk", color: "#9AA3AE", primary: true, empty: "A part lands here when only a supplier can make it." },
  needs_capability: { label: "One change", tone: "warn", color: "#8C5200", primary: true, empty: "A part lands here when one of your machines almost fits it." },
  not_makeable: { label: "Ruled out", tone: "bad", color: "#B42318", primary: true, empty: "A part lands here when no route makes it as drawn." },
  unknown: { label: "Needs evaluation", tone: "unk", color: "#5F656E", primary: false, empty: "A part lands here when it hasn’t been checked against your machines." },
  geometry_invalid: { label: "Invalid geometry", tone: "unk", color: "#141414", primary: false, empty: "A part lands here when its file isn’t a valid solid." },
};

export const PRIMARY_ORDER = ["makeable_in_house", "makeable_outside", "needs_capability", "not_makeable"];

export function humanize(key: string): string {
  const s = key.replace(/[_-]+/g, " ").trim();
  return s ? s[0].toUpperCase() + s.slice(1) : "Other";
}

/** A bucket's name and colour. An unknown key is its own neutral bucket. */
export function bucketDef(key: string, opts?: { severalChanges?: boolean }): BucketDef {
  const k = KNOWN[key];
  if (!k) return { key, label: humanize(key), tone: "unk", color: "#9AA3AE", primary: true, empty: "A part lands here when its check returns this verdict." };
  if (key === "needs_capability" && opts?.severalChanges) return { key, ...k, label: "Capability change" };
  return { key, ...k };
}

/** Bucket keys in display order: the four primary ones, then any new ones the server sends, then the honesty buckets. */
export function orderedBuckets(serverKeys: readonly string[] | null | undefined, summary: Record<string, unknown>): string[] {
  const keys = new Set<string>([...(serverKeys ?? []), ...Object.keys(KNOWN)]);
  for (const [k, v] of Object.entries(summary)) {
    if (typeof v === "number" && !["total", "stale_count"].includes(k)) keys.add(k);
  }
  const extra = [...keys].filter((k) => !KNOWN[k]);
  return [...PRIMARY_ORDER, ...extra, "unknown", "geometry_invalid"].filter((k) => keys.has(k));
}

export function countOf(summary: Record<string, unknown> | null | undefined, key: string): number {
  const v = summary?.[key];
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

/* ------------------------------------------------------------------ */
/*  Process names                                                      */
/* ------------------------------------------------------------------ */

const PROC: Record<string, string> = Object.fromEntries(Object.keys(PROCESS_NAME).map((c) => [c, processLabel(c)]));

export function procName(p: string | null | undefined): string {
  if (!p) return "—";
  return PROC[p] ?? humanize(p);
}

/** The one owned machine for a process, when there is exactly one. */
export function machineFor(process: string | null | undefined, machines: readonly Machine[] | null | undefined): Machine | null {
  if (!process || !machines) return null;
  const m = machines.filter((x) => x.process === process);
  return m.length === 1 ? m[0] : null;
}

/** "Haas VF-2" when one machine of the process is owned, else the process name. */
export function routeName(process: string | null | undefined, machines: readonly Machine[] | null | undefined): string {
  return machineFor(process, machines)?.name ?? procName(process);
}

/* ------------------------------------------------------------------ */
/*  A part's reason, cost and flags                                    */
/* ------------------------------------------------------------------ */

function firstSentence(s: string): string {
  const t = s.trim();
  const i = t.search(/\.\s/);
  return (i > 0 ? t.slice(0, i) : t).replace(/\.$/, "");
}

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function mm(v: number): string {
  return `${Math.round(v).toLocaleString("en-US")} mm`;
}

/** The first gap entry, or the DFM blocker the fit check names first. */
export function primaryGap(row: MakeRow): GapEntry | null {
  const g = row.makeability?.gap?.gap;
  return Array.isArray(g) && g.length ? g[0] : null;
}

/** A gap entry in a few words, e.g. "not qualified for PEEK", "needs ≥ 269 mm, Haas ST-20 takes 254 mm". */
export function gapPhrase(entry: GapEntry, process: string | null | undefined, machines?: readonly Machine[] | null): string {
  const have = num(entry.have);
  const need = num(entry.need);
  if (entry.gate === "envelope" && have != null && need != null) {
    return `needs at least ${mm(need)}; ${routeName(process, machines)} takes ${mm(have)}`;
  }
  if (entry.human) return firstSentence(entry.human);
  if (entry.gate) return `${humanize(entry.gate).toLowerCase()} limit`;
  return "one limit not met";
}

function unitCost(row: MakeRow): { qty: number | null; usd: number | null; withheld: boolean; reason: string | null } | null {
  const u = row.unit_cost;
  if (u == null) return null;
  if (typeof u === "number") return Number.isFinite(u) ? { qty: null, usd: u, withheld: false, reason: null } : null;
  return { qty: num(u.qty), usd: num(u.usd), withheld: !!u.withheld, reason: u.withheld_reason ?? null };
}

/** Why the part is in its bucket, in one line. */
export function reasonOf(row: MakeRow, machines?: readonly Machine[] | null): string {
  const v = row.makeability?.verdict ?? null;
  const gap = row.makeability?.gap ?? null;
  const entry = primaryGap(row);
  const route = row.recommended_route ?? null;
  const material = route?.material ? ` · ${route.material}` : "";
  switch (v) {
    case "makeable_in_house":
    case "makeable_with_secondary_op": {
      // The machine of yours that makes it, never the make-now route (a process you may not own).
      const owned = row.at_quantity?.owned;
      if (owned?.process) return `${owned.machine ?? routeName(owned.process, machines)}${owned.material ? ` · ${owned.material}` : ""}`;
      return `${routeName(route?.process, machines)}${material}`;
    }
    case "makeable_not_on_owned":
      if (entry) return `${routeName(gap?.process, machines)} · ${gapPhrase(entry, gap?.process, machines)}`;
      return "Owns the kind of machine; none fits";
    case "makeable_outsource_only":
      return `No owned machine for ${procName(route?.process).toLowerCase()}${material}`;
    case "environment_excluded":
      return "Ruled out by its service conditions";
    case "not_makeable": {
      if (entry) return wallWords(entry.human) ?? firstSentence(entry.human ?? gapPhrase(entry, gap?.process, machines));
      const c = unitCost(row);
      if (c?.reason) return wallWords(c.reason) ?? firstSentence(c.reason);
      return "No route makes it as drawn";
    }
    case null:
    case undefined:
      return "Not checked against your machines";
    default:
      return humanize(v);
  }
}

/** True when a machine of yours makes it, but the engine's own comparison buys it at the part's quantity. */
export function cheaperToBuy(row: MakeRow): boolean {
  const a = row.at_quantity;
  return !!a && !!a.owned?.process && a.in_house === false && (row.makeability?.verdict === "makeable_in_house" || row.makeability?.verdict === "makeable_with_secondary_op");
}

/** "Cheaper to buy at 200", saying when it's against your own price. */
export function cheaperToBuyText(row: MakeRow): string {
  const a = row.at_quantity!;
  return `Cheaper to buy at ${a.qty.toLocaleString("en-US")}${a.buy_price ? " (your price)" : ""}`;
}

/** "$19.54 at 10", "Withheld", or "—". At the part's own quantity when the row carries it. Never invents a figure. */
export function costLabel(row: MakeRow): string {
  const a = row.at_quantity;
  const money = (n: number) => `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  if (a) {
    const inside = (row.makeability?.verdict === "makeable_in_house" || row.makeability?.verdict === "makeable_with_secondary_op") && a.owned?.usd != null;
    const usd = inside ? a.owned!.usd : a.dfm_ready === false ? null : a.usd;
    if (typeof usd === "number" && Number.isFinite(usd)) return `${money(usd)} at ${a.qty.toLocaleString("en-US")}`;
  }
  const c = unitCost(row);
  if (!c) return "—";
  if (c.withheld || c.usd == null) return c.withheld ? "Withheld" : "—";
  const usd = `$${c.usd.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  return c.qty != null && c.qty > 1 ? `${usd} at ${c.qty.toLocaleString("en-US")}` : usd;
}

/** True when the part's own check names a wall too thin for its route. */
export function wallTooThin(row: MakeRow): boolean {
  const entries = row.makeability?.gap?.gap ?? [];
  if (entries.some((e) => /wall/i.test(`${e.axis ?? ""} ${e.human ?? ""}`) && (e.gate === "dfm" || /thin|min wall/i.test(e.human ?? "")))) return true;
  const c = unitCost(row);
  return !!c?.reason && /min(imum)? wall|too thin/i.test(c.reason);
}

/** True when the part's verdict was reached before the machine list last changed. */
export function isStale(row: MakeRow): boolean {
  return !!row.makeability?.stale;
}

/** Which batch lane a part sits in: its bucket, with "ruled out" split off when the part only needs a design change. */
export function laneKey(bucket: string, row: MakeRow | null): string {
  if (bucket === "not_makeable" && row) {
    const entry = primaryGap(row);
    if (entry?.gate === "dfm" || wallTooThin(row)) return "design_change";
  }
  return bucket;
}

export const LANES: Record<string, { label: string; tone: Tone; color: string }> = {
  makeable_in_house: { label: "Make in-house", tone: "ok", color: "#146C43" },
  design_change: { label: "Design change", tone: "warn", color: "#8C5200" },
  needs_capability: { label: "New equipment", tone: "warn", color: "#B97F0C" },
  not_makeable: { label: "Ruled out", tone: "bad", color: "#B42318" },
  makeable_outside: { label: "Outside only", tone: "unk", color: "#9AA3AE" },
  unknown: { label: "Not checked against your machines", tone: "unk", color: "#5F656E" },
  geometry_invalid: { label: "Invalid geometry", tone: "unk", color: "#141414" },
};

export const LANE_ORDER = ["makeable_in_house", "design_change", "needs_capability", "not_makeable", "makeable_outside", "unknown", "geometry_invalid"];

export function laneDef(key: string): { key: string; label: string; tone: Tone; color: string } {
  const l = LANES[key];
  return l ? { key, ...l } : { key, label: humanize(key), tone: "unk", color: "#9AA3AE" };
}
