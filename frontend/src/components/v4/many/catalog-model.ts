/**
 * The catalog run, as the screens read it: who may run one (from the usage
 * read), which picked files go in, the board's buckets in order, each part's
 * resources-first line, sorting and filtering, and the totals sentence. Pure:
 * no React, no fetch, so it runs under `node --test`. Every figure comes from
 * the board the server derived from the engine's own records; a missing one
 * stays missing ("—"), never zero.
 */
import { machineKind, processName } from "../process-names.ts";
import { inText, type LengthUnit } from "../units/units.ts";

/* ------------------------------------------------------------------ */
/*  The board, as GET /batch/{id}/catalog returns it                   */
/* ------------------------------------------------------------------ */

export type BucketKey = "in_house" | "outside" | "new_machine" | "cant_make" | "not_sorted" | "not_checked" | "checking";

export interface BoardRow {
  item_id: string;
  filename: string;
  part_number: string | null;
  description?: string | null;
  status: string;
  part_key: string | null;
  analysis_id: string | null;
  cost_decision_id: string | null;
  quantity: number;
  quantity_source: "list" | "run";
  verdict: string | null;
  bucket: BucketKey | string;
  reason: string | null;
  route: { process: string | null; machine: string | null; owned: boolean } | null;
  material: {
    declared: string | null;
    class: string | null;
    note: string | null;
    name: string | null;
    mass_kg_each: number | null;
    mass_basis: string | null;
    /** The material the engine charges for per part: stock cut from, material printed with supports, metal poured. */
    used_kg_each?: number | null;
  };
  hours_each: number | null;
  hours_total: number | null;
  mass_kg_total: number | null;
  used_kg_total?: number | null;
  unit_cost_usd: number | null;
  total_cost_usd: number | null;
  price_withheld: string | null;
  machine_rate_usd: number | null;
  marginal: boolean;
  capability: { process: string | null; gate: string | null; single?: boolean | null; need?: unknown; have?: unknown; human: string | null; all?: string[] } | null;
  cheaper_outside: { process: string; unit_cost_usd: number; same_process?: boolean } | null;
  duration_ms: number | null;
  error: string | null;
  /** The part specs the run priced with (or the parts list declared), and what the supplier must hold. */
  specs?: import("./row-specs").RowSpecs | null;
  /** The outcome recorded on the part's record, and its sign-off. */
  outcome?: string | null;
  signoff?: import("./row-specs").RowSignoff | null;
  record_out_of_date?: boolean;
  /** One body shape of a file the run checked body by body (a weldment, parts saved together). */
  body?: BodyOfFile | null;
  /** The row's name: the file, or "bracket-assembly.step, body 1 of 3". */
  name?: string;
  /** On the parts list (its quantity, material and price are the list's). */
  listed?: boolean;
  /** What you pay today for one, and where the price came from. */
  current_price?: { usd_each: number; source: "you" | "parts_list"; text: string } | null;
  /** The cheapest route on a machine of yours at the part's quantity. */
  make?: { process: string | null; machine: string | null; material?: string | null; unit_cost_usd: number; low_usd: number | null; high_usd: number | null } | null;
  /** What buying it costs: your price, else the cheapest outside price. */
  buy?: { unit_cost_usd: number; source: "you" | "parts_list" | "model"; text: string | null; process: string | null; same_process: boolean } | null;
  /** Buying wins: what making it on your machine would cost, and how many times the buy price. */
  could_make?: { process: string | null; machine: string | null; unit_cost_usd: number; times: number | null } | null;
  /** In-house against what you pay today: each and at the part's quantity. */
  saving?: { each: number; total: number; vs: "you" | "parts_list" } | null;
}

export interface BodyOfFile {
  file: string;
  file_key: string | null;
  kind: string | null;
  ids: number[];
  copies: number;
  of: number | null;
  shape: string | null;
  name: string | null;
}

/** A file the board shows body by body, and what it says about it. */
export interface SplitFile {
  filename: string;
  part_key: string | null;
  kind: string | null;
  summary: string | null;
  bodies: number;
  rows: number;
  words: string;
}

/**
 * "Body 1 of 4 in frame.stl · 2 per file · Square tube 40 × 40 × 3 mm, 600 mm long".
 * Only the shape's figures follow the person's unit; the body and file names are names.
 */
export function bodyLine(r: BoardRow, unit: LengthUnit = "mm"): string | null {
  const b = r.body;
  if (!b) return null;
  const which = b.name ? `${b.name}` : b.ids.length > 1 ? `Bodies ${b.ids.join(", ")}` : `Body ${b.ids[0] ?? "?"}`;
  const of = b.of ? ` of ${b.of}` : "";
  return [`${which}${of} in ${b.file}`, b.copies > 1 ? `${b.copies} per file` : null, b.shape ? inText(b.shape, unit) : null].filter(Boolean).join(" · ");
}

