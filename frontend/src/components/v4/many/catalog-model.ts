/**
 * The catalog run, as the screens read it: who may run one (from the usage
 * read), which picked files go in, the board's buckets in order, each part's
 * resources-first line, sorting and filtering, and the totals sentence. Pure:
 * no React, no fetch, so it runs under `node --test`. Every figure comes from
 * the board the server derived from the engine's own records; a missing one
 * stays missing ("—"), never zero.
 */
import { machineKind, processName } from "../process-names.ts";

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
  };
  hours_each: number | null;
  hours_total: number | null;
  mass_kg_total: number | null;
  unit_cost_usd: number | null;
  total_cost_usd: number | null;
  price_withheld: string | null;
  machine_rate_usd: number | null;
  marginal: boolean;
  capability: { process: string | null; gate: string | null; single?: boolean | null; need?: unknown; have?: unknown; human: string | null; all?: string[] } | null;
  cheaper_outside: { process: string; unit_cost_usd: number } | null;
  duration_ms: number | null;
  error: string | null;
}

export interface BucketTotal {
  parts: number;
  quantity: number;
  hours: number | null;
  hours_parts: number;
  mass_kg: number | null;
  mass_parts: number;
  cost_usd: number | null;
  cost_parts: number;
}

export interface Board {
  batch_id: string;
  status: string;
  free: boolean;
  material_class: string | null;
  quantity: number;
  parts_list: { name: string | null; rows: number; matched: number; unmatched: number } | null;
  unmatched: { row?: number; file: string | null; part_number: string | null; quantity: number | null; material: string | null }[];
  machines: { name: string; process: string }[];
  created_at: string | null;
  completed_at: string | null;
  rows: BoardRow[];
  totals: Record<string, BucketTotal>;
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

/** "45 g", "1.27 kg", "312 kg", or "—". */
export function massText(kg: number | null | undefined): string {
  if (!finite(kg)) return "—";
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
  const material = matName ? `${matName}${finite(r.material.mass_kg_each) ? ` · ${massText(r.material.mass_kg_each)} each` : ""}` : "—";
  let ownership = "—";
  if (r.route?.owned) ownership = `Your ${r.route.machine ?? procName(r.route.process)}${r.marginal && finite(r.machine_rate_usd) ? ` · marginal ${money(r.machine_rate_usd)}/h` : r.marginal ? " · marginal rate" : ""}`;
  else if (r.bucket === "new_machine") ownership = `You own ${aMachine(r.capability?.process ?? r.route?.process)}; none fits`;
  else if (r.bucket === "outside" && r.route?.process) ownership = `Not owned · ${aMachine(r.route.process)} would be an acquisition`;
  let price = "—";
  if (finite(r.unit_cost_usd)) price = `${money(r.unit_cost_usd)} each${finite(r.total_cost_usd) && q > 1 ? ` · ${money(r.total_cost_usd, 0)} for ${q.toLocaleString("en-US")}` : ""}`;
  else if (r.price_withheld) price = `Withheld: ${r.price_withheld}`;
  return { time, material, ownership, price };
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
  const byName = (a: BoardRow, b: BoardRow) => a.filename.localeCompare(b.filename, "en", { numeric: true });
  const out = [...rows];
  if (key === "name") return out.sort(byName);
  if (key === "hours") return out.sort((a, b) => desc(a.hours_total, b.hours_total) || byName(a, b));
  if (key === "cost") return out.sort((a, b) => desc(a.total_cost_usd, b.total_cost_usd) || byName(a, b));
  if (key === "mass") return out.sort((a, b) => desc(a.mass_kg_total, b.mass_kg_total) || byName(a, b));
  return out.sort((a, b) => (ORDER[a.bucket] ?? 99) - (ORDER[b.bucket] ?? 99) || desc(a.hours_total, b.hours_total) || byName(a, b));
}

export function filterRows(rows: readonly BoardRow[], bucket: string, query: string): BoardRow[] {
  const q = query.trim().toLowerCase();
  return rows.filter((r) => {
    if (bucket !== "all" && r.bucket !== bucket) return false;
    if (!q) return true;
    return [r.filename, r.part_number, r.reason, r.material.name, r.material.declared, r.route?.machine]
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
  if (finite(t.mass_kg)) bits.push(`${massText(t.mass_kg)}${cover(t.mass_parts)}`);
  if (finite(t.cost_usd)) bits.push(`${money(t.cost_usd, 0)}${cover(t.cost_parts)}`);
  return bits.join(" · ");
}

export function bucketCount(board: Board | null, key: string): number {
  return board?.totals?.[key]?.parts ?? 0;
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
