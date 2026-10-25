/**
 * How long this check should take, from how long checks take here (me-21: the
 * card always said "About 30 s" while checks took 70-100 s, and never said the
 * server was busy). GET /checks/timing gives the median of recent process
 * checks and pricings on the server and how many analyses it runs now.
 *
 * Pure, for node --test (check-timing.test.ts).
 */

export interface CheckTiming {
  validate_s: number | null;
  cost_s: number | null;
  validate_samples: number;
  cost_samples: number;
  /** Whose checks the medians are: the org's own, or everyone's on this server. */
  basis: "org" | "server" | null;
  running: number;
  running_org: number;
}

function secs(s: number): string {
  if (s < 90) return `${Math.round(s / 5) * 5 || 5} s`;
  const m = Math.round(s / 30) / 2;
  return `${m.toLocaleString("en-US")} min`;
}

/** The card's time line while the check runs: what to expect, what's in the way, and how long it has been. */
export function expectedLine(t: CheckTiming | null, elapsedMs: number, running: boolean): string {
  const el = Math.max(0, Math.round(elapsedMs / 1000));
  if (!running) return `${el} s`;
  const total = t && t.validate_s != null && t.cost_s != null ? t.validate_s + t.cost_s : null;
  const others = t ? Math.max(0, t.running - 1) : 0;
  const busy = others > 0 ? ` · ${others} other ${others === 1 ? "check" : "checks"} running on the server now` : "";
  if (total == null) return `${el} s so far${busy}`;
  const usual = t!.basis === "org" ? `Your recent checks took about ${secs(total)}` : `Checks here take about ${secs(total)} lately`;
  if (el > total * 1.2) return `Taking longer than usual: ${el} s so far (usually about ${secs(total)})${busy}`;
  return `${usual}${busy}`;
}