export interface BoardMachine {
  name: string;
  process: string;
  count?: number;
  /** The hourly rate you set, the share of it that pays for the machine, and what's left: the running rate. */
  hourly_rate_usd?: number;
  capital_frac?: number;
  capital_frac_set?: boolean;
  running_rate_usd?: number;
}

/** The run's answer: make N, buy M, the rest, and the saving against what you pay today. */
export interface RunAnswer {
  parts: number;
  make: number;
  buy: number;
  new_machine: number;
  cant_make: number;
  not_checked: number;
  not_sorted: number;
  checking: number;
  undecided: number;
  with_price: number;
  saving_usd: number | null;
  saving_parts: number;
  make_without_price: number;
  make_cost_usd: number | null;
}

export interface BucketTotal {
  parts: number;
  quantity: number;
  hours: number | null;
  hours_parts: number;
  mass_kg: number | null;
  mass_parts: number;
  /** The material used (what the routes charge for), where the records say it. */
  used_kg?: number | null;
  used_parts?: number;
  cost_usd: number | null;
  cost_parts: number;
}

/** Per bucket, resources first: machine hours by machine (or process), material by grade, the capability missing. */
export interface BreakdownMachine {
  machine: string | null;
  process: string | null;
  owned: boolean;
  parts: number;
  hours: number | null;
  hours_parts: number;
}
export interface BreakdownMaterial {
  material: string;
  parts: number;
  used_kg: number | null;
  used_parts: number;
  part_kg: number | null;
  part_parts: number;
}
export interface BreakdownMissing {
  process: string | null;
  gate: string | null;
  need: unknown;
  human: string | null;
  parts: number;
  hours: number | null;
}
export interface BucketBreakdown {
  machines: BreakdownMachine[];
  materials: BreakdownMaterial[];
  missing: BreakdownMissing[];
}

export interface Board {
  batch_id: string;
  status: string;
  free: boolean;
  material_class: string | null;
  quantity: number;
  parts_list: { name: string | null; rows: number; matched: number; unmatched: number } | null;
  unmatched: { row?: number; file: string | null; part_number: string | null; description?: string | null; quantity: number | null; material: string | null }[];
  machines: BoardMachine[];
  /** Machines counted as Your shop counts them (3 VF-2s are 3). */
  machine_count?: number;
  /** The run's name: its ZIP's, else its parts list's. */
  name?: string | null;
  /** The organization the run belongs to. */
  org_name?: string | null;
  /** Files in the ZIP (a file of several bodies is one file, several rows). */
  files?: number;
  /** With a parts list, the totals and the answer cover the parts on it. */
  has_list?: boolean;
  unlisted?: { parts: number; totals: Record<string, BucketTotal> } | null;
  answer?: RunAnswer;
  /** What decides make or buy, in one line. */
  bucket_rule?: string;
  created_at: string | null;
  completed_at: string | null;
  rows: BoardRow[];
  /** Files with several bodies: on the board one row per body shape, counted once as a file. */
  split_files?: SplitFile[];
  totals: Record<string, BucketTotal>;
  /** Present from the server; derived from the rows when it isn't. */
  breakdown?: Record<string, BucketBreakdown>;
}

/* ------------------------------------------------------------------ */
/*  Buckets                                                            */
/* ------------------------------------------------------------------ */

export interface BucketDef {
  key: BucketKey;
  label: string;
  short: string;
  tone: "ok" | "warn" | "bad" | "unk";
  color: string;
  /** What a part here means, for the bucket header. */
  note: string;
}

export const BUCKETS: BucketDef[] = [
  { key: "in_house", label: "Make in-house", short: "In-house", tone: "ok", color: "#146C43", note: "One of your machines makes it" },
  { key: "outside", label: "Buy outside", short: "Outside", tone: "unk", color: "#5F656E", note: "None of your machines does the process" },
  { key: "new_machine", label: "Needs a new machine", short: "New machine", tone: "warn", color: "#8C5200", note: "You own the kind of machine; none fits" },
  { key: "cant_make", label: "Can’t be made as drawn", short: "Can’t make", tone: "bad", color: "#B42318", note: "No route makes it as drawn" },
];

export const OTHER: BucketDef[] = [
  { key: "not_sorted", label: "Not sorted", short: "Not sorted", tone: "unk", color: "#9AA3AE", note: "Checked, no verdict on your machines" },
  { key: "not_checked", label: "Not checked", short: "Not checked", tone: "unk", color: "#141414", note: "The file couldn’t be checked" },
  { key: "checking", label: "Checking", short: "Checking", tone: "unk", color: "#1F4FC4", note: "Still running" },
];

const ALL_DEFS = [...BUCKETS, ...OTHER];

export function bucketDef(key: string): BucketDef {
  return ALL_DEFS.find((b) => b.key === key) ?? { key: key as BucketKey, label: key.replace(/_/g, " "), short: key, tone: "unk", color: "#9AA3AE", note: "" };
}

