/**
 * Pure helpers for Actual costs (board S2): the recalibration floors, the
 * per-method calibration rows, the "Log a job" form, and the range shown for
 * one part. Floors mirror the backend: groundtruth_service.MIN_REAL_RECORDS and
 * costing/groundtruth.MIN_RESIDUALS (a test reads both from the Python source).
 */
import type { EstimateRow, GroundTruthIn } from "./shop-api";

/** Real (non-stand-in) records an organization needs before recalibration runs. */
export const MIN_REAL_RECORDS = 8;
/** Held-out real results a method needs for a measured range. */
export const MIN_HELD_OUT = 3;

export type GtRecord = {
  part_id: string;
  process: string;
  quantity: number;
  /** Empty when the actual carries machine hours only. */
  actual_unit_cost_usd: number | null;
  stand_in: boolean;
  source: string;
  created_at: string | null;
  source_type?: string | null;
  invoice_date?: string | null;
  actual_machine_hours?: number | null;
  part_number?: string | null;
  machine?: string | null;
  match_basis?: string | null;
  evidence_sha256?: string | null;
};

export function countRecords(records: GtRecord[] | null): { real: number; standIn: number } {
  const real = (records ?? []).filter((r) => !r.stand_in).length;
  return { real, standIn: (records ?? []).length - real };
}

/** Kinds of job a user logs (source_type); synthetic kinds only come in by CSV and never count. */
export const JOB_KINDS: [string, string][] = [
  ["actual", "Actual job"],
  ["invoice", "Invoice"],
  ["quote", "Supplier quote"],
  ["pilot", "Pilot job"],
];

/** The engine's material classes, in the words the form shows. */
export const MATERIAL_CLASSES: [string, string][] = [
  ["aluminum", "Aluminum"],
  ["steel", "Steel"],
  ["stainless", "Stainless"],
  ["titanium", "Titanium"],
  ["polymer", "Plastic"],
];

export type RecalResult = {
  n_real: number;
  n_records: number;
  n_skipped: number;
  skipped?: { part_id: string; process: string; quantity: number; reason: string }[];
  validated: boolean;
  validated_processes?: string[];
  claim: string | null;
  heldout_metrics_real: { per_process?: Record<string, { n: number; median_abs_pct?: number }>; band_covers_80pct?: number } | null;
};

export type MethodRow = {
  process: string;
  machines: string[];
  savedParts: number;
  real: number;
  heldOut: number | null;
  measured: boolean;
};

/**
 * One row per method you own a machine for or have logged a job on. Held-out
 * results and the measured flag come from this session's recalibration when
 * there is one, else from what your saved estimates say their range was built
 * from (a validated band carries its sample count).
 */
export function methodRows(args: {
  machines: { process: string; name: string | null }[];
  records: GtRecord[];
  savedProcesses: (string | null)[];
  estimates: (EstimateRow | null)[];
  recal: RecalResult | null;
}): MethodRow[] {
  const procs: string[] = [];
  const add = (p: string | null | undefined) => {
    if (p && !procs.includes(p)) procs.push(p);
  };
  args.machines.forEach((m) => add(m.process));
  args.records.forEach((r) => add(r.process));
  return procs.map((p) => {
    const real = args.records.filter((r) => r.process === p && !r.stand_in).length;
    const savedParts = args.savedProcesses.filter((x) => x === p).length;
    let heldOut: number | null = null;
    let measured = false;
    if (args.recal) {
      heldOut = args.recal.heldout_metrics_real?.per_process?.[p]?.n ?? 0;
      measured = (args.recal.validated_processes ?? []).includes(p);
    } else {
      const v = args.estimates.find((e) => e && e.process === p && e.confidence?.validated);
      if (v) {
        measured = true;
        heldOut = v.confidence?.n_samples ?? null;
      }
    }
    return { process: p, machines: args.machines.filter((m) => m.process === p).map((m) => m.name ?? p), savedParts, real, heldOut, measured };
  });
}

