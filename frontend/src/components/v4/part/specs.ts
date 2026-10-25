/**
 * Part specs on the Conditions view: surface finish (named finishes and Ra),
 * heat treatment, inspection, and the certifications whoever makes the part must
 * hold. The vocabulary mirrors the engine (backend `src/costing/part_specs.py`);
 * the stored shape is `part_contexts.part_specs`.
 *
 * Pure: no React, no fetch (runs under node --test).
 */

export const UM_PER_UIN = 0.0254; // exact

export type SpecKey = "finishes" | "heat_treatments" | "inspection" | "certifications" | "nadcap_processes";

export interface PartSpecs {
  finishes?: string[];
  ra_um?: number;
  ra_unit?: "um" | "uin";
  heat_treatments?: string[];
  inspection?: string[];
  certifications?: string[];
  nadcap_processes?: string[];
  /** The general tolerance for undimensioned features: an ISO 2768-1 class, or ± in mm or inches. Sent to the supplier; not priced. */
  general_tolerance?: GeneralTolerance;
}

export type GeneralTolerance = { iso2768: "f" | "m" | "c" | "v" } | { plus_minus: number; unit: "mm" | "in" };

export const ISO_2768: [string, string][] = [
  ["f", "fine"],
  ["m", "medium"],
  ["c", "coarse"],
  ["v", "very coarse"],
];

/** "ISO 2768-m (medium)", "±0.1 mm", "±0.005 in (0.127 mm)": the engine's own words (part_specs.tolerance_text). */
export function toleranceText(t: GeneralTolerance | null | undefined): string | null {
  if (!t) return null;
  if ("iso2768" in t) return `ISO 2768-${t.iso2768} (${ISO_2768.find(([k]) => k === t.iso2768)?.[1] ?? ""})`;
  if (!(t.plus_minus > 0)) return null;
  return t.unit === "in" ? `±${trim(t.plus_minus)} in (${Number((t.plus_minus * 25.4).toPrecision(3))} mm)` : `±${trim(t.plus_minus)} mm`;
}

function tolerance(raw: unknown): GeneralTolerance | null {
  if (!raw || typeof raw !== "object") return null;
  const t = raw as Record<string, unknown>;
  if (typeof t.iso2768 === "string" && ISO_2768.some(([k]) => k === t.iso2768)) return { iso2768: t.iso2768 as "f" | "m" | "c" | "v" };
  if (typeof t.plus_minus === "number" && Number.isFinite(t.plus_minus) && t.plus_minus > 0) return { plus_minus: t.plus_minus, unit: t.unit === "in" ? "in" : "mm" };
  return null;
}

export const FINISHES: [string, string][] = [
  ["as_machined", "As machined"],
  ["bead_blast", "Bead blast"],
  ["anodize_ii", "Anodize, Type II"],
  ["anodize_iii", "Hard anodize, Type III"],
  ["passivate", "Passivation"],
  ["electropolish", "Electropolish"],
  ["powder_coat", "Powder coat"],
  ["plating", "Plating"],
];
export const HEAT_TREATMENTS: [string, string][] = [
  ["stress_relief", "Stress relief"],
  ["solution_age", "Solution treat and age"],
  ["quench_temper", "Quench and temper"],
  ["case_harden", "Case hardening"],
  ["hip", "HIP"],
];
export const INSPECTIONS: [string, string][] = [
  ["fai_as9102", "First article, AS9102"],
  ["cmm_report", "CMM report"],
  ["full_100", "100% inspection"],
];
export const CERTIFICATIONS: [string, string][] = [
  ["as9100", "AS9100"],
  ["iso9001", "ISO 9001"],
  ["nadcap", "NADCAP"],
  ["itar", "ITAR registration"],
];
export const NADCAP_PROCESSES: [string, string][] = [
  ["chemical_processing", "Chemical processing"],
  ["heat_treating", "Heat treating"],
  ["nondestructive_testing", "Nondestructive testing"],
  ["coatings", "Coatings"],
  ["welding", "Welding"],
  ["measurement_inspection", "Measurement and inspection"],
];
const OP_NADCAP: Record<string, string> = {
  anodize_ii: "chemical_processing",
  anodize_iii: "chemical_processing",
  passivate: "chemical_processing",
  electropolish: "chemical_processing",
  plating: "chemical_processing",
  stress_relief: "heat_treating",
  solution_age: "heat_treating",
  quench_temper: "heat_treating",
  case_harden: "heat_treating",
  hip: "heat_treating",
};

