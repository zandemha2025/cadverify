/**
 * The way the part will be made: ScaleCAD's pick at a quantity (which weighs a
 * machine you own against the cheapest outside route, decision.IN_HOUSE_RULE),
 * and the process you chose instead, saved on the part's record as its decided
 * outcome (PUT /cost-decisions/{id}/disposition, audited).
 *
 * Pure: no React, no fetch, and only relative `.ts` runtime imports, so it runs
 * under `node --test` (choice.test.ts). Every number is the engine's.
 */
import type { CostDecisionGovernance, CostDecisionSummary, CostEstimate, CostOptionPair, CostOptionSide, CostPickBasis, CostReport } from "@/lib/api";
import { days, methodName, money, qtyWord } from "./model.ts";

/** In-house and the cheapest outside route at one quantity, when a machine you own clears a route. */
export function pairAt(cost: CostReport | null | undefined, q: number): CostOptionPair | null {
  const o = cost?.decision?.options?.[String(q)];
  return o && o.in_house ? o : null;
}

export interface EnginePick {
  process: string;
  material: string;
  inHouse: boolean;
  machine: string | null;
  basis: CostPickBasis | null;
}

/** ScaleCAD's pick at a quantity: the engine's recommendation, which already applies the in-house rule. */
export function enginePick(cost: CostReport | null | undefined, q: number): EnginePick | null {
  const r = cost?.decision?.recommendation?.[String(q)];
  if (!r?.process) return null;
  return { process: r.process, material: r.material, inHouse: r.in_house === true, machine: r.machine ?? null, basis: r.basis ?? null };
}

export interface Choice {
  process: string;
  material: string;
  /** The quantity it was recorded at. The process applies at every quantity on the page. */
  quantity: number;
  kind: "inhouse" | "outside";
  at: string | null;
}

/** The process you chose for this part, from the record's saved outcome. Only Make in-house / Make outside name a way to make it. */
export function recordedChoice(gov: CostDecisionGovernance | null | undefined): Choice | null {
  const kind = gov?.user_disposition;
  const b = gov?.disposition_basis;
  if ((kind !== "inhouse" && kind !== "outside") || !b?.process) return null;
  return { process: b.process, material: b.material, quantity: b.quantity, kind, at: gov?.disposition_updated_at ?? null };
}

/** The process the page follows at q: yours when you chose one, else ScaleCAD's pick. */
export function followed(cost: CostReport | null | undefined, q: number, choice: Choice | null): { process: string; by: "you" | "scalecad" } | null {
  if (choice) return { process: choice.process, by: "you" };
  const p = enginePick(cost, q);
  return p ? { process: p.process, by: "scalecad" } : null;
}

function leadText(s: CostOptionSide): string {
  return days(s.lead_low_days, s.lead_high_days);
}

/** "Bambu Lab X1C · $15.66 each · 5–9 days" */
export function sideLine(s: CostOptionSide): string {
  const who = s.machine ? `${s.machine}` : methodName(s.process);
  return `${who} · ${money(s.unit_cost_usd)} each · ${leadText(s)}`;
}

/**
 * Why ScaleCAD picked what it picked at this quantity, in a sentence of facts.
 * `pair` comes from the engine; the wording only restates its numbers.
 */
export function pickWhy(pair: CostOptionPair, q: number): string {
  const i = pair.in_house;
  const o = pair.outside;
  const mine = `your ${i.machine ?? methodName(i.process)}`;
  const range = `${money(i.low_usd)}–${money(i.high_usd)}`;
  if (!o) return `Made on ${mine}. No outside process is priced for it.`;
  const oName = methodName(o.process);
  const diff = Math.abs(i.unit_cost_usd - o.unit_cost_usd);
  const pct = i.unit_cost_usd > 0 ? Math.round((diff / i.unit_cost_usd) * 100) : 0;
  switch (pair.basis) {
    case "in_house_cheapest":
      return `Made on ${mine}: ${money(i.unit_cost_usd)} each, ${money(diff)} less than ${oName.toLowerCase()} outside.${
        o.lead_high_days != null && i.lead_low_days != null && o.lead_high_days < i.lead_low_days ? ` Outside arrives sooner: ${leadText(o)} against ${leadText(i)}.` : ""
      }`;
    case "in_house_within_range":
      return `Made on ${mine}. ${oName} outside is ${money(diff)} less each (${pct}%), inside the in-house estimate's range of ${range}, so the two prices can't be told apart.`;
    case "outside_cheaper":
      return `${oName} outside, at ${money(o.unit_cost_usd)} each, is below the low end of the in-house range (${range}) on ${mine}.`;
    case "outside_sooner":
      return `${oName} outside is cheaper (${money(o.unit_cost_usd)} against ${money(i.unit_cost_usd)}) and sooner: ${leadText(o)} against ${leadText(i)} for ${qtyWord(q)} on ${i.machine_count && i.machine_count > 1 ? `your ${i.machine_count} × ${i.machine}` : mine}.`;
    default:
      return `Made on ${mine}.`;
  }
}

/** The outcome a "Make it this way" records: in-house when a machine of yours clears the process, else outside. */
export function chooseBody(e: Pick<CostEstimate, "process" | "material" | "quantity">, inHouse: boolean): { disposition: "inhouse" | "outside"; process: string; material: string; quantity: number } {
  return { disposition: inHouse ? "inhouse" : "outside", process: e.process, material: e.material, quantity: e.quantity };
}

/** Whether a process is the one you chose (same process; the material is the engine's for it). */
export function isChosen(choice: Choice | null, process: string): boolean {
  return !!choice && choice.process === process;
}

export interface EarlierChoice extends Choice {
  recordId: string;
}

/**
 * The newest choice recorded on an earlier check of this part (records newest
 * first), when the record on screen isn't it. A re-check makes a new record; the
 * choice stays on the old one until you keep it on the new one.
 */
export function earlierChoiceFrom(decisions: readonly CostDecisionSummary[], currentId: string | null): EarlierChoice | null {
  for (const d of decisions) {
    if (d.id === currentId) continue;
    const c = recordedChoice(d);
    if (c) return { ...c, recordId: d.id };
  }
  return null;
}
