/**
 * Pure helpers for the Your shop screens (boards O9, S1, S2, S3): method names,
 * machine status and envelope, the work-area drawing, the rate card in effect,
 * shop operations, and the record/provenance counts the Rates and Real costs
 * pages show. No fetching here; every number comes from the caller's API data.
 */
import { processLabel } from "../process-names.ts";

/** Processes in the order the add/edit form lists them (board O9), in the one spelling every screen uses. */
export const PROCS: readonly (readonly [string, string])[] = ["fdm", "sla", "dlp", "sls", "mjf", "dmls", "slm", "ebm", "binder_jetting", "ded", "waam", "cnc_3axis", "cnc_5axis", "cnc_turning", "wire_edm", "injection_molding", "die_casting", "investment_casting", "sand_casting", "sheet_metal", "forging"].map((c) => [c, processLabel(c)] as const);

const PROC_NAME: Record<string, string> = Object.fromEntries(PROCS);

/** Shorter names for headers and tiles (the sheet's "kind" line). */
const PROC_SHORT: Record<string, string> = { cnc_turning: "Lathe" };

export function procName(p: string | null | undefined): string {
  if (!p) return "Unknown method";
  return PROC_NAME[p] ?? p;
}

export function procShort(p: string | null | undefined): string {
  if (!p) return "Unknown method";
  return PROC_SHORT[p] ?? procName(p);
}

/** Additive methods: the ones a machine is called a printer for. */
export const PRINTER_PROCS = new Set(["fdm", "sla", "dlp", "sls", "mjf", "dmls", "slm", "ebm", "binder_jetting", "ded", "waam"]);

export const LATHE = "cnc_turning";

type MachineLike = {
  name: string | null;
  process: string;
  count: number | null;
  hourly_rate_usd: number | null;
  max_workpiece_kg: number | null;
  capabilities: Record<string, unknown> | null;
};

export function machineName(m: Pick<MachineLike, "name" | "process">): string {
  return m.name?.trim() || procName(m.process);
}

/** Owned, with or without a declared rate. A declaration never establishes fit. */
export function machineStatus(m: Pick<MachineLike, "hourly_rate_usd">): { label: string; rated: boolean } {
  return m.hourly_rate_usd != null ? { label: "Owned · rate declared", rated: true } : { label: "Owned · no rate", rated: false };
}

/** "$85/h", "$85.50/h". */
export function perHour(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  const digits = Number.isInteger(n) ? 0 : 2;
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}/h`;
}

/** A plain number without trailing zeros ("762", "0.4", "12.5"). */
export function plain(n: number): string {
  return String(Math.round(n * 1000) / 1000);
}

function capNum(cap: Record<string, unknown> | null | undefined, key: string): number | null {
  const v = cap?.[key];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

export type Envelope = {
  /** Drawing extents in mm (a lathe's swing is both width and depth). */
  w: number;
  d: number;
  h: number;
  /** "762 × 406 × 508 mm" or "Ø254 × 533 mm". */
  text: string;
  /** The compact figure form ("762×406×508", "Ø254×533"). */
  fig: string;
  /** The key/value label for this envelope. */
  label: string;
};

/**
 * A machine's declared work envelope, read from the same capability keys the API
 * stores and the engine reads. Lathes use swing_dia + between_centers; a lathe
 * saved before that used X × Y × Z and says so. Null when nothing is declared.
 */
export function envelopeOf(m: Pick<MachineLike, "process" | "capabilities">): Envelope | null {
  const cap = m.capabilities ?? {};
  const swing = capNum(cap, "swing_dia");
  const between = capNum(cap, "between_centers");
  if (swing != null && between != null) {
    return { w: swing, d: swing, h: between, text: `Ø${plain(swing)} × ${plain(between)} mm`, fig: `Ø${plain(swing)}×${plain(between)}`, label: "Swing × between centers" };
  }
  const x = capNum(cap, "x") ?? capNum(cap, "bed_x") ?? capNum(cap, "platen_x");
  const y = capNum(cap, "y") ?? capNum(cap, "bed_y") ?? capNum(cap, "platen_y");
  const z = capNum(cap, "z") ?? capNum(cap, "daylight");
  if (x == null || y == null) return null;
  const lathe = m.process === LATHE;
  const label = lathe ? "Work area (declared X × Y × Z)" : "Work area";
  if (z == null) return { w: x, d: y, h: Math.min(x, y) / 20, text: `${plain(x)} × ${plain(y)} mm`, fig: `${plain(x)}×${plain(y)}`, label };
  return { w: x, d: y, h: z, text: `${plain(x)} × ${plain(y)} × ${plain(z)} mm`, fig: `${plain(x)}×${plain(y)}×${plain(z)}`, label };
}

/**
 * The tile drawing: an isometric box of the envelope, proportions to scale,
 * fitted into a 300 × 150 view box (board O9's math). Returns SVG path data.
 */
export function isoBox(W: number, D: number, H: number): { floor: string; back: string; front: string } {
  const c30 = Math.cos(Math.PI / 6);
  const sc = Math.min(270 / ((W + D) * c30), 140 / ((W + D) * 0.5 + H));
  const ox = 150 - ((W - D) * c30 * sc) / 2;
  const oy = 145 - (W + D) * 0.5 * sc;
  const P = (x: number, y: number, z: number): [number, number] => [ox + (x - y) * c30 * sc, oy + (x + y) * 0.5 * sc - z * sc];
  const pt = (p: [number, number]) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`;
  const L = (a: [number, number], b: [number, number]) => `M${pt(a)} L${pt(b)}`;
  const o = P(0, 0, 0), x = P(W, 0, 0), y = P(0, D, 0), xy = P(W, D, 0);
  const z = P(0, 0, H), xz = P(W, 0, H), yz = P(0, D, H), xyz = P(W, D, H);
  return {
    floor: [o, x, xy, y].map(pt).join(" "),
    back: [L(o, x), L(o, y), L(o, z)].join(" "),
    front: [L(x, xy), L(y, xy), L(x, xz), L(y, yz), L(xy, xyz), L(z, xz), L(z, yz), L(xz, xyz), L(yz, xyz)].join(" "),
  };
}

