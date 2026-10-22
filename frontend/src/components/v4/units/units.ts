/**
 * Lengths in the person's unit (mm or in). The engine always works in
 * millimetres; this is display and input only. Conversions are exact
 * (1 in = 25.4 mm, 1 in² = 6.4516 cm², 1 in³ = 16.387064 cm³) and every figure
 * carries its unit.
 *
 * Pure: no React, no fetch (runs under node --test).
 */

export type LengthUnit = "mm" | "in";

export const MM_PER_IN = 25.4;
export const CM2_PER_IN2 = 6.4516;
export const CM3_PER_IN3 = 16.387064;

/** Inches to the thousandth below 10 in, the hundredth to 100 in, the tenth above (drawing practice). */
function inchDecimals(mm: number): number {
  const v = Math.abs(mm) / MM_PER_IN;
  return v < 10 ? 3 : v < 100 ? 2 : 1;
}

function fixed(v: number, dp: number): string {
  return v.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
}

function trimmed(v: number, dp: number): string {
  return v.toLocaleString("en-US", { maximumFractionDigits: dp });
}

/** A length in mm shown in the unit: "25.4 mm" / "1.000 in". */
export function len(mm: number | null | undefined, unit: LengthUnit, mmDp = 1): string {
  if (mm == null || !Number.isFinite(mm)) return "—";
  if (unit === "in") return `${fixed(mm / MM_PER_IN, inchDecimals(mm))} in`;
  return `${trimmed(mm, mmDp)} mm`;
}

/** A length's number only, in the unit (for inputs). */
export function lenValue(mm: number | null | undefined, unit: LengthUnit, mmDp = 1): string {
  if (mm == null || !Number.isFinite(mm)) return "";
  if (unit === "in") return String(Number((mm / MM_PER_IN).toFixed(inchDecimals(mm))));
  return String(Number(mm.toFixed(mmDp)));
}

/** "100 × 50 × 20 mm" / "3.94 × 1.97 × 0.79 in". */
export function dims(mm: readonly number[] | null | undefined, unit: LengthUnit, mmDp = 1): string | null {
  if (!mm || !mm.length || mm.some((n) => !Number.isFinite(n))) return null;
  if (unit === "in") return `${mm.map((n) => fixed(n / MM_PER_IN, inchDecimals(n))).join(" × ")} in`;
  return `${mm.map((n) => trimmed(n, mmDp)).join(" × ")} mm`;
}

/** An area in cm² shown in the unit. */
export function area(cm2: number | null | undefined, unit: LengthUnit): string {
  if (cm2 == null || !Number.isFinite(cm2)) return "—";
  return unit === "in" ? `${trimmed(cm2 / CM2_PER_IN2, 2)} in²` : `${trimmed(cm2, 2)} cm²`;
}

/** A volume in cm³ shown in the unit. */
export function volume(cm3: number | null | undefined, unit: LengthUnit): string {
  if (cm3 == null || !Number.isFinite(cm3)) return "—";
  return unit === "in" ? `${trimmed(cm3 / CM3_PER_IN3, 3)} in³` : `${trimmed(cm3, 2)} cm³`;
}

/** A length typed in either unit ("25.4", "25.4 mm", "1 in", '1"', "1in") → mm, or null. */
export function parseLen(text: string, unit: LengthUnit): number | null {
  const m = /^\s*(-?[0-9]*[.,]?[0-9]+)\s*(mm|millimet(?:er|re)s?|in|inch(?:es)?|"|″)?\s*$/i.exec(text ?? "");
  if (!m) return null;
  const v = Number(m[1].replace(",", "."));
  if (!Number.isFinite(v)) return null;
  const w = (m[2] ?? "").toLowerCase();
  const inches = w ? !w.startsWith("m") : unit === "in";
  return inches ? v * MM_PER_IN : v;
}

// A number with "mm" (or mm², mm³, cm², cm³) after it, in engine text. Ranges and
// boxes ("10 × 20 × 30 mm", "1–3 mm") convert every number before the unit.
const RUN = /((?:[-−±]?\d[\d,]*(?:\.\d+)?)(?:\s*(?:×|x|–|-|to)\s*(?:[-−±]?\d[\d,]*(?:\.\d+)?))*)\s?(mm³|mm²|mm\b|cm³|cm²)/g;
const NUM = /[-−±]?\d[\d,]*(?:\.\d+)?/g;

/**
 * Engine text with every mm figure shown in inches ("needs 1306 mm, has 1005 mm"
 * → "needs 51.42 in, has 39.57 in"). A no-op in mm. Numbers that aren't lengths
 * (prices, counts, µm roughness) are left as they are.
 */
export function inText(text: string | null | undefined, unit: LengthUnit): string {
  if (!text || unit === "mm") return text ?? "";
  return text.replace(RUN, (_all, run: string, u: string) => {
    const factor = u === "mm" ? MM_PER_IN : u === "mm²" ? MM_PER_IN * MM_PER_IN : u === "mm³" ? MM_PER_IN ** 3 : u === "cm²" ? CM2_PER_IN2 : CM3_PER_IN3;
    const out = run.replace(NUM, (n) => {
      const sign = /^[−±-]/.test(n) ? n[0] : "";
      const raw = n.replace(/^[−±-]/, "").replace(/,/g, "");
      const v = Number(raw);
      if (!Number.isFinite(v)) return n;
      const dp = u === "mm" ? inchDecimals(v) : 3;
      return `${sign}${fixed(v / factor, dp)}`;
    });
    const unitOut = u === "mm" ? "in" : u === "mm²" || u === "cm²" ? "in²" : "in³";
    return `${out} ${unitOut}`;
  });
}
