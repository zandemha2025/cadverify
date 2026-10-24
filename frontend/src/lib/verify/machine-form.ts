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
