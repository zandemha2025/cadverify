/**
 * Strict parsing for the machine-inventory form.
 *
 * Browser values arrive as strings.  `parseFloat` is intentionally not used:
 * it accepts prefixes (`"12abc" -> 12`) and would turn a malformed USER
 * declaration into a plausible-looking persisted capability.  Every non-blank
 * value must be a complete finite decimal before it can cross the API boundary.
 */

export type MachineNumberField =
  | "count"
  | "rate"
  | "maxKg"
  | "x"
  | "y"
  | "z"
  | "swing"
  | "between";

export type MachineNumberErrors = Partial<Record<MachineNumberField, string>>;

export interface MachineNumberInput {
  count: string;
  rate: string;
  maxKg: string;
  x: string;
  y: string;
  z: string;
  swing: string;
  between: string;
  isTurning: boolean;
}

export interface ParsedMachineNumbers {
  count: number;
  rate: number | null;
  maxKg: number | null;
  capabilities: Record<string, number>;
}

export type MachineNumberParseResult =
  | { ok: true; value: ParsedMachineNumbers; errors: MachineNumberErrors }
  | { ok: false; value: null; errors: MachineNumberErrors };

// Complete decimal grammar, including optional scientific notation. Hex,
// Infinity, NaN, and strings with trailing characters are deliberately refused.
const DECIMAL = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;

function parseField(
  raw: string,
  label: string,
  options: { required?: boolean; integer?: boolean; min: number; exclusiveMin?: boolean }
): { value: number | null; error?: string } {
  const text = raw.trim();
  if (!text) {
    return options.required
      ? { value: null, error: `${label} is required.` }
      : { value: null };
  }
  if (!DECIMAL.test(text)) {
    return { value: null, error: `${label} must be a complete number.` };
  }
  const value = Number(text);
  if (!Number.isFinite(value)) {
    return { value: null, error: `${label} must be finite.` };
  }
  if (options.integer && !Number.isInteger(value)) {
    return { value: null, error: `${label} must be a whole number.` };
  }
  const outside = options.exclusiveMin ? value <= options.min : value < options.min;
  if (outside) {
    const comparator = options.exclusiveMin ? "greater than" : "at least";
    return { value: null, error: `${label} must be ${comparator} ${options.min}.` };
  }
  return { value };
}

export function parseMachineNumbers(input: MachineNumberInput): MachineNumberParseResult {
  const errors: MachineNumberErrors = {};
  const parsed = {
    count: parseField(input.count, "Count", { required: true, integer: true, min: 0, exclusiveMin: true }),
    rate: parseField(input.rate, "Hourly rate", { min: 0 }),
    maxKg: parseField(input.maxKg, "Max workpiece", { min: 0, exclusiveMin: true }),
    x: parseField(input.x, "Envelope X", { min: 0, exclusiveMin: true }),
    y: parseField(input.y, "Envelope Y", { min: 0, exclusiveMin: true }),
    z: parseField(input.z, "Envelope Z", { min: 0, exclusiveMin: true }),
    swing: parseField(input.swing, "Swing diameter", { min: 0, exclusiveMin: true }),
    between: parseField(input.between, "Between centers", { min: 0, exclusiveMin: true }),
  };

  for (const key of Object.keys(parsed) as MachineNumberField[]) {
    const error = parsed[key].error;
    if (error) errors[key] = error;
  }
  if (Object.keys(errors).length > 0) {
    return { ok: false, value: null, errors };
  }

  const capabilities: Record<string, number> = {};
  if (input.isTurning) {
    if (parsed.swing.value != null) capabilities.swing_dia = parsed.swing.value;
    if (parsed.between.value != null) capabilities.between_centers = parsed.between.value;
  } else {
    if (parsed.x.value != null) capabilities.x = parsed.x.value;
    if (parsed.y.value != null) capabilities.y = parsed.y.value;
    if (parsed.z.value != null) capabilities.z = parsed.z.value;
  }

  return {
    ok: true,
    value: {
      count: parsed.count.value as number,
      rate: parsed.rate.value,
      maxKg: parsed.maxKg.value,
      capabilities,
    },
    errors,
  };
}

/** Capability keys each envelope layout shows. The lathe layout uses the same
 *  `swing_dia` + `between_centers` keys the API accepts and the engine reads. */
export const BOX_ENVELOPE_KEYS = ["x", "y", "z"] as const;
export const TURNING_ENVELOPE_KEYS = ["swing_dia", "between_centers"] as const;

export type MachineEnvelopeText = Pick<MachineNumberInput, "x" | "y" | "z" | "swing" | "between">;

