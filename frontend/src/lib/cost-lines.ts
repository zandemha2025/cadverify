/**
 * Cost lines that add up to the unit cost to the cent (ce-01): the screen's twin of
 * backend/src/costing/footing.py, which the PDF line table and the CSV use.
 *
 * The engine keeps each line to four decimals and rounds the unit cost once, from
 * the unrounded sum, so lines rounded one by one can miss it by a cent or two
 * ($0.70 + 17.50 + 15.69 + 0.52 + 1.23 + 0.78 + 0.26 = $36.68 against $36.69).
 * Each line is rounded on its own, so it still matches its own formula, and a
 * visible Rounding line carries the difference: the column adds up.
 */

export const ROUNDING_KEY = "rounding";

/** Dollars as whole cents, half-up on the decimal form (as toLocaleString shows them: 1.225 → 1.23). */
export function cents(v: number): number {
  if (!Number.isFinite(v)) return 0;
  const x = Number((Math.abs(v) * 100).toPrecision(12));
  return Math.sign(v) * Math.round(x);
}

/** The engine driver that explains a line (its formula, tag and band). */
const LINE_DRIVER: Record<string, string> = {
  amortized_fixed: "setup_cost",
  tooling: "tooling_per_part",
  tolerance: "tolerance_class",
  min_charge_floor: "min_charge_floor",
  finish_machining: "finish_machining",
};

export function lineDriver(key: string): string {
  return LINE_DRIVER[key] ?? `${key}_cost`;
}

/** A record priced before tooling became its own line (ce-04): its "amortized_fixed" holds the
 *  setup and the tool's share together, and must be named so. */
export function foldedTooling(e: { line_items?: Record<string, number> | null; drivers?: readonly { name: string }[] | null }): boolean {
  const items = e.line_items ?? {};
  return "amortized_fixed" in items && !("tooling" in items) && (e.drivers ?? []).some((d) => d.name === "tooling_cost");
}

export interface FootedLine {
  key: string;
  /** The line's own value as the engine keeps it (four decimals). */
  usd: number;
  /** The line rounded to the cent, as printed. */
  cents: number;
}

export interface Footing {
  lines: FootedLine[];
  /** Cents that make the printed lines add up to the printed unit cost (0 when they already do). */
  roundingCents: number;
  /** False when the gap is more than rounding can make (half a cent a line, and the unit's own):
   *  the lines then don't account for the price, and nothing may say they add up. */
  isRounding: boolean;
  unitCents: number;
  /** The lines added unrounded ("$36.6878"), for the words under the Rounding line. */
  exactSum: number;
}

/** The lines in cents and the rounding that makes them add up to `unit`. A line of exactly $0 is left out. */
export function footLines(items: Record<string, number> | null | undefined, unit: number): Footing {
  const lines: FootedLine[] = [];
  let exactSum = 0;
  for (const [key, usd] of Object.entries(items ?? {})) {
    if (typeof usd !== "number" || !Number.isFinite(usd) || usd === 0) continue;
    lines.push({ key, usd, cents: cents(usd) });
    exactSum += usd;
  }
  const unitCents = cents(unit);
  const roundingCents = unitCents - lines.reduce((s, l) => s + l.cents, 0);
  return { lines, roundingCents, isRounding: Math.abs(roundingCents) <= Math.ceil((lines.length + 1) / 2), unitCents, exactSum };
}

/** "Each line is rounded to the cent; unrounded they add to $36.6878, which is $36.69." */
export function roundingWords(f: Footing): string {
  const usd = (v: number, d: number) => `$${v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })}`;
  if (!f.isRounding) return `The lines add to ${usd(f.exactSum, 4)}, not ${usd(f.unitCents / 100, 2)}: they don’t account for the price.`;
  return `Each line is rounded to the cent; unrounded they add to ${usd(f.exactSum, 4)}, which is ${usd(f.unitCents / 100, 2)}.`;
}