/** The tile's detail line: "3-axis milling · ×1 · $85/h · 200 kg max". */
export function tileSub(m: MachineLike): string {
  const parts = [procShort(m.process), `×${m.count ?? 1}`];
  parts.push(m.hourly_rate_usd != null ? perHour(m.hourly_rate_usd) : "no rate");
  if (m.max_workpiece_kg != null) parts.push(`${plain(m.max_workpiece_kg)} kg max`);
  return parts.join(" · ");
}

/* ------------------------------------------------------------------ */
/*  Shop operations (the shop-level secondary ops the engine asks for)  */
/* ------------------------------------------------------------------ */

/** The ops the engine requires by name (makeability `_required_secondary_ops`). */
export const SHOP_OPS: readonly (readonly [string, string])[] = [
  ["stress_relief", "Stress relief"],
  ["sinter", "Sintering"],
  ["hip", "HIP"],
  ["grinding", "Grinding"],
];

/** An op is in-house when declared true or with size limits; `false` or absent is not. */
export function opOn(ops: Record<string, unknown>, key: string): boolean {
  const v = ops[key];
  return v === true || (typeof v === "object" && v !== null);
}

/** Toggle one op, keeping every other op (and a declared limits object) as it is. */
export function toggleOp(ops: Record<string, unknown>, key: string): Record<string, unknown> {
  const next = { ...ops };
  if (opOn(ops, key)) delete next[key];
  else next[key] = true;
  return next;
}

/* ------------------------------------------------------------------ */
/*  Rate card in effect                                                 */
/* ------------------------------------------------------------------ */

export type RateVersionLike = {
  id: number | string;
  version?: number | null;
  name?: string | null;
  status?: string | null;
  is_published?: boolean | null;
  effective_from?: string | null;
  effective_to?: string | null;
  published_at?: string | null;
  created_at?: string | null;
  change_note?: string | null;
};

export type RateCardView = {
  governed: boolean;
  flag: boolean;
  authored: number;
  published: number;
  drafts: number;
  inEffect: RateVersionLike | null;
  /** O9 chip ("Default v0", "Governed · 2 published"). */
  chip: string;
  /** S1 chip, with authored count ("Default v0 · none authored"). */
  chipLong: string;
  aria: string;
  title: string;
  counts: string;
};

function isPublished(v: RateVersionLike): boolean {
  return v.status === "published" || v.is_published === true;
}

/** The published version whose effective window contains `now` (latest start wins). */
export function versionInEffect(versions: RateVersionLike[], now: number): RateVersionLike | null {
  const live = versions.filter((v) => {
    if (!isPublished(v)) return false;
    const from = v.effective_from ? Date.parse(v.effective_from) : NaN;
    const to = v.effective_to ? Date.parse(v.effective_to) : NaN;
    return (Number.isNaN(from) || from <= now) && (Number.isNaN(to) || to > now);
  });
  live.sort((a, b) => (Date.parse(b.effective_from ?? "") || 0) - (Date.parse(a.effective_from ?? "") || 0));
  return live[0] ?? null;
}

