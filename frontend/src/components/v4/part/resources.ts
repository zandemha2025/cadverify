/**
 * What one route takes, in resources first: machine time, the material it
 * uses (mass, volume and grade) and whose machine it runs on. Read from the
 * engine's own estimate for that process and quantity, nothing added:
 *
 * - machine time is the estimate's `cycle_time` driver (machine hours per part);
 * - the material is the mass the engine charges for (stock, printed material
 *   with supports, poured metal), read from its `material_cost` derivation
 *   ("… = 0.0136 kg × $25/kg"), with the density it names for the volume;
 * - ownership is the engine's machine fit for the route (`Method.inHouse`, the
 *   `owned_in_house` driver for running cost only, the fit's gaps), and a
 *   machine's purchase price is never shown: ScaleCAD has none.
 *
 * A figure the estimate doesn't carry stays null and shows as "—".
 * Pure: no React, no fetch, only relative `.ts` runtime imports (node --test).
 */
import type { CostEstimate } from "@/lib/api";
import type { PerRouteFit } from "@/lib/verify/verification";
import { gapText } from "../../../lib/verify/verification.ts";
import { MACHINE_KIND, processName } from "../process-names.ts";

function finite(n: unknown): n is number {
  return typeof n === "number" && Number.isFinite(n);
}

/* ── formatting ─────────────────────────────────────────────────────────── */

/** "<1 min", "6 min", "1.3 h", "41 h", "1,204 h", or "—". */
export function hoursText(h: number | null | undefined): string {
  if (!finite(h) || h < 0) return "—";
  if (h === 0) return "0 min";
  if (h < 1 / 60) return "<1 min";
  if (h < 1) return `${Math.round(h * 60)} min`;
  if (h < 10) return `${(Math.round(h * 10) / 10).toLocaleString("en-US")} h`;
  return `${Math.round(h).toLocaleString("en-US")} h`;
}

/** "<1 g", "4.3 g", "13.6 g", "270 g", "1.27 kg", "12.4 kg", "312 kg", or "—". */
export function massText(kg: number | null | undefined): string {
  if (!finite(kg) || kg < 0) return "—";
  const g = kg * 1000;
  if (g < 1) return "<1 g";
  if (g < 100) return `${(Math.round(g * 10) / 10).toLocaleString("en-US")} g`;
  if (g < 1000) return `${Math.round(g).toLocaleString("en-US")} g`;
  if (kg < 10) return `${kg.toFixed(2)} kg`;
  if (kg < 100) return `${kg.toFixed(1)} kg`;
  return `${Math.round(kg).toLocaleString("en-US")} kg`;
}

/** "2.72 cm³", "23.8 cm³", "108 cm³", "1,350 cm³", or "—". */
export function cm3Text(v: number | null | undefined): string {
  if (!finite(v) || v < 0) return "—";
  if (v < 10) return `${v.toFixed(2)} cm³`;
  if (v < 100) return `${v.toFixed(1)} cm³`;
  return `${Math.round(v).toLocaleString("en-US")} cm³`;
}

/* ── one estimate's resources ───────────────────────────────────────────── */

export interface RouteResources {
  process: string;
  quantity: number;
  /** Machine hours per part (the estimate's cycle_time driver). */
  hoursEach: number | null;
  /** Machine hours for the run: per part × quantity. */
  hoursRun: number | null;
  /** The grade the route is priced in ("PA12 (Nylon 12)"). */
  grade: string;
  /** Material the engine charges for, per part: stock, printed material with supports, poured metal. */
  kgEach: number | null;
  kgRun: number | null;
  /** That material's volume, from the density the engine names. */
  cm3Each: number | null;
  /** The part's own volume, measured from the file. */
  partCm3: number | null;
  density: number | null;
  /** Costed on a machine you own at its running cost (capital removed): the owned_in_house driver. */
  runningCostOnly: boolean;
}