const LABEL: Record<string, string> = Object.fromEntries([...FINISHES, ...HEAT_TREATMENTS, ...INSPECTIONS, ...CERTIFICATIONS, ...NADCAP_PROCESSES]);
export function specLabel(key: string): string {
  return LABEL[key] ?? key.replace(/_/g, " ");
}

function list(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
}

/** A stored or sent value, in the canonical shape (or null when nothing is declared). */
export function normalizeSpecs(raw: unknown): PartSpecs | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const s = raw as Record<string, unknown>;
  const out: PartSpecs = {};
  for (const k of ["finishes", "heat_treatments", "inspection", "certifications", "nadcap_processes"] as SpecKey[]) {
    const vals = [...new Set(list(s[k]))].filter((v) => v !== "standard");
    if (vals.length) out[k] = vals;
  }
  if (typeof s.ra_um === "number" && Number.isFinite(s.ra_um)) {
    out.ra_um = s.ra_um;
    out.ra_unit = s.ra_unit === "uin" ? "uin" : "um";
  }
  const tol = tolerance(s.general_tolerance);
  if (tol) out.general_tolerance = tol;
  return Object.keys(out).length ? out : null;
}

export function hasSpecs(s: unknown): boolean {
  return !!normalizeSpecs(s);
}

/** The specs the price uses: all but the general tolerance (the engine leaves it out). */
export function pricedSpecs(s: unknown): PartSpecs | null {
  const n = normalizeSpecs(s);
  if (!n) return null;
  const { general_tolerance: _t, ...rest } = n;
  return Object.keys(rest).length ? rest : null;
}

/** Two declarations are the same when their canonical shapes match (order kept). */
export function sameSpecs(a: unknown, b: unknown): boolean {
  const x = normalizeSpecs(a);
  const y = normalizeSpecs(b);
  if (!x || !y) return !x && !y;
  if (toleranceText(x.general_tolerance) !== toleranceText(y.general_tolerance)) return false;
  const keys = ["finishes", "heat_treatments", "inspection", "certifications", "nadcap_processes"] as SpecKey[];
  if (keys.some((k) => (x[k] ?? []).join("|") !== (y[k] ?? []).join("|"))) return false;
  if ((x.ra_um == null) !== (y.ra_um == null)) return false;
  return x.ra_um == null || (Math.abs((x.ra_um ?? 0) - (y.ra_um ?? 0)) < 1e-9 && x.ra_unit === y.ra_unit);
}

/** NADCAP areas the declared finishes and treatments fall under. */
export function derivedNadcap(s: PartSpecs | null | undefined): string[] {
  const out: string[] = [];
  for (const op of [...(s?.finishes ?? []), ...(s?.heat_treatments ?? [])]) {
    const a = OP_NADCAP[op];
    if (a && !out.includes(a)) out.push(a);
  }
  return out;
}

/** What whoever makes the part must hold, in words ("NADCAP, heat treating"). */
export function mustHold(s: PartSpecs | null | undefined): string[] {
  const out: string[] = [];
  for (const c of s?.certifications ?? []) {
    if (c !== "nadcap") {
      out.push(specLabel(c));
      continue;
    }
    const areas = [...(s?.nadcap_processes ?? [])];
    for (const a of derivedNadcap(s)) if (!areas.includes(a)) areas.push(a);
    for (const a of areas) out.push(`NADCAP, ${specLabel(a).toLowerCase()}`);
  }
  return out;
}

