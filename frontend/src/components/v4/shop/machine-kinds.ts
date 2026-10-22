/**
 * What a machine is, beyond its process (me-02): a sheet-metal machine is a
 * press brake (fitted on bend length, press force and the thickest sheet it
 * bends per material) or a cutter (laser, punch, plasma, waterjet: its bed and
 * the thickest sheet it cuts). The engine reads the same keys
 * (makeability.SHEET_KINDS, capabilities.sheet_kind, max_bend_length_mm,
 * tonnage_t, bed_x/bed_y, material_thickness_map).
 *
 * Units follow the person: lengths in mm or in, press force in metric t or US
 * tons, weights in kg or lb. The API keeps mm, t and kg. Pure, for node --test.
 */
import { MM_PER_IN, type LengthUnit } from "../units/units.ts";

export const SHEET = "sheet_metal";
export const PRESS_BRAKE = "press_brake";
export const SHEET_KINDS: readonly (readonly [string, string])[] = [
  [PRESS_BRAKE, "Press brake"],
  ["laser", "Laser cutter"],
  ["punch", "Punch press"],
  ["plasma", "Plasma cutter"],
  ["waterjet", "Waterjet"],
];
const SHEET_KIND_NAME: Record<string, string> = Object.fromEntries(SHEET_KINDS);

/** The declared kind of a sheet-metal machine, or null (older machines: work area only). */
export function sheetKindOf(cap: Record<string, unknown> | null | undefined): string | null {
  const k = cap?.sheet_kind;
  return typeof k === "string" && k in SHEET_KIND_NAME ? k : null;
}

/** "Press brake", "Laser cutter"; a sheet machine that never said reads "Sheet-metal machine". Null off sheet metal. */
export function sheetKindName(process: string, cap: Record<string, unknown> | null | undefined): string | null {
  if (process !== SHEET) return null;
  const k = sheetKindOf(cap);
  return k ? SHEET_KIND_NAME[k] : "Sheet-metal machine";
}

/* ── press force ──────────────────────────────────────────────────────── */

/** 1 US (short) ton-force = 2,000 lbf = 907.18474 kgf = 0.90718474 metric t. */
export const T_PER_US_TON = 0.90718474;

export function forceUnit(unit: LengthUnit): string {
  return unit === "in" ? "US tons" : "t";
}

function trimmed(v: number, dp: number): string {
  return String(Number(v.toFixed(dp)));
}

/** Metric tonnes as the person reads press force: "100" t, or "110.23" US tons. */
export function forceIn(t: number | null | undefined, unit: LengthUnit): string {
  if (t == null || !Number.isFinite(t)) return "";
  return unit === "in" ? trimmed(t / T_PER_US_TON, 2) : trimmed(t, 2);
}

/* ── weight ───────────────────────────────────────────────────────────── */

export const KG_PER_LB = 0.45359237;

export function weightUnit(unit: LengthUnit): "kg" | "lb" {
  return unit === "in" ? "lb" : "kg";
}

export function weightIn(kg: number | null | undefined, unit: LengthUnit): string {
  if (kg == null || !Number.isFinite(kg)) return "";
  return unit === "in" ? trimmed(kg / KG_PER_LB, 1) : trimmed(kg, 3);
}

/* ── one number field that keeps what wasn't touched ─────────────────── */

/**
 * A number shown in the person's unit, back in the API's unit. Untouched, it
 * saves exactly what it came from (no round trip through a rounded display);
 * blank is blank; text that isn't a number passes through so the form's own
 * check names it.
 */
export function backToBase(shown: string, initialShown: string, initialBase: string, factor: number): string {
  if (shown === initialShown) return initialBase;
  const t = shown.trim();
  if (!t) return "";
  const n = Number(t);
  return Number.isFinite(n) && /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(t) ? String(Math.round(n * factor * 1e6) / 1e6) : shown;
}

/* ── thickest sheet by material ───────────────────────────────────────── */

/** The material classes a sheet shop states a thickness limit for, in the map's own keys. */
export const SHEET_CLASSES: readonly (readonly [string, string])[] = [
  ["steel", "Steel"],
  ["stainless", "Stainless"],
  ["aluminum", "Aluminum"],
];

