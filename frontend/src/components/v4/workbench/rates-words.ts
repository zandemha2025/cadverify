/**
 * Which rate card a breakdown's price was figured at, in words (ce-10, ce-20).
 * Pure; the record's `rates` basis comes from GET /cost-decisions/{id}.
 */
import type { CostReport, RateBasis } from "@/lib/api";

/** "your rates v1" / "typical rates": what a price was figured at (a bound shop profile names itself). */
export function ratesName(report: CostReport | null | undefined, shopName: string | null | undefined): string {
  if (shopName) return shopName;
  const v = report?.rate_card?.version;
  return v != null ? `your rates v${v}` : "typical rates";
}

/**
 * The decision summary for email or a ticket, with the line saying which rates
 * priced it, and the out-of-date caveat when the org has published newer rates.
 */
export function summaryWithRates(summary: string, rates: RateBasis | null | undefined): string {
  if (!summary || !rates) return summary;
  const lines = summary.split("\n");
  const note = rates.out_of_date ? `Out of date: ${lowerFirst(rates.text)} Re-cost before quoting.` : rates.text;
  return [lines[0], note, ...lines.slice(1)].join("\n");
}

function lowerFirst(s: string): string {
  return s.replace(/^\w/, (c) => c.toLowerCase());
}
