/**
 * Plain-English names the v4 screens use for engine ids: ways of making a part
 * and finding codes. Pure (no imports) so the derivations that use it run under
 * `node --test`. Unknown ids fall back to a readable version of the id, never to
 * an invented name.
 */

export const WAY: Record<string, string> = {
  fdm: "Filament printing",
  sla: "Resin printing, SLA",
  dlp: "Resin printing, DLP",
  sls: "Nylon powder printing",
  mjf: "Multi Jet Fusion",
  binder_jetting: "Metal binder jetting",
  dmls: "Metal powder printing, DMLS",
  slm: "Metal powder printing, SLM",
  ebm: "Electron beam melting",
  ded: "Metal deposition",
  waam: "Wire arc deposition",
  cnc_3axis: "3-axis milling",
  cnc_5axis: "5-axis milling",
  cnc_turning: "Lathe",
  wire_edm: "Wire EDM",
  investment_casting: "Investment casting",
  sand_casting: "Sand casting",
  die_casting: "Die casting",
  injection_molding: "Injection molding",
  forging: "Forging",
  sheet_metal: "Sheet metal",
};

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
