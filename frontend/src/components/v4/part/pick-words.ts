/**
 * One pick per part (np-16, de-05, np-15, de-16, oo-03). The part page names
 * exactly one pick: yours when you chose one, else ScaleCAD's pick (the
 * engine's recommendation at the page's quantity). The design-rule best and
 * the router's usual process for the shape are evidence, never called a
 * pick or "chosen". And the problems figure counts the same problems the
 * list below it shows. Pure, for node --test.
 */
import type { CostReport } from "@/lib/api";
import { enginePick } from "./choice.ts";
import { defaultQty, methodName, methodShort, qtyWord, quantitiesOf } from "./model.ts";

/** The progress panel's "Process chosen" line: the same pick the part page opens with. */
export function chosenLine(cost: CostReport | null, q: number | null = null): string | null {
  if (!cost) return null;
  const at = q ?? defaultQty(quantitiesOf(cost));
  const pick = enginePick(cost, at);
  if (!pick) return null;
  const where = pick.inHouse && pick.machine ? ` on your ${pick.machine}` : pick.inHouse ? " in-house" : "";
  return `${methodName(pick.process)} (${methodShort(pick.process)})${where} · ScaleCAD’s pick at ${qtyWord(at)}`;
}

/** A row's note after its sub line: the one pick, else the evidence in its own words. */
export function rowNote(m: { code: string; members: unknown[]; geometryPick: boolean; routePick: boolean }, choice: string | null, pick: string | null): string {
  if (m.members.length !== 1) return "";
  if (choice) {
    if (choice === m.code) return " · your choice";
  } else if (pick === m.code) return " · ScaleCAD’s pick";
  if (m.geometryPick) return " · highest design score";
  if (m.routePick) return " · typical for the shape";
  return "";
}

/** The Make lens's problems figure: the count the problem list shows, and how many stop a process. */
export function problemsFigure(problems: { severity: string }[]): { k: string; v: string; s: string; tone?: "ok" | "warn" } {
  const n = problems.length;
  const stopping = problems.filter((x) => x.severity === "error").length;
  if (!n) return { k: "Problems", v: "0", s: "none found", tone: "ok" };
  return { k: "Problems", v: String(n), s: stopping ? `${stopping} ${stopping === 1 ? "stops" : "stop"} a process` : "none stops a process", tone: "warn" };
}

/** The outside side's process in words: "3-axis milling at a job shop" when it is your own process bought outside. */
export function outsideName(side: { process: string; same_process?: boolean }): string {
  return side.same_process ? `${methodName(side.process)} at a job shop` : methodName(side.process);
}