const MASS_RE = /=\s*(\d+(?:\.\d+)?)\s*kg\s*×\s*\$/;
const DENSITY_RE = /density\s+(\d+(?:\.\d+)?)\s*g\/cm(?:³|3)/g;

/** The material mass and density an estimate's material_cost derivation names, or nulls. */
export function materialFromSource(source: string | null | undefined): { kg: number | null; density: number | null } {
  const s = String(source ?? "");
  const m = MASS_RE.exec(s);
  const kg = m ? Number(m[1]) : null;
  // The density the mass was computed with: the last one named before the mass.
  const head = m ? s.slice(0, m.index) : s;
  let density: number | null = null;
  for (const d of head.matchAll(DENSITY_RE)) density = Number(d[1]);
  return {
    kg: finite(kg) && kg > 0 ? kg : null,
    density: finite(density) && density > 0 ? density : null,
  };
}

function driver(e: CostEstimate, name: string) {
  return e.drivers.find((d) => d.name === name) ?? null;
}

export function routeResources(e: CostEstimate | null | undefined, partCm3: number | null | undefined): RouteResources | null {
  if (!e) return null;
  const q = e.quantity;
  const cycle = driver(e, "cycle_time");
  const hoursEach = cycle && cycle.unit === "hr" && finite(cycle.value) && cycle.value >= 0 ? cycle.value : null;
  const mat = materialFromSource(driver(e, "material_cost")?.source);
  const vol = finite(partCm3) && partCm3 > 0 ? partCm3 : null;
  const cm3Each = mat.kg != null && mat.density != null ? (mat.kg * 1000) / mat.density : null;
  return {
    process: e.process,
    quantity: q,
    hoursEach,
    hoursRun: hoursEach != null ? hoursEach * q : null,
    grade: e.material,
    kgEach: mat.kg,
    kgRun: mat.kg != null ? mat.kg * q : null,
    cm3Each,
    partCm3: vol,
    density: mat.density,
    runningCostOnly: driver(e, "owned_in_house") != null,
  };
}

/** What the material figure is, in the route's own words: stock you cut from, material printed, metal poured. */
function feedWord(process: string): string {
  if (/^cnc_|^wire_edm$|^sheet_metal$/.test(process)) return "of stock";
  if (/casting$/.test(process)) return "poured";
  if (process === "forging") return "of bar";
  if (process === "injection_molding") return "molded";
  return "printed";
}

/** "PLA · 10.95 cm³ printed · part 23.8 cm³": the grade, then the volume used next to the part's own, when they differ. */
export function materialSub(r: RouteResources): string {
  const bits = [r.grade];
  if (r.cm3Each != null) {
    const same = r.partCm3 != null && Math.abs(r.cm3Each - r.partCm3) <= 0.02 * r.partCm3;
    if (same || r.partCm3 == null) bits.push(cm3Text(r.cm3Each));
    else bits.push(`${cm3Text(r.cm3Each)} ${feedWord(r.process)}`, `part ${cm3Text(r.partCm3)}`);
  } else if (r.partCm3 != null) bits.push(`part ${cm3Text(r.partCm3)}`);
  return bits.join(" · ");
}

/** "Mild Steel, 6.60 cm³ of stock", "PLA, 11.0 cm³ printed", "PA12 (Nylon 12), 23.8 cm³": the grade and the volume it uses. */
export function materialShort(r: RouteResources): string {
  if (r.cm3Each == null) return r.grade;
  const same = r.partCm3 == null || Math.abs(r.cm3Each - r.partCm3) <= 0.02 * r.partCm3;
  return `${r.grade}, ${cm3Text(r.cm3Each)}${same ? "" : ` ${feedWord(r.process)}`}`;
}

