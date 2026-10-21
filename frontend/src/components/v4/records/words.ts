/**
 * Words and number formats shared by Records, Compare, Analyses, Supplier
 * packages and Programs (boards P2–P6). Pure: no React, only relative .ts imports, so
 * the derivations that use it run under `node --test`.
 */
import { PROCESS_NAME, processLabel } from "../process-names.ts";

/** Plain names for the engine's process codes: the one spelling every screen uses (tells SLA from DLP). */
export const PROC: Record<string, string> = Object.fromEntries(Object.keys(PROCESS_NAME).map((c) => [c, processLabel(c)]));

export function way(code: string | null | undefined): string {
  if (!code) return "—";
  return PROC[code] ?? code.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

/** Lower-case way for use mid-sentence ("cheapest at 10, metal binder jetting"). */
export function wayLower(code: string | null | undefined): string {
  const w = way(code);
  // "Metal binder jetting" → "metal binder jetting"; names like "Multi Jet Fusion" or "Wire EDM" keep their capitals.
  return /^[A-Z][a-z]+(?:,|$| [a-z0-9])/.test(w) ? w[0].toLowerCase() + w.slice(1) : w;
}

/** Plain names for finding codes (board P4). Unknown codes fall back to a tidy version of the code. */
export const FIND: Record<string, string> = {
  WALL_THICKNESS_PRECISION: "Walls near the limit, unconfirmed",
  THIN_WALL: "Walls too thin",
  INSUFFICIENT_DRAFT: "No draft",
  OVERHANG: "Overhangs need support",
  SETUP_ACCESS_UNVERIFIED: "Tool access unconfirmed",
  WALL_UNIFORMITY_SAMPLED: "Wall evenness sampled",
  EXCEEDS_BUILD_VOLUME: "Bigger than the build volume",
  BUILD_ENVELOPE_UNVERIFIED: "Fit in the machine unconfirmed",
  BUILD_ENVELOPE_PRECISION: "Fit near the machine limit",
  FEATURE_SIZE_PRECISION: "Small features near the limit",
  MACHINING_ALLOWANCE: "Needs machining after",
  THICK_WALL: "Thick walls",
  MISSING_FILLETS: "Sharp edges, no fillets",
  NON_UNIFORM_WALLS: "Uneven walls",
  THIN_WALL_MOLDING: "Walls too thin to mold",
  RESIDUAL_STRESS_RISK: "Residual stress",
  CONDUCTIVITY_REQUIRED: "Needs a conductive material",
  SINTERING_SHRINKAGE: "Shrinks when sintered",
  PATTERN_TOOLING_REVIEW: "Pattern tooling to review",
  UNDERCUT_MOLDING: "Undercuts",
  TRAPPED_VOLUME: "Trapped volume",
  CUPPING_RISK: "Cupping",
  PRISMATIC_PROFILE_UNVERIFIED: "Profile unconfirmed",
  PRISMATIC_PROFILE_PRECISION: "Profile near the limit",
  SHEET_GAUGE_UNVERIFIED: "Sheet gauge unconfirmed",
  SHEET_GAUGE_PRECISION: "Sheet gauge near the limit",
  TOO_THICK_SHEET: "Too thick for sheet",
  SHARP_INTERNAL_CORNERS: "Sharp inside corners",
  NOT_ROTATIONALLY_SYMMETRIC: "Not a round part",
  RIB_RULES_CHECK: "Ribs to check",
  HIGH_RIB_RATIO: "Tall thin ribs",
  EXTREME_ASPECT_RATIO: "Very long and thin",
  SHRINKAGE_RISK: "Shrinkage",
  SMALL_FEATURES: "Features too small",
  BUILD_REORIENTATION_REQUIRED: "Must be turned to fit",
  NON_WATERTIGHT: "Mesh has gaps",
  INCONSISTENT_NORMALS: "Faces point the wrong way",
  NOT_SOLID_VOLUME: "Not a closed solid",
  DEGENERATE_FACES: "Collapsed faces",
  MULTIPLE_BODIES: "More than one body",
};

export function finding(code: string | null | undefined): string {
  if (!code) return "No findings";
  return FIND[code] ?? code.toLowerCase().replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

/** Mesh problems a repair can fix in a copy. */
export const REPAIRABLE = new Set(["NON_WATERTIGHT", "INCONSISTENT_NORMALS", "NOT_SOLID_VOLUME", "DEGENERATE_FACES", "MULTIPLE_BODIES"]);

export const MATERIAL: Record<string, string> = {
  polymer: "Plastic",
  stainless: "Stainless",
  aluminum: "Aluminum",
  steel: "Steel",
  titanium: "Titanium",
};

export function materialClass(code: string | null | undefined): string {
  if (!code) return "Material not recorded";
  return MATERIAL[code] ?? code.replace(/^\w/, (c) => c.toUpperCase());
}

export type Tone = "ok" | "warn" | "bad" | "unk";

/** The machine verdict a record carries, in the board's words. */
export const VERDICT: Record<string, [string, Tone]> = {
  makeable_in_house: ["In-house", "ok"],
  makeable_with_secondary_op: ["In-house, plus a second step", "ok"],
  makeable_not_on_owned: ["None of yours", "warn"],
  makeable_outsource_only: ["Outside only", "warn"],
  environment_excluded: ["Ruled out", "bad"],
  not_makeable: ["Can't as drawn", "bad"],
  unknown: ["Not checked", "unk"],
};

export const OUTCOMES = [
  { key: "inhouse", label: "Make in-house" },
  { key: "outside", label: "Make outside" },
  { key: "acquire", label: "Acquire capability" },
  { key: "redesign", label: "Redesign" },
] as const;

export type OutcomeKey = (typeof OUTCOMES)[number]["key"];

export function outcomeLabel(k: string | null | undefined): string | null {
  return OUTCOMES.find((o) => o.key === k)?.label ?? null;
}

/* ── numbers ────────────────────────────────────────────────────────────── */

export function money(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return "$" + v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function num(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toLocaleString("en-US");
}

export function parts(q: number): string {
  return `${num(q)} ${q === 1 ? "part" : "parts"}`;
}

export function plural(n: number, one: string, many?: string): string {
  return `${n.toLocaleString("en-US")} ${n === 1 ? one : many ?? one + "s"}`;
}

export function trim1(v: number): string {
  return (Math.round(v * 10) / 10).toLocaleString("en-US", { maximumFractionDigits: 1 });
}

/** "20 × 15 × 10 mm" from a bounding box. */
export function sizeText(bbox: readonly number[] | null | undefined): string {
  if (!bbox || bbox.length !== 3 || !bbox.every((n) => Number.isFinite(n))) return "—";
  return `${bbox.map((n) => trim1(n)).join(" × ")} mm`;
}

/** "2.72 cm³" (two places under 10, one under 1,000, whole numbers above). */
export function volumeText(cm3: number | null | undefined): string {
  if (cm3 == null || !Number.isFinite(cm3)) return "—";
  const d = cm3 < 10 ? 2 : cm3 < 1000 ? 1 : 0;
  return `${cm3.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })} cm³`;
}

/** "0.03 s" under a second, "10.1 s" above. */
export function seconds(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${(ms / 1000).toFixed(2)} s`;
}

/** The last six characters of a record or analysis id ("#ZAEQ1"-style short ids). */
export function short(id: string | null | undefined): string {
  return id ? id.slice(-6) : "";
}

/* ── dates (UTC, as the boards print them) ──────────────────────────────── */

function d(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const t = new Date(iso);
  return Number.isNaN(t.getTime()) ? null : t;
}

/** "05:00" (UTC). */
export function timeUtc(iso: string | null | undefined): string {
  const t = d(iso);
  if (!t) return "—";
  return t.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC" });
}

/** "Oct 18, 2026". */
export function dateUtc(iso: string | null | undefined): string {
  const t = d(iso);
  if (!t) return "—";
  return t.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}

/** "Oct 18, 2026, 05:00 UTC". */
export function stampUtc(iso: string | null | undefined): string {
  const t = d(iso);
  if (!t) return "—";
  return `${dateUtc(iso)}, ${timeUtc(iso)} UTC`;
}

/** A list row's time: "05:00" today (UTC), else "Oct 17". */
export function rowTime(iso: string | null | undefined, now: Date = new Date()): string {
  const t = d(iso);
  if (!t) return "—";
  const same = t.toISOString().slice(0, 10) === now.toISOString().slice(0, 10);
  if (same) return timeUtc(iso);
  const sameYear = t.getUTCFullYear() === now.getUTCFullYear();
  return t.toLocaleDateString("en-US", { month: "short", day: "numeric", year: sameYear ? undefined : "numeric", timeZone: "UTC" });
}

/** The declared service conditions as one plain line, or null when none are declared. */
export function conditionsText(env: Record<string, unknown> | null | undefined): string | null {
  if (!env || typeof env !== "object") return null;
  const bits: string[] = [];
  const medium = typeof env.medium === "string" && env.medium.trim() ? env.medium.trim() : null;
  if (medium) bits.push(medium.replace(/^\w/, (c) => c.toUpperCase()));
  else if (env.sour_service === true) bits.push("Sour service");
  else if (env.corrosive === true) bits.push("Corrosive");
  const lo = typeof env.min_temp_c === "number" ? env.min_temp_c : null;
  const hi = typeof env.max_temp_c === "number" ? env.max_temp_c : null;
  if (lo != null && hi != null) bits.push(`${fmtSigned(lo)} to ${fmtSigned(hi)} °C`);
  else if (hi != null) bits.push(`up to ${fmtSigned(hi)} °C`);
  else if (lo != null) bits.push(`from ${fmtSigned(lo)} °C`);
  if (typeof env.pressure_bar === "number") bits.push(`${num(env.pressure_bar)} bar`);
  if (typeof env.standard === "string" && env.standard.trim()) bits.push(env.standard.trim());
  return bits.length ? bits.join(", ") : null;
}

/** A short tag for list lines: "sour gas (H2S)" → "sour gas". */
export function conditionsTag(env: Record<string, unknown> | null | undefined): string | null {
  if (!env || typeof env !== "object") return null;
  const medium = typeof env.medium === "string" && env.medium.trim() ? env.medium.trim().replace(/\s*\(.*\)\s*$/, "") : null;
  if (medium) return medium.toLowerCase();
  if (env.sour_service === true) return "sour service";
  if (env.corrosive === true) return "corrosive";
  return conditionsText(env) ? "conditions" : null;
}

function fmtSigned(n: number): string {
  return n < 0 ? `−${num(Math.abs(n))}` : num(n);
}

/** Why a record went out of date, in words ("machine_inventory_changed" → "Your machines changed"). */
export function staleText(reason: string | null | undefined): string {
  if (!reason) return "A machine or rate it used changed";
  const [code, a, b] = reason.split(":");
  const v = (x?: string) => (x && /^v\d+$/.test(x) ? ` (${x})` : "");
  switch (code) {
    case "machine_inventory_changed":
      return "Your machines changed";
    case "rate_library_published":
      return `New rates were published${v(a)}`;
    case "material_library_published":
      return `New material prices were published${v(a)}`;
    case "shop_profile_published":
      return `Shop profile ${a || ""} was updated${v(b)}`.replace("  ", " ");
    default:
      return reason.replace(/[_:]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());
  }
}