function capText(cap: Record<string, unknown> | null | undefined, key: string): string {
  const v = cap?.[key];
  return typeof v === "number" && Number.isFinite(v) ? String(v) : "";
}

/** Envelope field text from a capability bag (a machine being edited, or the
 *  catalog template prefilling an add). Undeclared keys stay blank. */
export function envelopeFieldsFrom(cap: Record<string, unknown> | null | undefined): MachineEnvelopeText {
  return {
    x: capText(cap, "x"),
    y: capText(cap, "y"),
    z: capText(cap, "z"),
    swing: capText(cap, "swing_dia"),
    between: capText(cap, "between_centers"),
  };
}

/**
 * The capability bag to submit. Starts from `base` (the machine being edited,
 * or the catalog template that prefilled an add) and replaces ONLY the envelope
 * keys the visible layout shows; a blank visible field removes its key. Every
 * key the form does not show (axes, motion_mode, min_layer_um, min_feature_mm,
 * the other layout's envelope, ...) is carried through unchanged, so saving an
 * edit to just the rate never erases a declared capability.
 */
export function mergeMachineCapabilities(
  base: Record<string, unknown> | null | undefined,
  edited: Record<string, number>,
  isTurning: boolean
): Record<string, unknown> {
  const out: Record<string, unknown> = { ...(base ?? {}) };
  for (const key of isTurning ? TURNING_ENVELOPE_KEYS : BOX_ENVELOPE_KEYS) {
    delete out[key];
    if (edited[key] != null) out[key] = edited[key];
  }
  return out;
}

// ── Capital fraction (typed as a percent) ───────────────────────────────────

/**
 * Capital fraction is stored as a fraction in [0, 1] but typed as a percent
 * ("35" or "35%" → 0.35), the way the form's placeholder reads. Blank → null
 * (the rate card's default applies).
 */
export function parseCapitalPercent(raw: string): { value: number | null; error?: string } {
  const text = raw.trim().replace(/\s*%$/, "");
  if (!text) return { value: null };
  if (!DECIMAL.test(text)) return { value: null, error: "Capital fraction must be a complete number." };
  const pct = Number(text);
  if (!Number.isFinite(pct)) return { value: null, error: "Capital fraction must be finite." };
  if (pct < 0 || pct > 100) return { value: null, error: "Capital fraction must be between 0 and 100%." };
  return { value: Math.round(pct * 1000) / 100000 };
}

/** The percent text for a stored fraction (0.35 → "35"). */
export function capitalPercentText(frac: number | null | undefined): string {
  return typeof frac === "number" && Number.isFinite(frac) ? String(Math.round(frac * 100000) / 1000) : "";
}

// ── Printer details ─────────────────────────────────────────────────────────
//
// Capability keys the API accepts per additive method (machine_inventory_service
// _PRINTER_KEY_PROCESSES): an extrusion nozzle and an enclosure only on filament
// printers, a layer-height range on layer-by-layer printers, and stocked
// filament or resin on filament and resin printers. Layer heights are stored in
// µm under `min_layer_um` (the existing key) and `max_layer_um`; the form takes mm.

export const NOZZLE_PROCESSES: readonly string[] = ["fdm"];
export const ENCLOSURE_PROCESSES: readonly string[] = ["fdm"];
export const LAYER_PROCESSES: readonly string[] = ["fdm", "sla", "dlp", "sls", "mjf", "dmls", "slm", "ebm", "binder_jetting"];
export const STOCK_PROCESSES: readonly string[] = ["fdm", "sla", "dlp"];

/** Keys only some printers may carry. `min_layer_um` is older and accepted on any machine. */
export const PRINTER_ONLY_KEYS = ["nozzle_dia_mm", "max_layer_um", "enclosure", "max_chamber_c", "stocked_materials"] as const;

export const ENCLOSURES = ["none", "enclosed", "heated"] as const;
export type Enclosure = (typeof ENCLOSURES)[number];

export interface PrinterFieldsShown {
  nozzle: boolean;
  layers: boolean;
  enclosure: boolean;
  stocked: boolean;
  /** Any printer field at all. */
  any: boolean;
}

export function printerFieldsFor(process: string): PrinterFieldsShown {
  const f = {
    nozzle: NOZZLE_PROCESSES.includes(process),
    layers: LAYER_PROCESSES.includes(process),
    enclosure: ENCLOSURE_PROCESSES.includes(process),
    stocked: STOCK_PROCESSES.includes(process),
  };
  return { ...f, any: f.nozzle || f.layers || f.enclosure || f.stocked };
}