/** "Ra 0.8 µm" or "Ra 32 µin (0.813 µm)", as entered. */
export function raText(s: PartSpecs | null | undefined): string | null {
  if (s?.ra_um == null) return null;
  if (s.ra_unit === "uin") return `Ra ${trim(s.ra_um / UM_PER_UIN)} µin (${trim(s.ra_um)} µm)`;
  return `Ra ${trim(s.ra_um)} µm`;
}

function trim(v: number): string {
  if (Math.abs(v - Math.round(v)) < 1e-6) return String(Math.round(v));
  return v < 10 ? String(Number(v.toPrecision(3))) : v.toFixed(1);
}

/** One short line per declared spec (the Conditions sheet's summary). */
export function specLines(s: PartSpecs | null | undefined): string[] {
  const n = normalizeSpecs(s);
  if (!n) return [];
  const lines: string[] = [];
  const fin = (n.finishes ?? []).map(specLabel);
  const ra = raText(n);
  if (fin.length || ra) lines.push([...fin, ...(ra ? [ra] : [])].join(", "));
  if (n.heat_treatments?.length) lines.push(n.heat_treatments.map(specLabel).join(", "));
  if (n.inspection?.length) lines.push(n.inspection.map(specLabel).join(", "));
  const must = mustHold(n);
  if (must.length) lines.push(`Supplier must hold ${must.join(", ")}`);
  const tol = toleranceText(n.general_tolerance);
  if (tol) lines.push(`General tolerance ${tol}`);
  return lines;
}

/* ── the editor's draft ──────────────────────────────────────────────── */

export interface SpecsDraft {
  finishes: string[];
  ra: string;
  raUnit: "um" | "uin";
  heat: string[];
  inspection: string[];
  certs: string[];
  nadcap: string[];
  /** none, an ISO 2768 class, or a ± value typed in `tolUnit`. */
  tolKind: "none" | "iso" | "pm";
  tolIso: "f" | "m" | "c" | "v";
  tolValue: string;
  tolUnit: "mm" | "in";
}

export function draftFrom(s: PartSpecs | null | undefined): SpecsDraft {
  const n = normalizeSpecs(s);
  const unit = n?.ra_unit === "uin" ? "uin" : "um";
  const ra = n?.ra_um != null ? trim(unit === "uin" ? n.ra_um / UM_PER_UIN : n.ra_um) : "";
  return {
    finishes: n?.finishes ?? [],
    ra,
    raUnit: unit,
    heat: n?.heat_treatments ?? [],
    inspection: n?.inspection ?? [],
    certs: n?.certifications ?? [],
    nadcap: n?.nadcap_processes ?? [],
    tolKind: !n?.general_tolerance ? "none" : "iso2768" in n.general_tolerance ? "iso" : "pm",
    tolIso: n?.general_tolerance && "iso2768" in n.general_tolerance ? n.general_tolerance.iso2768 : "m",
    tolValue: n?.general_tolerance && "plus_minus" in n.general_tolerance ? trim(n.general_tolerance.plus_minus) : "",
    tolUnit: n?.general_tolerance && "plus_minus" in n.general_tolerance ? n.general_tolerance.unit : "mm",
  };
}

/** Toggle one value; "As machined" and the named finishes exclude each other. */
export function toggle(values: string[], v: string, group?: "finishes"): string[] {
  if (values.includes(v)) return values.filter((x) => x !== v);
  if (group === "finishes") return v === "as_machined" ? ["as_machined"] : [...values.filter((x) => x !== "as_machined"), v];
  return [...values, v];
}

