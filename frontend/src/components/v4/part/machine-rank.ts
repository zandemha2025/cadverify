/**
 * The In-house view's order (me-08, me-10): the machine the in-house answer is
 * on comes first, the other machines that can make it follow cheapest first,
 * then the ones that can't confirm, aren't set up or can't make it. And the
 * summary names every machine: one left out of "Can make" says why there, not
 * only inside its row.
 *
 * Pure: type-only imports, so it runs under `node --test` (machine-rank.test.ts).
 */
import type { MachineView } from "./model.ts";

/** The in-house answer at a quantity: the engine's cheapest route on a machine of yours (decision.options[q].in_house). */
export interface InHouseSide {
  process: string;
  machine?: string | null;
}

/** The row the in-house answer is on: the named machine on that route, else the one machine of yours that clears it. */
export function pickedMachineId(views: readonly MachineView[], side: InHouseSide | null | undefined): string | null {
  if (!side?.process) return null;
  const ok = views.filter((v) => v.process === side.process && v.tone === "ok");
  const named = side.machine ? ok.find((v) => v.name === side.machine) : null;
  return (named ?? (ok.length === 1 ? ok[0] : null))?.id ?? null;
}

const TONE_ORDER: Record<MachineView["tone"], number> = { ok: 0, warn: 1, unk: 2, bad: 3 };

/** The pick first; then the machines that can make it, cheapest first; then can't confirm, not checked, can't. Stable otherwise. */
export function rankMachines(views: readonly MachineView[], pickedId: string | null): MachineView[] {
  return views
    .map((v, i) => ({ v, i }))
    .sort((a, b) => {
      const pa = a.v.id === pickedId ? 0 : 1;
      const pb = b.v.id === pickedId ? 0 : 1;
      if (pa !== pb) return pa - pb;
      const ta = TONE_ORDER[a.v.tone];
      const tb = TONE_ORDER[b.v.tone];
      if (ta !== tb) return ta - tb;
      if (a.v.tone === "ok") {
        const ca = a.v.cost ?? Number.POSITIVE_INFINITY;
        const cb = b.v.cost ?? Number.POSITIVE_INFINITY;
        if (ca !== cb) return ca - cb;
      }
      return a.i - b.i;
    })
    .map((x) => x.v);
}

/** One machine's reason in a few words, for the summary: "max workpiece weight not declared". */
export function shortWhy(v: MachineView): string {
  if (v.verdict === "Can't") return "can't make it as drawn";
  // The first sentence, without the "Declare it in Your shop to confirm." the row carries.
  const first = (v.why.split(/(?<=\.)\s+(?=[A-Z])/)[0] ?? v.why).replace(/\.$/, "").trim();
  return first ? first[0].toLowerCase() + first.slice(1) : v.verdict.toLowerCase();
}

function cap(t: string): string {
  return t ? t[0].toUpperCase() + t.slice(1) : t;
}

export interface SummaryGroup {
  /** "Can make", "Can't confirm", "Not set up", "Not compared", "Can't". */
  k: string;
  names: string;
  /** "Max workpiece weight not declared" for one machine, "Amada HG-1003: max workpiece weight not declared · …" for several; absent for "Can make". */
  why: string | null;
  tone: "ok" | "warn" | "bad" | null;
}

/**
 * Every machine in the summary, once, in its group: can make (in rank order),
 * can't confirm, not set up, not compared (not checked, another machine, not
 * priced), and can't, each with its reason.
 */
export function machineSummary(ranked: readonly MachineView[]): SummaryGroup[] {
  const groups: SummaryGroup[] = [];
  const add = (k: string, xs: MachineView[], tone: SummaryGroup["tone"], withWhy: boolean) => {
    if (!xs.length) return;
    groups.push({
      k,
      names: xs.map((v) => v.name).join(", "),
      // One machine: its reason, capitalized (its name is the figure above). Several: "Name: reason" each.
      why: !withWhy ? null : xs.length === 1 ? cap(shortWhy(xs[0])) : xs.map((v) => `${v.name}: ${shortWhy(v)}`).join(" · "),
      tone,
    });
  };
  add("Can make", ranked.filter((v) => v.tone === "ok"), "ok", false);
  add("Can't confirm", ranked.filter((v) => v.tone === "warn" && v.verdict !== "Not set up"), "warn", true);
  add("Material not declared", ranked.filter((v) => v.tone === "warn" && v.verdict === "Not set up"), "warn", true);
  add("Not compared", ranked.filter((v) => v.tone === "unk"), null, true);
  add("Can't", ranked.filter((v) => v.tone === "bad"), "bad", true);
  return groups;
}
