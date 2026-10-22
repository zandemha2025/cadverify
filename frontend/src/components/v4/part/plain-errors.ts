/**
 * Server refusals in plain words (buyer-04, buyer-05). A buyer re-checking a part or
 * opening its 3D view read "this organization has reached its concurrent-analysis limit
 * of 3" and "Could not tessellate this part: gmsh could not mesh the geometry [rung 2
 * exceeded 15s cap]". Each is said here as what happened, what it means for the page and
 * what to do; the server's own words stay available as `detail` for a Details line.
 * Pure, for node --test.
 */

export type ErrorPlace = "recheck" | "view" | "cost";

export interface PlainError {
  text: string;
  /** The server's own words, when `text` replaced them. */
  detail: string | null;
  /** Waiting and trying again can work (busy, out of time); a refusal of the input can't. */
  retry: boolean;
}

const TESSELLATE = /could not tessellate|mesh strateg|\bgmsh\b|exceeded \d+(?:\.\d+)?\s*s cap|\brung \d/i;
const TIMEOUT = /analysis_timeout|exceeded \d+(?:\.\d+)?\s*s timeout|timed out/i;
const BUSY_ORG = /concurrent-analysis limit|org_at_capacity/i;
const BUSY_SERVER = /server is at capacity|server_busy/i;

const UNCHANGED = "Nothing was saved; the record on this page is unchanged.";

export function plainError(place: ErrorPlace, status: number, detail: string | null | undefined, code?: string | null): PlainError {
  const raw = (detail ?? "").trim() || null;
  const said = `${code ?? ""} ${raw ?? ""}`;
  if (BUSY_ORG.test(said) || (status === 429 && /capacity/i.test(said) && !BUSY_SERVER.test(said))) {
    const limit = said.match(/limit of (\d+)/)?.[1];
    const n = limit ? `${limit} ` : "";
    const jobs = `ScaleCAD is already running ${n ? `${n}jobs` : "as many jobs as it runs at once"} for your organization (checks, re-checks and 3D views).`;
    const lead = place === "view" ? `The 3D view is waiting: ${jobs}` : place === "cost" ? `Prices are waiting: ${jobs}` : `Not re-checked yet: ${jobs}`;
    return { text: `${lead} Try again when one finishes.${place === "recheck" ? ` ${UNCHANGED}` : ""}`, detail: raw, retry: true };
  }
  if (BUSY_SERVER.test(said)) {
    return { text: `ScaleCAD's servers are busy. Try again in a minute.${place === "recheck" ? ` ${UNCHANGED}` : ""}`, detail: raw, retry: true };
  }
  if (TESSELLATE.test(said)) {
    return {
      text:
        place === "view"
          ? "ScaleCAD couldn't turn the kept file into a 3D shape in the time a 3D view gets. Try again in a minute."
          : place === "cost"
            ? "The process checks are ready. Prices didn't finish: ScaleCAD couldn't turn the file into a 3D shape for pricing in the time a check gets. Retry cost: it gets more time."
            : `Not re-checked: ScaleCAD couldn't turn the kept file into a 3D shape in the time a check gets, so nothing was priced. ${UNCHANGED} Try again in a minute.`,
      detail: raw,
      retry: true,
    };
  }
  if (TIMEOUT.test(said) || status === 504) {
    const limit = said.match(/exceeded (\d+(?:\.\d+)?)\s*s timeout/i)?.[1];
    const secs = limit ? ` (${Number(limit)} seconds)` : "";
    return {
      text:
        place === "view"
          ? `The 3D view took longer than it's allowed${secs} and stopped. Try again in a minute.`
          : place === "cost"
            ? `The process checks are ready. Prices took longer than a check is allowed${secs} and stopped. Retry cost: it gets more time.`
            : `Not re-checked: it took longer than a check is allowed${secs} and stopped. ${UNCHANGED} Try again in a minute.`,
      detail: raw,
      retry: true,
    };
  }
  return { text: raw ?? (place === "view" ? "The 3D view didn't load." : place === "cost" ? "Prices didn't finish." : `The re-check didn't finish. ${UNCHANGED}`), detail: null, retry: status >= 500 || status === 0 };
}

/** A refusal that waiting can fix because the request ran out of time or room, not because of the file. */
export function ranOutOfTime(message: string | null | undefined): boolean {
  if (!message) return false;
  return TESSELLATE.test(message) && /exceeded \d+(?:\.\d+)?\s*s cap/i.test(message) ? true : TIMEOUT.test(message);
}