/** Parse an Ra typed with or without a unit ("0.8", "32 µin", "1.6um"). */
export function parseRa(text: string, unit: "um" | "uin"): { um: number | null; unit: "um" | "uin"; error: string | null } {
  const t = text.trim();
  if (!t) return { um: null, unit, error: null };
  const m = /^(?:ra\s*)?([0-9]*[.,]?[0-9]+)\s*(µm|um|micron|microns|µin|uin|microinch(?:es)?)?$/i.exec(t);
  if (!m) return { um: null, unit, error: "Ra must be a number, in µm or µin." };
  const v = Number(m[1].replace(",", "."));
  const w = (m[2] ?? "").toLowerCase();
  const u: "um" | "uin" = w ? (/in/.test(w) ? "uin" : "um") : unit;
  const um = u === "uin" ? v * UM_PER_UIN : v;
  if (!(um >= 0.012 && um <= 50)) return { um: null, unit: u, error: `Ra must be from 0.012 to 50 µm (${trim(0.012 / UM_PER_UIN)} to ${trim(50 / UM_PER_UIN)} µin).` };
  return { um: Number(um.toPrecision(10)), unit: u, error: null };
}

/** The draft as the API body (`part_specs`), or null to clear, plus anything wrong with it. */
export function specsFromDraft(d: SpecsDraft): { specs: PartSpecs | null; errors: string[] } {
  const errors: string[] = [];
  const ra = parseRa(d.ra, d.raUnit);
  if (ra.error) errors.push(ra.error);
  const out: PartSpecs = {};
  if (d.finishes.length) out.finishes = [...d.finishes];
  if (ra.um != null) {
    out.ra_um = ra.um;
    out.ra_unit = ra.unit;
  }
  if (d.heat.length) out.heat_treatments = [...d.heat];
  if (d.inspection.length) out.inspection = [...d.inspection];
  if (d.certs.length) out.certifications = [...d.certs];
  if (d.certs.includes("nadcap")) {
    if (d.nadcap.length) out.nadcap_processes = [...d.nadcap];
    else if (!derivedNadcap(out).length) errors.push("Name the NADCAP special process, for example heat treating.");
  }
  if (d.tolKind === "iso") out.general_tolerance = { iso2768: d.tolIso };
  else if (d.tolKind === "pm" && d.tolValue.trim()) {
    const v = Number(d.tolValue.trim().replace(/^±/, "").replace(",", "."));
    if (!(v > 0) || !Number.isFinite(v)) errors.push("The general tolerance must be a number above 0, for example 0.1.");
    else if (v * (d.tolUnit === "in" ? 25.4 : 1) > 10) errors.push("The general tolerance can be at most ±10 mm (±0.39 in).");
    else out.general_tolerance = { plus_minus: v, unit: d.tolUnit };
  }
  return { specs: Object.keys(out).length ? out : null, errors };
}

/* ── what the check did with them ───────────────────────────────────── */

export interface SpecFinding {
  code: string;
  message: string;
  fix_suggestion?: string | null;
  process?: string;
}

interface EstimateLike {
  process: string;
  quantity: number;
  spec_excluded?: boolean;
  spec_exclusion_reason?: string;
  spec_findings?: SpecFinding[];
  spec_notes?: string[];
  line_items?: Record<string, number>;
}

/** One finding per process the specs rule out (the first quantity's), in the report's order. */
export function specExclusions(estimates: EstimateLike[] | null | undefined): { process: string; reason: string; findings: SpecFinding[] }[] {
  const seen = new Set<string>();
  const out: { process: string; reason: string; findings: SpecFinding[] }[] = [];
  for (const e of estimates ?? []) {
    if (!e.spec_excluded || seen.has(e.process)) continue;
    seen.add(e.process);
    out.push({ process: e.process, reason: e.spec_exclusion_reason ?? e.spec_findings?.[0]?.message ?? "Can't meet the specs", findings: e.spec_findings ?? [] });
  }
  return out;
}

/** The specs a check was priced with (the report's own record of them), or null. */
export function runSpecs(cost: { specs?: { declared?: unknown } | null } | null | undefined): PartSpecs | null {
  return normalizeSpecs(cost?.specs?.declared ?? null);
}

/** Saved specs differ from the ones the shown prices were computed with (the tolerance isn't priced, so it doesn't count). */
export function specsChangedSinceRun(cost: { specs?: { declared?: unknown } | null } | null | undefined, stored: unknown): boolean {
  if (!cost) return false;
  return !sameSpecs(pricedSpecs(runSpecs(cost)), pricedSpecs(stored));
}
