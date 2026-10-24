/**
 * RFQ packages: the picker's price and pick, in words (buyer-11). A record's
 * price is ScaleCAD's at the quantity the package would ask for, with the
 * engine's pick there (the part page's pick at that quantity), never "at 1".
 * Backend: POST /rfq-packages/preview (src/services/rfq_package_service.py).
 */
import type { CostDecisionSummary } from "@/lib/api";
import type { PackagePreviewItem } from "./api";
import { summaryLines } from "./facts.ts";
import { money, num, wayLower } from "./words.ts";

/** Where a prefilled quantity came from, in words. */
export const QTY_FROM: Record<string, string> = {
  outside_route: "the route you marked to buy outside",
  yearly_volume: "the part's yearly volume",
  run: "the run it was checked in",
  record: "the quantity it was priced at",
};

/**
 * "$193.18 at 250" and "ScaleCAD’s pick at 250: 3-axis milling". With no
 * quantity asked for, the price where the part's page opens, and the line says
 * no quantity is set.
 */
export function pickerLine(r: CostDecisionSummary, p: PackagePreviewItem | undefined): { price: string; what: string } {
  if (!p) return { price: "", what: summaryLines(r).what };
  const pr = p.price;
  if (p.quantity == null && !pr) return { price: "", what: "No quantity set" };
  if (!pr) return { price: "", what: `Not priced at ${num(p.quantity)}` };
  const pick = r.user_disposition_label ? summaryLines(r).what : `ScaleCAD’s pick at ${num(pr.quantity)}: ${wayLower(pr.process)}`;
  return { price: `${money(pr.unit_cost_usd)} at ${num(pr.quantity)}`, what: p.quantity == null ? `${pick} · no quantity set` : pick };
}
