import { R } from "../routes";

/** Where the pilot report lives (Make or buy section): for one catalog run, or for every part. */
export function reportHref(run?: string | null): string {
  return run ? `${R.many}/report?run=${encodeURIComponent(run)}` : `${R.many}/report`;
}

/** The Actual costs page, at its "checked against your real numbers" panel. */
export const ACTUALS_ACCURACY = `${R.actuals}#accuracy`;
