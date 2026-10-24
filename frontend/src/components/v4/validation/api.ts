/**
 * Same-origin calls for your actuals (backend /api/v1/actuals): the import
 * preview and import, the comparison with ScaleCAD's estimates, the calibration
 * (what it would change, apply, undo) and the pilot report.
 */
import { API_BASE } from "@/lib/api-base";
import type { BreakdownMachine, BreakdownMaterial, BreakdownMissing, BucketBreakdown } from "../many/catalog-model";

export class ActualsApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  constructor(message: string, status: number, code: string | null) {
    super(message);
    this.name = "ActualsApiError";
    this.status = status;
    this.code = code;
  }
}

function messageOf(body: unknown, status: number): { msg: string; code: string | null } {
  const b = body as { detail?: unknown; message?: unknown } | null;
  const d = b?.detail ?? b?.message;
  if (typeof d === "string" && d) return { msg: d, code: null };
  if (d && typeof d === "object" && !Array.isArray(d)) {
    const o = d as { message?: unknown; reason?: unknown; code?: unknown };
    const m = typeof o.message === "string" ? o.message : typeof o.reason === "string" ? o.reason : null;
    if (m) return { msg: m, code: typeof o.code === "string" ? o.code : null };
  }
  if (Array.isArray(d)) return { msg: d.map((x) => (x && typeof x === "object" && "msg" in x ? String((x as { msg: unknown }).msg) : String(x))).join("; "), code: null };
  return { msg: `Request failed (${status})`, code: null };
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...init });
  } catch {
    throw new ActualsApiError("ScaleCAD couldn’t be reached. Check your connection and try again.", 0, "network");
  }
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!res.ok) {
    const { msg, code } = messageOf(body, res.status);
    throw new ActualsApiError(msg, res.status, code);
  }
  return body as T;
}

/* ---------------- import ---------------- */

export type FieldKey =
  | "part"
  | "file_name"
  | "part_number"
  | "file_hash"
  | "quantity"
  | "machine_hours"
  | "machine_hours_total"
  | "cost_each"
  | "cost_total"
  | "process"
  | "machine"
  | "date"
  | "reference"
  | "notes"
  | "kind";

export type Mapping = {
  columns: Partial<Record<FieldKey, number>>;
  hours_unit: "h" | "min";
  date_order: "mdy" | "dmy";
  process_map: Record<string, string>;
  test: boolean;
  /** What the file's numbers are (op-18): what we paid a supplier, or what it cost us to make. A row's Kind wins. */
  source?: "made" | "bought";
  /** Why ScaleCAD guessed it ("it has a Vendor column"), until the person chooses. */
  source_guess?: string | null;
};

export type PartPick = { key: string; file_name: string; label: string | null; record_id: string; checked_at: string | null; part_numbers: string[] };

export type PreviewRow = {
  line: number;
  status: "matched" | "ambiguous" | "unmatched" | "error";
  values: {
    part_number: string | null;
    file_name: string | null;
    file_hash: string | null;
    quantity: number | null;
    hours_each: number | null;
    cost_each: number | null;
    process: string | null;
    method_from: string | null;
    machine: string | null;
    date: string | null;
    reference: string | null;
    notes: string | null;
    source_type: string;
    test: boolean;
  };
  errors: string[];
  warnings: string[];
  basis: string | null;
  reason: string;
  part: PartPick | null;
  candidates: PartPick[];
};

export type Preview = {
  file: { name: string; kind: "csv" | "xlsx"; rows: number; notes: string[] };
  headers: string[];
  sample: string[][];
  fields: { key: FieldKey; label: string }[];
  mapping: Mapping;
  process_values: { value: string; key: string; rows: number; guess: string | null; method: string | null }[];
  parts_checked: number;
  parts: PartPick[];
  summary: { rows: number; matched: number; ambiguous: number; unmatched: number; error: number; test: number; parts: number };
  rows: PreviewRow[];
};

export type ImportResult = { imported: number; parts: number; test: number; bought?: number; made?: number; rows: number; not_imported: { line: number | null; status?: string; reason: string }[] };

function form(file: File, mapping: Mapping | null, choices: Record<string, string> | null): FormData {
  const f = new FormData();
  f.append("file", file, file.name);
  if (mapping) f.append("mapping", JSON.stringify(mapping));
  if (choices && Object.keys(choices).length) f.append("choices", JSON.stringify(choices));
  return f;
}

export function previewActuals(file: File, mapping: Mapping | null, choices: Record<string, string> | null): Promise<Preview> {
  return call("/actuals/preview", { method: "POST", body: form(file, mapping, choices) });
}