export type ThickText = Record<string, string>;

/** The form's rows from a stored map (mm), in the person's unit. Other keys stay in the map untouched. */
export function thickRowsFrom(map: Record<string, unknown> | null | undefined, unit: LengthUnit): ThickText {
  const out: ThickText = {};
  for (const [k] of SHEET_CLASSES) {
    const v = map?.[k];
    out[k] = typeof v === "number" && Number.isFinite(v) ? (unit === "in" ? trimmed(v / MM_PER_IN, 4) : trimmed(v, 3)) : "";
  }
  return out;
}

const DECIMAL = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/;

/** A thickness typed as a decimal or a fraction of an inch ("3/16", "0.1875"). */
function parseThick(text: string, unit: LengthUnit): number | null {
  const t = text.trim().replace(/\s*(?:in|"|mm)$/i, "");
  const frac = /^(\d+)\s*\/\s*(\d+)$/.exec(t);
  const v = frac ? Number(frac[1]) / Number(frac[2]) : DECIMAL.test(t) ? Number(t) : NaN;
  if (!Number.isFinite(v) || v <= 0) return null;
  return unit === "in" ? v * MM_PER_IN : v;
}

/**
 * The map to save: the stored one with the three class rows replaced (mm). An
 * untouched row keeps its exact stored value; a blank row removes the key.
 * Errors name the row ("Stainless: a thickness like 0.1875 or 3/16").
 */
export function thickMapToSave(
  base: Record<string, unknown> | null | undefined,
  rows: ThickText,
  initialRows: ThickText,
  unit: LengthUnit,
): { map: Record<string, unknown> | null; errors: Record<string, string> } {
  const out: Record<string, unknown> = { ...(base ?? {}) };
  const errors: Record<string, string> = {};
  for (const [k, label] of SHEET_CLASSES) {
    const shown = (rows[k] ?? "").trim();
    if (shown === (initialRows[k] ?? "").trim()) continue;
    delete out[k];
    if (!shown) continue;
    const mm = parseThick(shown, unit);
    if (mm == null) errors[k] = `${label}: a thickness like ${unit === "in" ? "0.1875 or 3/16" : "4.8"}.`;
    else out[k] = Math.round(mm * 1e4) / 1e4;
  }
  return { map: Object.keys(out).length ? out : null, errors };
}

/* ── the capability keys each layout owns ─────────────────────────────── */

/**
 * The capability keys a sheet-metal layout replaces when saved. Choosing a kind
 * drops an older work-area box (x/y/z), which a brake or cutter doesn't have.
 */
export function sheetKeys(kind: string | null): string[] {
  if (kind === PRESS_BRAKE) return ["sheet_kind", "max_bend_length_mm", "tonnage_t", "bed_x", "bed_y", "x", "y", "z"];
  if (kind) return ["sheet_kind", "bed_x", "bed_y", "max_bend_length_mm", "tonnage_t", "x", "y", "z"];
  return [];
}

/** The capability bag with the sheet layout's keys replaced by what the form says. */
export function mergeSheetCapabilities(base: Record<string, unknown>, kind: string | null, values: { bend?: number | null; tonnage?: number | null; bedX?: number | null; bedY?: number | null }): Record<string, unknown> {
  if (!kind) return base;
  const out: Record<string, unknown> = { ...base };
  for (const k of sheetKeys(kind)) delete out[k];
  out.sheet_kind = kind;
  if (kind === PRESS_BRAKE) {
    if (values.bend != null) out.max_bend_length_mm = values.bend;
    if (values.tonnage != null) out.tonnage_t = values.tonnage;
  } else {
    if (values.bedX != null) out.bed_x = values.bedX;
    if (values.bedY != null) out.bed_y = values.bedY;
  }
  return out;
}

/** A positive decimal typed in a field, or why not ("Bend length must be a number above 0."). Blank is null. */
export function parsePositive(raw: string, label: string): { value: number | null; error?: string } {
  const t = raw.trim();
  if (!t) return { value: null };
  if (!DECIMAL.test(t) || !(Number(t) > 0) || !Number.isFinite(Number(t))) return { value: null, error: `${label} must be a number above 0.` };
  return { value: Number(t) };
}
