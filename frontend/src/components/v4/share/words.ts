/**
 * The Share dialog's words and choices (buyer-12, buyer-13, it-22). Pure, so
 * every sentence a sharer reads is tested.
 *
 * A link is what a buyer sends a supplier: anyone with it can open it without
 * signing in until it ends (7 days unless 1, 30 or 90 days or a date is
 * picked) or is switched off. A part's link shows the part, its specs, the
 * quantity and a note; the CAD only when ticked; our cost estimate only when
 * turned on. A package's link shows the package as built. Backend:
 * src/services/share_links.py and supplier_links.py.
 */

export type ShareKind = "record" | "check" | "package";
export type LinkDays = 1 | 7 | 30 | 90;

export const LINK_DAYS: { value: LinkDays; label: string }[] = [
  { value: 1, label: "1 day" },
  { value: 7, label: "7 days" },
  { value: 30, label: "30 days" },
  { value: 90, label: "90 days" },
];
export const DEFAULT_LINK_DAYS: LinkDays = 7;
/** A date of the sharer's own: at most a year ahead (backend MAX_DAYS_AHEAD). */
export const MAX_LINK_DAYS = 366;

export interface LinkChoice {
  /** One of the day choices, or null when a date is picked. */
  days: LinkDays | null;
  /** "YYYY-MM-DD" when the sharer picks a date. */
  date: string | null;
}

export interface LinkShows {
  includeCost: boolean;
  includeCad: boolean;
  note: string;
  quantity: string;
}

export interface LinkPayload {
  expires_in_days?: LinkDays;
  expires_on?: string;
  include_cost?: boolean;
  include_cad?: boolean;
  note?: string | null;
  quantity?: number | null;
}

function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function addDays(d: Date, n: number): Date {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
}

/** The date input's bounds: today to a year ahead. */
export function dateBounds(now = new Date()): { min: string; max: string } {
  return { min: iso(now), max: iso(addDays(now, MAX_LINK_DAYS - 1)) };
}

/** "29 Oct 2026". */
export function dayText(d: Date): string {
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

/** When the link will end, before it is made. */
export function endsText(choice: LinkChoice, now = new Date()): string {
  if (choice.days == null) {
    if (!choice.date) return "Pick a day.";
    const [y, m, d] = choice.date.split("-").map(Number);
    return `Works until the end of ${dayText(new Date(y, m - 1, d))}.`;
  }
  return `Works for ${choice.days === 1 ? "1 day" : `${choice.days} days`}, until ${dayText(addDays(now, choice.days))}.`;
}

/** The request body, or the plain reason it can't be sent. */
export function linkPayload(kind: ShareKind, choice: LinkChoice, shows: LinkShows | null, now = new Date()): { ok: true; body: LinkPayload } | { ok: false; error: string } {
  const body: LinkPayload = {};
  if (choice.days != null) body.expires_in_days = choice.days;
  else {
    if (!choice.date || !/^\d{4}-\d{2}-\d{2}$/.test(choice.date)) return { ok: false, error: "Pick the day the link stops working." };
    const { min, max } = dateBounds(now);
    if (choice.date < min) return { ok: false, error: "That day has passed. Pick today or a later day." };
    if (choice.date > max) return { ok: false, error: "A link lasts a year at most. Pick an earlier day." };
    body.expires_on = choice.date;
  }
  if (kind === "record" && shows) {
    body.include_cost = shows.includeCost;
    body.include_cad = shows.includeCad;
    body.note = shows.note.trim() || null;
    const q = shows.quantity.trim();
    if (q) {
      if (!/^\d+$/.test(q) || Number(q) < 1 || Number(q) > 10_000_000) return { ok: false, error: "Quantity is a whole number from 1 to 10,000,000." };
      body.quantity = Number(q);
    } else body.quantity = null;
  }
  return { ok: true, body };
}

export interface SeesInput {
  kind: ShareKind;
  name: string;
  shows?: LinkShows;
  specs?: string[];
  cadKept?: boolean;
  /** A package: its parts, how many carry CAD, and whether it was built with our cost. */
  parts?: number;
  cadParts?: number;
  packageHasCost?: boolean;
}

/** "What they will see", line by line. */
export function seesLines(x: SeesInput): string[] {
  if (x.kind === "check") return [`${x.name}: its size, the findings and measurements`, "No prices and no file"];
  if (x.kind === "package") {
    const n = x.parts ?? 0;
    return [
      `The request for quote: ${n} ${n === 1 ? "part" : "parts"}, each with material, quantity and specs, your note and reply-by date`,
      x.cadParts ? `CAD files for ${x.cadParts} of ${n}, and the whole package as a ZIP` : "No CAD files (the package holds none), and the package as a ZIP",
      x.packageHasCost ? "Your cost estimate: this package was built with it" : "None of your cost: the package was built without it",
    ];
  }
  const s = x.shows;
  const lines = [`${x.name}: its size and material`];
  lines.push(x.specs?.length ? x.specs.join(" · ") : "Specs: none declared on the part");
  if (s?.quantity.trim()) lines.push(`Quantity: ${Number(s.quantity).toLocaleString("en-US")}`);
  if (s?.note.trim()) lines.push("Your note");
  if (s?.includeCad) lines.push("The CAD file, to download");
  if (s?.includeCost) lines.push("Your cost estimate: the price per part, its lines and the process it picks");
  return lines;
}

/** What never leaves, whatever is picked. */
export const NEVER_SHOWN = "Never shown: your machines, rates, notes, approvals and who checked the part.";
export const WHO_OPENS = "Anyone with the link, without signing in.";
export const COST_WARNING = "The supplier will see your should-cost: price per part, its lines and the process it picks. Quotes tend to come back at that price.";

/** The line under a made link (and the toast after it). */
export function madeText(expiresAt: string | null): string {
  if (!expiresAt) return "Link copied. Anyone with it can open it without signing in. It has no end date.";
  return `Link copied. Anyone with it can open it without signing in, until ${dayText(new Date(expiresAt))}.`;
}

/** A link already on for this target: what making a new one does to it. */
export function replacesText(expiresAt: string | null): string {
  return `A link is already on${expiresAt ? `, until ${dayText(new Date(expiresAt))}` : ""}. A new link switches that one off.`;
}