const ORDER: Record<string, number> = Object.fromEntries(ALL_DEFS.map((b, i) => [b.key, i]));

/* ------------------------------------------------------------------ */
/*  Numbers                                                            */
/* ------------------------------------------------------------------ */

function finite(n: number | null | undefined): n is number {
  return typeof n === "number" && Number.isFinite(n);
}

/** "6 min", "1.3 h", "41 h", "1,204 h", or "—". */
export function hoursText(h: number | null | undefined): string {
  if (!finite(h)) return "—";
  if (h < 1 / 60) return "<1 min";
  if (h < 1) return `${Math.round(h * 60)} min`;
  if (h < 10) return `${h.toFixed(1)} h`;
  return `${Math.round(h).toLocaleString("en-US")} h`;
}

/** "<1 g", "45 g", "1.27 kg", "312 kg", or "—". */
export function massText(kg: number | null | undefined): string {
  if (!finite(kg)) return "—";
  if (kg > 0 && kg < 0.0005) return "<1 g"; // a tiny part's 0.04 g, not "1 g"
  if (kg < 1) return `${Math.max(1, Math.round(kg * 1000)).toLocaleString("en-US")} g`;
  if (kg < 100) return `${kg.toFixed(kg < 10 ? 2 : 1)} kg`;
  return `${Math.round(kg).toLocaleString("en-US")} kg`;
}