export function importActuals(file: File, mapping: Mapping, choices: Record<string, string>): Promise<ImportResult> {
  return call("/actuals/import", { method: "POST", body: form(file, mapping, choices) });
}

/* ---------------- accuracy ---------------- */

/** What a row prints and its arithmetic on exactly those printed numbers ("12.55 min ÷ 14.40 min − 1 = −12.8%"). */
export type Shown = { estimate: string; actual: string; error: string | null; formula: string | null };

export type Metric = {
  actual: number;
  estimate: number;
  low: number | null;
  high: number | null;
  error_pct: number;
  inside: boolean | null;
  /** exact: the record priced this quantity · model: the record's own quantity model at it */
  basis?: "exact" | "model" | string | null;
  /** For a model price: "ScaleCAD's model at 25: $188.50 once ÷ 25 + $47.74 a part = $55.28 (...)" */
  basis_note?: string | null;
  shown?: Shown;
};

/** Setup (for the order), labor and inspection (a part) hours an actual carries, next to the record's stated hours. */
export type HourLine = { line: "setup" | "labor" | "inspection"; label: string; actual: number; estimate: number | null; error_pct?: number; shown?: Shown; note?: string };

/** Which rate card priced the record an actual is compared with, and which is in effect now. */
export type RatesBasis = { priced: number; current: number; out_of_date: boolean; text: string };

export type Comparison = {
  id: string;
  part_key: string;
  file_name: string | null;
  part_number: string | null;
  record_id: string | null;
  process: string | null;
  quantity: number | null;
  machine: string | null;
  date: string | null;
  reference: string | null;
  test: boolean;
  hours: Metric | null;
  cost: Metric | null;
  note: string | null;
  calibrated_record: boolean;
  rates?: RatesBasis | null;
  /** true: cost not compared because the record predates the org's published rates */
  rates_excluded?: boolean;
  hour_lines?: HourLine[];
  /** made: what it cost you to make; bought: what you paid a supplier (compared with ScaleCAD's outside price). */
  kind?: "made" | "bought";
  /** What the actual was compared with, in words ("ScaleCAD's outside price for 3-axis milling at a job shop, at 500"). */
  compared_with?: string | null;
};

export type Stats = {
  n: number;
  parts: number;
  median_abs_pct: number | null;
  median_pct: number | null;
  worst_pct: number | null;
  worst: { file_name: string | null; part_key: string | null; part_number: string | null; process: string | null } | null;
  inside: number;
  with_range: number;
  enough: boolean;
};

export type Summary = {
  parts: number;
  actuals: number;
  compared: number;
  not_compared: number;
  test: number;
  min_parts: number;
  min_per_method: number;
  enough: boolean;
  hours: Stats;
  cost: Stats;
  per_process: { process: string; hours: Stats; cost: Stats }[];
  /** Cost rows left out because their record was priced at older rates than the org's published ones. */
  rates_excluded?: number;
  /** The rate card versions the compared costs were priced at (0 = typical). */
  rates_priced?: number[];
  /** What the figures above summarize: your own job costs against ScaleCAD's estimate. */
  population?: string;
  /** What you paid suppliers against ScaleCAD's outside price: never mixed into the figures above. */
  bought?: { population: string; actuals: number; compared: number; not_compared: number; parts: number; enough: boolean; cost: Stats };
};

export type CalibrationEntry = {
  id: string;
  status: "applied" | "undone";
  in_effect: boolean;
  factors: Record<string, { hours: number | null; cost: number | null; hours_parts?: number; cost_parts?: number; hours_before_pct?: number | null; hours_after_pct?: number | null; cost_before_pct?: number | null; cost_after_pct?: number | null }>;
  basis: { parts?: number; applied_processes?: string[] };
  applied_at: string | null;
  applied_by: string | null;
  undone_at: string | null;
  undone_by: string | null;
};

export type Accuracy = { rows: Comparison[]; summary: Summary; calibration: CalibrationEntry | null; scope: { part: string | null; run: string | null } };

export function getAccuracy(scope: { part?: string | null; run?: string | null } = {}): Promise<Accuracy> {
  const q = scope.part ? `?part=${encodeURIComponent(scope.part)}` : scope.run ? `?run=${encodeURIComponent(scope.run)}` : "";
  return call(`/actuals/accuracy${q}`);
}

/* ---------------- calibration ---------------- */

export type FactorEntry = {
  n: number;
  parts: number;
  factor: number | null;
  before_pct?: number | null;
  after_pct?: number | null;
  offer: boolean;
  why: "offer" | "few" | "out_of_range" | "no_change" | "no_better" | "org_few" | "none" | null;
  after_hours?: boolean;
};

