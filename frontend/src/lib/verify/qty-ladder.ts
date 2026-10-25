/**
 * The quantities a check prices. Six points (the backend's `_MAX_QTYS = 6` in
 * routes.py), log-spaced so the crossover story has real computed points on
 * both sides of the tooling break-even (~1–2k).
 *
 * Pure (runs under node --test).
 */

export const QTY_LADDER = [1, 100, 1000, 2000, 5000, 10000];

const MAX_QTY = 10_000_000;

/**
 * The ladder with each given quantity as an exact computed point: a declared
 * annual volume, or the order quantity the person was looking at when they
 * opened Check a part from the cost breakdown. Each one replaces the nearest
 * interior point of the base ladder (the 1 and 10,000 anchors stay), in the
 * order given, so the ladder keeps six points; a quantity already on it, or
 * not a whole number from 1 to 10,000,000, changes nothing.
 */
export function quantityLadderFor(points: readonly (number | null | undefined)[]): number[] {
  let ladder = [...QTY_LADDER];
  for (const p of points) {
    if (p == null || !Number.isInteger(p) || p <= 0 || p > MAX_QTY || ladder.includes(p)) continue;
    const replaceable = QTY_LADDER.slice(1, -1).filter((q) => ladder.includes(q));
    if (!replaceable.length) break;
    const nearest = replaceable.reduce((best, q) => (Math.abs(Math.log(q) - Math.log(p)) < Math.abs(Math.log(best) - Math.log(p)) ? q : best));
    ladder = [...ladder.filter((q) => q !== nearest), p].sort((a, b) => a - b);
  }
  return ladder;
}

/** Keep the six-point engine contract while a declared annual volume becomes an exact computed point. */
export function quantityLadderForAnnual(annualVolume: number | null | undefined): number[] {
  return quantityLadderFor([annualVolume]);
}