/** "31 min each · 52 h for 100" (just "each" for one part). */
export function timeLine(r: RouteResources): string {
  if (r.hoursEach == null) return "—";
  return r.quantity > 1 ? `${hoursText(r.hoursEach)} each · ${hoursText(r.hoursRun)} for ${r.quantity.toLocaleString("en-US")}` : `${hoursText(r.hoursEach)} each`;
}

/** "13.6 g each · 1.36 kg for 100". */
export function massLine(r: RouteResources): string {
  if (r.kgEach == null) return "—";
  return r.quantity > 1 ? `${massText(r.kgEach)} each · ${massText(r.kgRun)} for ${r.quantity.toLocaleString("en-US")}` : `${massText(r.kgEach)} each`;
}

/** For the run: "52 h machine time · 1.36 kg PLA" (the grade left out with `grade: false`); null when neither is known. */
export function runLine(r: RouteResources | null, opts: { grade?: boolean } = {}): string | null {
  if (!r) return null;
  const bits: string[] = [];
  if (r.hoursRun != null) bits.push(`${hoursText(r.hoursRun)} machine time`);
  if (r.kgRun != null) bits.push(opts.grade === false ? massText(r.kgRun) : `${massText(r.kgRun)} ${r.grade}`);
  return bits.length ? bits.join(" · ") : null;
}

/* ── ownership ─────────────────────────────────────────────────────────── */

export type OwnershipKind = "owned" | "not_fit" | "unconfirmed" | "not_owned" | "no_machines";

export interface Ownership {
  kind: OwnershipKind;
  /** The figure: the machine's name, "Doesn't fit yours", "Not owned". */
  v: string;
  /** Under it: "you own it · running cost only", "Haas VF-2: not qualified for Delrin (POM)", "needs a filament printer". */
  s: string;
  machine: string | null;
}

/** "a filament printer", "an injection molder"; null when there's no machine word for the process. */
export function aMachine(process: string): string | null {
  const kind = MACHINE_KIND[process];
  if (!kind) return null;
  const k = /^[A-Z][a-z]/.test(kind) ? kind[0].toLowerCase() + kind.slice(1) : kind;
  return `${/^[aeiou]/i.test(k) ? "an" : "a"} ${k}`;
}

/**
 * Whose machine a route runs on. Owned: the machine that clears every check
 * (running cost only when the engine removed its capital). Not owned: the
 * machine it would need, by kind; a machine you own of that kind that doesn't
 * fit says why, in the engine's words. Tooling that pays back (a mold or die)
 * names the engine's crossover quantity; no machine price is ever shown.
 */
export function ownershipOf(
  route: { code: string; inHouse: string | null; fit: PerRouteFit | null },
  r: RouteResources | null,
  machinesDeclared: number,
  paybackQty: number | null = null,
): Ownership {
  if (route.inHouse) {
    return { kind: "owned", v: route.inHouse, s: r?.runningCostOnly ? "you own it · running cost only" : "you own it", machine: route.inHouse };
  }
  const fit = route.fit;
  const gaps = (fit?.failures ?? []).map(gapText).filter(Boolean);
  if (fit?.best_machine && gaps.length && (fit.verdict === "makeable_not_on_owned" || fit.verdict === "unknown")) {
    return {
      kind: fit.verdict === "unknown" ? "unconfirmed" : "not_fit",
      v: fit.verdict === "unknown" ? "Can't confirm" : "Doesn't fit yours",
      s: `${fit.best_machine}: ${gaps.join(" · ")}`,
      machine: fit.best_machine,
    };
  }
  if (!machinesDeclared) return { kind: "no_machines", v: "No machines yet", s: "add yours to see which you own", machine: null };
  const need = aMachine(route.code);
  const pay = finite(paybackQty) && paybackQty > 0 ? ` · tooling pays back from about ${Math.round(paybackQty).toLocaleString("en-US")} parts` : "";
  return { kind: "not_owned", v: "Not owned", s: `${need ? `needs ${need}` : `no ${processName(route.code).toLowerCase()} of yours`}${pay}`, machine: null };
}
