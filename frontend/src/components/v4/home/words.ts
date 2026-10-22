/**
 * Plain-English names the v4 screens use for engine ids: ways of making a part
 * and finding codes. Pure (only relative .ts imports) so the derivations that use it run under
 * `node --test`. Unknown ids fall back to a readable version of the id, never to
 * an invented name.
 */
import { PROCESS_NAME, processLabel } from "../process-names.ts";

export const WAY: Record<string, string> = Object.fromEntries(Object.keys(PROCESS_NAME).map((c) => [c, processLabel(c)]));

/** "cnc_3axis" → "3-axis milling"; an unknown id → "Some process" (spaces, first letter up). */
export function wayName(process: string | null | undefined): string {
  if (!process) return "";
  const known = WAY[process];
  if (known) return known;
  const words = process.replace(/[_-]+/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : process;
}

export const FINDING: Record<string, string> = {
  WALL_THICKNESS_PRECISION: "Walls near the limit, unconfirmed",
  INSUFFICIENT_DRAFT: "No draft on the straight walls",
  SETUP_ACCESS_UNVERIFIED: "Tool access unconfirmed",
  WALL_UNIFORMITY_SAMPLED: "Wall evenness sampled",
  MACHINING_ALLOWANCE: "Needs machining after",
  SINTERING_SHRINKAGE: "Shrinks when sintered",
  PATTERN_TOOLING_REVIEW: "Pattern tooling to review",
  CUPPING_RISK: "Cupping",
  RESIDUAL_STRESS_RISK: "Residual stress",
  PRISMATIC_PROFILE_UNVERIFIED: "Profile unconfirmed",
  CONDUCTIVITY_REQUIRED: "Needs a conductive material",
  SHEET_GAUGE_UNVERIFIED: "Sheet gauge unconfirmed",
  NOT_ROTATIONALLY_SYMMETRIC: "Not a round part",
  THICK_WALL: "Thick walls",
  THIN_WALL: "Walls too thin",
  RIB_RULES_CHECK: "Rib rules to check",
};

/** A finding's short name; falls back to the engine's own message when the code is unknown. */
export function findingName(code: string, message?: string | null): string {
  return FINDING[code] ?? (message?.trim() || code.replace(/_/g, " ").toLowerCase());
}

export const SEVERITY: Record<string, string> = { error: "must change", warning: "advisory", info: "info" };

/** "2026-10-18T05:00:33Z" → "05:00" when it's today (local), else "Oct 18". */
export function shortWhen(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "";
  const d = new Date(t);
  const sameDay = d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
  if (sameDay) return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/** "Oct 18, 2026" from an ISO string; "" when unparseable. */
export function longDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "";
  return new Date(t).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export function plural(n: number, one: string, many?: string): string {
  return `${n.toLocaleString("en-US")} ${n === 1 ? one : many ?? one + "s"}`;
}

/** "20 × 15 × 10 mm" from a bounding box; rounds to whole mm above 10, one decimal below. */
export function sizeText(bbox: readonly number[] | null | undefined): string {
  if (!bbox || bbox.length < 3 || bbox.some((v) => !Number.isFinite(v))) return "";
  const f = (v: number) => (Math.abs(v) >= 10 ? String(Math.round(v)) : String(Math.round(v * 10) / 10));
  return `${bbox.slice(0, 3).map(f).join(" × ")} mm`;
}

export function money(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** The wall check's sentence ("88060 mesh triangles (97.0%) below 0.8mm min wall for 3-axis milling. Thinnest: 0.364mm.";
 * "faces" in records before op-15), as backend analysis/serialization.wall_words reads it. */
const WALL_SENTENCE = /^\s*(\d+) (?:mesh triangles|faces) \(\d+(?:\.\d+)?%\) below (\d+(?:\.\d+)?)\s?mm( min wall)? for ([^.]+?)\.\s*Thinnest:\s*(\d+(?:\.\d+)?)\s?mm\b/i;

/**
 * The wall check in plain words, the thinnest wall first, its numbers as the engine wrote them (op-15):
 * "Walls down to 0.364 mm, under the 0.8 mm min wall for 3-axis milling (88,060 mesh triangles)". Null for any other sentence.
 */
export function wallWords(text: string | null | undefined): string | null {
  const m = WALL_SENTENCE.exec(text ?? "");
  if (!m) return null;
  const [, n, need, minWall, process, thinnest] = m;
  const named = wayName(process); // older records name the method by its code ("ded")
  const how = /^[a-z0-9_]+$/.test(process) && named ? named.charAt(0).toLowerCase() + named.slice(1) : process;
  return `Walls down to ${thinnest} mm, under the ${need} mm ${minWall ? "min wall" : "recommended"} for ${how} (${Number(n).toLocaleString("en-US")} mesh triangles)`;
}
