/**
 * The running rate of a machine you own, said where the number shows (buyer-03): a buyer typed $87/h
 * for a mill and the run said "running rate $56.55/h", with the reason behind a closed "Running rate"
 * line. The engine prices an owned machine's time at the rate you set less the share that pays for
 * the machine (machine_capital_frac, 35% unless you set it): you already own it, so that share isn't
 * charged again on each part. Pure, for node --test.
 */

/** The engine's default share of an hourly rate that pays for the machine itself (rates.py machine_capital_frac). */
export const DEFAULT_CAPITAL_FRAC = 0.35;

function usd(v: number): string {
  return `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** "$87.00/h you set, less 35% that pays for the machine you already own" (a typical 35% when you set none). */
export function runningRateWhy(hourly: number, capitalFrac: number | null | undefined, capitalSet = capitalFrac != null): string {
  const frac = capitalFrac ?? DEFAULT_CAPITAL_FRAC;
  return `${usd(hourly)}/h you set, less ${capitalSet ? "" : "a typical "}${Math.round(frac * 100)}% that pays for the machine you already own`;
}

/** The add/edit form's line under the capital share: what in-house prices will use, and why. Null without a rate. */
export function runningRateLine(hourly: number | null, capitalPct: number | null): string | null {
  if (hourly == null || !Number.isFinite(hourly) || hourly <= 0) return null;
  const frac = capitalPct != null && Number.isFinite(capitalPct) ? capitalPct / 100 : null;
  const running = hourly * (1 - (frac ?? DEFAULT_CAPITAL_FRAC));
  return `In-house prices use ${usd(running)}/h: ${runningRateWhy(hourly, frac)}. Buying outside uses a shop's full rate.`;
}