export type Proposal = { parts: number; min_parts: number; min_per_method: number; enough: boolean; processes: { process: string; hours: FactorEntry; cost: FactorEntry }[]; /** Supplier invoices, never fitted on. */ bought_excluded?: number };

export type CalibrationState = { proposal: Proposal; history: CalibrationEntry[]; can_apply: boolean };

export function getCalibration(): Promise<CalibrationState> {
  return call("/actuals/calibration");
}

export function applyCalibration(processes: string[]): Promise<{ applied: CalibrationEntry | null; history: CalibrationEntry[] }> {
  return call("/actuals/calibration/apply", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ processes }) });
}

export function undoCalibration(): Promise<{ undone: string; in_effect: CalibrationEntry | null; history: CalibrationEntry[] }> {
  return call("/actuals/calibration/undo", { method: "POST" });
}

/* ---------------- report ---------------- */

export type ReportBucket = {
  key: string;
  label: string;
  parts: number;
  quantity: number;
  hours: number | null;
  hours_parts: number;
  mass_kg: number | null;
  mass_parts: number;
  /** Material the routes use (stock, printed material with supports), where the records say it. */
  used_kg?: number | null;
  used_parts?: number;
  cost_usd: number | null;
  cost_parts: number;
} & Partial<BucketBreakdown>;

export type Report = {
  organization: string | null;
  generated_at: string;
  scope: { kind: "run" | "all"; run_id: string | null; created_at?: string | null; quantity: number | null; parts_list?: { name: string } | null };
  /** Page one (op-20): the run's answer as the run page says it, what it covers, what the prices assume. */
  headline?: { head: string; sub: string; missing: string | null } | null;
  coverage?: {
    parts: number;
    checked: number;
    /** Failed or skipped. */
    not_checked: number;
    /** Queued or being checked (op-28). */
    to_go?: number;
    not_sorted: number;
    text: string;
    reasons: { reason: string; parts: number }[];
    unchecked: { part: string | null; reason: string | null }[];
    unsorted: { part: string | null; reason: string | null }[];
  } | null;
  basis?: string[];
  /** "Haas VF-2: 12,400 h needed of 11,520 h a year (108%)" for each machine overloaded. */
  overloaded?: string[];
  /** Accuracy figures only with enough actuals to say something. */
  accuracy_shown?: boolean;
  parts: number;
  buckets: ReportBucket[];
  other: Record<string, number>;
  in_house: {
    parts: number;
    hours: number | null;
    hours_parts: number;
    mass_kg: number | null;
    mass_parts: number;
    used_kg?: number | null;
    used_parts?: number;
    cost_usd: number | null;
    machines: { machine: string; process: string | null; hours: number; parts: number; available_hours?: number | null; utilization_pct?: number | null; overloaded?: boolean | null; capacity?: { set: boolean; text: string } | null }[];
    materials?: BreakdownMaterial[];
  };
  /** Needs a new machine: the capability each part lacks. */
  missing?: BreakdownMissing[];
  /** Made outside: the processes no machine of yours does, with their machine time. */
  outside?: BreakdownMachine[];
  wins: { file_name: string | null; part_number: string | null; part_key: string | null; quantity: number; process: string | null; machine: string | null; in_house_each: number; outside_each: number; outside_process: string | null; vs?: "you" | "parts_list" | "model"; saving_total: number; hours_total: number | null }[];
  decisions: {
    part_key: string;
    file_name: string | null;
    part_number: string | null;
    decision: string;
    code: string;
    process: string | null;
    /** The quantity the decision was recorded at. */
    quantity?: number | null;
    note: string | null;
    by: string | null;
    at: string | null;
    /** The sign-off on the recorded decision, and whether what was signed off has changed since. */
    signoff?: { by: string | null; at: string | null; note: string | null; stale: boolean; stale_reason: string | null } | null;
  }[];
  /** Recorded decisions signed off, and how many of those are now out of date. */
  signoffs?: { signed_off: number; out_of_date: number; recorded: number };
  accuracy: Summary;
  accuracy_rows: Comparison[];
  calibration: CalibrationEntry | null;
  caveats: string[];
};

export function getReport(run?: string | null): Promise<Report> {
  return call(`/actuals/report${run ? `?run=${encodeURIComponent(run)}` : ""}`);
}

export function reportPdfUrl(run?: string | null): string {
  return `${API_BASE}/actuals/report.pdf${run ? `?run=${encodeURIComponent(run)}` : ""}`;
}