export function rateCardView(
  eff: { using_governed: boolean; flag_enabled: boolean } | null,
  versions: RateVersionLike[] | null,
  now: number = Date.now()
): RateCardView | null {
  if (!eff || !versions) return null;
  const authored = versions.length;
  const published = versions.filter(isPublished).length;
  const drafts = versions.filter((v) => v.status === "draft").length;
  const counts = `${count(authored, "version")} authored, ${published} published.`;
  if (eff.using_governed) {
    const inEffect = versionInEffect(versions, now);
    const vn = inEffect?.version != null ? `v${inEffect.version}` : "published card";
    return {
      governed: true,
      flag: eff.flag_enabled,
      authored,
      published,
      drafts,
      inEffect,
      chip: `Governed · ${published} published`,
      chipLong: `Governed · ${vn} in effect`,
      aria: `Rate card: governed, ${vn} in effect, ${published} published. Show details`,
      title: inEffect?.version != null ? `Rate card v${inEffect.version}${inEffect.name ? ` · ${inEffect.name}` : ""}` : "Governed rate card",
      counts: `Reviewed rates. ${counts}`,
    };
  }
  const none = authored === 0;
  return {
    governed: false,
    flag: eff.flag_enabled,
    authored,
    published,
    drafts,
    inEffect: null,
    chip: "Default v0",
    chipLong: none ? "Default v0 · none authored" : `Default v0 · ${authored} authored, none in effect`,
    aria: `Rate card: default v0, ${none ? "none authored" : `${authored} authored, none in effect`}. Show details`,
    title: "Default rate card v0",
    counts: `Built-in default rates. ${counts}`,
  };
}

function count(n: number, one: string): string {
  return `${n} ${n === 1 ? one : one + "s"}`;
}

/* ------------------------------------------------------------------ */
/*  Dates                                                               */
/* ------------------------------------------------------------------ */

/** "Oct 18, 04:16" in the viewer's zone. */
export function shortWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
}

/** "Oct 18, 2026". */
export function longDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

/* ------------------------------------------------------------------ */
/*  Machine load (the hours of work checked parts put on a machine)    */
/* ------------------------------------------------------------------ */

/** "<1 min", "6 min", "1.3 h", "41 h", "1,204 h", or "—". */
export function hoursShort(h: number | null | undefined): string {
  if (h == null || !Number.isFinite(h) || h < 0) return "—";
  if (h === 0) return "0 h";
  if (h < 1 / 60) return "<1 min";
  if (h < 1) return `${Math.round(h * 60)} min`;
  if (h < 10) return `${(Math.round(h * 10) / 10).toLocaleString("en-US")} h`;
  return `${Math.round(h).toLocaleString("en-US")} h`;
}

export interface LoadLike {
  machine: string;
  parts: number;
  hours: number | null;
  hours_parts: number;
  decided_parts: number;
  decided_hours: number | null;
  default_parts: number;
  default_hours: number | null;
  stale_parts: number;
}

function partsWord(n: number): string {
  return `${n.toLocaleString("en-US")} ${n === 1 ? "part" : "parts"}`;
}

/** The load of the machine named, matched by name (records name the machine they were fitted to). */
export function loadFor<T extends { machine: string }>(loads: readonly T[] | null | undefined, name: string): T | null {
  return (loads ?? []).find((l) => l.machine === name) ?? null;
}

/** The tile's line: "41 h of work · 12 parts", or "No checked parts" when none land on it. */
export function loadTile(l: LoadLike | null): string {
  if (!l || !l.parts) return "No checked parts on it";
  return l.hours != null ? `${hoursShort(l.hours)} of work · ${partsWord(l.parts)}` : `${partsWord(l.parts)} · machine time not estimated`;
}

/** The sheet's rows: total, then recorded in-house (at their quantities) and not decided yet (at the quantity each was checked for, else `qty` of each). */
export function loadRows(l: LoadLike | null, qty: number): [string, string][] {
  if (!l || !l.parts) return [];
  const cover = l.hours_parts < l.parts ? ` (${l.hours_parts} of ${l.parts} parts)` : "";
  const rows: [string, string][] = [["Machine time", `${hoursShort(l.hours)}${cover} · ${partsWord(l.parts)}`]];
  if (l.decided_parts) rows.push(["Recorded in-house", `${partsWord(l.decided_parts)} · ${hoursShort(l.decided_hours)} at their quantities`]);
  if (l.default_parts) rows.push(["Not decided yet", `${partsWord(l.default_parts)} · ${hoursShort(l.default_hours)} at the quantity checked, else ${qty.toLocaleString("en-US")} of each`]);
  return rows;
}
