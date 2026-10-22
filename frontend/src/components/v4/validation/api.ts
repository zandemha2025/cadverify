/**
 * Same-origin calls for your actuals (backend /api/v1/actuals): the import
 * preview and import, the comparison with ScaleCAD's estimates, the calibration
 * (what it would change, apply, undo) and the pilot report.
 */
import { API_BASE } from "@/lib/api-base";

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

export type ImportResult = { imported: number; parts: number; test: number; rows: number; not_imported: { line: number | null; status?: string; reason: string }[] };

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

export type Metric = { actual: number; estimate: number; low: number | null; high: number | null; error_pct: number; inside: boolean | null; basis?: string | null };

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

export type Proposal = { parts: number; min_parts: number; min_per_method: number; enough: boolean; processes: { process: string; hours: FactorEntry; cost: FactorEntry }[] };

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

export type ReportBucket = { key: string; label: string; parts: number; quantity: number; hours: number | null; hours_parts: number; mass_kg: number | null; mass_parts: number; cost_usd: number | null; cost_parts: number };

export type Report = {
  organization: string | null;
  generated_at: string;
  scope: { kind: "run" | "all"; run_id: string | null; created_at?: string | null; quantity: number | null; parts_list?: { name: string } | null };
  parts: number;
  buckets: ReportBucket[];
  other: Record<string, number>;
  in_house: { parts: number; hours: number | null; hours_parts: number; mass_kg: number | null; mass_parts: number; cost_usd: number | null; machines: { machine: string; process: string | null; hours: number; parts: number }[] };
  wins: { file_name: string | null; part_number: string | null; part_key: string | null; quantity: number; process: string | null; machine: string | null; in_house_each: number; outside_each: number; outside_process: string | null; saving_total: number; hours_total: number | null }[];
  decisions: { part_key: string; file_name: string | null; part_number: string | null; decision: string; code: string; process: string | null; note: string | null; by: string | null; at: string | null }[];
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