export function money(n: number | null | undefined, digits = 2): string {
  if (!finite(n)) return "—";
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

export function procName(p: string | null | undefined): string {
  return p ? processName(p) : "—";
}

/** "a 3-axis mill", "an EDM machine". */
function aMachine(p: string | null | undefined): string {
  const name = machineKind(p) || "machine";
  const k = /^[A-Z][a-z]/.test(name) ? name[0].toLowerCase() + name.slice(1) : name;
  return `${/^[aeiouAEIOU]/.test(k) ? "an" : "a"} ${k}`;
}

/* ------------------------------------------------------------------ */
/*  A part's line: resources first, price second                       */
/* ------------------------------------------------------------------ */

export interface PartLine {
  /** "Machine time 0.3 h each · 7.5 h for 25" */
  time: string;
  /** "6061-T6 Aluminum · 270 g each" */
  material: string;
  /** "Your Haas VF-2 · marginal $48.76/h" | "Not owned · a filament printer would be an acquisition" */
  ownership: string;
  /** "$30.00 each · $750.00 for 25" | "Withheld: walls under 0.8 mm" | "—" */
  price: string;
}

export function partLine(r: BoardRow): PartLine {
  const q = r.quantity;
  const time = finite(r.hours_each) ? `${hoursText(r.hours_each)} each${finite(r.hours_total) && q > 1 ? ` · ${hoursText(r.hours_total)} for ${q.toLocaleString("en-US")}` : ""}` : "—";
  const matName = r.material.name ?? (r.material.declared ? r.material.declared : null);
  // The engine prices a class (aluminum, plastic…) and picks the grade for the route; when
  // that differs from what the parts list named, say so instead of hiding the list's word.
  const declared = r.material.declared?.trim();
  const listed = declared && r.material.name && !r.material.name.toLowerCase().includes(declared.toLowerCase()) && !declared.toLowerCase().includes(r.material.name.toLowerCase()) ? ` · listed ${declared}` : "";
  // The material the route uses leads (stock, printed material with supports); the part's own mass follows when it differs.
  const used = r.material.used_kg_each;
  const part = r.material.mass_kg_each;
  const mass = finite(used)
    ? ` · ${massText(used)} each${finite(part) && Math.abs(used - part) > 0.02 * part ? ` · part ${massText(part)}` : ""}`
    : finite(part)
      ? ` · ${massText(part)} each`
      : "";
  const material = matName ? `${matName}${mass}${listed}` : "—";
  let ownership = "—";
  if (r.route?.owned) ownership = `Your ${r.route.machine ?? procName(r.route.process)}${r.marginal && finite(r.machine_rate_usd) ? ` · running rate ${money(r.machine_rate_usd)}/h` : r.marginal ? " · running rate" : ""}`;
  else if (r.could_make) ownership = `Bought · your ${r.could_make.machine ?? procName(r.could_make.process)} could make it`;
  else if (r.bucket === "new_machine") {
    const cap = r.capability;
    const why = cap?.gate === "material" && typeof cap.need === "string" ? `not qualified for ${cap.need}` : cap?.gate === "envelope" ? "too small for it" : "none fits";
    ownership = `You own ${aMachine(cap?.process ?? r.route?.process)}; ${why}`;
  }
  else if (r.bucket === "outside" && r.route?.process) ownership = `Not owned · ${aMachine(r.route.process)} would be an acquisition`;
  let price = "—";
  if (finite(r.unit_cost_usd)) price = `${money(r.unit_cost_usd)} each${finite(r.total_cost_usd) && q > 1 ? ` · ${money(r.total_cost_usd, 0)} for ${q.toLocaleString("en-US")}` : ""}`;
  else if (r.price_withheld) price = `Withheld: ${r.price_withheld}`;
  return { time, material, ownership, price };
}

/**
 * A row's words in the person's unit: the reason, the body's shape, its spec
 * line, the price (a withheld price says why, often a wall in mm) and the
 * material note. Every mm figure in the engine's words reads in inches when the
 * person chose inches; the file name and part number are never touched (a file
 * called "box-60mm.stl" keeps its name).
 */
export function rowWords(r: BoardRow, unit: LengthUnit, spec: string | null = null): { reason: string | null; body: string | null; spec: string | null; price: string; note: string | null } {
  const u = (t: string | null | undefined) => (t ? inText(t, unit) : null);
  return { reason: u(r.reason), body: bodyLine(r, unit), spec: u(spec), price: inText(partLine(r).price, unit), note: u(r.material.note) };
}

/** The row's name: the file the person gave, or which body of it. */
export function rowName(r: Pick<BoardRow, "name" | "filename">): string {
  return r.name || r.filename;
}

function priceFrom(source: string | null | undefined): string {
  return source === "you" ? "your price" : source === "parts_list" ? "your parts list's price" : "";
}

/**
 * Make against buy on one row: "Make $38.71 on your Haas VF-2 · Buy $5.13, sheet metal outside",
 * "Buy $4.00, your price", with the saving when it's against what you pay today. Null when neither side is priced.
 */
export function compareLine(r: BoardRow): string | null {
  const make = r.make ?? (r.could_make ? { unit_cost_usd: r.could_make.unit_cost_usd, machine: r.could_make.machine, process: r.could_make.process } : null);
  const buy = r.buy;
  if (!make && !buy) return null;
  const bits: string[] = [];
  if (make) bits.push(`Make ${money(make.unit_cost_usd)} on your ${make.machine ?? procName(make.process)}`);
  if (buy) {
    const from = buy.source === "model" ? (buy.process ? `${procName(buy.process).toLowerCase()} outside${buy.same_process ? " (a shop running your process)" : ""}` : "outside") : priceFrom(buy.source);
    bits.push(`Buy ${money(buy.unit_cost_usd)}${from ? `, ${from}` : ""}`);
  }
  if (r.saving) bits.push(r.saving.each >= 0 ? `saves ${money(r.saving.each)} each` : `costs ${money(-r.saving.each)} more each, inside the estimate's range`);
  return bits.join(" · ");
}

/** The run's name: its ZIP's, else its parts list's (older runs kept only that), else "Catalog run". */
export function runTitle(board: Board | null): string {
  const list = board?.parts_list?.name?.replace(/\.(csv|tsv|txt)$/i, "").trim();
  return board?.name || list || "Catalog run";
}

/** The parts the answer covers: the parts list's when the run has one, else all. */
export function scopedRows(board: Board | null): BoardRow[] {
  if (!board) return [];
  return board.has_list ? board.rows.filter((r) => r.listed) : board.rows;
}

/** Files in the ZIP the parts list doesn't name: shown apart, not in the answer. */
export function unlistedRows(board: Board | null): BoardRow[] {
  return board?.has_list ? board.rows.filter((r) => !r.listed) : [];
}

/** "50 files → 56 parts (2 assemblies split into bodies)", or "12 parts". */
export function countLine(board: Board | null): string {
  if (!board) return "";
  const parts = board.rows.length;
  const files = board.files ?? parts;
  const split = board.split_files ?? [];
  const p = (n: number, one: string, many = `${one}s`) => `${n.toLocaleString("en-US")} ${n === 1 ? one : many}`;
  if (!split.length || files === parts) return p(parts, "part");
  const kinds = new Set(split.map((f) => f.kind));
  const what = kinds.size === 1 && kinds.has("assembly") ? p(split.length, "assembly", "assemblies") : kinds.size === 1 && kinds.has("weldment") ? p(split.length, "weldment") : p(split.length, "file");
  return `${p(files, "file")} → ${p(parts, "part")} (${what} split into bodies)`;
}

/** "Against 5 machines", counted as Your shop counts them. */
export function machinesText(board: Board | null): string {
  if (!board) return "Machines loading";
  const n = board.machine_count ?? board.machines.reduce((s, m) => s + (m.count ?? 1), 0);
  return n ? `Against ${n} ${n === 1 ? "machine" : "machines"}` : "No machines yet";
}

/** What a running rate is, per machine with a rate you set: "Haas VF-2: $85.00/h you set, less 35% that pays for the machine: $55.25/h". */
export function runningRateLines(board: Board | null): string[] {
  return (board?.machines ?? [])
    .filter((m) => finite(m.hourly_rate_usd) && finite(m.running_rate_usd))
    .map((m) => `${m.name}: ${money(m.hourly_rate_usd)}/h you set, less ${Math.round((m.capital_frac ?? 0) * 100)}% that pays for the machine itself${m.capital_frac_set ? "" : " (a typical share; set yours in Your shop)"}: ${money(m.running_rate_usd)}/h`);
}

/**
 * The run's answer, as a heading and a line under it. With current prices:
 * "Make these 12 parts in-house: save $41,200 a year against what you pay today".
 * Without: the counts, and what's missing for a saving.
 */
export function answerText(board: Board | null): { head: string; sub: string; missing: string | null } | null {
  const a = board?.answer;
  if (!a || !board) return null;
  const n = (k: number, one: string, many = `${one}s`) => `${k.toLocaleString("en-US")} ${k === 1 ? one : many}`;
  const year = board.has_list ? " a year" : "";
  let head: string;
  if (a.saving_usd != null && a.saving_parts) {
    const these = a.make === a.saving_parts ? `these ${n(a.make, "part")}` : `${n(a.make, "part")}`;
    head = `Make ${these} in-house: save ${money(a.saving_usd, 0)}${year} against what you pay today${a.make_without_price ? ` (on the ${a.saving_parts} with a current price)` : ""}`;
  } else if (a.make) head = `Make ${n(a.make, "part")} in-house, buy ${a.buy}`;
  else if (a.buy) head = `Buy all ${n(a.buy, "part")} that could be decided`;
  else if (a.checking) head = `Checking ${n(a.checking, "part")}: the answer fills in as each one finishes`;
  else head = a.parts ? "No part could be decided yet" : "No parts yet";
  const rest: string[] = [];
  if (a.saving_usd != null && a.saving_parts) rest.push(`Buy ${a.buy}`);
  if (a.new_machine) rest.push(`${a.new_machine} need a new machine`);
  if (a.undecided) {
    const why = [a.cant_make ? `${a.cant_make} can’t be made as drawn` : null, a.not_checked ? `${a.not_checked} not checked` : null, a.not_sorted ? `${a.not_sorted} not sorted` : null, a.checking ? `${a.checking} still checking` : null].filter(Boolean).join(", ");
    rest.push(`${a.undecided} can’t be decided yet (${why})`);
  }
  if (board.has_list) rest.push("parts on your list, at their listed quantities");
  const sub = rest.join(" · ");
  const missing =
    a.saving_usd == null
      ? a.make
        ? "No saving yet: it needs what you pay today. Add a Current price column to the parts list, or type the price on a part’s Decision view."
        : null
      : a.make_without_price
        ? `${n(a.make_without_price, "in-house part")} ${a.make_without_price === 1 ? "has" : "have"} no current price, so ${a.make_without_price === 1 ? "it isn’t" : "they aren’t"} in the saving.`
        : null;
  return { head, sub, missing };
}

/* ------------------------------------------------------------------ */
/*  Sorting, filtering, grouping                                       */
/* ------------------------------------------------------------------ */

export type SortKey = "bucket" | "hours" | "cost" | "mass" | "name";

export const SORTS: [SortKey, string][] = [
  ["bucket", "Bucket"],
  ["hours", "Machine time"],
  ["mass", "Material"],
  ["cost", "Price"],
  ["name", "Name"],
];

function desc(a: number | null, b: number | null): number {
  if (!finite(a) && !finite(b)) return 0;
  if (!finite(a)) return 1;
  if (!finite(b)) return -1;
  return b - a;
}

export function sortRows(rows: readonly BoardRow[], key: SortKey): BoardRow[] {
  const byName = (a: BoardRow, b: BoardRow) => rowName(a).localeCompare(rowName(b), "en", { numeric: true });
  const out = [...rows];
  if (key === "name") return out.sort(byName);
  if (key === "hours") return out.sort((a, b) => desc(a.hours_total, b.hours_total) || byName(a, b));
  if (key === "cost") return out.sort((a, b) => desc(a.total_cost_usd, b.total_cost_usd) || byName(a, b));
  if (key === "mass") return out.sort((a, b) => desc(a.used_kg_total ?? a.mass_kg_total, b.used_kg_total ?? b.mass_kg_total) || byName(a, b));
  return out.sort((a, b) => (ORDER[a.bucket] ?? 99) - (ORDER[b.bucket] ?? 99) || desc(a.hours_total, b.hours_total) || byName(a, b));
}

export function filterRows(rows: readonly BoardRow[], bucket: string, query: string): BoardRow[] {
  const q = query.trim().toLowerCase();
  return rows.filter((r) => {
    if (bucket !== "all" && r.bucket !== bucket) return false;
    if (!q) return true;
    return [r.filename, r.name, r.part_number, r.description, r.reason, r.material.name, r.material.declared, r.route?.machine]
      .some((s) => typeof s === "string" && s.toLowerCase().includes(q));
  });
}

/** Parts needing a new machine, grouped by the capability each lacks, most parts first. */
export function capabilityGroups(rows: readonly BoardRow[]): { key: string; process: string | null; text: string; rows: BoardRow[] }[] {
  const m = new Map<string, { key: string; process: string | null; text: string; rows: BoardRow[] }>();
  for (const r of rows) {
    if (r.bucket !== "new_machine") continue;
    const cap = r.capability;
    const gate = cap?.gate ?? "fit";
    const kind = machineKind(cap?.process ?? null) || "Machine";
    const text = cap?.gate === "material" && typeof cap.need === "string"
      ? `${kind} qualified for ${cap.need}`
      : cap?.gate === "envelope"
        ? `${kind} with a larger work area`
        : cap?.human
          ? `${kind}: ${cap.human}`
          : `${kind} that fits`;
    const key = `${cap?.process ?? ""}:${gate}:${cap?.gate === "material" ? String(cap.need) : ""}`;
    if (!m.has(key)) m.set(key, { key, process: cap?.process ?? null, text, rows: [] });
    m.get(key)!.rows.push(r);
  }
  return [...m.values()].sort((a, b) => b.rows.length - a.rows.length || a.text.localeCompare(b.text));
}

/** "41 h · 12.4 kg · $3,420" for a bucket's totals, with "of N" when a sum covers fewer parts. */
export function totalsText(t: BucketTotal | undefined): string {
  if (!t || !t.parts) return "";
  const cover = (n: number) => (n < t.parts ? ` (${n} of ${t.parts})` : "");
  const bits: string[] = [];
  if (finite(t.hours)) bits.push(`${hoursText(t.hours)}${cover(t.hours_parts)}`);
  if (finite(t.used_kg) && t.used_parts) bits.push(`${massText(t.used_kg)}${cover(t.used_parts)}`);
  else if (finite(t.mass_kg)) bits.push(`${massText(t.mass_kg)}${cover(t.mass_parts)}`);
  if (finite(t.cost_usd)) bits.push(`${money(t.cost_usd, 0)}${cover(t.cost_parts)}`);
  return bits.join(" · ");
}

/** The bucket's breakdown: the server's, else the same sums from the rows (an older board). */
export function bucketBreakdown(rows: readonly BoardRow[], key: string): BucketBreakdown {
  const machines = new Map<string, BreakdownMachine>();
  const materials = new Map<string, BreakdownMaterial>();
  const missing = new Map<string, BreakdownMissing>();
  const add = (a: number | null, b: number | null | undefined) => (finite(b) ? Math.round(((a ?? 0) + b) * 1e4) / 1e4 : a);
  for (const r of rows) {
    if (r.bucket !== key) continue;
    const process = r.route?.process ?? r.capability?.process ?? null;
    const owned = !!r.route?.owned;
    if (process || r.route?.machine) {
      const machine = owned ? r.route?.machine ?? null : null;
      const k = `${machine ?? ""}|${process ?? ""}`;
      const m = machines.get(k) ?? { machine, process, owned, parts: 0, hours: null, hours_parts: 0 };
      m.parts += 1;
      if (finite(r.hours_total)) m.hours_parts += 1;
      m.hours = add(m.hours, r.hours_total);
      machines.set(k, m);
    }
    const mat = r.material?.name;
    if (mat) {
      const g = materials.get(mat) ?? { material: mat, parts: 0, used_kg: null, used_parts: 0, part_kg: null, part_parts: 0 };
      g.parts += 1;
      if (finite(r.used_kg_total)) g.used_parts += 1;
      if (finite(r.mass_kg_total)) g.part_parts += 1;
      g.used_kg = add(g.used_kg, r.used_kg_total);
      g.part_kg = add(g.part_kg, r.mass_kg_total);
      materials.set(mat, g);
    }
    const cap = r.capability;
    if (key === "new_machine" && cap) {
      const need = cap.gate === "material" && (typeof cap.need === "string" || typeof cap.need === "number") ? cap.need : null;
      const k = `${cap.process ?? ""}|${cap.gate ?? ""}|${need ?? ""}`;
      const g = missing.get(k) ?? { process: cap.process, gate: cap.gate, need, human: cap.human, parts: 0, hours: null };
      g.parts += 1;
      g.hours = add(g.hours, r.hours_total);
      missing.set(k, g);
    }
  }
  return {
    machines: [...machines.values()].sort((a, b) => (b.hours ?? 0) - (a.hours ?? 0) || b.parts - a.parts || String(a.machine ?? a.process).localeCompare(String(b.machine ?? b.process))),
    materials: [...materials.values()].sort((a, b) => (b.used_kg ?? b.part_kg ?? 0) - (a.used_kg ?? a.part_kg ?? 0) || b.parts - a.parts || a.material.localeCompare(b.material)),
    missing: [...missing.values()].sort((a, b) => b.parts - a.parts || String(a.process ?? "").localeCompare(String(b.process ?? ""))),
  };
}

export function breakdownOf(board: Board | null, key: string): BucketBreakdown {
  return board?.breakdown?.[key] ?? bucketBreakdown(board?.rows ?? [], key);
}

function plural(n: number, one: string): string {
  return `${n.toLocaleString("en-US")} ${n === 1 ? one : `${one}s`}`;
}

/** "On Haas VF-2" · "12 parts · 41 h", or "Filament printing, not owned" outside. Hours "of N" when they cover fewer parts. */
export function machineLine(m: BreakdownMachine): { label: string; value: string } {
  const label = m.owned && m.machine ? `On ${m.machine}` : `${procName(m.process)}${m.owned ? "" : ", not owned"}`;
  const cover = m.hours_parts < m.parts ? ` (${m.hours_parts} of ${m.parts})` : "";
  return { label, value: `${plural(m.parts, "part")} · ${finite(m.hours) ? `${hoursText(m.hours)}${cover}` : "machine time not estimated"}` };
}

/** "6061-T6 Aluminum" · "3.20 kg used · 4 parts" (the parts' own mass when the records don't say what's used). */
export function materialLine(g: BreakdownMaterial): { label: string; value: string } {
  const mass = finite(g.used_kg) && g.used_parts ? `${massText(g.used_kg)} used${g.used_parts < g.parts ? ` (${g.used_parts} of ${g.parts})` : ""}` : finite(g.part_kg) ? `${massText(g.part_kg)} in the parts` : "mass not known";
  return { label: g.material, value: `${mass} · ${plural(g.parts, "part")}` };
}

export function bucketCount(board: Board | null, key: string): number {
  return board?.totals?.[key]?.parts ?? 0;
}

/** Parts that couldn't be checked and can be checked again (a body's file goes back whole). */
export function recheckable(board: Board | null): BoardRow[] {
  return (board?.rows ?? []).filter((r) => r.bucket === "not_checked");
}

/** "12 of 50 checked · 3 checking" from the board (part by part). */
export function boardProgress(board: Board | null): { done: number; total: number; checking: number; failed: number } {
  if (!board) return { done: 0, total: 0, checking: 0, failed: 0 };
  const checking = bucketCount(board, "checking");
  const failed = bucketCount(board, "not_checked");
  const total = board.rows.length;
  return { done: total - checking, total, checking, failed };
}

/* ------------------------------------------------------------------ */
/*  Who may run one                                                    */
/* ------------------------------------------------------------------ */

export interface CatalogUsage {
  eligible: boolean;
  unlimited: boolean;
  cap: number | null;
  used: number | null;
  reserved: number | null;
  remaining: number | null;
}

export type CatalogAccess =
  | { kind: "loading" }
  | { kind: "pilot" }
  | { kind: "free"; usage: CatalogUsage; phoneNeeded: boolean }
  | { kind: "personal" }
  | { kind: "unknown" };

/** From GET /auth/me/usage: pilot, a work-email free allowance, or personal email (single checks only). */
export function catalogAccess(u: unknown): CatalogAccess {
  if (!u || typeof u !== "object") return { kind: "unknown" };
  const usage = u as { plan?: unknown; catalog?: unknown; phone_verification_required?: unknown };
  if (usage.plan === "pilot") return { kind: "pilot" };
  const c = usage.catalog as Partial<CatalogUsage> | undefined;
  if (!c || typeof c !== "object") return { kind: "unknown" };
  if (c.unlimited) return { kind: "pilot" };
  if (!c.eligible) return { kind: "personal" };
  return {
    kind: "free",
    phoneNeeded: usage.phone_verification_required === true,
    usage: {
      eligible: true,
      unlimited: false,
      cap: typeof c.cap === "number" ? c.cap : null,
      used: typeof c.used === "number" ? c.used : null,
      reserved: typeof c.reserved === "number" ? c.reserved : null,
      remaining: typeof c.remaining === "number" ? c.remaining : null,
    },
  };
}

/** "50 free catalog parts", "38 of 50 free parts left", "Free parts used". */
export function allowanceText(a: CatalogAccess): string {
  if (a.kind === "pilot") return "Pilot plan · no part limit";
  if (a.kind !== "free") return "";
  const { cap, used, reserved, remaining } = a.usage;
  if (cap == null || remaining == null) return "Free catalog parts";
  if ((used ?? 0) + (reserved ?? 0) === 0) return `${cap} free catalog parts`;
  if (remaining === 0) return `All ${cap} free catalog parts used`;
  return `${remaining} of ${cap} free catalog parts left`;
}

/* ------------------------------------------------------------------ */
/*  Picked files                                                       */
/* ------------------------------------------------------------------ */

export const CAD_EXT = /\.(stl|step|stp|iges|igs)$/i;
const NATIVE = /\.(sldprt|sldasm|ipt|iam|prt|asm|catpart|catproduct|x_t|x_b|3dm|f3d|par|psm|dwg|dxf|jt|obj|3mf)$/i;
const LIST = /\.(csv|tsv|txt)$/i;
/** The batch's per-file limit (backend BATCH_MAX_FILE_BYTES). */
export const MAX_FILE_BYTES = 100 * 1024 * 1024;
export const FREE_MAX_ZIP_BYTES = 1024 ** 3;

export interface PickedFile {
  name: string;
  /** Folder path inside a picked folder ("parts/brackets/a.step"), else the name. */
  path: string;
  size: number;
}

export interface FilePlan<T extends PickedFile> {
  cad: T[];
  zip: T | null;
  list: T | null;
  skipped: { name: string; why: string }[];
  bytes: number;
  problem: string | null;
}

/**
 * Sort what was picked or dropped: CAD files go in, one ZIP can go alone, a
 * CSV is the parts list, the rest is named and left out with the reason.
 */
export function planFiles<T extends PickedFile>(files: readonly T[], opts: { maxZipBytes?: number } = {}): FilePlan<T> {
  const cad: T[] = [];
  const zips: T[] = [];
  const lists: T[] = [];
  const skipped: { name: string; why: string }[] = [];
  const seen = new Set<string>();
  for (const f of files) {
    const base = f.name;
    if (/^\./.test(base) || /(^|\/)__MACOSX\//.test(f.path)) continue;
    if (/\.zip$/i.test(base)) zips.push(f);
    else if (LIST.test(base)) lists.push(f);
    else if (CAD_EXT.test(base)) {
      if (f.size === 0) skipped.push({ name: base, why: "empty file" });
      else if (f.size > MAX_FILE_BYTES) skipped.push({ name: base, why: "over 100 MB" });
      else if (seen.has(f.path)) continue;
      else {
        seen.add(f.path);
        cad.push(f);
      }
    } else if (NATIVE.test(base)) skipped.push({ name: base, why: "native CAD or drawing: export STEP" });
    else skipped.push({ name: base, why: "not a CAD file" });
  }
  const zip = zips[0] ?? null;
  for (const z of zips.slice(1)) skipped.push({ name: z.name, why: "one ZIP at a time" });
  const list = lists[0] ?? null;
  for (const l of lists.slice(1)) skipped.push({ name: l.name, why: "one parts list at a time" });
  const bytes = zip ? zip.size : cad.reduce((s, f) => s + f.size, 0);
  let problem: string | null = null;
  if (zip && cad.length) problem = "Choose one ZIP, or loose files and folders, not both.";
  else if (!zip && !cad.length) problem = files.length ? "None of these is a STEP, STL or IGES file." : null;
  else if (opts.maxZipBytes && bytes > opts.maxZipBytes) problem = `These add up to ${sizeText(bytes)}; a free run takes up to ${sizeText(opts.maxZipBytes)}. Split them into two runs.`;
  return { cad, zip, list, skipped, bytes, problem };
}

export function sizeText(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** A free account's note on how many picked parts fit, before the server counts reruns. */
export function fitNote(nFiles: number, a: CatalogAccess): string | null {
  if (a.kind !== "free" || a.usage.remaining == null || nFiles === 0) return null;
  const left = a.usage.remaining;
  if (nFiles <= left) return null;
  return `${nFiles} files and ${left} free ${left === 1 ? "part" : "parts"} left. Parts you’ve already run or checked don’t count again; ScaleCAD counts them when the run starts.`;
}

/** Names inside the ZIP built in the browser: folder paths kept, so the server's file names stay readable. */
export function zipEntryName(f: PickedFile): string {
  const p = (f.path || f.name).replace(/\\/g, "/").replace(/^\/+/, "");
  return p.split("/").filter((s) => s && s !== "." && s !== "..").join("/") || f.name;
}

/* ------------------------------------------------------------------ */
/*  Server refusals, in product words                                  */
/* ------------------------------------------------------------------ */

export interface RunError {
  code: string | null;
  message: string;
  batchId?: string | null;
}

export function refusalTitle(e: RunError): string {
  switch (e.code) {
    case "catalog_allowance_exceeded":
      return "More parts than your free run has left";
    case "catalog_run_active":
      return "A run is still going";
    case "catalog_run_work_email":
      return "Catalog runs need a work email";
    case "phone_verification_required":
      return "Verify your phone first";
    case "free_tool_limit":
      return "Free run limit reached";
    case "INVALID_PARTS_LIST":
      return "The parts list couldn’t be read";
    default:
      return "The run didn’t start";
  }
}

/* ------------------------------------------------------------------ */
/*  Materials                                                          */
/* ------------------------------------------------------------------ */

export const MATERIALS: [string, string][] = [
  ["", "From the file, else plastic"],
  ["aluminum", "Aluminum"],
  ["steel", "Steel"],
  ["stainless", "Stainless steel"],
  ["titanium", "Titanium"],
  ["polymer", "Plastic"],
];

export function materialWord(cls: string | null | undefined): string {
  const m = MATERIALS.find(([k]) => k === (cls ?? ""));
  return m ? m[1] : cls ?? "";
}
