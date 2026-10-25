/**
 * What a re-check changed (buyer-04). "Re-verify with saved specs" ran for 35-48 s and the
 * page looked the same: the buyer couldn't tell whether FAI was in the block's price. After
 * a re-check the page shows the new record and says, in one line, why it was re-checked,
 * which record it is, and what moved at the page's quantity: ScaleCAD's pick, its price
 * and its lead time. Engine numbers only. Pure, for node --test.
 */
import type { CostReport, CostRecommendation } from "@/lib/api";
import { days, methodName, money, qtyWord } from "./model.ts";
import { runSpecs, sameSpecs, specLines } from "./specs.ts";

const MATERIAL_WORD: Record<string, string> = { polymer: "plastic", aluminum: "aluminum", steel: "steel", stainless: "stainless steel", titanium: "titanium" };

function recAt(cost: CostReport | null, q: number): CostRecommendation | null {
  return cost?.decision?.recommendation?.[String(q)] ?? null;
}

function where(r: CostRecommendation): string {
  return r.in_house ? (r.machine ? `on your ${r.machine}` : "in-house") : r.same_process_outside ? "at a job shop" : "outside";
}

/** The quantity the summary talks about: the page's, else the nearest the new record priced. */
function quantityFor(after: CostReport, q: number): number | null {
  const qs = Object.keys(after.decision?.recommendation ?? {}).map(Number).filter((n) => Number.isFinite(n));
  if (!qs.length) return null;
  if (qs.includes(q)) return q;
  return qs.reduce((best, n) => (Math.abs(n - q) < Math.abs(best - q) ? n : best), qs[0]);
}

/** Why it was re-checked, from what differs between the two records. */
export function recheckReason(before: CostReport | null, after: CostReport): string {
  const a = runSpecs(before);
  const b = runSpecs(after);
  if (!sameSpecs(a, b)) return b ? "with the saved specs" : "without specs";
  if (before?.material_class && after.material_class && before.material_class !== after.material_class) {
    return `in ${MATERIAL_WORD[after.material_class] ?? after.material_class}`;
  }
  return "with your machines and conditions";
}

/** "Re-checked with the saved specs · record #E853J · at 250: ScaleCAD's pick 3-axis milling on your KCM Mill 3, $17.89 → $18.73 each; 1–3 → 8–10 days · in the price: First article inspection, AS9102 · no check used" */
export function recheckSummary(before: CostReport | null, after: CostReport, q: number, recordId: string | null, reused = false): string {
  const parts = [`Re-checked ${recheckReason(before, after)}`];
  // The same evidence as a record saved earlier answers with that record (ScaleCAD keeps one per answer).
  if (recordId) parts.push(reused ? `same answer as record #${recordId.slice(-6)}, shown now` : `new record #${recordId.slice(-6)}`);
  const at = quantityFor(after, q);
  const now = at != null ? recAt(after, at) : null;
  const was = at != null ? recAt(before, at) : null;
  if (now && at != null) {
    const name = `${methodName(now.process).toLowerCase()} ${where(now)}`;
    let line: string;
    if (!was) line = `at ${qtyWord(at)}: ScaleCAD's pick ${name}, ${money(now.unit_cost_usd)} each`;
    else if (was.process === now.process && !!was.in_house === !!now.in_house) {
      line =
        Math.abs(was.unit_cost_usd - now.unit_cost_usd) < 0.005
          ? `at ${qtyWord(at)}: ScaleCAD's pick ${name}, unchanged at ${money(now.unit_cost_usd)} each`
          : `at ${qtyWord(at)}: ScaleCAD's pick ${name}, ${money(was.unit_cost_usd)} → ${money(now.unit_cost_usd)} each`;
    } else {
      line = `at ${qtyWord(at)}: ScaleCAD's pick was ${methodName(was.process).toLowerCase()} ${where(was)} at ${money(was.unit_cost_usd)}, now ${name} at ${money(now.unit_cost_usd)} each`;
    }
    const d0 = was ? days(was.lead_low_days, was.lead_high_days) : null;
    const d1 = days(now.lead_low_days, now.lead_high_days);
    if (d0 && d0 !== d1 && d0 !== "—" && d1 !== "—") line += `; ${d0.replace(" days", "")} → ${d1}`;
    parts.push(line);
  }
  const specs = runSpecs(after);
  if (specs && !sameSpecs(runSpecs(before), specs)) parts.push(`priced with the specs: ${specLines(specs).join("; ")}`);
  parts.push("no check used");
  return parts.join(" · ");
}