export interface PrinterText {
  nozzle: string;
  layerMin: string;
  layerMax: string;
  enclosure: "" | Enclosure;
  chamber: string;
  stocked: string;
}

export type PrinterField = keyof PrinterText;
export type PrinterErrors = Partial<Record<PrinterField, string>>;

const umToMmText = (v: unknown): string =>
  typeof v === "number" && Number.isFinite(v) ? String(Math.round(v * 1000) / 1e6) : "";

/** Form text from a capability bag (a machine being edited or a catalog template). */
export function printerFieldsFrom(cap: Record<string, unknown> | null | undefined): PrinterText {
  const enc = cap?.enclosure;
  const stocked = cap?.stocked_materials;
  return {
    nozzle: capText(cap, "nozzle_dia_mm"),
    layerMin: umToMmText(cap?.min_layer_um),
    layerMax: umToMmText(cap?.max_layer_um),
    enclosure: typeof enc === "string" && (ENCLOSURES as readonly string[]).includes(enc) ? (enc as Enclosure) : "",
    chamber: capText(cap, "max_chamber_c"),
    stocked: Array.isArray(stocked) ? stocked.filter((s) => typeof s === "string").join(", ") : "",
  };
}

const mmToUm = (mm: number): number => Math.round(mm * 1e6) / 1000;

export type PrinterParseResult =
  | { ok: true; value: Record<string, unknown>; errors: PrinterErrors }
  | { ok: false; value: null; errors: PrinterErrors };

/**
 * Parse the printer fields this method shows. Only shown fields are checked;
 * a blank field means "not declared". Returns the capability keys to set.
 */
export function parsePrinterDetails(input: PrinterText, process: string): PrinterParseResult {
  const shown = printerFieldsFor(process);
  const errors: PrinterErrors = {};
  const value: Record<string, unknown> = {};
  if (shown.nozzle) {
    const r = parseField(input.nozzle, "Nozzle diameter", { min: 0, exclusiveMin: true });
    if (r.error) errors.nozzle = r.error;
    else if (r.value != null) value.nozzle_dia_mm = r.value;
  }
  if (shown.layers) {
    const lo = parseField(input.layerMin, "Finest layer", { min: 0, exclusiveMin: true });
    const hi = parseField(input.layerMax, "Thickest layer", { min: 0, exclusiveMin: true });
    if (lo.error) errors.layerMin = lo.error;
    else if (lo.value != null) value.min_layer_um = mmToUm(lo.value);
    if (hi.error) errors.layerMax = hi.error;
    else if (hi.value != null) value.max_layer_um = mmToUm(hi.value);
    if (!lo.error && !hi.error && lo.value != null && hi.value != null && hi.value < lo.value) {
      errors.layerMax = "Thickest layer must be at least the finest layer.";
    }
  }
  if (shown.enclosure && input.enclosure) {
    value.enclosure = input.enclosure;
    if (input.enclosure === "heated") {
      const c = parseField(input.chamber, "Max chamber temperature", { min: 0, exclusiveMin: true });
      if (c.error) errors.chamber = c.error;
      else if (c.value != null) value.max_chamber_c = c.value;
    }
  }
  if (shown.stocked) {
    const list = Array.from(new Set(input.stocked.split(",").map((s) => s.trim()).filter(Boolean)));
    if (list.length) value.stocked_materials = list;
  }
  if (Object.keys(errors).length) return { ok: false, value: null, errors };
  return { ok: true, value, errors };
}

/**
 * The capability bag with this method's printer fields applied. Every printer
 * key the method shows is replaced (blank removes it); printer-only keys the
 * method can't carry are dropped, since the API refuses them there (they only
 * linger after the method was changed). `min_layer_um` on a non-layer machine
 * is carried through untouched.
 */
export function mergePrinterCapabilities(
  base: Record<string, unknown> | null | undefined,
  parsed: Record<string, unknown>,
  process: string
): Record<string, unknown> {
  const out: Record<string, unknown> = { ...(base ?? {}) };
  const shown = printerFieldsFor(process);
  const owned: string[] = [];
  if (shown.nozzle) owned.push("nozzle_dia_mm");
  if (shown.layers) owned.push("min_layer_um", "max_layer_um");
  if (shown.enclosure) owned.push("enclosure", "max_chamber_c");
  if (shown.stocked) owned.push("stocked_materials");
  for (const key of PRINTER_ONLY_KEYS) if (!owned.includes(key)) delete out[key];
  for (const key of owned) {
    delete out[key];
    if (parsed[key] !== undefined) out[key] = parsed[key];
  }
  return out;
}
