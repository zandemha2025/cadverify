import { R } from "../routes";

/** A catalog run's summary, laid out to print or save as PDF (under the run's own route). */
export function runSummaryHref(batchId: string): string {
  return `${R.batch(batchId)}/summary`;
}

/** The Batches page with the new catalog run sheet in front. */
export const NEW_RUN_HREF = `${R.many}?new=1`;