/* ------------------------------------------------------------------ */
/*  Log a job                                                           */
/* ------------------------------------------------------------------ */

export type JobForm = {
  part: string;
  process: string;
  quantity: string;
  cost: string;
  material: string;
  kind: string;
  source: string;
  date: string;
  machineH: string;
  setupH: string;
  laborH: string;
  inspectH: string;
};

export type JobErrors = Partial<Record<keyof JobForm, string>>;

const DECIMAL = /^(?:\d+(?:\.\d*)?|\.\d+)$/;

function hours(v: string, label: string, errors: JobErrors, key: keyof JobForm): number | null {
  const t = v.trim();
  if (!t) return null;
  if (!DECIMAL.test(t)) {
    errors[key] = `${label} must be a number of hours.`;
    return null;
  }
  return Number(t);
}

/** Validate the form the way the API will; returns the request body or the errors. */
export function parseJob(f: JobForm): { ok: true; body: GroundTruthIn } | { ok: false; errors: JobErrors } {
  const errors: JobErrors = {};
  if (!f.part.trim()) errors.part = "Pick a part.";
  if (!f.process) errors.process = "Pick a process.";
  const q = f.quantity.trim();
  if (!/^\d+$/.test(q) || Number(q) < 1) errors.quantity = "Whole number, 1 or more.";
  const c = f.cost.trim().replace(/^\$/, "");
  let cost: number | null = null;
  if (c) {
    if (!DECIMAL.test(c) || !(Number(c) > 0)) errors.cost = "Cost each in dollars, more than 0.";
    else cost = Number(c);
  }
  let date: string | null = null;
  const d = f.date.trim();
  if (d) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(d);
    const dt = m ? new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])) : null;
    if (!m || !dt || dt.getUTCFullYear() !== +m[1] || dt.getUTCMonth() !== +m[2] - 1 || dt.getUTCDate() !== +m[3]) errors.date = "Use YYYY-MM-DD.";
    else date = d;
  }
  const machineH = hours(f.machineH, "Machine hours", errors, "machineH");
  const setupH = hours(f.setupH, "Setup hours", errors, "setupH");
  const laborH = hours(f.laborH, "Labor hours", errors, "laborH");
  const inspectH = hours(f.inspectH, "Inspection hours", errors, "inspectH");
  // A cost each, machine hours each, or both: an hours-only actual is real too.
  if (!c && !(machineH && machineH > 0) && !errors.machineH) errors.cost = "Cost each, machine hours each, or both.";
  if (Object.keys(errors).length) return { ok: false, errors };
  return {
    ok: true,
    body: {
      part_id: f.part.trim(),
      process: f.process,
      quantity: Number(q),
      actual_unit_cost_usd: cost,
      material_class: f.material || "polymer",
      source: f.source.trim(),
      source_type: f.kind || "actual",
      invoice_date: date,
      actual_machine_hours: machineH,
      actual_setup_hours: setupH,
      actual_labor_hours: laborH,
      actual_inspection_hours: inspectH,
    },
  };
}

/* ------------------------------------------------------------------ */
/*  The range on one part                                               */
/* ------------------------------------------------------------------ */

export type PartRange = { point: number; low: number; high: number; pct: number | null; measured: boolean; n: number };

export function rangeOf(e: EstimateRow | null): PartRange | null {
  const c = e?.confidence;
  if (!e || !c || typeof c.low_usd !== "number" || typeof c.high_usd !== "number") return null;
  const point = typeof c.point_usd === "number" ? c.point_usd : e.unit_cost_usd;
  return { point, low: c.low_usd, high: c.high_usd, pct: typeof c.half_width_pct === "number" ? c.half_width_pct : null, measured: !!c.validated, n: c.n_samples ?? 0 };
}

/** Where a value sits on the band's 6%–94% track. */
export function bandPos(r: PartRange, v: number): number {
  if (r.high <= r.low) return 50;
  return 6 + ((v - r.low) / (r.high - r.low)) * 88;
}
