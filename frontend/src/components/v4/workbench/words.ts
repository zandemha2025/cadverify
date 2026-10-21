/**
 * Plain names the Workbench uses for engine ids (methods, cost drivers, line
 * items, assumptions, finding codes) and the number formats every tab shares.
 * Pure, only relative .ts imports, so the derivations that use it run under `node --test`.
 * An unknown id falls back to a readable version of the id, never to an
 * invented name.
 */
import { PROCESS_NAME, processLabel } from "../process-names.ts";

export const METHOD: Record<string, string> = Object.fromEntries(Object.keys(PROCESS_NAME).map((c) => [c, processLabel(c)]));

function readable(id: string): string {
  const words = id.replace(/[_-]+/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : id;
}

/** "cnc_3axis" → "3-axis milling"; unknown ids read as words. */
export function methodName(process: string | null | undefined): string {
  if (!process) return "";
  return METHOD[process] ?? readable(process);
}

/** Lower-case first letter for use inside a sentence ("Cheapest at 10 is wire EDM"). */
export function inSentence(name: string): string {
  if (!name) return name;
  // Keep acronyms (EDM, DMLS) and numbers as they are; lower only a leading capital word.
  return /^[A-Z][a-z]/.test(name) ? name[0].toLowerCase() + name.slice(1) : name;
}

export const DRIVER: Record<string, string> = {
  material_cost: "Material",
  machine_cost: "Machine",
  owned_in_house: "Owned in-house",
  cycle_time: "Cycle time",
  labor_cost: "Labor",
  setup_cost: "Setup",
  nre_cost: "Programming",
  inspection_cost: "Inspection",
  consumables_cost: "Tools and coolant",
  region_split: "Region split",
  finish_machining: "Finish machining",
  learning_curve: "Learning curve",
  min_charge_floor: "Minimum charge",
  parts_per_build: "Parts per build",
  plate_removal_cost: "Plate removal",
  sinter_cost: "Sintering",
  stress_relief_cost: "Stress relief",
  support_material: "Support material",
  support_removal_cost: "Support removal",
  tooling_cost: "Tooling",
};

export function driverName(name: string): string {
  return DRIVER[name] ?? readable(name);
}

export const LINE: Record<string, string> = {
  amortized_fixed: "Setup, spread",
  material: "Material",
  machine: "Machine",
  labor: "Labor",
  nre: "Programming",
  inspection: "Inspection",
  consumables: "Tools and coolant",
  finish_machining: "Finish machining",
  min_charge_floor: "Minimum charge",
  plate_removal: "Plate removal",
  sinter: "Sintering",
  stress_relief: "Stress relief",
  support_removal: "Support removal",
  tooling: "Tooling",
};

export function lineName(name: string): string {
  return LINE[name] ?? readable(name);
}

export const ASSUMPTION: Record<string, string> = {
  labor_rate: "Labor rate",
  region_labor: "Region, labor",
  region_material: "Region, material",
  region_tooling: "Region, tooling",
  margin: "Margin",
  overhead: "Overhead",
  utilization: "Utilization",
  stock_allowance: "Stock allowance",
  machine_labor_frac: "Operator share of machine rate",
  perishable_frac: "Tools and coolant share",
  daily_machine_hours: "Machine hours per day",
  n_cavities: "Mold cavities",
  complexity: "Tooling complexity",
  material_class: "Material class",
  machine_capital_frac: "Capital share of machine rate",
};

export function assumptionName(name: string): string {
  return ASSUMPTION[name] ?? readable(name);
}

/** Finding titles. A code we don't know shows the engine's own words, never a made-up title. */
const FINDING: Record<string, string> = {
  INSUFFICIENT_DRAFT: "Sidewalls have no draft",
  NOT_ROTATIONALLY_SYMMETRIC: "Not round",
  WALL_THICKNESS_PRECISION: "Wall check partly measured",
  WALL_UNIFORMITY_SAMPLED: "Wall evenness sampled",
  SETUP_ACCESS_UNVERIFIED: "Setup access not confirmed",
  RESIDUAL_STRESS_RISK: "Large flat area may curl",
  CUPPING_RISK: "Large flat underside",
  PRISMATIC_PROFILE_UNVERIFIED: "Straight profile not confirmed",
  SHEET_GAUGE_UNVERIFIED: "No constant sheet thickness",
  THICK_WALL: "Too thick for molding",
  THIN_WALL: "Walls too thin",
  MACHINING_ALLOWANCE: "Near-net shape",
  SINTERING_SHRINKAGE: "Shrinks when sintered",
  CONDUCTIVITY_REQUIRED: "Needs conductive material",
  PATTERN_TOOLING_REVIEW: "Pattern and core need review",
  RIB_RULES_CHECK: "Rib rules apply",
};

export function findingTitle(code: string, measured?: number | null, unit?: string | null, message?: string | null): string {
  if (code === "WALL_UNIFORMITY_SAMPLED" && measured != null && Number.isFinite(measured)) {
    return `Thickest section ${Number(measured.toPrecision(4))}${unit === "mm" || !unit ? " mm" : ""}`;
  }
  if (FINDING[code]) return FINDING[code];
  const first = message?.trim().split(/(?<=\.)\s/)[0];
  if (first && first.length <= 70) return first.replace(/\.$/, "");
  return readable(code.toLowerCase());
}

export const SEVERITY: Record<string, string> = { error: "Required fix", warning: "Advisory", info: "Note" };

export const MATERIAL: Record<string, string> = {
  polymer: "Polymer",
  aluminum: "Aluminum",
  steel: "Steel",
  stainless: "Stainless",
  titanium: "Titanium",
};

export function materialName(cls: string | null | undefined): string {
  if (!cls) return "";
  return MATERIAL[cls] ?? readable(cls);
}

export const MATERIAL_OPTIONS: [string, string][] = Object.entries(MATERIAL);

export const REGION_OPTIONS: [string, string][] = [
  ["auto", "Auto (shop, else US)"],
  ["US", "US · labor ×1.00"],
  ["EU", "EU · labor ×1.10"],
  ["MX", "MX · labor ×0.70"],
  ["CN", "CN · labor ×0.55"],
  ["IN", "IN · labor ×0.50"],
  ["SA", "SA · labor ×1.05"],
];

export const COMPLEXITY_OPTIONS: [string, string][] = [
  ["simple", "Simple"],
  ["moderate", "Moderate"],
  ["complex", "Complex"],
  ["very_complex", "Very complex"],
];

export function money(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function qtyText(n: number): string {
  return Math.round(n).toLocaleString("en-US");
}

/** One quantity → "10"; two → "50 and 5,000"; more → "1 to 10,000". */
export function qtyListText(list: readonly number[]): string {
  const qs = [...new Set(list)].filter((q) => Number.isFinite(q)).sort((a, b) => a - b);
  if (qs.length === 0) return "";
  if (qs.length === 1) return qtyText(qs[0]);
  if (qs.length === 2) return `${qtyText(qs[0])} and ${qtyText(qs[1])}`;
  return `${qtyText(qs[0])} to ${qtyText(qs[qs.length - 1])}`;
}

export function plural(n: number, one: string, many?: string): string {
  return `${n.toLocaleString("en-US")} ${n === 1 ? one : many ?? one + "s"}`;
}

/** Days, without trailing zeros: 7.7–14.3. */
export function daysRange(lo: number | null | undefined, hi: number | null | undefined): string {
  if (lo == null || hi == null || !Number.isFinite(lo) || !Number.isFinite(hi)) return "—";
  return `${+lo.toFixed(1)}–${+hi.toFixed(1)}`;
}

/** An assumption value the way the boards print it: $35/h, 25%, ×1.10, 8 h/day. */
export function assumptionValue(name: string, value: number, unit: string): string {
  if (unit === "$/hr") return `$${+value.toFixed(2)}/h`;
  if (unit === "frac") return `${Math.round(value * 1000) / 10}%`;
  if (unit === "×") return `×${Number(value).toFixed(2)}`;
  if (unit === "hr/day") return `${+value.toFixed(2)} h/day`;
  if (unit === "cav") return String(+value.toFixed(2));
  if (name === "complexity" || name === "material_class") return readable(unit);
  return `${+value.toFixed(4)} ${unit}`.trim();
}

/** "Today 05:00" / "Oct 17 05:00", in the viewer's local time. */
export function whenText(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "";
  const d = new Date(t);
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  const same = d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
  if (same) return `Today ${hm}`;
  return `${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })} ${hm}`;
}

/** "Shop accounting export 2026-Q2 (loaded rates + …)" → "Shop accounting export 2026-Q2". */
export function shortSource(source: string | null | undefined): string {
  if (!source) return "";
  return source.replace(/\s*\([^)]*\)\s*$/, "").trim();
}

/** "sour gas (H2S)" → "Sour gas". */
export function environmentLabel(env: Record<string, unknown> | null | undefined): string | null {
  if (!env) return null;
  const medium = typeof env.medium === "string" ? env.medium.replace(/\s*\([^)]*\)\s*$/, "").trim() : "";
  if (medium) return medium[0].toUpperCase() + medium.slice(1);
  if (env.sour_service === true) return "Sour service";
  if (env.corrosive === true) return "Corrosive service";
  return null;
}
